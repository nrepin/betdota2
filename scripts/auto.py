"""Автопилот: сам собирает линию и расписание, ведёт лайв, в начале каждой карты (когда выбраны герои обеих команд)
даёт один прогноз — победа, время или убийства, с учётом героев, — дожидается результатов, закрывает прогнозы и
пересобирает страницы. Доматчевых прогнозов нет.

Каждый запуск — один «тик»: смотрит, что пора сделать (по времени последних действий в auto_state.json), и делает.
Ничего не требует от Claude: только Python и интернет.

    python scripts/auto.py --once           # один тик (для планировщика, запускать каждую минуту)
    python scripts/auto.py --loop           # работать постоянно, тик каждые 30 с
    python scripts/auto.py --once --dry     # ничего не писать, только показать, что было бы сделано
Опции: --league ID (иначе все с analysis/<id>.schedule.json), --after "команда" (выполнить после тика, где
что-то изменилось, например git add/commit/push или rsync), переменные окружения TG_TOKEN и TG_CHAT — уведомления в Telegram.

Расписание работ:
  линия PARI + расписание  — раз в 3 мин, когда есть матч в окне «старт − 10 мин … + 5 ч»; раз в 5 мин, если до старта < 3 ч; иначе раз в 20 мин;
  коэффициенты до матча    — при каждом скачивании линии: odds/<лига>/prematch/<event_id>.json (открытие и закрытие);
  лайв                     — раз в минуту в окне матча: герои, оценка драфтов, страницы;
  прогноз                  — на карту один, как только выбраны все 10 героев: из победы, времени и убийств берётся рынок
                             с наибольшим расхождением «оценка по драфтам против линии» (forecast.from_draft);
  закрытие                 — через 25 мин после старта, пока есть незакрытые прогнозы, раз в 5 мин (через 6 ч — раз в 30 мин): обновить матчи, посчитать результат;
                             при запуске незакрытые прогнозы закрываются сразу (после простоя), несыгранные карты серии не ждутся.
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
import hawk
import heroes_stats
import live as livemod
import prematch
import render_index
import render_schedule
from render_html import ROOT

LOCK = ROOT / ".auto.lock"
STATE = ROOT / "auto_state.json"
LOCK_TTL = 15 * 60
LIVE_BEFORE, LIVE_AFTER = 10 * 60, 5 * 3600
SETTLE_AFTER = 25 * 60      # когда начинать искать результат (от старта матча в линии)
SETTLE_EVERY = 5 * 60
SERIES_EVERY = 4 * 60       # пока идёт серия: как часто подтягивать результаты сыгранных карт
FAST_EVERY, FAST_FOR = 90, 10 * 60   # карта только что закончилась: 10 мин ищем результат каждые 90 с
STALE_AFTER, STALE_EVERY = 6 * 3600, 30 * 60   # результат не находится 6 ч: искать реже, но не бросать
WAIT_EVERY = 15             # пока идёт матч и прогноза на карту ещё нет: лайв каждые 15 с, после прогноза — обычный ритм
WAIT_START = 45 * 60        # драфт первой карты ждём до 45 мин от старта серии
WAIT_GAP = 10 * 60          # после конца карты ждём драфт следующей до 10 мин
LATE_AFTER = 7 * 60         # позже этого времени игры прогноз уже не даём (только начало карты)
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


def draft_forecast(lid, ev, g, snap, teams, ser, st, now, dry):
    """Прогноз на идущую карту, когда выбраны все герои. Один на карту: решение (прогноз или отказ) запоминается."""
    key = str(g["match_id"])
    if key in st.setdefault("live_bets", {}):
        return False
    hs = heroes_stats.stats()
    names = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    sides = [[p["hero_id"] for p in g["players"] if p["team"] == t and p["hero_id"]] for t in (0, 1)]
    if min(len(sides[0]), len(sides[1])) < 5:
        return False  # драфт ещё идёт
    if g["game_time"] > LATE_AFTER:
        st["live_bets"][key] = "пропуск: карта уже идёт"
        log.info("[%s] прогноз %s: карта идёт %d мин — прогноз даём только в начале", lid, key, g["game_time"] // 60)
        return False
    sr = render_schedule.find_series(ser, ev["a"], ev["b"], ev["start"])
    map_no = (len(sr["maps"]) if sr else 0) + 1
    if forecast.load(lid, f"{ev['event_id']}L{map_no}"):   # карта уже в прогнозах (например, по hawk.live, потом появилась в OpenDota)
        st["live_bets"][key] = "прогноз уже есть"
        return False
    m = next((x for x in snap["matches"] if str(x.get("event_id")) == str(ev["event_id"])), None) if snap else None
    if m and forecast.map_no(m.get("map")) != map_no:
        m = None  # в линии рынки другой карты
    fc, why = forecast.from_draft(lid, ev, g, m, hs, names)
    if not fc:
        if why == "в линии нет рынков по этой карте" and g["game_time"] < 600:
            log.info("[%s] прогноз %s: %s, ещё раз на следующем тике", lid, key, why)
            return False
        st["live_bets"][key] = "нет прогноза: " + why
        log.info("[%s] прогноз %s: нет (%s)", lid, key, why)
        return False
    if not dry:
        forecast.save(lid, fc)
    p = fc["picks"][0] if fc["picks"] else None
    st["live_bets"][key] = p["text"] if p else "ставки нет (коэффициенты ниже минимума)"
    notify(f"Прогноз на карту {fc['map_no']}: {fc['t1']} – {fc['t2']}: "
           + (f"{p['text']}, коэф {p['odds']} (перевес: {p['signal']})" if p else "ставки нет, коэффициенты ниже минимума"))
    return True


def do_live(lid, st, now, events, snap, teams, dry):
    """Возвращает True, если нашли идущую карту (страницы нужно пересобрать)."""
    ser = render_schedule.series_results(lid, 3)
    try:
        games = livemod.fetch_live()
    except Exception as ex:
        log.warning("лайв: %s", ex)
        games = []   # OpenDota недоступен: пробуем резервный источник
    extra = hawk.extra_games(games, lid, events, teams)
    if extra:
        log.info("[%s] карты нет в OpenDota, лайв с hawk.live: %d", lid, len(extra))
    games = games + extra
    found = False
    waiting = False
    for ev in events:
        g = next((x for x in games if str(x.get("league_id")) == lid and not x.get("deactivate_time")
                  and {x.get("team_id_radiant"), x.get("team_id_dire")} == {ev["a"], ev["b"]}), None)
        eid = str(ev["event_id"])
        seen = st.setdefault("live_seen", {})
        if not g:
            if eid in seen:   # карта была в лайве и пропала: она закончилась, результат нужен сразу
                del seen[eid]
                st["gap_until"] = now + WAIT_GAP
                st["fast_until"] = now + FAST_FOR
                log.info("[%s] карта закончилась (пропала из лайва): быстро ищу результат", lid)
            if ev["start"] <= now <= ev["start"] + WAIT_START or now < st.get("gap_until", 0):
                waiting = True   # матч начался, карты в лайве ещё нет (драфт)
            continue
        seen[eid] = now
        found = True
        log.info("[%s] лайв: %s – %s, %d:%02d, убийства %d:%d", lid, teams[ev["a"]]["name"], teams[ev["b"]]["name"],
                 g["game_time"] // 60, g["game_time"] % 60, g["radiant_score"], g["dire_score"])
        try:
            draft_forecast(lid, ev, g, snap, teams, ser, st, now, dry)
        except Exception as ex:
            log.exception("прогноз по драфту: %s", ex)
        if str(g["match_id"]) not in st.get("live_bets", {}):
            waiting = True       # карта идёт, прогноза (или отказа) ещё нет
    st["fc_wait"] = waiting
    return found


def live_event_ids(lid, events):
    """События, у которых карта идёт прямо сейчас (None — лайв недоступен)."""
    try:
        games = livemod.fetch_live()
    except Exception:
        return None
    games = games + hawk.extra_games(games, lid, events, render_schedule.teams_of(lid))
    return {str(ev["event_id"]) for ev in events for x in games
            if str(x.get("league_id")) == lid and not x.get("deactivate_time")
            and {x.get("team_id_radiant"), x.get("team_id_dire")} == {ev["a"], ev["b"]}}


def pending(lid, now):
    """Незакрытые прогнозы по картам. Карты, которых не было (серия закончилась раньше), не считаются: их не дождаться."""
    d = ROOT / "forecasts" / lid
    out = []
    ser = None
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        fc = json.loads(f.read_text(encoding="utf-8"))
        if fc.get("live_bet") and fc["result"] is None and fc["start"] + SETTLE_AFTER < now:
            if ser is None:
                ser = render_schedule.series_results(lid, 3)
            s = render_schedule.find_series(ser, fc["t1_id"], fc["t2_id"], fc["start"])
            if s and s["done"] and len(s["maps"]) < fc["map_no"]:
                continue
            out.append(fc)
    return out


def do_settle(lid, st, now, dry, running=()):
    """Обновить матчи лиги: когда ждут результата прогнозы или идёт серия (страница матча показывает результаты карт)."""
    pend = pending(lid, now)
    run = [m for m in running if m["start"] + SETTLE_AFTER < now]
    every = FAST_EVERY if now < st.get("fast_until", 0) else SETTLE_EVERY if pend else SERIES_EVERY
    if pend and all(fc["start"] + STALE_AFTER < now for fc in pend):
        every = max(every, STALE_EVERY)
    if not (pend or run) or not due(st, "settle_ts", every, now):
        return False
    log.info("[%s] закрытие: ждут результата %d прогнозов, идущих серий %d, обновляю матчи", lid, len(pend), len(run))
    if dry:
        return False
    st["settle_ts"] = now
    try:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "collect_team.py"), "--league", lid, "--all", "--refresh"],
                       cwd=ROOT, timeout=25 * 60, check=False, capture_output=True)
    except subprocess.TimeoutExpired:
        log.warning("[%s] обновление матчей не уложилось в 25 мин, считаю по тому, что есть", lid)
    before = {fc["event_id"] for fc in pend}
    n = forecast.settle(lid)
    log.info("[%s] закрыто прогнозов: %d", lid, n)
    if n:
        st["dirty"] = True  # страницы пересоберутся, даже если дальше что-то упадёт
    for fc in (forecast.load(lid, eid) for eid in before):
        try:
            if fc and fc["result"]:
                hits = [p for p in fc["picks"] if p["hit"] is not None]
                stake = lambda p: STAKES.get(p["signal"], 50)
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
    every = 60 if s.get("fc_wait") else 180 if active else 300 if soon else 1200
    snap = None
    if due(s, "odds_ts", every, now):
        try:
            snap = refresh_odds(lid, s, now, dry)
            changed = True
        except Exception as ex:
            log.exception("[%s] линия: %s", lid, ex)
    fresh = snap is not None
    if snap is None:
        f = ROOT / "odds" / lid / "latest.json"
        snap = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    if not active:
        s["fc_wait"] = False
    if active and due(s, "live_ts", WAIT_EVERY if s.get("fc_wait") else 55, now):
        s["live_ts"] = now
        changed |= do_live(lid, s, now, active, snap, teams, dry)
    if fresh and snap and not dry:   # коэффициенты до матча/карты: открытие и закрытие линии
        try:
            if prematch.save(lid, snap, now, live_event_ids(lid, events)):
                log.info("[%s] сохранены коэффициенты до матча", lid)
        except Exception as ex:
            log.warning("[%s] коэффициенты до матча: %s", lid, ex)
    changed |= do_settle(lid, s, now, dry, active)
    return changed


RESTART = 3   # код выхода: родитель запускает автопилот заново (подхватить изменённый код)


def code_mtimes():
    return {f.name: f.stat().st_mtime for f in (ROOT / "scripts").glob("*.py")}


def supervise():
    """Родительский процесс цикла: запускает автопилот как дочерний и перезапускает его, когда он завершился кодом RESTART
    (изменился код в scripts/). Ctrl+C останавливает всё."""
    env = dict(os.environ, DOTA_AUTO_CHILD="1")
    while True:
        try:
            rc = subprocess.call([sys.executable] + sys.argv, env=env)
        except KeyboardInterrupt:
            return 0
        if rc != RESTART:
            return rc


def windows_tune():
    """Windows: не давать компьютеру уходить в сон, пока идёт цикл, и выключить «быстрое выделение» консоли
    (клик мышью по окну cmd/PowerShell ставит программу на паузу, пока не нажать Esc)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        h = k.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value | 0x0080) & ~0x0040)   # ENABLE_EXTENDED_FLAGS без ENABLE_QUICK_EDIT_MODE
        log.info("Windows: сон запрещён на время работы, быстрое выделение консоли выключено")
    except Exception as ex:
        log.warning("windows_tune: %s", ex)


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
    if a.loop and not os.environ.get("DOTA_AUTO_CHILD"):
        sys.exit(supervise())
    if a.loop:
        windows_tune()
    code_stamp = code_mtimes()
    if not a.dry:   # после остановки автопилота зависшие прогнозы закрываются сразу, а не по расписанию
        st0 = load_state()
        for lid in leagues(a.league):
            st0.setdefault(lid, {})["settle_ts"] = 0
        save_state(st0)
    while True:
        if a.loop and code_mtimes() != code_stamp:
            log.info("код скриптов изменился — перезапускаюсь")
            sys.exit(RESTART)
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
        time.sleep(WAIT_EVERY if any(isinstance(v, dict) and v.get("fc_wait") for v in load_state().values()) else 30)


if __name__ == "__main__":
    main()
