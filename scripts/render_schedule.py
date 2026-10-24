"""Таблица серий и ближайшее расписание для страницы турнира.

Результаты считаются из raw/league_<id>_matches.json (OpenDota), расписание берётся из линии PARI
(открытый JSON-API, только чтение) и сохраняется в odds/<league>/schedule.json.
Настройка турнира: analysis/<league>.schedule.json
    {"pari_segment": "PARI Universe", "aliases": {"1w team": "1win"}, "bo": 3}
aliases — как PARI называет команду -> название в лиге (если нормализованные имена не совпали).

    python scripts/render_schedule.py --league 20395      # обновить расписание и пересобрать страницы
"""
import argparse
import datetime
import json
from collections import defaultdict
from html import escape as e

from collect_odds import API, get, norm
from render_html import ROOT, logo_cls, rel, team_logo

MSK = datetime.timezone(datetime.timedelta(hours=3))
DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

SCHEDULE_CSS = """
.sch-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;align-items:start}
.sch-box{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.sch-box table{width:100%;border-collapse:collapse;font-size:13.5px}
.sch-box th{font:600 11.5px var(--mono);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);text-align:left;padding:10px 12px;border-bottom:1px solid var(--line)}
.sch-box td{padding:9px 12px;border-bottom:1px solid var(--line)}.sch-box tr:last-child td{border-bottom:0}
.sch-box td.n,.sch-box th.n{text-align:right;font-family:var(--mono);white-space:nowrap}
.sch-box .tm{display:flex;align-items:center;gap:8px;color:inherit;text-decoration:none;font-weight:600}
.sch-box .tm img{width:22px;height:22px;object-fit:contain}.sch-box .tm img.dark{background:#111;border-radius:4px;padding:2px}
.sch-box a.tm:hover span{text-decoration:underline}
.sch-box tr.dim td{color:var(--muted)}
.sch-day{padding:8px 12px;font:600 11.5px var(--mono);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);background:var(--hover);border-bottom:1px solid var(--line)}
.sch-m{display:grid;grid-template-columns:54px 1fr;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid var(--line)}
.sch-m:last-child{border-bottom:0}.sch-m time{font:600 13px var(--mono)}
.sch-m .vs{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}.sch-m .vs i{font-style:normal;color:var(--muted);font-size:12px}
.sch-m.live time{color:var(--win)}.sch-m .live-b{font:600 11px var(--mono);color:var(--win);margin-left:auto}
.sch-m{color:inherit;text-decoration:none}a.sch-m:hover{background:var(--hover)}a.sch-m:active{transform:scale(.995)}
.sch-m .sc{font-family:var(--mono)}
.sch-note{font-size:12.5px;color:var(--muted);margin-top:8px;max-width:80ch}
"""


def cfg(lid):
    f = ROOT / "analysis" / f"{lid}.schedule.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def teams_of(lid):
    return {t["team_id"]: t for t in json.loads((ROOT / "raw" / f"league_{lid}_teams.json").read_text(encoding="utf-8"))}


def fetch(lid):
    c = cfg(lid)
    teams = teams_of(lid)
    byname = {norm(t["name"]): t for t in teams.values()}
    byname.update({norm(k): byname[norm(v)] for k, v in c.get("aliases", {}).items() if norm(v) in byname})
    base = get(f"{API}/events/listBase?lang=ru&scopeMarket=2300")
    segs = {s["id"]: s["name"] for s in base["sports"]
            if "Dota" in s.get("name", "") and c["pari_segment"].lower() in s["name"].lower()}
    out = []
    for ev in base["events"]:
        if ev.get("sportId") not in segs or ev.get("level") != 1 or not ev.get("team2"):
            continue
        a, b = byname.get(norm(ev["team1"])), byname.get(norm(ev["team2"]))
        if not a or not b:
            print("  не сопоставлено:", ev["team1"], "-", ev["team2"])
            continue
        out.append({"event_id": ev["id"], "start": ev["startTime"], "a": a["team_id"], "b": b["team_id"],
                    "url": f"https://pari.ru/esports/category/dota2/{ev['sportId']}/{ev['id']}"})
    d = ROOT / "odds" / lid
    d.mkdir(parents=True, exist_ok=True)
    old = d / "schedule.json"
    if old.exists():  # матчи, ушедшие из линии после игры, остаются в истории
        seen = {m["event_id"] for m in out}
        out += [m for m in json.loads(old.read_text(encoding="utf-8"))["matches"] if m.get("event_id") and m["event_id"] not in seen]
    out.sort(key=lambda x: x["start"])
    snap = {"fetched": datetime.datetime.now(MSK).strftime("%Y-%m-%d %H:%M"), "matches": out}
    (d / "schedule.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return snap


def series_results(lid, bo):
    """series_id -> {w: {team_id: выигранные карты}, teams, done}"""
    ms = json.loads((ROOT / "raw" / f"league_{lid}_matches.json").read_text(encoding="utf-8"))
    ser = defaultdict(lambda: {"w": defaultdict(int), "teams": set(), "maps": []})
    need = bo // 2 + 1
    for m in ms:
        r, d = m.get("radiant_team_id"), m.get("dire_team_id")
        if not r or not d:
            continue
        s = ser[m["series_id"]]
        s["teams"] |= {r, d}
        winner, loser = (r, d) if m["radiant_win"] else (d, r)
        s["w"][loser] += 0
        s["w"][winner] += 1
        s["maps"].append(m)
    for s in ser.values():
        s["done"] = max(s["w"].values()) >= need
        s["maps"].sort(key=lambda m: m["start_time"])
        s["start"] = s["maps"][0]["start_time"]
    return ser


def find_series(ser, a, b, start):
    """Серия пары команд, начавшаяся не раньше чем за 3 часа до времени матча в линии."""
    best = [s for s in ser.values() if s["teams"] == {a, b} and s["start"] >= start - 3 * 3600]
    return min(best, key=lambda s: s["start"]) if best else None


def _team(tid, teams, out, link):
    name = teams.get(tid, {}).get("name", str(tid))
    logo = team_logo(tid)
    img = f"<img class={logo_cls(tid)} src='{e(rel(logo, out))}' alt='' loading=lazy>" if logo else ""
    inner = f"{img}<span>{e(name)}</span>"
    return f"<a class=tm href='{e(link)}'>{inner}</a>" if link else f"<span class=tm>{inner}</span>"


def schedule_html(lid, out):
    c = cfg(lid)
    if not c:
        return ""
    teams = teams_of(lid)
    bo = c.get("bo", 3)
    ser = series_results(lid, bo)
    stems = {}
    for f in (ROOT / "data" / lid).glob("*.json"):
        stems[json.loads(f.read_text(encoding="utf-8"))["team_id"]] = f.stem

    def link(tid):
        return rel(ROOT / "reports" / lid / f"{stems[tid]}.html", out) if tid in stems else ""

    row = {tid: {"sw": 0, "sl": 0, "mw": 0, "ml": 0} for tid in teams}
    for s in ser.values():
        for tid in s["teams"]:
            r = row.setdefault(tid, {"sw": 0, "sl": 0, "mw": 0, "ml": 0})
            mine = s["w"][tid]
            other = sum(v for k, v in s["w"].items() if k != tid)
            r["mw"] += mine
            r["ml"] += other
            if s["done"]:
                r["sw" if mine > other else "sl"] += 1
    order = sorted(row, key=lambda t: (-row[t]["sw"], row[t]["sl"], -(row[t]["mw"] - row[t]["ml"]),
                                       teams.get(t, {}).get("name", "").lower()))
    tb = ["<div class=sch-box><table><thead><tr><th>#</th><th>Команда</th><th class=n>Серии</th>"
          "<th class=n>Карты</th><th class=n>±</th></tr></thead><tbody>"]
    for i, tid in enumerate(order, 1):
        r = row[tid]
        dim = " class=dim" if not any(r.values()) else ""
        tb.append(f"<tr{dim}><td>{i}</td><td>{_team(tid, teams, out, link(tid))}</td><td class=n>{r['sw']}–{r['sl']}</td>"
                  f"<td class=n>{r['mw']}–{r['ml']}</td><td class=n>{r['mw'] - r['ml']:+d}</td></tr>")
    tb.append("</tbody></table></div>")

    snap_f = ROOT / "odds" / lid / "schedule.json"
    snap = json.loads(snap_f.read_text(encoding="utf-8")) if snap_f.exists() else {"matches": [], "fetched": "—"}
    now = datetime.datetime.now(MSK).timestamp()
    from forecast import load as load_fc
    sch, fin, day = [], [], None
    for m in snap["matches"]:
        sr = find_series(ser, m["a"], m["b"], m["start"])
        href = rel(ROOT / "matches" / lid / f"{m['event_id']}.html", out) if m.get("event_id") else ""
        tag, close = (f"a class='sch-m{{c}}' href='{e(href)}'", "a") if href else ("div class='sch-m{c}'", "div")
        if sr and sr["done"]:
            fc = load_fc(lid, str(m.get("event_id")))
            hits = [p["hit"] for p in fc["picks"] if p["hit"] is not None] if fc else []
            mk = f"<span class=live-b>прогноз {sum(hits)}/{len(hits)}</span>" if hits else ""
            dt = datetime.datetime.fromtimestamp(m["start"], MSK)
            fin.append(f"<{tag.format(c='')}><time>{dt:%d.%m}</time><div class=vs>{_team(m['a'], teams, out, '')}"
                       f"<b class=sc>{sr['w'][m['a']]}:{sr['w'][m['b']]}</b>{_team(m['b'], teams, out, '')}{mk}</div></{close}>")
            continue
        if m["start"] < now - 6 * 3600:
            continue
        dt = datetime.datetime.fromtimestamp(m["start"], MSK)
        key = dt.strftime("%d.%m")
        if key != day:
            day = key
            sch.append(f"<div class=sch-day>{key}, {DAYS[dt.weekday()]}</div>")
        live = m["start"] <= now
        sch.append(f"<{tag.format(c=' live' if live else '')}><time>{dt:%H:%M}</time><div class=vs>"
                   f"{_team(m['a'], teams, out, '')}<i>vs</i>{_team(m['b'], teams, out, '')}"
                   f"{'<span class=live-b>идёт</span>' if live else ''}</div></{close}>")
    if not sch:
        sch.append("<div class=sch-m><div class=vs><i>Ближайших матчей в линии нет</i></div></div>")
    if fin:
        sch.append("<div class=sch-day>Сыгранные</div>" + "".join(reversed(fin)))
    note = (f"Время МСК. Клик по матчу — коэффициенты, прогноз ИИ и результат. Расписание — из линии PARI на {snap['fetched']} МСК, показаны только открытые букмекером матчи. "
            f"Серии Bo{bo}. Обновить: <code>python scripts/render_schedule.py --league {lid}</code>")
    return ("<div class=bsec><h3>Таблица и расписание</h3></div><div class=sch-grid>" + "".join(tb)
            + f"<div class=sch-box>{''.join(sch)}</div></div><div class=sch-note>{note}</div>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    a = ap.parse_args()
    snap = fetch(a.league)
    print(f"расписание: {len(snap['matches'])} матчей")
    import render_index
    render_index.main()


if __name__ == "__main__":
    main()
