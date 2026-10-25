"""Текущий лайв турнира: герои, время, убийства, золото, оценка драфтов (быстрый/затяжной) и сверка с линией по времени.

Источник — OpenDota /live (открытый, без ключа). Герои идут в оценку темпа из heroes_stats (только сыгранные карты
в базе). После вывода пересобираются страницы (на странице матча блок «Лайв»).

    python scripts/live.py --league 20395         # один снимок
    python scripts/live.py --league 20395 --watch 60   # обновлять каждые 60 с (Ctrl+C — выход)
    python scripts/live.py                        # все лайвы с league_id из data/
"""
import argparse
import json
import time
import urllib.request

import netutil

import heroes_stats
from render_html import ROOT


def fetch_live():
    req = urllib.request.Request("https://api.opendota.com/api/live", headers={"User-Agent": "dota-stats/1.0"})
    return json.loads(netutil.urlopen(req, timeout=30).read())


def current_game(lid, ev, teams):
    """Идущая карта события: сначала hawk.live, запасной вариант — OpenDota /live (None, если карты нет)."""
    import hawk
    g = (hawk.extra_games([], str(lid), [ev], teams) or [None])[0]
    if g:
        return g
    try:
        live = fetch_live()
    except Exception:
        return None
    return next((x for x in live if str(x.get("league_id")) == str(lid) and not x.get("deactivate_time")
                 and {x.get("team_id_radiant"), x.get("team_id_dire")} == {ev["a"], ev["b"]}), None)


def mmss(t):
    return f"{t // 60}:{abs(t) % 60:02d}"


def time_lines(lid, tids):
    """Рынки «Время карты больше N мин» из последнего снимка линии для этой пары (если есть)."""
    f = ROOT / "odds" / lid / "latest.json"
    if not f.exists():
        return []
    for m in json.loads(f.read_text(encoding="utf-8"))["matches"]:
        if {m.get("t1_id"), m.get("t2_id")} == set(tids):
            return [r for r in m["rows"] if r["market"].startswith("Время карты")]
    return []


def show(g, st, names, lid):
    tid = (g["team_id_radiant"], g["team_id_dire"])
    print(f"\n== {g['team_name_radiant']} (Radiant) vs {g['team_name_dire']} (Dire) — {mmss(g['game_time'])}, "
          f"убийства {g['radiant_score']}:{g['dire_score']}, "
          f"золото {g['team_name_radiant'] if g['radiant_lead'] > 0 else g['team_name_dire']} +{abs(g['radiant_lead'])}, "
          f"зрителей {g.get('spectators', 0)}, match {g['match_id']}")
    ids = {}
    for team in (0, 1):
        ps = [p for p in g["players"] if p["team"] == team]
        ids[team] = [p["hero_id"] for p in ps if p["hero_id"]]
        cells = []
        th = heroes_stats.team_hero_stats(g["team_id_radiant"] if team == 0 else g["team_id_dire"])
        for p in ps:
            h = st["heroes"].get(p["hero_id"])
            nm = names.get(str(p["hero_id"]), {}).get("localized_name", "—") if p["hero_id"] else "пик не сделан"
            n, w = th.get(p["hero_id"], (0, 0))
            tm = f"команда: {n}× {w / n:.0%}" if n else "команда: не брала"
            cells.append(f"{nm} ({h['tilt']:+g}, {h['label']}; вышки: {h['tlabel']}; {tm})" if h else f"{nm} (нет данных; {tm})")
        t = heroes_stats.draft_tempo(ids[team], st)
        print(f"  {g['team_name_radiant'] if team == 0 else g['team_name_dire']}: " + "; ".join(cells)
              + f"\n    темп драфта: {heroes_stats.tempo_word(t)}" + ("" if t is None else f" ({t:+g})"))
    ev = heroes_stats.draft_eval(ids[0], ids[1], st) if min(len(ids[0]), len(ids[1])) == 5 else None
    import forecast
    wn = forecast.draft_win(g["team_id_radiant"], g["team_id_dire"], ids[0], ids[1], st)
    if wn:
        pa = wn["p"]
        part = "" if min(wn["na"], wn["nb"]) == 5 else f" [пики не завершены: {wn['na']}+{wn['nb']}]"
        print(f"  Прогноз по драфту: победит {g['team_name_radiant'] if pa >= 0.5 else g['team_name_dire']} "
              f"{max(pa, 1 - pa):.0%} (команды {wn['base']:.0%}, герои {wn['hero'] * 100:+.0f} п.п., форма {wn['form'] * 100:+.0f} п.п.; "
              f"форма: {wn['form_a']} / {wn['form_b']}){part}")
    if ev:
        w = {"затяжной": "затяжная", "быстрый": "быстрая", "средний": "средняя"}[ev["word"]]
        print(f"  Оценка драфтов: карта {w} (темп {ev['mean']:+g}), ожидаемая длительность ≈ {ev['exp']:g} мин "
              f"(средняя по базе {st['overall']:g})")
        print(f"  Вышки: драфты {ev['tw_word']}" + (f" (индекс {ev['tw']:+g})" if ev["tw"] is not None else "") + f"; {ev['tw_note']}")
        for r in time_lines(lid, tid):
            print(f"    линия: {r['market']} — Да {r['k1']} / нет {r['k2']}, сейчас {mmss(g['game_time'])}")


def once(league):
    st = heroes_stats.stats()
    names = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    lids = {p.name for p in (ROOT / "data").iterdir() if p.is_dir()}
    n = 0
    for g in fetch_live():
        lid = str(g.get("league_id"))
        if (league and lid != league) or (not league and lid not in lids) or g.get("deactivate_time"):
            continue
        show(g, st, names, lid)
        n += 1
    if not n:
        print("Сейчас лайвов нет" + (f" в лиге {league}" if league else "") + ".")
    import render_index
    render_index.main()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league")
    ap.add_argument("--watch", type=int, metavar="СЕК")
    a = ap.parse_args()
    while True:
        once(a.league)
        if not a.watch:
            break
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
