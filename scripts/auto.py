"""Автопилот: сам собирает линию и расписание, фиксирует прогнозы до старта, ведёт лайв (с лайв-ставками на время
карты по оценке драфтов), дожидается результатов, закрывает прогнозы и пересобирает страницы.

Каждый запуск — один «тик»: смотрит, что пора сделать (по времени последних действий в auto_state.json), и делает.
Ничего не требует от Claude: только Python и интернет.

    python scripts/auto.py --once           # один тик (для планировщика, запускать каждую минуту)
    python scripts/auto.py --loop           # работать постоянно, тик каждые 30 с
    python scripts/auto.py --once --dry     # ничего не писать, только показать, что было бы сделано
Опции: --league ID (иначе все с analysis/<id>.schedule.json), --after "команда" (выполнить после тика, где
что-то изменилось, например git add/commit/push или rsync), переменные окружения TG_TOKEN и TG_CHAT — уведомления в Telegram.

Расписание работ:
  линия PARI + расписание  — раз в 3 мин, когда есть матч в окне «старт − 10 мин … + 5 ч»; раз в 5 мин, если до старта < 3 ч; иначе раз в 20 мин;
  прогноз                  — один раз, за 45 мин до старта (ранее — линии по картам обычно нет);
  лайв                     — раз в минуту в окне матча: герои, оценка драфтов, страницы;
  лайв-ставка              — на карту одна: когда выбраны все герои и идёт ≥ 3 мин, по оценке драфтов против линии «Время карты больше N»;
  закрытие                 — через 40 мин после старта, пока есть незакрытые прогнозы, раз в 10 мин: обновить матчи, посчитать результат.
"""
import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import collect_odds
import forecast
import heroes_stats
import live as livemod
import render_index
import render_schedule
from render_html import ROOT

LOCK = ROOT / ".auto.lock"
STATE = ROOT / "auto_state.json"
LOCK_TTL = 15 * 60
PRE_WINDOW = 45 * 60        # прогноз за столько до старта
LIVE_BEFORE, LIVE_AFTER = 10 * 60, 5 * 3600
SETTLE_AFTER = 25 * 60      # когда начинать искать результат (от старта матча в линии)
SETTLE_EVERY = 10 * 60
LIVE_EDGE_MIN, LIVE_EDGE_STRONG = 3.0, 6.0   # минут расхождения оценки драфта с линией
LIVE_MIN_TIME = 180         # секунд игры, когда герои уже выбраны
LIVE_SAFE_LEFT = 300        # до линии должно оставаться не меньше 5 мин игры
STAKES = forecast.STAKES

log = logging.getLogger("auto")


# ---------------- служебное ----------------
def setup_log():
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%d.%m %H:%M:%S")
    for h in (logging.FileHandler(ROOT / "logs" / "auto.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def notify(text):
    log.info("УВЕДОМЛЕНИЕ: %s", text)
    token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if not (token and chat):
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20)
    except Exception as ex:
        log.warning("Telegram: %s", ex)


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def take_lock():
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < LOCK_TTL:
        return False
    LOCK.write_text(str(os.getpid()))
    return True


def leagues(arg):
    if arg:
        return [arg]
    return sorted(p.name.split(".")[0] for p in (ROOT / "analysis").glob("*.schedule.json"))


def schedule_of(lid):
    f = ROOT / "odds" / lid / "schedule.json"
    return json.loads(f.read_text(encoding="utf-8"))["matches"] if f.exists() else []


def due(st, key, every, now):
    return now - st.get(key, 0) >= every


# ---------------- шаги ----------------
def refresh_odds(lid, st, now, dry):
    log.info("[%s] линия PARI и расписание", lid)
    if dry:
        return None
    snap = collect_odds.collect(lid)
    render_schedule.fetch(lid)
    st["odds_ts"] = now
    return snap


def live_bet(lid, ev, g, snap, teams, ser, st, now, dry):
    """Лайв-ставка на время карты по оценке драфтов. Одна на идущую карту."""
    key = str(g["match_id"])
    if key in st.setdefault("live_bets", {}):
        return False
    main = forecast.load(lid, str(ev["event_id"]))
    names = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    hs = heroes_stats.stats()
    sides = [[p["hero_id"] for p in g["players"] if p["team"] == t and p["hero_id"]] for t in (0, 1)]
    if min(len(sides[0]), len(sides[1])) < 5 or g["game_time"] < LIVE_MIN_TIME:
        return False
    known = sum(1 for h in sides[0] + sides[1] if hs["heroes"].get(h, {}).get("label") not in (None, "мало данных"))
    evd = heroes_stats.draft_eval(sides[0], sides[1], hs)
    sr = render_schedule.find_series(ser, ev["a"], ev["b"], ev["start"])
    map_no = (len(sr["maps"]) if sr else 0) + 1
    if main and main["map_no"] == map_no and main["picks"]:  # одна ставка на матч: прогноз на эту карту уже есть
        st["live_bets"][key] = "пропуск: уже есть ставка"
        log.info("[%s] лайв %s: ставка на карту уже есть", lid, key)
        return False
    m = next((x for x in snap["matches"] if str(x.get("event_id")) == str(ev["event_id"])), None) if snap else None
    rows = [r for r in (m["rows"] if m else []) if r["market"].startswith("Время карты больше")]
    best = None
    if known >= 6 and evd and rows:
        for r in rows:
            N = forecast.line_of(r["market"])
            if N * 60 - g["game_time"] < LIVE_SAFE_LEFT:
                continue
            for side, odds, edge in (("Да", r["k1"], evd["exp"] - N), ("нет", r["k2"], N - evd["exp"])):
                if edge >= LIVE_EDGE_MIN and (best is None or odds > best[2]):
                    best = (r, side, odds, edge, N)
    if not best:
        st["live_bets"][key] = "пропуск"
        log.info("[%s] лайв %s: ставки нет (оценка %s мин, известных героев %d)", lid, key, evd and evd["exp"], known)
        return False
    r, side, odds, edge, N = best
    signal = "явный" if edge >= LIVE_EDGE_STRONG else "небольшой"
    more = side == "Да"
    a, b = teams[ev["a"]]["name"], teams[ev["b"]]["name"]
    text = f"Время карты {'больше' if more else 'меньше'} {N:g} мин"
    fc = {"event_id": f"{ev['event_id']}L{map_no}", "match_event_id": str(ev["event_id"]), "league": lid, "live_bet": True,
          "created": datetime.datetime.now(render_schedule.MSK).strftime("%Y-%m-%d %H:%M"), "after_start": True,
          "t1": a, "t2": b, "t1_id": ev["a"], "t2_id": ev["b"], "start": ev["start"], "map_no": map_no,
          "series_win": [], "url": ev.get("url"),
          "picks": [{"cat": "time", "label": "Время карты (лайв)", "text": text, "market": r["market"], "side": side,
                     "line": N, "odds": odds, "est": None, "implied": round(1 / odds, 3), "n": 0,
                     "basis": f"драфты: ожидание {evd['exp']:g} мин, линия {N:g}", "signal": signal, "ev": None,
                     "stake": STAKES[signal], "hit": None}],
          "note": (f"Лайв на {g['game_time'] // 60}-й минуте: оценка драфтов даёт ≈ {evd['exp']:g} мин "
                   f"(темп {evd['mean']:+g}), линия {N:g} мин — расхождение {edge:.1f} мин."),
          "rows": rows, "result": None}
    if not dry:
        forecast.save(lid, fc)
    st["live_bets"][key] = text
    notify(f"Лайв-ставка {STAKES[signal]} $: {a} – {b}, карта {map_no}: {text}, коэф {odds} (перевес: {signal})")
    return True


def do_live(lid, st, now, events, snap, teams, dry):
    """Возвращает True, если нашли идущую карту (страницы нужно пересобрать)."""
    ser = render_schedule.series_results(lid, 3)
    try:
        games = livemod.fetch_live()
    except Exception as ex:
        log.warning("лайв: %s", ex)
        return False
    found = False
    for ev in events:
        g = next((x for x in games if str(x.get("league_id")) == lid and not x.get("deactivate_time")
                  and {x.get("team_id_radiant"), x.get("team_id_dire")} == {ev["a"], ev["b"]}), None)
        if not g:
            continue
        found = True
        log.info("[%s] лайв: %s – %s, %d:%02d, убийства %d:%d", lid, teams[ev["a"]]["name"], teams[ev["b"]]["name"],
                 g["game_time"] // 60, g["game_time"] % 60, g["radiant_score"], g["dire_score"])
        try:
            live_bet(lid, ev, g, snap, teams, ser, st, now, dry)
        except Exception as ex:
            log.exception("лайв-ставка: %s", ex)
    return found


def pending(lid, now):
    d = ROOT / "forecasts" / lid
    out = []
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        fc = json.loads(f.read_text(encoding="utf-8"))
        if fc["result"] is None and fc["start"] + SETTLE_AFTER < now:
            out.append(fc)
    return out


def do_settle(lid, st, now, dry):
    pend = pending(lid, now)
    if not pend or not due(st, "settle_ts", SETTLE_EVERY, now):
        return False
    log.info("[%s] закрытие: ждут результата %d прогнозов, обновляю матчи", lid, len(pend))
    if dry:
        return False
    st["settle_ts"] = now
    subprocess.run([sys.executable, str(ROOT / "scripts" / "collect_team.py"), "--league", lid, "--all", "--refresh"],
                   cwd=ROOT, timeout=25 * 60, check=False, capture_output=True)
    before = {fc["event_id"] for fc in pend}
    n = forecast.settle(lid)
    log.info("[%s] закрыто прогнозов: %d", lid, n)
    if n:
        st["dirty"] = True  # страницы пересоберутся, даже если дальше что-то упадёт
    for fc in (forecast.load(lid, eid) for eid in before):
        try:
            if fc and fc["result"]:
                hits = [p for p in fc["picks"] if p["hit"] is not None]
                stake = lambda p: p.get("stake") or STAKES.get(p["signal"], 100)
                pl = sum(stake(p) * (p["odds"] - 1) if p["hit"] else -stake(p) for p in hits)
                notify(f"Карта закрыта: {fc['t1']} – {fc['t2']}, карта {fc['map_no']}: зашло {sum(p['hit'] for p in hits)} из "
                       f"{len(hits)}, {pl:+.0f} $")
        except Exception as ex:
            log.warning("уведомление о закрытии: %s", ex)
    return n > 0


# ---------------- тик ----------------
def tick(lid, st, dry):
    now = time.time()
    s = st.setdefault(lid, {})
    changed = False
    teams = render_schedule.teams_of(lid)
    ser = render_schedule.series_results(lid, 3)
    events = [m for m in schedule_of(lid) if m.get("event_id")
              and not (render_schedule.find_series(ser, m["a"], m["b"], m["start"]) or {}).get("done")]
    active = [m for m in events if m["start"] - LIVE_BEFORE <= now <= m["start"] + LIVE_AFTER]
    soon = [m for m in events if 0 <= m["start"] - now <= 3 * 3600]
    every = 180 if active else 300 if soon else 1200
    snap = None
    if due(s, "odds_ts", every, now):
        try:
            snap = refresh_odds(lid, s, now, dry)
            changed = True
        except Exception as ex:
            log.exception("[%s] линия: %s", lid, ex)
    if snap is None:
        f = ROOT / "odds" / lid / "latest.json"
        snap = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    if snap and not dry:
        n = forecast.make(lid, snap, window=PRE_WINDOW)
        if n:
            changed = True
            notify(f"Новых прогнозов: {n} ({lid})")
    if active and due(s, "live_ts", 55, now):
        s["live_ts"] = now
        changed |= do_live(lid, s, now, active, snap, teams, dry)
    changed |= do_settle(lid, s, now, dry)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--league")
    ap.add_argument("--after", help="команда после тика с изменениями (git push и т. п.)")
    a = ap.parse_args()
    if not (a.once or a.loop):
        ap.error("нужен --once или --loop")
    setup_log()
    while True:
        if not take_lock():
            log.info("другой экземпляр уже работает (.auto.lock) — пропускаю тик")
        else:
            try:
                st = load_state()
                changed = False
                for lid in leagues(a.league):
                    try:
                        changed |= tick(lid, st, a.dry)
                    except Exception as ex:
                        log.exception("[%s] ошибка тика: %s", lid, ex)
                        notify(f"Автопилот: ошибка в тике {lid}: {ex}")
                dirty = st.pop("dirty", False)
                page = ROOT / "forecasts.html"  # данные новее страницы (например, прошлый тик упал) — пересобрать
                if not page.exists() or any(f.stat().st_mtime > page.stat().st_mtime for f in (ROOT / "forecasts").glob("*/*.json")):
                    dirty = True
                if (changed or dirty) and not a.dry:
                    save_state(st)
                    render_index.main()
                    if a.after:
                        subprocess.run(a.after, shell=True, cwd=ROOT, check=False)
                elif not a.dry:
                    save_state(st)
            finally:
                LOCK.unlink(missing_ok=True)
        if a.once:
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
