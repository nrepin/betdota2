"""Сбор статистики команды на турнире через OpenDota API.

Использование:
    python scripts/collect_team.py --league 19102 --team 9824702
    python scripts/collect_team.py --league 19102 --all

Результат:
    raw/league_<id>_matches.json, raw/matches/<match_id>.json  — кеш ответов API
    data/<league>/<team_slug>.json                            — все данные по команде
    reports/<league>/<team_slug>.md / .html                   — читаемый отчёт
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from render_html import fmt_date, write_html
import aggregate
import render_analysis
import render_index

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.opendota.com/api"
RAW = ROOT / "raw"
DELAY = 1.1  # бесплатный лимит OpenDota ~60 запросов/мин


def fetch(url, cache=None, refresh=False):
    if cache and cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dota-stats/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:  # 429 / сетевые ошибки — ждём и повторяем
            print(f"  retry {attempt + 1} {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"не удалось получить {url}")
    time.sleep(DELAY)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def mmss(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def avg(xs):
    return sum(xs) / len(xs) if xs else 0


def pct(w, n):
    return round(100 * w / n, 1) if n else 0


def build_team(league_id, team_id, league_matches, teams, heroes, refresh_matches):
    hero = lambda hid: heroes.get(str(hid), {}).get("localized_name", f"#{hid}")
    team_name = lambda tid: teams.get(tid, {}).get("name", str(tid))

    games = []
    for lm in sorted(league_matches, key=lambda m: m["start_time"]):
        if team_id not in (lm["radiant_team_id"], lm["dire_team_id"]):
            continue
        mid = lm["match_id"]
        m = fetch(f"{API}/matches/{mid}", RAW / "matches" / f"{mid}.json", refresh_matches)
        is_rad = m["radiant_team_id"] == team_id
        side = 0 if is_rad else 1  # в picks_bans: team 0 = Radiant, 1 = Dire
        opp_id = m["dire_team_id"] if is_rad else m["radiant_team_id"]
        win = m["radiant_win"] == is_rad
        kills_for = m["radiant_score"] if is_rad else m["dire_score"]
        kills_against = m["dire_score"] if is_rad else m["radiant_score"]

        pb = sorted(m.get("picks_bans") or [], key=lambda x: x["order"])
        picks = [hero(x["hero_id"]) for x in pb if x["is_pick"] and x["team"] == side]
        opp_picks = [hero(x["hero_id"]) for x in pb if x["is_pick"] and x["team"] != side]
        bans = [hero(x["hero_id"]) for x in pb if not x["is_pick"] and x["team"] == side]
        opp_bans = [hero(x["hero_id"]) for x in pb if not x["is_pick"] and x["team"] != side]
        first_pick = next((x["team"] == side for x in pb if x["is_pick"]), None)

        players = []
        for p in m["players"]:
            if p["isRadiant"] != is_rad:
                continue
            players.append({
                "account_id": p.get("account_id"),
                "name": p.get("name") or p.get("personaname"),
                "hero": hero(p["hero_id"]),
                "position": p.get("position_est") or p.get("lane_role"),
                "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
                "last_hits": p["last_hits"], "denies": p["denies"],
                "gpm": p["gold_per_min"], "xpm": p["xp_per_min"],
                "net_worth": p.get("net_worth"), "hero_damage": p.get("hero_damage"),
                "tower_damage": p.get("tower_damage"), "hero_healing": p.get("hero_healing"),
                "obs_placed": p.get("obs_placed"), "sen_placed": p.get("sen_placed"),
                "stuns": p.get("stuns"), "roshans_killed": p.get("roshans_killed"),
                "teamfight_participation": p.get("teamfight_participation"),
                "firstblood_claimed": p.get("firstblood_claimed"),
            })
        players.sort(key=lambda p: (p["position"] or 9))

        # первая кровь: у кого из игроков firstblood_claimed
        fb_ours = any(p.get("firstblood_claimed") for p in players)
        gold_adv = m.get("radiant_gold_adv") or []
        adv10 = gold_adv[10] if len(gold_adv) > 10 else None
        if adv10 is not None and not is_rad:
            adv10 = -adv10
        max_lead = max((g if is_rad else -g for g in gold_adv), default=None)
        max_deficit = min((g if is_rad else -g for g in gold_adv), default=None)

        games.append({
            "match_id": mid,
            "series_id": m.get("series_id"),
            "start_time": m["start_time"],
            "opponent_id": opp_id,
            "opponent": team_name(opp_id),
            "side": "Radiant" if is_rad else "Dire",
            "win": win,
            "duration_sec": m["duration"],
            "duration": mmss(m["duration"]),
            "kills_for": kills_for,
            "kills_against": kills_against,
            "total_kills": kills_for + kills_against,
            "first_pick": first_pick,
            "first_blood": fb_ours,
            "first_blood_time": m.get("first_blood_time"),
            "gold_adv_10min": adv10,
            "max_gold_lead": max_lead,
            "max_gold_deficit": max_deficit,
            "roshans": sum(p.get("roshans_killed") or 0 for p in players),
            "towers": sum(p.get("towers_killed") or 0 for p in players)
                       if any("towers_killed" in p for p in m["players"]) else None,
            "picks": picks, "bans": bans,
            "opp_picks": opp_picks, "opp_bans": opp_bans,
            "players": players,
            "patch": m.get("patch"),
            "dotabuff": f"https://www.dotabuff.com/matches/{mid}",
        })

    return {"team_id": team_id, "team": team_name(team_id), "league_id": league_id,
            "games": games, "summary": summarize(games)}


def summarize(games):
    n = len(games)
    wins = [g for g in games if g["win"]]
    losses = [g for g in games if not g["win"]]
    s = {
        "games": n, "wins": len(wins), "losses": len(losses), "winrate": pct(len(wins), n),
        "avg_duration": mmss(avg([g["duration_sec"] for g in games])),
        "avg_duration_win": mmss(avg([g["duration_sec"] for g in wins])),
        "avg_duration_loss": mmss(avg([g["duration_sec"] for g in losses])),
        "shortest": mmss(min((g["duration_sec"] for g in games), default=0)),
        "longest": mmss(max((g["duration_sec"] for g in games), default=0)),
        "avg_kills_for": round(avg([g["kills_for"] for g in games]), 1),
        "avg_kills_against": round(avg([g["kills_against"] for g in games]), 1),
        "avg_total_kills": round(avg([g["total_kills"] for g in games]), 1),
        "kills_per_min": round(sum(g["kills_for"] for g in games) / max(1, sum(g["duration_sec"] for g in games) / 60), 2),
        "first_blood_rate": pct(sum(g["first_blood"] for g in games), n),
        "avg_gold_adv_10min": round(avg([g["gold_adv_10min"] for g in games if g["gold_adv_10min"] is not None])),
        "avg_roshans": round(avg([g["roshans"] for g in games]), 2),
    }
    for side in ("Radiant", "Dire"):
        gs = [g for g in games if g["side"] == side]
        s[f"{side.lower()}"] = {"games": len(gs), "wins": sum(g["win"] for g in gs),
                               "winrate": pct(sum(g["win"] for g in gs), len(gs))}
    for fp, key in ((True, "first_pick"), (False, "second_pick")):
        gs = [g for g in games if g["first_pick"] is fp]
        s[key] = {"games": len(gs), "wins": sum(g["win"] for g in gs),
                  "winrate": pct(sum(g["win"] for g in gs), len(gs))}

    # серии
    # у части матчей в OpenDota series_id = None — приклеиваем к ближайшей карте
    # против того же соперника в пределах 8 часов
    def series_key(g):
        if g["series_id"]:
            return g["series_id"]
        near = [x for x in games if x["series_id"] and x["opponent_id"] == g["opponent_id"]
                and abs(x["start_time"] - g["start_time"]) < 8 * 3600]
        return min(near, key=lambda x: abs(x["start_time"] - g["start_time"]))["series_id"] if near else f"m{g['match_id']}"

    series = defaultdict(list)
    for g in games:
        series[series_key(g)].append(g)
    s["series"] = []
    for sid, gs in series.items():
        w = sum(g["win"] for g in gs)
        s["series"].append({"series_id": sid, "opponent": gs[0]["opponent"],
                            "score": f"{w}-{len(gs) - w}", "won": w > len(gs) - w})
    s["series_record"] = f"{sum(x['won'] for x in s['series'])}-{sum(not x['won'] for x in s['series'])}"

    # герои
    hp = defaultdict(lambda: [0, 0])
    for g in games:
        for h in g["picks"]:
            hp[h][0] += 1
            hp[h][1] += g["win"]
    s["hero_picks"] = sorted(({"hero": h, "games": c, "wins": w, "winrate": pct(w, c)}
                              for h, (c, w) in hp.items()), key=lambda x: (-x["games"], -x["wins"]))
    s["bans_by_team"] = Counter(h for g in games for h in g["bans"]).most_common()
    s["bans_against_team"] = Counter(h for g in games for h in g["opp_bans"]).most_common()
    op = defaultdict(lambda: [0, 0])
    for g in games:
        for h in g["opp_picks"]:
            op[h][0] += 1
            op[h][1] += g["win"]
    s["vs_heroes"] = sorted(({"hero": h, "games": c, "our_wins": w, "our_winrate": pct(w, c)}
                             for h, (c, w) in op.items()), key=lambda x: (-x["games"], x["our_wins"]))

    # игроки
    pl = defaultdict(list)
    for g in games:
        for p in g["players"]:
            pl[p["account_id"]].append((g, p))
    s["players"] = []
    for aid, rows in pl.items():
        ps = [p for _, p in rows]
        k, d, a = sum(p["kills"] for p in ps), sum(p["deaths"] for p in ps), sum(p["assists"] for p in ps)
        pos = Counter(p["position"] for p in ps).most_common(1)[0][0]
        hcount = defaultdict(lambda: [0, 0])
        for g, p in rows:
            hcount[p["hero"]][0] += 1
            hcount[p["hero"]][1] += g["win"]
        s["players"].append({
            "account_id": aid, "name": Counter(p["name"] for p in ps).most_common(1)[0][0],
            "position": pos, "games": len(ps),
            "avg_kills": round(k / len(ps), 1), "avg_deaths": round(d / len(ps), 1),
            "avg_assists": round(a / len(ps), 1), "kda": round((k + a) / max(1, d), 2),
            "avg_gpm": round(avg([p["gpm"] for p in ps])), "avg_xpm": round(avg([p["xpm"] for p in ps])),
            "avg_last_hits": round(avg([p["last_hits"] for p in ps])),
            "avg_hero_damage": round(avg([p["hero_damage"] or 0 for p in ps])),
            "avg_wards": round(avg([(p["obs_placed"] or 0) + (p["sen_placed"] or 0) for p in ps]), 1),
            "heroes": [{"hero": h, "games": c, "wins": w} for h, (c, w) in
                       sorted(hcount.items(), key=lambda x: -x[1][0])],
        })
    s["players"].sort(key=lambda p: (p["position"] or 9))
    return s


def report_md(t, league_name):
    s, games = t["summary"], t["games"]
    L = [f"# {t['team']} — {league_name}", "",
         f"Источник: OpenDota API (league {t['league_id']}, team {t['team_id']}). "
         f"Dotabuff: https://www.dotabuff.com/esports/teams/{t['team_id']}", "",
         "## Итог", "",
         f"- Карты: **{s['wins']}-{s['losses']}** (винрейт {s['winrate']}%), серии: **{s['series_record']}**",
         f"- Средняя длительность: **{s['avg_duration']}** (победы {s['avg_duration_win']}, поражения {s['avg_duration_loss']}); "
         f"самая короткая {s['shortest']}, самая длинная {s['longest']}",
         f"- Фраги за карту: **{s['avg_kills_for']}:{s['avg_kills_against']} ({s['avg_total_kills']})**; "
         f"{s['kills_per_min']} убийства/мин",
         f"- Первая кровь: {s['first_blood_rate']}% карт; золото на 10-й минуте в среднем: {s['avg_gold_adv_10min']:+}",
         f"- Рошаны за карту: {s['avg_roshans']}",
         f"- Radiant: {s['radiant']['wins']}/{s['radiant']['games']} ({s['radiant']['winrate']}%), "
         f"Dire: {s['dire']['wins']}/{s['dire']['games']} ({s['dire']['winrate']}%)",
         f"- First pick: {s['first_pick']['wins']}/{s['first_pick']['games']} ({s['first_pick']['winrate']}%), "
         f"second pick: {s['second_pick']['wins']}/{s['second_pick']['games']} ({s['second_pick']['winrate']}%)",
         "", "## Серии", "", "| Соперник | Счёт |", "|---|---|"]
    L += [f"| {x['opponent']} | {x['score']} {'✅' if x['won'] else '❌'} |" for x in s["series"]]
    L += ["", "## Карты", "", "| Дата | Соперник | Сторона | Итог | Время | Фраги | Пики | Пики соперника |", "|---|---|---|---|---|---|---|---|"]
    for g in reversed(games):  # свежие карты сверху
        L.append(f"| [{fmt_date(g['start_time'])}]({g['dotabuff']}) | {g['opponent']} | {g['side']}{' FP' if g['first_pick'] else ''} | "
                 f"{'W' if g['win'] else 'L'} | {g['duration']} | {g['kills_for']}:{g['kills_against']} ({g['total_kills']}) | "
                 f"{', '.join(g['picks'])} | {', '.join(g['opp_picks'])} |")
    L += ["", "## Игроки", "", "| Поз. | Игрок | Карты | K/D/A (ср.) | KDA | GPM | XPM | LH | Урон | Варды | Герои |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in s["players"]:
        heroes = ", ".join(f"{h['hero']} {h['wins']}/{h['games']}" for h in p["heroes"])
        L.append(f"| {p['position']} | {p['name']} | {p['games']} | {p['avg_kills']}/{p['avg_deaths']}/{p['avg_assists']} | "
                 f"{p['kda']} | {p['avg_gpm']} | {p['avg_xpm']} | {p['avg_last_hits']} | {p['avg_hero_damage']} | {p['avg_wards']} | {heroes} |")
    L += ["", "## Пики команды", "", "| Герой | Карты | Победы | Винрейт |", "|---|---|---|---|"]
    L += [f"| {h['hero']} | {h['games']} | {h['wins']} | {h['winrate']}% |" for h in s["hero_picks"]]
    L += ["", "## Баны", "", "**Банит команда:** " + ", ".join(f"{h} ×{c}" for h, c in s["bans_by_team"]),
          "", "**Банят против команды:** " + ", ".join(f"{h} ×{c}" for h, c in s["bans_against_team"]),
          "", "## Против каких героев играли", "", "| Герой соперника | Карты | Наши победы |", "|---|---|---|"]
    L += [f"| {h['hero']} | {h['games']} | {h['our_wins']} ({h['our_winrate']}%) |" for h in s["vs_heroes"][:20]]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", type=int, required=True)
    ap.add_argument("--team", type=int, action="append", default=[])
    ap.add_argument("--all", action="store_true", help="все команды турнира")
    ap.add_argument("--refresh", action="store_true", help="перекачать список матчей лиги (новые игры)")
    ap.add_argument("--refresh-matches", action="store_true", help="перекачать детали матчей")
    args = ap.parse_args()

    lid = args.league
    league = fetch(f"{API}/leagues/{lid}", RAW / f"league_{lid}.json")
    lm = fetch(f"{API}/leagues/{lid}/matches", RAW / f"league_{lid}_matches.json", args.refresh)
    teams = {t["team_id"]: t for t in fetch(f"{API}/leagues/{lid}/teams", RAW / f"league_{lid}_teams.json", args.refresh)}
    heroes = fetch(f"{API}/constants/heroes", RAW / "heroes.json")

    team_ids = args.team
    if args.all:
        team_ids = sorted({m[k] for m in lm for k in ("radiant_team_id", "dire_team_id")})
    for tid in team_ids:
        t = build_team(lid, tid, lm, teams, heroes, args.refresh_matches)
        name = slug(t["team"])
        out_json = ROOT / "data" / str(lid) / f"{name}.json"
        out_md = ROOT / "reports" / str(lid) / f"{name}.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
        out_md.write_text(report_md(t, league["name"]), encoding="utf-8")
        write_html(t, league["name"], out_md.with_suffix(".html"))
        s = t["summary"]
        print(f"{t['team']}: {s['wins']}-{s['losses']} ({s['winrate']}%), {s['avg_duration']}, "
              f"kills {s['avg_kills_for']}:{s['avg_kills_against']} -> {out_md.relative_to(ROOT)}")
    aggregate.build_pages()
    render_analysis.main()
    render_index.main()


if __name__ == "__main__":
    main()
