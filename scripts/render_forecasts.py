"""Страница «Прогнозы ИИ» (forecasts.html): условный учёт ставок по сохранённым прогнозам.

Ставка по прогнозу: перевес «явный» — 200 $, «небольшой» — 100 $ (STAKES). Это бухгалтерия прогнозов,
реальные ставки не делаются. Выигрыш = ставка × (коэффициент − 1), проигрыш = −ставка. Прогноз — один на карту, в её начале (герои обеих команд выбраны).

    python scripts/render_forecasts.py
"""
import datetime
import json
from collections import defaultdict
from html import escape as e

from render_html import ROOT, SORT_JS, rel

OUT = ROOT / "forecasts.html"
STAKES = {"явный": 200, "небольшой": 100, "слабый": 50}
MSK = datetime.timezone(datetime.timedelta(hours=3))
CATS = {"win": "Победа на карте", "time": "Время карты", "kills": "Убийства"}

CSS = """
.fk{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:16px}
.fk .k{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.fk .k .l{font-size:12.5px;color:var(--muted)}.fk .k .v{font:650 24px var(--mono);margin-top:4px}.fk .k .s{font-size:12px;color:var(--muted);margin-top:2px}
.pos{color:var(--win)}.neg{color:var(--loss)}
.fbox{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:10px}
.fbox table{width:100%;border-collapse:collapse;font-size:13.5px}
.fbox th{font:600 11.5px var(--mono);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.fbox td{padding:9px 12px;border-bottom:1px solid var(--line)}.fbox tr:last-child td{border-bottom:0}
.fbox td.n,.fbox th.n{text-align:right;font-family:var(--mono);white-space:nowrap}
.fbox a{color:inherit}.fbox tr.out td{color:var(--muted)}
.fgrid{display:grid;grid-template-columns:minmax(0,1fr);gap:16px;align-items:start}
.fgrid .fbox{margin-top:0;overflow-x:auto}
.fgrid .fbox th,.fgrid .fbox td{padding:9px 6px;font-size:13px}.fgrid .fbox td:first-child,.fgrid .fbox th:first-child{padding-left:12px;white-space:normal}.fgrid .fbox th{letter-spacing:.02em}

"""


def money(v):
    return f"{v:+,.0f} $".replace(",", " ")


def cls(v):
    return "pos" if v > 0 else "neg" if v < 0 else ""


def collect():
    rows = []
    for f in sorted((ROOT / "forecasts").glob("*/*.json")):
        fc = json.loads(f.read_text(encoding="utf-8"))
        if not fc.get("live_bet"):
            continue  # доматчевых прогнозов больше нет: старые файлы в учёт не идут
        lname = json.loads((ROOT / "raw" / f"league_{fc['league']}.json").read_text(encoding="utf-8"))["name"]
        for p in fc["picks"]:
            stake = p.get("stake") or STAKES.get(p["signal"], 100)
            profit = None if p["hit"] is None else (stake * (p["odds"] - 1) if p["hit"] else -stake)
            rows.append({"fc": fc, "league": lname, "p": p, "stake": stake, "profit": profit,
                         "counted": True, "live": True})
    rows.sort(key=lambda r: r["fc"]["start"], reverse=True)
    return rows


def agg(rows):
    done = [r for r in rows if r["counted"] and r["profit"] is not None]
    st = sum(r["stake"] for r in done)
    pr = sum(r["profit"] for r in done)
    return {"n": len(done), "hit": sum(1 for r in done if r["p"]["hit"]), "stake": st, "profit": pr,
            "roi": pr / st if st else 0}


def render_page():
    import render_index
    rows = collect()
    t = agg(rows)
    pending = [r for r in rows if r["counted"] and r["profit"] is None]
    out_of = [r for r in rows if not r["counted"]]
    body = [f"<div class=page-h><h2>Прогнозы ИИ</h2><div class=sub>Условный учёт: перевес «явный» — 200 $, «небольшой» — 100 $, «слабый» — 50 $ "
            f"на прогноз. Реальные ставки не делаются. Выигрыш = ставка × (коэффициент − 1), проигрыш = −ставка. "
            f"Один прогноз на каждую карту, в её начале, когда выбраны герои обеих команд: победа, время или убийства.</div></div>"]
    hr = f"{t['hit'] / t['n']:.0%}" if t["n"] else "—"
    body.append(
        "<div class=fk>"
        f"<div class=k><div class=l>Прибыль</div><div class='v {cls(t['profit'])}'>{money(t['profit'])}</div><div class=s>ROI {t['roi']:+.0%}</div></div>"
        f"<div class=k><div class=l>Поставлено</div><div class=v>{t['stake']:,.0f} $</div><div class=s>{t['n']} ставок рассчитано</div></div>"
        f"<div class=k><div class=l>Зашло</div><div class=v>{t['hit']} из {t['n']}</div><div class=s>{hr}</div></div>"
        f"<div class=k><div class=l>Ждут результата</div><div class=v>{len(pending)}</div><div class=s>{sum(r['stake'] for r in pending):,.0f} $ в игре</div></div>"
        "</div>".replace(",", " "))

    def table(title, groups):
        h = [f"<div class=fbox><table><thead><tr><th>{title}</th><th class=n>Ставок</th><th class=n>Зашло</th>"
             "<th class=n>Поставлено</th><th class=n>Прибыль</th><th class=n>ROI</th></tr></thead><tbody>"]
        for name, rs in groups:
            a = agg(rs)
            h.append(f"<tr><td>{e(name)}</td><td class=n>{a['n']}</td><td class=n>{a['hit']}</td>"
                     f"<td class=n>{a['stake']:,.0f}</td><td class='n {cls(a['profit'])}'>{money(a['profit'])}</td>"
                     f"<td class='n {cls(a['roi'])}'>{a['roi']:+.0%}</td></tr>".replace(",", " "))
        h.append("</tbody></table></div>")
        return "".join(h)

    by_cat = [(CATS[c], [r for r in rows if r["p"]["cat"] == c]) for c in CATS]
    by_sig = [(f"{s} · {v} $", [r for r in rows if r["p"]["signal"] == s]) for s, v in STAKES.items()]
    by_lg = defaultdict(list)
    for r in rows:
        by_lg[r["league"]].append(r)
    body.append("<h3 class=grp-h>Разрезы</h3><div class=fgrid>" + table("Рынок", by_cat) + table("Перевес", by_sig)
                + table("Турнир", sorted(by_lg.items())) + "</div>")

    body.append("<h3 class=grp-h>Все ставки</h3><div class=fbox><table class=sortable><thead><tr><th>Матч</th><th>Прогноз</th>"
                "<th class=n>Коэф</th><th class=n>Ставка</th><th>Результат</th><th class=n>Прибыль</th></tr></thead><tbody>")
    for r in rows:
        fc, p = r["fc"], r["p"]
        href = rel(ROOT / "matches" / fc["league"] / f"{fc.get('match_event_id', fc['event_id'])}.html", OUT)
        d = datetime.datetime.fromtimestamp(fc["start"], MSK).strftime("%d.%m")
        res = "ждём" if p["hit"] is None else "✓ зашло" if p["hit"] else "✗ не зашло"
        live = ""
        if fc.get("result"):
            mid = fc["result"]["match_id"]
            res += (f"<div style='font-size:12px'><a href='https://www.dotabuff.com/matches/{mid}'>Dotabuff</a> · "
                    f"{fc['result']['duration']:g} мин, {fc['result']['kills']} уб.</div>")
        if fc.get("url"):
            res += f"<div style='font-size:12px'><a href='{e(fc['url'])}'>PARI</a></div>"
        pr = "—" if r["profit"] is None else money(r["profit"])
        body.append(f"<tr class='{'' if r['counted'] else 'out'}'><td><a href='{e(href)}'>{d} {e(fc['t1'])} – {e(fc['t2'])}</a>"
                    f"<div class=muted style='font-size:12px'>{e(r['league'])}, карта {fc['map_no']}{live}</div></td>"
                    f"<td>{e(p['text'])}<div class=muted style='font-size:12px'>перевес: {e(p['signal'])}</div></td>"
                    f"<td class=n>{p['odds']}</td><td class=n>{r['stake']}</td><td>{res}</td>"
                    f"<td class='n {cls(r['profit'] or 0)}' data-v='{r['profit'] or 0}'>{pr}</td></tr>")
    if not rows:
        body.append("<tr><td colspan=6>Прогнозов пока нет.</td></tr>")
    body.append("</tbody></table></div>")
    render_index.page(OUT, "Прогнозы ИИ: учёт ставок", "Условный учёт ставок по прогнозам ИИ: прибыль, ROI, попадания",
                      "forecasts", "".join(body), SORT_JS, extra_css=CSS)


if __name__ == "__main__":
    render_page()
