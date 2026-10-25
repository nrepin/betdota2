"""Ручной прогноз по драфтам: берёт идущую карту (hawk.live, запасной вариант — OpenDota /live), и если герои обеих
команд выбраны, сверяет оценку по драфтам с линией PARI и печатает прогноз на победу, время и убийства.
Та же логика, что у автопилота (forecast.from_draft), но запускается руками в любой момент.

    python scripts/draft.py                                # сам находит все идущие карты в лайве (по всем лигам)
    python scripts/draft.py --league 20395                 # только эта лига
    python scripts/draft.py --event og                     # матч по event_id или части названия команды
    python scripts/draft.py --save                         # заодно сохранить в forecasts/ и пересобрать страницы
Опции: --force (перезаписать уже сохранённый прогноз этой карты), --no-odds (не качать линию, взять odds/<лига>/latest.json),
--wait N (если карты нет или пики не готовы — проверять раз в N секунд, пока не будут).
Код возврата: 0 — прогноз есть, 2 — нет идущей карты или пики не готовы, 3 — прогноз не получился (нет рынков и т. п.).
"""
import argparse
import json
import sys
import time

import collect_odds
import forecast
import heroes_stats
import live as livemod
import render_schedule
from render_html import ROOT


def leagues():
    return sorted(f.name.split(".")[0] for f in (ROOT / "analysis").glob("*.schedule.json"))


def events_of(lid, key, teams, ser, now):
    """Матчи лиги, которые могут идти сейчас (или указанный --event)."""
    f = ROOT / "odds" / lid / "schedule.json"
    evs = [m for m in json.loads(f.read_text(encoding="utf-8"))["matches"] if m.get("event_id")] if f.exists() else []
    if key:
        k = key.lower()
        return [m for m in evs if str(m["event_id"]) == key or k in teams[m["a"]]["name"].lower() or k in teams[m["b"]]["name"].lower()]
    return [m for m in evs if m["start"] - 1800 <= now <= m["start"] + 8 * 3600
            and not (render_schedule.find_series(ser, m["a"], m["b"], m["start"]) or {}).get("done")]


def find_live(lids, key):
    """Идущие сейчас карты: [(лига, матч, игра, команды, серии)] — по всем лигам (или по --event)."""
    out = []
    for lid in lids:
        teams, ser = render_schedule.teams_of(lid), render_schedule.series_results(lid, 3)
        for ev in events_of(lid, key, teams, ser, time.time()):
            g = livemod.current_game(lid, ev, teams)
            if g:
                out.append((lid, ev, g, teams, ser))
    return out


def run(a):
    while True:
        found = find_live([a.league] if a.league else leagues(), a.event)
        ready = [f for f in found if min(sum(1 for p in f[2]["players"] if p["team"] == t and p["hero_id"]) for t in (0, 1)) >= 5]
        if ready or not a.wait:
            break
        print("идущих карт нет" if not found else "пики не готовы: " + "; ".join(
            f"{f[3][f[1]['a']]['name']} – {f[3][f[1]['b']]['name']} "
            f"({sum(1 for p in f[2]['players'] if p['team'] == 0 and p['hero_id'])} + {sum(1 for p in f[2]['players'] if p['team'] == 1 and p['hero_id'])} из 5 + 5)"
            for f in found))
        time.sleep(a.wait)
    if not found:
        print("сейчас ни одна карта не идёт в лайве (hawk.live и OpenDota)"); return 2
    code = 0
    for lid, ev, g, teams, ser in found:
        code = max(code, forecast_one(a, lid, ev, g, teams, ser))
    return code


def forecast_one(a, lid, ev, g, teams, ser):
    na, nb = teams[ev["a"]]["name"], teams[ev["b"]]["name"]
    sides = [[p["hero_id"] for p in g["players"] if p["team"] == t and p["hero_id"]] for t in (0, 1)]
    if min(map(len, sides)) < 5:
        print(f"{na} – {nb}: пики не готовы ({len(sides[0])} + {len(sides[1])} из 5 + 5)")
        return 2
    src = g.get("source", "OpenDota")
    sr = render_schedule.find_series(ser, ev["a"], ev["b"], ev["start"])
    map_no = g.get("map_no") or (len(sr["maps"]) if sr else 0) + 1
    names = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    nm = lambda ids: ", ".join(names[str(h)]["localized_name"] for h in ids)
    print(f"\n== [{lid}] {na} – {nb}, карта {map_no}, источник {src}, время {g['game_time'] // 60}:{abs(g['game_time']) % 60:02d}")
    print(f"  Radiant {g['team_name_radiant']}: {nm(sides[0])}\n  Dire    {g['team_name_dire']}: {nm(sides[1])}")
    if a.no_odds:
        snap = json.loads((ROOT / "odds" / lid / "latest.json").read_text(encoding="utf-8"))
    else:
        snap = collect_odds.collect(lid)
    m = next((x for x in snap["matches"] if str(x.get("event_id")) == str(ev["event_id"])), None)
    if m and forecast.map_no(m.get("map")) != map_no:
        print(f"  в линии сейчас карта {forecast.map_no(m.get('map'))}, а идёт {map_no}: рынков этой карты нет")
        m = None
    fc, why = forecast.from_draft(lid, ev, g, m, heroes_stats.stats(), names)
    if not fc:
        print("  прогноза нет:", why); return 3
    print("\n" + fc["note"])
    for p in fc["picks"]:
        print(f"\nСтавка: {p['text']}, коэф {p['odds']}, оценка {p.get('est') or '—'}, перевес: {p['signal']}")
    if not fc["picks"]:
        print("\nСтавки нет: коэффициенты ниже минимума")
    if a.save:
        if forecast.load(lid, fc["event_id"]) and not a.force:
            print(f"прогноз {fc['event_id']} уже сохранён (--force — перезаписать)"); return 0
        forecast.save(lid, fc)
        import render_index
        render_index.main()
        print(f"сохранено: forecasts/{lid}/{fc['event_id']}.json, страницы пересобраны")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", help="id лиги; без него — все лиги из analysis/*.schedule.json")
    ap.add_argument("--event")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-odds", action="store_true")
    ap.add_argument("--wait", type=int, default=0)
    sys.exit(run(ap.parse_args()))


if __name__ == "__main__":
    main()
