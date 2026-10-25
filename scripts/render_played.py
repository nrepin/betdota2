"""Страница «Сыгранные матчи» (played.html): серии и карты по турнирам и датам (МСК), новые сверху.

    python scripts/render_played.py
"""
import datetime
import json
from collections import defaultdict
from html import escape as e

from render_html import ROOT, logo_cls, rel, team_logo

OUT = ROOT / "played.html"
MSK = datetime.timezone(datetime.timedelta(hours=3))
DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

CSS = """
.pl-day{margin:18px 0 8px;font:600 12.5px var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.pl-s{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin-top:8px}
.pl-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pl-h .tm{display:inline-flex;align-items:center;gap:8px;font-weight:650;color:inherit;text-decoration:none}
.pl-h .tm img{width:24px;height:24px;object-fit:contain}.pl-h .tm img.dark{background:#111;border-radius:6px;padding:2px}
.pl-h .tm.w{color:var(--win)}
.pl-h .sc{font:700 16px var(--mono)}
.pl-h .tm0{margin-left:auto;font:12px var(--mono);color:var(--muted)}
.pl-h .tm0 a{color:inherit}
.pl-maps{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:8px;font:12.5px var(--mono);color:var(--muted)}
.pl-maps a{color:inherit}.pl-maps b{color:var(--text);font-weight:600}
"""


def leagues():
    return sorted((p.name for p in (ROOT / "data").iterdir() if p.is_dir()), reverse=True)


def schedule_events(lid):
    f = ROOT / "odds" / lid / "schedule.json"
    return json.loads(f.read_text(encoding="utf-8"))["matches"] if f.exists() else []


def match_page(lid, evs, a, b, start):
    """Страница матча из линии: та же пара, ближайший по времени старт."""
    c = [x for x in evs if {x["a"], x["b"]} == {a, b} and x.get("event_id") and abs(x["start"] - start) < 12 * 3600]
    if not c:
        return None
    p = ROOT / "matches" / lid / f"{min(c, key=lambda x: abs(x['start'] - start))['event_id']}.html"
    return p if p.exists() else None


def series_of(lid):
    ms = json.loads((ROOT / "raw" / f"league_{lid}_matches.json").read_text(encoding="utf-8"))
    ser = defaultdict(list)
    for m in ms:
        if m.get("radiant_team_id") and m.get("dire_team_id"):
            ser[m["series_id"]].append(m)
    for v in ser.values():
        v.sort(key=lambda m: m["start_time"])
    return sorted(ser.values(), key=lambda v: v[0]["start_time"], reverse=True)


def team_html(tid, teams, lid, win):
    name = teams.get(tid, {}).get("name", str(tid))
    logo = team_logo(tid)
    img = f"<img class={logo_cls(tid)} src='{e(rel(logo, OUT))}' alt='' loading=lazy>" if logo else ""
    return f"<span class='tm{' w' if win else ''}'>{img}<span>{e(name)}</span></span>"


def render_page():
    import render_index
    body = []
    total = 0
    for lid in leagues():
        name = json.loads((ROOT / "raw" / f"league_{lid}.json").read_text(encoding="utf-8"))["name"]
        teams = {t["team_id"]: t for t in json.loads((ROOT / "raw" / f"league_{lid}_teams.json").read_text(encoding="utf-8"))}
        evs = schedule_events(lid)
        days = defaultdict(list)
        for maps in series_of(lid):
            days[datetime.datetime.fromtimestamp(maps[0]["start_time"], MSK).date()].append(maps)
        if not days:
            continue
        n = sum(len(v) for v in days.values())
        total += n
        body.append(f"<h3 class=grp-h>{e(name)} · {n} серий</h3>")
        for day in sorted(days, reverse=True):
            body.append(f"<div class=pl-day>{day.strftime('%d.%m.%Y')}, {DAYS[day.weekday()]}</div>")
            for maps in days[day]:
                a, b = maps[0]["radiant_team_id"], maps[0]["dire_team_id"]
                wins = {a: 0, b: 0}
                for m in maps:
                    wins[m["radiant_team_id"] if m["radiant_win"] else m["dire_team_id"]] += 1
                top = max(wins.values())
                start = datetime.datetime.fromtimestamp(maps[0]["start_time"], MSK).strftime("%H:%M")
                pg = match_page(lid, evs, a, b, maps[0]["start_time"])
                link = f"<a href='{e(rel(pg, OUT))}'>страница матча</a>" if pg else ""
                head = (f"<div class=pl-h>{team_html(a, teams, lid, wins[a] == top and wins[a] != wins[b])}"
                        f"<span class=sc>{wins[a]}:{wins[b]}</span>"
                        f"{team_html(b, teams, lid, wins[b] == top and wins[a] != wins[b])}"
                        f"<span class=tm0>{start} МСК{' · ' + link if link else ''}</span></div>")
                cells = []
                for i, m in enumerate(maps, 1):
                    w = m["radiant_team_id"] if m["radiant_win"] else m["dire_team_id"]
                    dur = f"{m['duration'] // 60}:{m['duration'] % 60:02d}"
                    cells.append(f"<span>Карта {i}: <b>{e(teams.get(w, {}).get('name', str(w)))}</b>, {dur}, "
                                 f"{m['radiant_score'] + m['dire_score']} уб. "
                                 f"(<a href='https://www.dotabuff.com/matches/{m['match_id']}'>Dotabuff</a>)</span>")
                body.append(f"<div class=pl-s>{head}<div class=pl-maps>{''.join(cells)}</div></div>")
    lead = (f"<div class=page-h><h2>Сыгранные матчи</h2><div class=sub>{total} серий по турнирам и датам (МСК), новые сверху. "
            f"Данные OpenDota.</div></div>")
    render_index.page(OUT, "Сыгранные матчи Dota 2", "Сыгранные серии и карты по турнирам и датам", "played",
                      lead + ("".join(body) or "<p>Сыгранных матчей пока нет.</p>"), extra_css=CSS)


if __name__ == "__main__":
    render_page()
