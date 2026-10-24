"""Прогнозы ИИ по матчам: сохраняются до игры и сверяются с результатом.

Прогноз = ставки-подсказки по трём рынкам карты (победа, время, убийства), выбранные из снимка линии
odds/<league>/latest.json по перевесу «статистика против линии». Файл forecasts/<league>/<event_id>.json
создаётся один раз и потом не перезаписывается (чтобы прогноз не подгонялся под итог); текст «note» — разбор
от ИИ, его можно задать/заменить через --note. Результат подставляется из raw/league_<id>_matches.json.

    python scripts/forecast.py --league 20395                       # новые прогнозы + результаты + страницы
    python scripts/forecast.py --league 20395 --event 69039564 --note "разбор..."   # заменить текст
"""
import argparse
import datetime
import json
import re

from render_html import ROOT
from render_schedule import MSK, find_series, series_results, teams_of

DIR = ROOT / "forecasts"
RANK = {"явный": 2, "небольшой": 1, "нет перевеса": 0}
STAKES = {"явный": 200, "небольшой": 100}  # условная ставка по перевесу, $
CATS = (("win", "Победа на карте", "Победа на карте"), ("time", "Время карты", "Время карты"),
        ("kills", "Убийства", "Тотал убийств больше"))


def path(lid, eid):
    return DIR / lid / f"{eid}.json"


def load(lid, eid):
    f = path(lid, eid)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def save(lid, fc):
    f = path(lid, fc["event_id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")


def line_of(market):
    m = re.search(r"([\d.]+)(?: мин)?$", market)
    return float(m.group(1)) if m else None


def build_picks(m):
    """Одна лучшая подсказка на матч (из лучших по категориям): перевес «явный/небольшой» и положительное ожидание."""
    picks = []
    for cat, label, prefix in CATS:
        rows = [r for r in m["rows"] if r["market"].startswith(prefix) and r["signal"] != "нет перевеса" and r["ev"] > 0]
        if not rows:
            continue
        r = max(rows, key=lambda r: (RANK[r["signal"]], r["ev"]))
        side, odds = r["ev_side"], (r["k1"] if r["ev_side"] == r["c1"] else r["k2"])
        L = line_of(r["market"])
        if cat == "win":
            name = m["t1"] if side == "1" else m["t2"]
            text, p_est = f"Победа на карте: {name}", r["est"] if side == "1" else 1 - r["est"]
        elif cat == "time":
            more = side == "Да"
            text, p_est = f"Время карты {'больше' if more else 'меньше'} {L:g} мин", r["est"] if more else 1 - r["est"]
        else:
            more = side == "Б"
            text, p_est = f"Убийства {'больше' if more else 'меньше'} {L:g}", r["est"] if more else 1 - r["est"]
        picks.append({"cat": cat, "label": label, "text": text, "market": r["market"], "side": side, "line": L,
                      "odds": odds, "est": round(p_est, 3), "implied": round(1 / odds, 3), "n": r["n"], "basis": r["basis"],
                      "signal": r["signal"], "ev": round(r["ev"], 3),
                      "stake": STAKES[r["signal"]], "hit": None})
    # одна ставка на матч — с наибольшим перевесом (затем по ожиданию)
    return sorted(picks, key=lambda p: (-RANK[p["signal"]], -p["ev"]))[:1]


def auto_note(m, picks, after_start):
    if not picks:
        return "Статистика не расходится с линией ни по победе, ни по времени, ни по убийствам: подсказок нет."
    s = "; ".join(f"{p['text']} (коэф {p['odds']}, по статистике {p['est']:.0%} против {p['implied']:.0%} у букмекера, "
                  f"{p['basis']}, перевес: {p['signal']})" for p in picks)
    tail = " Прогноз сделан уже после старта матча." if after_start else ""
    return f"{s}.{tail} Выборки малые, маржа букмекера около 8%: это разбор статистики, а не гарантия."


def map_no(name):
    m = re.search(r"(\d+)", name or "")
    return int(m.group(1)) if m else None


def make(lid, snap, force=False, window=None):
    """Создать недостающие прогнозы по матчам снимка. Возвращает число созданных."""
    n = 0
    now = datetime.datetime.now(MSK)
    for m in snap["matches"]:
        if not m.get("event_id") and not m.get("url"):
            continue
        eid = str(m["event_id"])
        if window is not None and not (0 <= (m.get("start") or 0) - datetime.datetime.now().timestamp() <= window):
            continue  # автопилот: прогноз только за window секунд до старта
        if load(lid, eid) and not force:
            continue
        if not m["rows"] or not map_no(m["map"]):
            continue
        after = bool(m.get("start") and m["start"] <= now.timestamp())
        picks = build_picks(m)
        save(lid, {"event_id": eid, "league": lid, "created": now.strftime("%Y-%m-%d %H:%M"), "after_start": after,
                   "t1": m["t1"], "t2": m["t2"], "t1_id": m["t1_id"], "t2_id": m["t2_id"], "start": m["start"],
                   "map_no": map_no(m["map"]), "series_win": m["series_win"], "url": m.get("url"),
                   "picks": picks, "note": auto_note(m, picks, after), "rows": m["rows"], "result": None})
        n += 1
    return n


def settle(lid):
    """Подставить результат карты и отметить попадания прогнозов."""
    ser = series_results(lid, 3)
    done = 0
    for f in sorted((DIR / lid).glob("*.json")) if (DIR / lid).exists() else []:
        fc = json.loads(f.read_text(encoding="utf-8"))
        if fc["result"]:
            continue
        s = find_series(ser, fc["t1_id"], fc["t2_id"], fc["start"])
        if not s or len(s["maps"]) < fc["map_no"]:
            continue
        mp = s["maps"][fc["map_no"] - 1]
        win_id = mp["radiant_team_id"] if mp["radiant_win"] else mp["dire_team_id"]
        kills, dur = mp["radiant_score"] + mp["dire_score"], mp["duration"] / 60
        for p in fc["picks"]:
            if p["cat"] == "win":
                p["hit"] = (win_id == (fc["t1_id"] if p["side"] == "1" else fc["t2_id"]))
            elif p["cat"] == "time":
                p["hit"] = (dur > p["line"]) == (p["side"] == "Да")
            else:
                p["hit"] = (kills > p["line"]) == (p["side"] == "Б")
        fc["result"] = {"match_id": mp["match_id"], "winner_id": win_id, "kills": kills,
                        "kills_for": {"t1": mp["radiant_score"] if mp["radiant_team_id"] == fc["t1_id"] else mp["dire_score"],
                                      "t2": mp["radiant_score"] if mp["radiant_team_id"] == fc["t2_id"] else mp["dire_score"]},
                        "duration": round(dur, 1), "start_time": mp["start_time"],
                        "series": {str(k): v for k, v in s["w"].items()}, "series_done": s["done"]}
        save(lid, fc)
        done += 1
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--event")
    ap.add_argument("--note")
    ap.add_argument("--force", action="store_true", help="пересоздать прогнозы (по умолчанию существующие не трогаем)")
    a = ap.parse_args()
    if a.event and a.note:
        fc = load(a.league, a.event)
        fc["note"] = a.note
        save(a.league, fc)
        print("текст разбора обновлён")
    else:
        f = ROOT / "odds" / a.league / "latest.json"
        if f.exists():
            print("создано прогнозов:", make(a.league, json.loads(f.read_text(encoding="utf-8")), a.force))
    print("результатов подставлено:", settle(a.league))
    import render_index
    render_index.main()


if __name__ == "__main__":
    main()
