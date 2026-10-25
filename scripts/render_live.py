"""Страница «Лайв» (live.html) и пункт меню: идущие сейчас матчи (старт в расписании PARI наступил, серия не завершена).
Пункт меню показывается, только если такие матчи есть.

    python scripts/render_live.py
"""
import datetime
import json
import time
from html import escape as e

from render_html import ROOT, logo_cls, rel, team_logo
from render_schedule import cfg, find_series, series_results, teams_of

OUT = ROOT / "live.html"
MSK = datetime.timezone(datetime.timedelta(hours=3))
MAX_AGE = 8 * 3600     # матч, у которого старт был давнее, лайвом не считается
_cache = {}


def reset():
    _cache.clear()


def live_matches():
    """[{lid, name, eid, a, b, na, nb, score, map_no, start}] — идущие матчи, ближайшие по старту первыми."""
    if "m" in _cache:
        return _cache["m"]
    now = time.time()
    out = []
    for d in sorted((ROOT / "data").iterdir()):
        lid = d.name
        sf = ROOT / "odds" / lid / "schedule.json"
        if not sf.exists() or not cfg(lid):
            continue
        teams, ser = teams_of(lid), series_results(lid, cfg(lid).get("bo", 3))
        lname = json.loads((ROOT / "raw" / f"league_{lid}.json").read_text(encoding="utf-8"))["name"]
        for ev in json.loads(sf.read_text(encoding="utf-8"))["matches"]:
            if not ev.get("event_id") or ev["start"] > now or ev["start"] < now - MAX_AGE:
                continue
            s = find_series(ser, ev["a"], ev["b"], ev["start"])
            if s and s["done"]:
                continue
            out.append({"lid": lid, "league": lname, "eid": ev["event_id"], "a": ev["a"], "b": ev["b"],
                        "na": teams.get(ev["a"], {}).get("name", str(ev["a"])), "nb": teams.get(ev["b"], {}).get("name", str(ev["b"])),
                        "score": (s["w"].get(ev["a"], 0), s["w"].get(ev["b"], 0)) if s else (0, 0),
                        "map_no": (len(s["maps"]) + 1) if s else 1, "start": ev["start"]})
    out.sort(key=lambda m: m["start"])
    _cache["m"] = out
    return out


CSS = """
.lv{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px;margin-top:12px}
a.lv-c{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;color:inherit;text-decoration:none;
transition:border-color .2s,background-color .2s}a.lv-c:hover{border-color:color-mix(in srgb,var(--text) 35%,transparent);background:var(--hover)}
.lv-c .tt{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:10px}
.lv-c .tm{display:flex;align-items:center;gap:8px;font-weight:650;min-width:0}.lv-c .tm img{width:28px;height:28px;object-fit:contain}
.lv-c .tm img.dark{background:#111;border-radius:6px;padding:2px}.lv-c .sc{font:700 20px var(--mono)}
.lv-c .st{font:11.5px/1.5 var(--mono);color:var(--muted);margin-top:8px}
"""


def team_html(tid, name):
    logo = team_logo(tid)
    img = f"<img class={logo_cls(tid)} src='{e(rel(logo, OUT))}' alt='' loading=lazy>" if logo else ""
    return f"<span class=tm>{img}<span>{e(name)}</span></span>"


def render_page():
    import render_index
    ms = live_matches()
    cards = []
    for m in ms:
        pg = ROOT / "matches" / m["lid"] / f"{m['eid']}.html"
        start = datetime.datetime.fromtimestamp(m["start"], MSK).strftime("%H:%M")
        cards.append(f"<a class=lv-c href='{e(rel(pg, OUT))}'><span class='badge live'>идёт</span>"
                     f"<div class=tt>{team_html(m['a'], m['na'])}<span class=sc>{m['score'][0]}:{m['score'][1]}</span>{team_html(m['b'], m['nb'])}</div>"
                     f"<div class=st>{e(m['league'])} · карта {m['map_no']} · старт {start} МСК</div></a>")
    body = ("<div class=page-h><h2>Лайв</h2><div class=sub>Матчи, которые идут сейчас: старт по расписанию наступил, серия не закончена. "
            "Герои и прогнозы — на странице матча.</div></div>"
            + (f"<div class=lv>{''.join(cards)}</div>" if cards else "<p>Сейчас матчей нет.</p>"))
    render_index.page(OUT, "Лайв: идущие матчи Dota 2", "Идущие сейчас матчи Dota 2", "live", body, extra_css=CSS)


if __name__ == "__main__":
    render_page()
