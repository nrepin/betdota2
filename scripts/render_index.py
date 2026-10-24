"""Страницы-навигаторы: index.html (все турниры: команды и их общая статистика)
и tournaments/<league>.html (страница турнира: анализ, сетка, команды турнира).

Использование (вызывается из collect_team.py автоматически):
    python scripts/render_index.py
"""
import datetime
import json
import time
from html import escape as e

import aggregate
import render_match
from render_bracket import BRACKET_CSS, BRACKET_JS, bracket_parts
from render_schedule import SCHEDULE_CSS, schedule_html
from render_html import CSS, INDEX, ROOT, head, league_page, logo_cls, rel, team_logo

INDEX_CSS = """
.teams{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:16px}
a.team{display:flex;gap:16px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px;color:inherit;text-decoration:none;transition:border-color .2s,background-color .2s}
a.team:hover{border-color:color-mix(in srgb,var(--text) 35%,transparent);background:var(--hover)}
a.team:active{transform:scale(.98)}
.team .logo{width:64px;height:64px;object-fit:contain;flex:none}
.team .logo.dark{background:#111;border-radius:12px;padding:6px}
.team .nologo{width:64px;height:64px;border-radius:12px;background:var(--line);display:grid;place-items:center;font-weight:700;flex:none}
.team .nm{font-size:16px;font-weight:650;letter-spacing:-.01em}
.team .st{font:11.5px/1.5 var(--mono);color:var(--muted);margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
a.team>div{min-width:0}
.team .wr{margin-top:8px;display:flex;align-items:center;gap:8px;font:600 12px var(--mono)}
.team .bar{flex:1;min-width:0}
.team.off{opacity:.5;pointer-events:none}
.nav{display:flex;flex-wrap:wrap;gap:4px;margin:16px 0 8px;background:var(--bar);padding:4px;border-radius:12px;width:100%}
.nav a{font-size:13px;font-weight:600;padding:7px 14px;border-radius:6px;color:var(--muted);text-decoration:none;
transition:background-color .2s,color .2s}
.nav a:hover{color:var(--text)}.nav a:active{transform:scale(.98)}
.nav a[aria-current=page]{background:var(--card);color:var(--text);box-shadow:var(--shadow)}
.an{display:inline-flex;align-items:center;gap:6px;margin-top:14px;padding:10px 18px;border-radius:6px;background:var(--accent);color:var(--on-accent);text-decoration:none;font-weight:650;transition:transform .15s,opacity .2s}.an:hover{opacity:.88}.an:active{transform:scale(.98)}
.nav a.right{margin-left:auto}.nav a.arch{opacity:.55}.nav a.arch[aria-current=page]{opacity:1}
.tours{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:12px}
a.tour-c{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;color:inherit;text-decoration:none;
transition:border-color .2s,background-color .2s}
a.tour-c:hover{border-color:color-mix(in srgb,var(--text) 35%,transparent);background:var(--hover)}a.tour-c:active{transform:scale(.98)}
a.tour-c.arch{opacity:.55}a.tour-c.arch:hover{opacity:.9}
.tour-c .nm{font-size:16px;font-weight:650;letter-spacing:-.01em;margin:8px 0 4px}
.tour-c .st{font:11.5px/1.5 var(--mono);color:var(--muted)}
.badge{display:inline-block;font:600 11px var(--mono);text-transform:uppercase;letter-spacing:.05em;padding:3px 8px;border-radius:6px;background:var(--bar);color:var(--muted)}
.badge.live{background:var(--accent);color:var(--on-accent)}
.grp-h{margin:24px 0 0;font-size:13px;font-weight:600;color:var(--muted)}
.page-h{margin-top:28px}.page-h h2{margin:0;font-size:26px;letter-spacing:-.02em}
"""


def leagues():
    """[(league_id, name)] — новые турниры первыми."""
    out = []
    for p in sorted((p for p in (ROOT / "data").iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        out.append((p.name, json.loads((ROOT / "raw" / f"league_{p.name}.json").read_text(encoding="utf-8"))["name"]))
    return out


CURRENT_DAYS = 3


def league_info(lid):
    """Текущий турнир — если последний матч был не раньше CURRENT_DAYS суток назад (или ещё впереди), иначе архив."""
    ms = json.loads((ROOT / "raw" / f"league_{lid}_matches.json").read_text(encoding="utf-8"))
    ts = [m["start_time"] for m in ms] or [0]
    cur = max(ts) > time.time() - CURRENT_DAYS * 86400
    fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime("%d.%m.%Y")
    return {"current": cur, "from": fmt(min(ts)), "to": fmt(max(ts)), "maps": len(ms)}


def nav(active, out):
    """Вкладки-ссылки: Все турниры + каждый турнир (отдельные адреса)."""
    items = [("all", "Все турниры", INDEX)] + [(lid, name, league_page(lid)) for lid, name in leagues()
                                                 if league_info(lid)["current"] or lid == active] + [("forecasts", "Прогнозы ИИ", ROOT / "forecasts.html"), ("heroes", "Герои", ROOT / "heroes.html")]
    def a(key, name, path):
        arch = key not in ("all", "heroes", "forecasts") and not league_info(key)["current"]
        cur = " aria-current=page" if key == active else ""
        cls = " class=arch" if arch else " class=right" if key == "forecasts" else ""
        return f"<a href='{e(rel(path, out))}'{cur}{cls}>{e(name)}</a>"

    return "<nav class=nav aria-label='Турниры'>" + "".join(a(*x) for x in items) + "</nav>"


def tournaments_block(out):
    """Блок на главной: текущие турниры и архив (архив бледнее)."""
    infos = [(lid, name, league_info(lid)) for lid, name in leagues()]
    parts = []
    for title, cur in (("Текущие турниры", True), ("Архивные турниры", False)):
        group = [x for x in infos if x[2]["current"] == cur]
        if not group:
            continue
        cards = "".join(
            f"<a class='tour-c{'' if cur else ' arch'}' href='{e(rel(league_page(lid), out))}'>"
            f"<span class='badge{' live' if cur else ''}'>{'идёт' if cur else 'архив'}</span>"
            f"<div class=nm>{e(name)}</div><div class=st>{i['from']} – {i['to']} · {i['maps']} карт</div></a>"
            for lid, name, i in group)
        parts.append(f"<h3 class=grp-h>{title}</h3><div class=tours>{cards}</div>")
    return "".join(parts)


def card(tid, name, s, href, out, first_line):
    logo = team_logo(tid)
    img = (f"<img class={logo_cls(tid)} src='{e(rel(logo, out))}' alt='Логотип {e(name)}' loading=lazy>" if logo
           else f"<div class=nologo>{e(name[:3])}</div>")
    return (f"<a class=team href='{e(href)}'>{img}<div style='flex:1;min-width:0'>"
            f"<div class=nm>{e(name)}</div><div class=st>{first_line}</div>"
            f"<div class=st>{s['avg_duration']} · фраги {s['avg_kills_for']}:{s['avg_kills_against']} ({s['avg_total_kills']})</div>"
            f"<div class=wr><div class=bar><span style='width:{s['winrate']}%'></span></div>{s['winrate']:.0f}%</div>"
            f"</div></a>")


def page(out, title, description, active, body, js="", extra_css=""):
    out.parent.mkdir(parents=True, exist_ok=True)
    html = (head(title, description) + f"<style>{CSS}{INDEX_CSS}{BRACKET_CSS}{SCHEDULE_CSS}{extra_css}</style></head><body><main class=wrap>"
            + "<h1>Статистика команд Dota 2</h1>" + nav(active, out) + body + f"</main><script>{js}</script></body></html>")
    out.write_text(html, encoding="utf-8")
    print(out)


def series_won(s):
    return sum(x["won"] for x in s["series"])


def render_all():
    """index.html: только команды и их статистика за все турниры."""
    out = INDEX
    agg = aggregate.all_teams()
    n = len(leagues())
    body = [f"<div class=page-h><h2>Все турниры</h2><div class=sub>{len(agg)} команд, {n} "
            f"{'турнир' if n == 1 else 'турниров'}. Статистика по всем сыгранным картам</div></div>", tournaments_block(out), "<h3 class=grp-h>Команды</h3><div class=teams>"]
    for t in sorted(agg.values(), key=lambda t: (-series_won(t["summary"]), -t["summary"]["winrate"], t["team"].lower())):
        s = t["summary"]
        body.append(card(t["team_id"], t["team"], s, rel(ROOT / "reports" / "all" / f"{t['stem']}.html", out), out,
                         f"Турниров {len(t['leagues'])}, серии {s['series_record']}, карты {s['wins']}-{s['losses']}"))
    body.append("</div>")
    page(out, "Статистика команд Dota 2", "Статистика команд Dota 2 за все турниры: карты, фраги, винрейт", "all", "".join(body))


def render_league(lid, name):
    """tournaments/<lid>.html: анализ, турнирная сетка, команды турнира."""
    out = league_page(lid)
    teams = json.loads((ROOT / "raw" / f"league_{lid}_teams.json").read_text(encoding="utf-8"))
    data = {}
    for f in (ROOT / "data" / lid).glob("*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        data[t["team_id"]] = (t, f.stem)

    def order(team):
        if team["team_id"] not in data:
            return (1, 0, 0, team["name"].lower())
        s = data[team["team_id"]][0]["summary"]
        return (0, -series_won(s), -s["winrate"], team["name"].lower())

    body = [f"<div class=page-h><h2>{e(name)}</h2><div class=sub>{len(teams)} команд, данные OpenDota, "
            f"<a href='https://www.dotabuff.com/esports/leagues/{lid}'>Dotabuff</a></div></div>"]
    an = ROOT / "reports" / lid / "analysis.html"
    if an.exists():
        body.append(f"<a class=an href='{e(rel(an, out))}'>Анализ плей-офф →</a>")
    b_top, b_rest = bracket_parts(lid, out)
    render_match.build(lid)
    body.append(schedule_html(lid, out))
    body.append("<div class=bsec><h3>Команды</h3></div><div class=teams>")
    for team in sorted(teams, key=order):
        if team["team_id"] in data:
            t, stem = data[team["team_id"]]
            s = t["summary"]
            body.append(card(team["team_id"], team["name"], s, rel(ROOT / "reports" / lid / f"{stem}.html", out), out,
                             f"Серии {s['series_record']}, карты {s['wins']}-{s['losses']}"))
        else:
            logo = team_logo(team["team_id"])
            img = (f"<img class={logo_cls(team['team_id'])} src='{e(rel(logo, out))}' alt='Логотип {e(team['name'])}'>" if logo
                   else f"<div class=nologo>{e((team.get('tag') or team['name'])[:3])}</div>")
            body.append(f"<a class='team off'>{img}<div><div class=nm>{e(team['name'])}</div>"
                        f"<div class=st>статистика не собрана</div></div></a>")
    body.append("</div>" + b_top + b_rest)
    page(out, f"{name}: турнир, сетка и команды", f"{name}: турнирная сетка, анализ плей-офф и статистика команд",
         lid, "".join(body), BRACKET_JS)


def main():
    import heroes_stats
    render_all()
    heroes_stats.render_page()
    import render_forecasts
    render_forecasts.render_page()
    for lid, name in leagues():
        render_league(lid, name)


if __name__ == "__main__":
    main()
