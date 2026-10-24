"""Страница анализа турнира и тизер для главной.

Входные файлы (пишутся руками):
    analysis/<league_id>.json — сетка плей-офф: команды (цвет, слоган), матчи (стадия, a, b, оценка шансов pa в %)
    analysis/<league_id>.html — текст анализа (фрагмент без <html>). Плейсхолдеры:
        <!--bracket-->            шапка с сеткой из json
        <!--compare:id1,id2,...--> сравнение команд полосами (считается из data/)
        <!--totals:id1,id2,...-->  калькулятор тоталов по времени и убийствам
Результат: reports/<league_id>/analysis.html; на index.html — блок с сеткой и кнопкой (teaser()).

Использование (вызывается из collect_team.py автоматически):
    python scripts/render_analysis.py
"""
import json
import re
from html import escape as e

from collect_odds import ODDS_CSS, odds_html
from render_html import CSS, DARK_LOGO, INDEX, ROOT, TOTALS_CSS, head, league_page, rel

ANALYSIS_CSS = """
.banner{position:relative;border-radius:12px;padding:28px 24px 24px;margin-top:4px;background:var(--card);border:1px solid var(--line)}
.banner h1{font-size:34px;line-height:1.1;letter-spacing:-.03em;max-width:760px}
.banner .lead{color:var(--muted);margin-top:8px;max-width:65ch}
.banner .tourb{display:inline-block;margin-bottom:12px;padding:3px 10px;border-radius:6px;background:var(--bar);font-size:12.5px;font-weight:600}
.bracket{display:grid;grid-template-columns:1fr 1fr;gap:1px;margin-top:22px;background:var(--line);border:1px solid var(--line);border-radius:12px;overflow:hidden}
@media (max-width:800px){.bracket{grid-template-columns:1fr}}
.mcard{background:var(--card);padding:16px}
.mcard .st{font-size:12.5px;font-weight:600;color:var(--muted)}
.mcard .row{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:12px 0 10px}
.mcard .tm{display:flex;flex-direction:column;align-items:center;gap:6px;flex:1;text-align:center;font-weight:650;color:var(--text);text-decoration:none;transition:color .2s}
.mcard .tm:hover{color:var(--muted)}.mcard .tm:active{transform:scale(.98)}
.mcard .tm img{width:64px;height:64px;object-fit:contain}
.mcard .tm img.dark{background:#111;border-radius:12px;padding:6px}
.mcard .tm .q{width:64px;height:64px;border-radius:12px;border:1.5px dashed var(--v-axis);display:grid;place-items:center;font-size:24px;color:var(--muted)}
.mcard .x{font-weight:600;color:var(--muted);font-size:14px}
.mcard .nt{font-size:13px;color:var(--muted);text-align:center}
.prob{display:flex;gap:2px;height:26px;font-size:12px;font-weight:600;margin-top:10px}
.prob span{display:flex;align-items:center;padding:0 10px;color:#0b0b0b;white-space:nowrap;min-width:0}
.prob span:first-child{border-radius:6px 0 0 6px}.prob span:last-child{justify-content:flex-end;border-radius:0 6px 6px 0}
.scn{font-size:12px;color:var(--muted);margin-top:10px}
.sec{margin-top:36px}.sec>h2{margin:0 0 4px;font-size:22px}.sec>.muted{margin-bottom:14px}
.cmpbars{display:grid;gap:10px}
.metric{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.metric .ml{font-size:12.5px;color:var(--muted);font-weight:600;margin-bottom:8px}
.mrow{display:grid;grid-template-columns:120px 1fr 90px;align-items:center;gap:10px;margin:5px 0;font-size:13px}
.mrow .nm{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mrow .tr{height:10px;border-radius:5px;background:var(--line);overflow:hidden;position:relative}
.mrow .tr.div::after{content:"";position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--v-axis)}
.mrow .sw{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;vertical-align:0}
.mrow .fl{height:100%;border-radius:0 4px 4px 0}
.mrow .tr.div .fl[style*="right"]{border-radius:4px 0 0 4px}
.mrow .vl{text-align:right;font-variant-numeric:tabular-nums;font-weight:650}
.mrow.best .vl::after{content:" ★";color:#f59e0b}
.tcards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media (max-width:900px){.tcards{grid-template-columns:1fr}}
.tcard{background:var(--card);border:1px solid var(--line);border-top:4px solid var(--tc);border-radius:12px;padding:16px}
.tcard .th{display:flex;align-items:center;gap:12px;margin-bottom:4px}
.tcard .th img{width:48px;height:48px;object-fit:contain}.tcard .th img.dark{background:#111;border-radius:12px;padding:5px}
.tcard .th a{font-size:18px;font-weight:750;color:inherit;text-decoration:none}
.tcard .tg{font-size:13px;color:var(--muted);margin-bottom:10px}
.tcard h4{margin:14px 0 6px;font-size:12.5px;letter-spacing:.06em}
.tcard ul{list-style:none;margin:0;padding:0}.tcard li{position:relative;padding-left:22px;margin:6px 0}
.tcard .pros li::before{content:"✓";position:absolute;left:0;color:var(--win);font-weight:900}
.tcard .cons li::before{content:"✕";position:absolute;left:0;color:var(--loss);font-weight:900}
.tcard h4.p{color:var(--win)}.tcard h4.c{color:var(--loss)}
.preview{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
.preview .ph{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.preview .ph img{width:40px;height:40px;object-fit:contain}.preview .ph img.dark{background:#000;border-radius:8px;padding:4px}
.preview .ph b{font-size:18px}
.keys{counter-reset:k;list-style:none;padding:0;margin:8px 0}
.keys li{counter-increment:k;position:relative;padding-left:36px;margin:10px 0}
.keys li::before{content:counter(k);position:absolute;left:0;top:-1px;width:24px;height:24px;border-radius:50%;background:var(--accent);color:var(--on-accent);font-size:12px;font-weight:800;display:grid;place-items:center}
.duo{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:800px){.duo{grid-template-columns:1fr}}
.verdict{margin-top:14px;padding:12px 14px;border-radius:10px;background:var(--bar);font-weight:500}
.verdict b{color:var(--accent)}
.facts{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.fact{border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:13px}
.note{font-size:12px;color:var(--muted);margin-top:28px}
.cta{position:relative;z-index:1;display:inline-block;margin-top:18px;padding:10px 20px;border-radius:10px;background:#fff;color:#0b0d14;font-weight:750;text-decoration:none}
.cta:hover{background:#e9d5ff}
.cmp{border-radius:14px}
.cmp .in{display:flex;gap:24px;flex-wrap:wrap;padding:16px;border-bottom:1px solid var(--line)}
.cmp label{display:block;font-size:12.5px;color:var(--muted);letter-spacing:.04em;font-weight:700;margin-bottom:4px}
.cmp input{font:inherit;font-size:22px;font-weight:700;width:120px;padding:8px 12px;border-radius:10px;border:2px solid var(--line);background:var(--bg);color:var(--text)}
.cmp input:focus{outline:none;border-color:var(--accent)}
.cmp td{padding:12px 16px}.cmp td b{font-size:16px;color:var(--text)}.cmp .ov,.cmp .un{color:var(--muted)}
.cmp .tn{display:flex;align-items:center;gap:10px}.cmp .tn i{width:10px;height:10px;border-radius:50%;background:var(--tc);flex:none}
.split{display:flex;gap:2px;height:8px;margin-top:6px;max-width:260px}
.split .o{background:var(--text);border-radius:4px 0 0 4px}.split .u{border:1.5px solid var(--muted);border-radius:0 4px 4px 0}
.split .q{border:1.5px dashed var(--muted)}
"""

CMP_JS = """
document.querySelectorAll('.cmp').forEach(root=>{
const teams=JSON.parse(root.dataset.teams),ins=root.querySelectorAll('input'),rows=root.querySelectorAll('tbody tr');
const cell=(games,val,x)=>{if(isNaN(x))return '—';let o=0,u=0;games.forEach(g=>{const v=val(g);v>x?o++:v<x?u++:0});const n=games.length,q=n-o-u,po=n?Math.round(100*o/n):0,pu=n?Math.round(100*u/n):0;
 return `<span class=ov><b>${o}</b> больше</span> · <span class=un><b>${u}</b> меньше</span>`+(q?` · <b>${q}</b> ровно`:'')+` <span class=muted>из ${n}</span>`+
 `<div class=split><div class=o style="width:${po}%"></div>`+(q?`<div class=q style="width:${100-po-pu}%"></div>`:'')+`<div class=u style="width:${pu}%"></div></div><div class=muted style="font-size:12px;margin-top:2px">${po}% / ${pu}%</div>`};
const upd=()=>{const d=parseFloat(String(ins[0].value).replace(',','.')),k=parseFloat(String(ins[1].value).replace(',','.'));
 teams.forEach((t,i)=>{rows[i].cells[1].innerHTML=cell(t.g,g=>g.d/60,d);rows[i].cells[2].innerHTML=cell(t.g,g=>g.k,k)})};
ins.forEach(i=>i.addEventListener('input',upd));upd();});
"""


def load_teams(lid):
    teams = {}
    for f in (ROOT / "data" / lid).glob("*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        teams[t["team_id"]] = (t, f.stem)
    return teams


def logo_img(tid, base):
    p = ROOT / "assets" / "teams" / f"{tid}.png"
    cls = " class=dark" if tid in DARK_LOGO else ""
    return f"<img{cls} src='{rel(p, base)}' alt=''>" if p.exists() else ""


def team_color(meta, tid):
    slot = meta.get("teams", {}).get(str(tid), {}).get("slot")
    return f"var(--s{slot})" if slot else "var(--muted)"


def bracket(lid, meta, teams, base, link_base):
    """Карточки матчей плей-офф (используется и в шапке анализа, и на главной)."""
    def tm(tid):
        if tid is None:
            return "<div class=tm><div class=q>?</div>победитель полуфинала</div>"
        t, stem = teams[tid]
        href = rel(ROOT / "reports" / lid / f"{stem}.html", link_base)
        return f"<a class=tm href='{href}'>{logo_img(tid, base)}{e(t['team'])}</a>"

    def prob(a, b, pa):
        na, nb = teams[a][0]["team"], teams[b][0]["team"]
        return (f"<div class=prob title='Оценка шансов по статистике турнира'>"
                f"<span style='width:{pa}%;background:{team_color(meta, a)}'>{e(na)} {pa}%</span>"
                f"<span style='width:{100 - pa}%;background:{team_color(meta, b)}'>{100 - pa}%</span></div>")

    H = ["<div class=bracket>"]
    for m in meta["matches"]:
        H.append(f"<div class=mcard><div class=st>{e(m['stage'])}</div>"
                 f"<div class=row>{tm(m['a'])}<span class=x>VS</span>{tm(m.get('b'))}</div>"
                 f"<div class=nt>{e(m.get('note', ''))}</div>")
        if m.get("b") and m.get("pa") is not None:
            H.append(prob(m["a"], m["b"], m["pa"]))
        for sc in m.get("scenarios", []):
            H.append(f"<div class=scn>если против {e(teams[sc['b']][0]['team'])}:</div>" + prob(m["a"], sc["b"], sc["pa"]))
        H.append("</div>")
    H.append("</div>")
    return "".join(H)


def compare(lid, meta, teams, ids):
    """Сравнение команд полосами по ключевым метрикам."""
    ts = [teams[i][0] for i in ids if i in teams]

    def sec(mmss):
        m, s = mmss.split(":")
        return int(m) * 60 + int(s)

    metrics = [  # подпись, функция значения, формат, больше = лучше (None — нейтрально)
        ("Винрейт по картам", lambda t: t["summary"]["winrate"], lambda v: f"{v:.1f}%", True),
        ("Свои фраги за карту", lambda t: t["summary"]["avg_kills_for"], lambda v: f"{v}", True),
        ("Пропущенные фраги за карту", lambda t: t["summary"]["avg_kills_against"], lambda v: f"{v}", False),
        ("Убийств в минуту", lambda t: t["summary"]["kills_per_min"], lambda v: f"{v}", True),
        ("Первая кровь", lambda t: t["summary"]["first_blood_rate"], lambda v: f"{v:.0f}%", True),
        ("Золото на 10:00", lambda t: t["summary"]["avg_gold_adv_10min"], lambda v: f"{v:+}", True),
        ("Средняя длительность", lambda t: sec(t["summary"]["avg_duration"]), lambda v: f"{v // 60}:{v % 60:02d}", None),
        ("Длительность поражений", lambda t: sec(t["summary"]["avg_duration_loss"]), lambda v: f"{v // 60}:{v % 60:02d}", None),
    ]
    H = ["<div class=cmpbars>"]
    for label, fn, fmt, better in metrics:
        vals = [fn(t) for t in ts]
        mx = max(abs(v) for v in vals) or 1
        best = None if better is None else (max(vals) if better else min(vals))
        signed = any(v < 0 for v in vals)  # есть минус — шкала от центра (ноль посередине)
        H.append(f"<div class=metric><div class=ml>{label}</div>")
        for t, v in zip(ts, vals):
            col = team_color(meta, t["team_id"])
            if signed:
                w = max(2, 50 * abs(v) / mx)
                pos = f"left:50%;width:{w:.1f}%" if v >= 0 else f"right:50%;width:{w:.1f}%"
                bar = f"<div class='tr div'><div class=fl style='position:absolute;top:0;bottom:0;{pos};background:{col}'></div></div>"
            else:
                bar = f"<div class=tr><div class=fl style='width:{max(2, 100 * v / mx):.0f}%;background:{col}'></div></div>"
            H.append(f"<div class='mrow{' best' if v == best else ''}'><div class=nm><i class=sw style='background:{col}'></i>{e(t['team'])}</div>"
                     f"{bar}<div class=vl>{fmt(v)}</div></div>")
        H.append("</div>")
    H.append("</div>")
    return "".join(H)


def totals_compare(meta, teams, ids):
    """Общий калькулятор тоталов: одна линия — результат по каждой команде."""
    ts = [teams[i][0] for i in ids if i in teams]
    data = [{"n": t["team"], "g": [{"d": g["duration_sec"], "k": g["total_kills"]} for g in t["games"]]} for t in ts]
    rows = "".join(f"<tr><td><div class=tn style='--tc:{team_color(meta, t['team_id'])}'><i></i><div><b>{e(t['team'])}</b>"
                   f"<div class=muted style='font-size:12px'>ср. {t['summary']['avg_duration']} · {t['summary']['avg_total_kills']} убийств</div>"
                   f"</div></div></td><td></td><td></td></tr>" for t in ts)
    return (f"<div class='card cmp' data-teams='{e(json.dumps(data, ensure_ascii=False))}'>"
            f"<div class=in><div><label>Тотал времени, мин</label><input type=number step=0.5 min=0 value=43></div>"
            f"<div><label>Тотал убийств</label><input type=number step=0.5 min=0 value=60></div></div>"
            f"<table><thead><tr><th>Команда</th><th>Время</th><th>Убийства</th></tr></thead><tbody>{rows}</tbody></table></div>")


def render(lid, body):
    league = json.loads((ROOT / "raw" / f"league_{lid}.json").read_text(encoding="utf-8"))
    meta = json.loads((ROOT / "analysis" / f"{lid}.json").read_text(encoding="utf-8"))
    teams = load_teams(lid)
    out = ROOT / "reports" / lid / "analysis.html"
    ids = lambda m: [int(x) for x in m.group(1).split(",")]
    hero = (f"<div class=banner><div class=tourb>{e(league['name'])}</div><h1>{e(meta['title'])}</h1>"
            f"<div class=lead>{e(meta.get('subtitle', ''))}</div>{bracket(lid, meta, teams, out, out)}</div>")
    body = body.replace("<!--bracket-->", hero)
    body = re.sub(r"<!--compare:([\d,]+)-->", lambda m: compare(lid, meta, teams, ids(m)), body)
    body = re.sub(r"<!--totals:([\d,]+)-->", lambda m: totals_compare(meta, teams, ids(m)), body)
    body = body.replace("<!--odds-->", odds_html(lid))
    body = re.sub(r"<!--logo:(\d+)-->", lambda m: logo_img(int(m.group(1)), out), body)
    for tid, tm in meta.get("teams", {}).items():  # --tc для карточек команд
        body = body.replace(f"data-team={tid}", f"style='--tc:{team_color(meta, int(tid))}'")
    html = (head(f"Анализ плей-офф, {league['name']}", meta.get("subtitle", ""))
            + f"<style>{CSS}{TOTALS_CSS}{ANALYSIS_CSS}{ODDS_CSS}</style></head><body><main class=wrap>"
            + f"<a class=back href='{rel(league_page(lid), out)}'>← страница турнира</a>"
            f"{body}</main><script>{CMP_JS}</script></body></html>")
    out.write_text(html, encoding="utf-8")
    return out


def teaser(lid):
    """Блок для главной: сетка плей-офф + кнопка на полный анализ. Пусто, если анализа нет."""
    mp = ROOT / "analysis" / f"{lid}.json"
    page = ROOT / "reports" / lid / "analysis.html"
    if not mp.exists() or not page.exists():
        return ""
    meta = json.loads(mp.read_text(encoding="utf-8"))
    teams = load_teams(lid)
    return (f"<div class=banner style='margin-top:16px'><div class=tourb>Аналитика плей-офф</div>"
            f"<h1 style='font-size:24px'>{e(meta['title'])}</h1><div class=lead>{e(meta.get('subtitle', ''))}</div>"
            f"{bracket(lid, meta, teams, INDEX, INDEX)}"
            f"<a class=cta href='{rel(page, INDEX)}'>Читать полный анализ →</a></div>")


def main():
    for f in sorted((ROOT / "analysis").glob("*.html")):
        print(render(f.stem, f.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
