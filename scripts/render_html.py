"""HTML-отчёт по команде из data/<league>/<team>.json.

Использование (обычно вызывается из collect_team.py):
    python scripts/render_html.py data/19102/parivision.json
"""
import datetime
import json
import os
import sys
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CDN = "https://cdn.cloudflare.steamstatic.com"

CSS = """
:root{--bg:#f4f5f7;--card:#fff;--text:#14161b;--muted:#646b78;--line:#e4e6ea;--win:#1f63b5;--loss:#c23434;
--win-bg:#e3eefc;--loss-bg:#fbe6e4;--accent:#14161b;--on-accent:#fff;--bar:#e6e8ec;--hover:#f7f8fa;
--shadow:0 1px 2px rgba(20,24,34,.04),0 4px 14px -6px rgba(20,24,34,.08);--ring:0 0 0 3px rgba(20,22,27,.18);
--v-win:#2a78d6;--v-loss:#e34948;--v-opp:#c9cbd1;--v-grid:#ebecef;--v-axis:#c3c2b7;--v-tick:#898781;
--v-track:#cde2fb;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;color-scheme:light}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Geist",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
:root{--mono:"Geist Mono",ui-monospace,"SF Mono",Consolas,monospace}
.num,td.num,.kpi .v,.viz .gl span,.viz .cap,.tot input,.tot .res b,.tot .dot,.pill,.chip b,.mrow .vl,.prob,.fact{font-family:var(--mono)}
a{color:inherit;text-underline-offset:3px}a:hover{text-decoration-thickness:2px}
:focus-visible{outline:none;box-shadow:var(--ring);border-radius:6px}
h1,h2,h3{text-wrap:balance}p,li{text-wrap:pretty}
.wrap{max-width:1200px;margin:0 auto;padding:24px 16px 48px}
h1{margin:0;font-size:34px;line-height:1.1;letter-spacing:-.025em;font-weight:700}
.head{display:flex;align-items:center;gap:14px}.logo{width:56px;height:56px;object-fit:contain}
.logo.dark{background:#111;border-radius:12px;padding:6px}
.tour{display:inline-block;margin-bottom:12px;padding:4px 10px;border-radius:6px;background:var(--bar);font-size:12.5px;font-weight:600}
.back{display:block;width:max-content;margin-bottom:14px;color:var(--muted);text-decoration:none;font-weight:500;transition:color .2s}.back:hover{color:var(--text)}h2{font-size:20px;letter-spacing:-.015em;font-weight:650;margin:40px 0 14px}
.sub{color:var(--muted);margin-top:6px}.sub a{color:var(--text)}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));grid-auto-flow:dense;gap:1px;margin-top:24px;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.kpi.wide{grid-column:span 2}.kpi .v{white-space:nowrap}
.kpi .v small{font-size:.62em;font-weight:500;color:var(--muted);letter-spacing:0}
.kpi{background:var(--card);padding:14px 16px;outline:1px solid var(--line)}
.kpi.main{grid-column:span 2;background:var(--accent);color:var(--on-accent)}
.kpi.main .l,.kpi.main .s{color:inherit;opacity:.7}.kpi.main .v{font-size:40px;letter-spacing:-.05em}
.kpi .l{color:var(--muted);font-size:12.5px;font-weight:500}
.kpi .v{font-size:24px;font-weight:600;letter-spacing:-.03em;margin-top:4px;font-variant-numeric:tabular-nums}
.kpi .s{color:var(--muted);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap;vertical-align:middle}
th{font-size:12px;color:var(--muted);font-weight:500;position:sticky;top:0;background:var(--card);cursor:pointer;user-select:none;transition:color .2s}
th[data-asc="1"]::after{content:" ↑"}th[data-asc="0"]::after{content:" ↓"}
tbody tr{transition:background-color .15s}tbody tr:hover{background:var(--hover)}
th:hover{color:var(--text)}th:active{transform:translateY(1px)}tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right}
.w{color:var(--win);font-weight:650}.lo{color:var(--loss);font-weight:650}
.pill{display:inline-block;padding:1px 8px;border-radius:6px;font-size:12px;font-weight:650}
.pill.w{background:var(--win-bg)}.pill.lo{background:var(--loss-bg)}
.series{display:flex;flex-wrap:wrap;gap:8px}
.ser{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:8px 12px;display:flex;gap:10px;align-items:center}
.heroes{display:flex;gap:3px}
td.links{white-space:nowrap;font-size:12.5px;line-height:1.7}
.hero{width:44px;height:25px;border-radius:4px;object-fit:cover;background:var(--line)}
.hero.ban{filter:grayscale(1);opacity:.55}
.hcell{display:flex;align-items:center;gap:8px}
.bar{height:8px;border-radius:4px;background:var(--v-track);position:relative;min-width:120px}
.bar span{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--s1)}
.viz{position:relative;padding:18px 18px 14px;overflow:visible}
.viz .lg{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:12px;color:var(--muted);margin-bottom:14px}
.viz .lg span{display:inline-flex;align-items:center;gap:6px}.viz .lg i{width:10px;height:10px;border-radius:2px;flex:none}
.viz .sc{overflow-x:auto;overflow-y:hidden;padding:22px 6px 2px 58px;margin-left:-6px}
.viz .in{min-width:calc(var(--n)*38px)}
.viz .plot{position:relative;height:190px;border-bottom:1px solid var(--v-axis)}
.viz .gl{position:absolute;left:0;right:0;border-top:1px solid var(--v-grid)}
.viz .gl span{position:absolute;right:calc(100% + 8px);top:-8px;font-size:11px;color:var(--v-tick);font-variant-numeric:tabular-nums;white-space:nowrap}
.viz .avg{position:absolute;left:0;right:0;border-top:1px solid var(--text);opacity:.5;z-index:2;pointer-events:none}
.viz .avg span{position:absolute;right:0;bottom:2px;font-size:11px;font-weight:600;color:var(--text);background:var(--card);padding:0 4px}
.viz .cols{position:absolute;inset:0;display:flex;z-index:1}
.viz .c{flex:1;min-width:38px;position:relative;display:flex;justify-content:center;align-items:flex-end;outline:none;cursor:default}
.viz .c:hover,.viz .c:focus-visible{background:color-mix(in srgb,var(--text) 5%,transparent)}
.viz .c:focus-visible{box-shadow:inset var(--ring)}
.viz .stk{width:min(24px,62%);display:flex;flex-direction:column;gap:2px}
.viz .sg{width:100%}.viz .sg:first-child{border-radius:4px 4px 0 0}
.viz .sg.w{background:var(--v-win)}.viz .sg.lo{background:var(--v-loss)}.viz .sg.opp{background:var(--v-opp)}
.viz .cap{position:absolute;left:0;right:0;text-align:center;font-size:11px;font-weight:650;color:var(--text);padding-bottom:3px;font-variant-numeric:tabular-nums}
.viz .xa{display:flex;margin-top:6px}
.viz .xa div{flex:1;min-width:38px;text-align:center;font-size:10.5px;line-height:1.35;color:var(--muted);white-space:nowrap}
.viz .xa b{display:block;font-size:10px;font-weight:700}.viz .xa b.w{color:var(--win)}.viz .xa b.lo{color:var(--loss)}
.viz .tip{position:absolute;z-index:5;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:8px;
box-shadow:var(--shadow);padding:8px 10px;font-size:12px;min-width:150px;opacity:0;transition:opacity .12s}
.viz .tip.on{opacity:1}.viz .tip .h{color:var(--muted);margin-bottom:4px;font-size:11.5px}
.viz .tip .r{display:flex;align-items:center;gap:8px;margin-top:2px}.viz .tip .r i{width:12px;height:2px;border-radius:1px;flex:none}
.viz .tip .r b{font-weight:650;font-variant-numeric:tabular-nums}.viz .tip .r span{color:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:800px){.grid2{grid-template-columns:1fr}}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding:12px}
.chip{display:flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:6px;padding:3px 8px 3px 3px;font-size:13px}
.chip img{width:36px;height:20px;border-radius:4px;object-fit:cover}
.chip b{font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='7' fill='%2314161b'/%3E%3Cpath d='M10 23V9h5.5a7 7 0 010 14z' fill='none' "
           "stroke='%23fff' stroke-width='3'/%3E%3C/svg%3E")


def head(title, description):
    """Общий <head>: шрифт Geist (без интернета — системный), favicon, description."""
    return (f"<!doctype html><html lang=ru><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)}</title><meta name=description content='{escape(description)}'>"
            f'<link rel=icon href="{FAVICON}">'
            f"<link rel=preconnect href=https://fonts.googleapis.com><link rel=preconnect href=https://fonts.gstatic.com crossorigin>"
            f"<link rel=stylesheet href='https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap'>")



TOTALS_CSS = """
.tot{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:800px){.tot{grid-template-columns:1fr}}
.tot .box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tot label{font-size:12.5px;color:var(--muted);font-weight:500}
.tot .in{display:flex;align-items:center;gap:8px;margin:6px 0 10px}
.tot input{font-size:20px;font-weight:600;width:110px;padding:6px 10px;border-radius:6px;
border:1px solid var(--line);background:var(--bg);color:var(--text);transition:border-color .2s}
.tot input:focus{outline:none;border-color:var(--text);box-shadow:var(--ring)}
.tot .res{display:flex;gap:16px;flex-wrap:wrap;font-variant-numeric:tabular-nums}
.tot .res div{font-size:13px;color:var(--muted)}.tot .res b{display:block;font-size:22px}
.tot .res b{color:var(--text)}.tot .res i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.tot .res .ov i{background:var(--text)}.tot .res .un i{border:1.5px solid var(--muted)}.tot .res .eq i{border:1.5px dashed var(--muted)}
.tot .dots{display:flex;flex-wrap:wrap;gap:4px;margin-top:10px}
.tot .dot{font-size:11px;padding:2px 6px;border-radius:6px;font-variant-numeric:tabular-nums}
.tot .dot{border:1px solid transparent}.tot .dot.ov{background:var(--text);color:var(--card)}.tot .dot.un{border-color:var(--muted);color:var(--text)}
.tot .dot.eq{border:1px dashed var(--muted);color:var(--muted)}
"""

TOTALS_JS = """
document.querySelectorAll('.tot[data-games]').forEach(root=>{
const games=JSON.parse(root.dataset.games);
root.querySelectorAll('.box').forEach(box=>{
 const key=box.dataset.k,inp=box.querySelector('input'),res=box.querySelector('.res'),dots=box.querySelector('.dots');
 const val=g=>key==='d'?g.d/60:g.k, fmt=g=>key==='d'?`${Math.floor(g.d/60)}:${String(g.d%60).padStart(2,'0')}`:g.k;
 const upd=()=>{const x=parseFloat(String(inp.value).replace(',','.'));if(isNaN(x)){res.innerHTML='';dots.innerHTML='';return}
  let o=0,u=0,q=0;dots.innerHTML='';
  games.forEach(g=>{const v=val(g),c=v>x?'ov':v<x?'un':'eq';c==='ov'?o++:c==='un'?u++:q++;
   const s=document.createElement('span');s.className='dot '+c;s.title=g.o;s.textContent=fmt(g);dots.appendChild(s)});
  const n=games.length,p=v=>n?Math.round(100*v/n):0;
  res.innerHTML=`<div class=ov><b>${o} из ${n}</b><i></i>больше · ${p(o)}%</div><div class=un><b>${u} из ${n}</b><i></i>меньше · ${p(u)}%</div>`+(q?`<div class=eq><b>${q}</b><i></i>ровно</div>`:'');};
 inp.addEventListener('input',upd);upd();});});
"""


VIZ_JS = """
document.querySelectorAll('.viz').forEach(v=>{const tip=v.querySelector('.tip');
const show=c=>{const d=JSON.parse(c.dataset.tip);tip.replaceChildren();
 const h=document.createElement('div');h.className='h';h.textContent=d.h;tip.appendChild(h);
 d.r.forEach(([val,lab,col])=>{const r=document.createElement('div');r.className='r';const i=document.createElement('i');
  if(col)i.style.background=col;else i.style.visibility='hidden';const b=document.createElement('b');b.textContent=val;
  const sp=document.createElement('span');sp.textContent=lab;r.append(i,b,sp);tip.appendChild(r)});
 const vr=v.getBoundingClientRect(),cr=c.getBoundingClientRect();tip.classList.add('on');
 let x=cr.left-vr.left+cr.width/2-tip.offsetWidth/2;x=Math.max(8,Math.min(x,vr.width-tip.offsetWidth-8));
 tip.style.left=x+'px';tip.style.top=Math.max(4,cr.top-vr.top+8)+'px'};
v.querySelectorAll('.c').forEach(c=>{c.addEventListener('pointerenter',()=>show(c));c.addEventListener('focus',()=>show(c));
 c.addEventListener('pointerleave',()=>tip.classList.remove('on'));c.addEventListener('blur',()=>tip.classList.remove('on'))});});
"""


def nice_ticks(vmax, steps=(5, 10, 20, 25, 50)):
    """Круглые деления оси: 3–5 штук до ближайшего «красивого» максимума."""
    for st in steps:
        if vmax / st <= 5:
            top = -(-vmax // st) * st
            return top, list(range(0, int(top) + 1, st))
    st = steps[-1]
    top = -(-vmax // st) * st
    return top, list(range(0, int(top) + 1, st))


def column_chart(cols, top, ticks, tick_fmt, legend, avg=None, avg_label="", label=""):
    """Столбчатый график: cols = [{segs:[(value, cls)], total, x, tip, cap}] (сегменты сверху вниз)."""
    H = [f"<figure class='card viz' aria-label='{escape(label)}' style='margin:0'><div class=lg>"]
    H += [f"<span><i style='background:{col}'></i>{escape(txt)}</span>" for col, txt in legend]
    H.append(f"</div><div class=sc><div class=in style='--n:{len(cols)}'><div class=plot>")
    H += [f"<div class=gl style='bottom:{100 * t / top:.2f}%'><span>{tick_fmt(t)}</span></div>" for t in ticks]
    if avg is not None:
        H.append(f"<div class=avg style='bottom:{100 * avg / top:.2f}%'><span>{escape(avg_label)}</span></div>")
    H.append("<div class=cols>")
    for c in cols:
        segs = "".join(f"<div class='sg {cls}' style='height:{190 * v / top:.1f}px'></div>" for v, cls in c["segs"] if v > 0)
        cap = (f"<div class=cap style='bottom:{100 * c['total'] / top:.2f}%'>{escape(c['cap'])}</div>" if c.get("cap") else "")
        H.append(f"<div class=c tabindex=0 data-tip='{escape(json.dumps(c['tip'], ensure_ascii=False))}'>{cap}<div class=stk>{segs}</div></div>")
    H.append("</div></div><div class=xa>")
    H += [f"<div>{c['x']}</div>" for c in cols]
    H.append("</div></div></div><div class=tip role=status></div></figure>")
    return "".join(H)


def totals_widget(t, title=None):
    """Калькулятор тоталов: ввёл число — видно, сколько карт команды больше/меньше по времени и убийствам."""
    games = [{"d": g["duration_sec"], "k": g["total_kills"], "o": g["opponent"]} for g in t["games"]]
    s = t["summary"]
    avg_min = round(sum(g["d"] for g in games) / len(games) / 60) if games else 45
    avg_k = round(s["avg_total_kills"]) if games else 60
    head = f"<h3 style='margin:0 0 10px'>{escape(title)}</h3>" if title else ""
    return (f"<div class=tot data-games='{escape(json.dumps(games, ensure_ascii=False))}'>"
            f"<div class=box data-k=d>{head}<label>Тотал времени, мин</label>"
            f"<div class=in><input type=number step=0.5 min=0 value={avg_min}><span class=muted>ср. {s['avg_duration']}</span></div>"
            f"<div class=res></div><div class=dots></div></div>"
            f"<div class=box data-k=k>{head}<label>Тотал убийств (обе команды)</label>"
            f"<div class=in><input type=number step=0.5 min=0 value={avg_k}><span class=muted>ср. {s['avg_total_kills']}</span></div>"
            f"<div class=res></div><div class=dots></div></div></div>")


SORT_JS = """
document.querySelectorAll('table.sortable th').forEach((th,i)=>th.addEventListener('click',()=>{
const tb=th.closest('table').tBodies[0],rows=[...tb.rows],asc=th.dataset.asc!=='1';
th.closest('tr').querySelectorAll('th').forEach(x=>delete x.dataset.asc);th.dataset.asc=asc?'1':'0';
const key=r=>{const c=r.cells[i],v=c.dataset.v??c.textContent.trim();const n=parseFloat(v);return isNaN(n)?v.toLowerCase():n};
rows.sort((a,b)=>{const x=key(a),y=key(b);return (x>y?1:x<y?-1:0)*(asc?1:-1)});rows.forEach(r=>tb.appendChild(r))}));
"""


HERO_DIR = ROOT / "assets" / "heroes"


def load_heroes():
    """Имя героя -> локальный файл assets/heroes/<slug>.png (скачивается один раз с CDN Steam)."""
    heroes = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    HERO_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    for h in heroes.values():
        url = CDN + h["img"].rstrip("?")
        path = HERO_DIR / url.rsplit("/", 1)[1]
        if not path.exists():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "dota-stats/1.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    path.write_bytes(r.read())
            except Exception as ex:
                print(f"  нет картинки {h['localized_name']}: {ex}", file=sys.stderr)
                continue
        result[h["localized_name"]] = path
    return result


def rel_imgs(imgs, out_path):
    """Пути к картинкам относительно HTML-файла, чтобы отчёт открывался без интернета."""
    return {name: os.path.relpath(p, out_path.parent).replace(os.sep, "/") for name, p in imgs.items()}


def fmt_date(ts):
    # дата карты по Москве (UTC+3)
    return (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc) + datetime.timedelta(hours=3)).strftime("%d.%m")


HEROTAG_CSS = """
.tag{display:inline-block;padding:2px 8px;border-radius:6px;font:600 11.5px var(--mono);background:var(--bar);color:var(--muted)}
.tag.fast{background:var(--win-bg);color:var(--win)}.tag.long{background:var(--loss-bg);color:var(--loss)}.tag.tf{background:#e0f2e6;color:#1d7a3e}.tag.ts{background:#fdefd6;color:#9a6200}
"""


def team_heroes_html(t, himg):
    """Блок «Герои: быстрые и затяжные»: темп драфтов и герои команды — на турнире и всего."""
    import heroes_stats as hs
    e = escape
    all_games = hs.team_all_games(t["team_id"])
    rows, summ = hs.team_heroes(t["games"], all_games)
    is_all = t["league_id"] == "all"
    word = lambda x: "нет данных" if x is None else hs.tempo_word(x)
    pct = lambda v: f"{v:.0%}"

    def tile(title, sm):
        tv = "—" if sm["tempo"] is None else f"{sm['tempo']:+g}"
        return (f"<div class=kpi><div class=l>{title}</div><div class=v>{word(sm['tempo'])}</div>"
                f"<div class=s>темп {tv} · быстрых героев {pct(sm['fast'])}, затяжных {pct(sm['long'])} · {sm['maps']} карт</div></div>")

    H = ["<h2>Герои: быстрые и затяжные</h2><div class=kpis style='grid-template-columns:repeat(auto-fit,minmax(260px,1fr))'>"]
    if not is_all:
        H.append(tile("Драфты на турнире", summ["scope"]))
    H.append(tile("Драфты за всё время", summ["all"]))
    H.append("</div>")
    def cell(c):
        n = c["n"]
        if not n:
            return "<td class=num data-v=-1>—</td><td class=num data-v=0>—</td>"
        return (f"<td class=num data-v={c['w'] / n:.3f}>{c['w']}/{n} ({c['w'] / n:.0%})</td>"
                f"<td class=num data-v={c['dur'] / n:.1f}>{c['dur'] / n:.1f}</td>")

    def heads(sfx):
        return f"<th class=num>W/игр · {sfx}</th><th class=num>Мин · {sfx}</th>"

    H.append("<div class=card><table class=sortable><thead><tr><th>Герой</th><th>Темп героя</th><th>Вышки</th>"
             + ("" if is_all else heads("турнир")) + heads("всего") + "</tr></thead><tbody>")
    ttag = {"быстро ломает": "tf", "медленно ломает": "ts"}
    order = {"быстрый": 0, "затяжной": 1, "нейтральный": 2, "мало данных": 3}
    for nm, r in sorted(rows.items(), key=lambda kv: (order[kv[1]["label"]], -kv[1]["all"]["n"], kv[0])):
        tag = {"затяжной": "long", "быстрый": "fast"}.get(r["label"], "")
        H.append(f"<tr><td><div class=hcell>{himg(nm)}{e(nm)}</div></td>"
                 f"<td data-v={order[r['label']]}><span class='tag {tag}'>{e(r['label'])}</span> <span class=muted>{r['tilt']:+g}</span></td>"
                 f"<td><span class='tag {ttag.get(r['tlabel'], '')}'>{e(r['tlabel'])}</span></td>"
                 + ("" if is_all else cell(r["scope"])) + cell(r["all"]) + "</tr>")
    H.append("</tbody></table></div><div class=muted style='font-size:12.5px;margin-top:6px'>Темп героя — по всем сыгранным картам базы "
             "(страница «Герои»); «Мин» — средняя длительность карт команды с этим героем. Сортировка: быстрые, затяжные, "
             "нейтральные, мало данных.</div>")
    return "".join(H)


def date_link(g, match_links):
    """Дата карты: ссылка на нашу страницу матча, если она есть, иначе на Dotabuff."""
    own = (match_links or {}).get(g["match_id"])
    if own:
        return f"<a href='{escape(own)}' title='Детальная страница матча'>{fmt_date(g['start_time'])}</a>"
    return f"<a href='{g['dotabuff']}' title='Матч на Dotabuff'>{fmt_date(g['start_time'])}</a>"


def render(t, league_name, imgs, logo=None, back=None, tags=None, switch="", match_links=None):
    s, games = t["summary"], t["games"]
    e = escape
    tags = tags or {}
    logo_html = f"<img class={logo_cls(t['team_id'])} src='{e(logo)}' alt='Логотип {e(t['team'])}'>" if logo else ""

    def himg(name, ban=False):
        return f'<img class="hero{" ban" if ban else ""}" src="{e(imgs.get(name, ""))}" alt="{e(name)}" title="{e(name)}" loading="lazy">'

    def kpi(label, value, sub="", main=False, wide=False):
        cls = "kpi main" if main else "kpi wide" if wide else "kpi"
        return f'<div class="{cls}"><div class="l">{label}</div><div class="v">{value}</div><div class="s">{sub}</div></div>'

    def wl(w, n):
        return f"{w}/{n} ({round(100 * w / n) if n else 0}%)"

    H = [head(f"{t['team']}, {league_name}", f"Статистика {t['team']} на {league_name}: карты, фраги, пики, игроки, тоталы")
         + f"<style>{CSS}{TOTALS_CSS}{SWITCH_CSS}{HEROTAG_CSS}</style></head><body><main class=wrap>",
         (f"<a class=back href='{e(back)}'>← {'все команды' if t['league_id'] == 'all' else 'страница турнира'}</a>" if back else ""),
         switch or f"<div class=tour>{'Все турниры' if t['league_id'] == 'all' else 'Турнир'}: {e(league_name)}</div>",
         f"<div class=head>{logo_html}<h1>{e(t['team'])}</h1></div>",
         f"<div class=sub>Данные OpenDota, профиль на "
         f"<a href='https://www.dotabuff.com/esports/teams/{t['team_id']}'>Dotabuff</a></div>",
         "<div class=kpis>",
         kpi("Карты", f"{s['wins']}-{s['losses']}", f"винрейт {s['winrate']}%", main=True),
         kpi("Серии", s["series_record"], f"{len(s['series'])} серий"),
         kpi("Ср. длительность", s["avg_duration"], f"W {s['avg_duration_win']} · L {s['avg_duration_loss']}"),
         kpi("Мин / макс", f"{s['shortest']}", f"самая долгая {s['longest']}"),
         kpi("Фраги за карту", f"{s['avg_kills_for']}:{s['avg_kills_against']} <small>({s['avg_total_kills']})</small>", "свои : пропущено (всего)", wide=True),
         kpi("Убийств в минуту", s["kills_per_min"], ""),
         kpi("Первая кровь", f"{s['first_blood_rate']}%", "карт с FB"),
         kpi("Золото на 10:00", f"{s['avg_gold_adv_10min']:+}", "в среднем"),
         kpi("Рошаны", s["avg_roshans"], "за карту"),
         kpi("Radiant / Dire", f"{s['radiant']['winrate']:.0f}% / {s['dire']['winrate']:.0f}%",
             f"{s['radiant']['wins']}/{s['radiant']['games']} · {s['dire']['wins']}/{s['dire']['games']}"),
         kpi("First / second pick", f"{s['first_pick']['winrate']:.0f}% / {s['second_pick']['winrate']:.0f}%",
             f"{s['first_pick']['wins']}/{s['first_pick']['games']} · {s['second_pick']['wins']}/{s['second_pick']['games']}"),
         "</div>"]

    H.append("<h2>Тоталы</h2>" + totals_widget(t))

    # серии
    H.append("<h2>Серии</h2><div class=series>")
    for x in s["series"]:
        cls = "w" if x["won"] else "lo"
        H.append(f"<div class=ser><span class='pill {cls}'>{x['score']}</span>{e(x['opponent'])}</div>")
    H.append("</div>")

    # графики по картам: победа — синий, поражение — красный (+ буква W/L под столбцом), соперник — серый
    def xlab(g):
        tag = e(tags.get(g["opponent_id"]) or g["opponent"][:6])
        cls, res = ("w", "W") if g["win"] else ("lo", "L")
        return f"{tag}<b class={cls}>{res}</b>"

    def head_tip(g):
        return f"{fmt_date(g['start_time'])} · {g['opponent']} · {'победа' if g['win'] else 'поражение'}"

    res_col = lambda g: "var(--v-win)" if g["win"] else "var(--v-loss)"
    legend_wl = [("var(--v-win)", "Победа"), ("var(--v-loss)", "Поражение")]

    durs = [g["duration_sec"] / 60 for g in games]
    if games:
        top, ticks = nice_ticks(max(durs), (10, 15, 20, 30))
        i_max, i_min = durs.index(max(durs)), durs.index(min(durs))
        cols = [{"segs": [(d, "w" if g["win"] else "lo")], "total": d, "x": xlab(g),
                 "cap": g["duration"] if i in (i_max, i_min) else "",
                 "tip": {"h": head_tip(g), "r": [[g["duration"], "длительность", res_col(g)],
                                                 [f"{g['kills_for']}:{g['kills_against']} ({g['total_kills']})", "фраги", ""]]}}
                for i, (g, d) in enumerate(zip(games, durs))]
        H.append("<h2>Длительность карт</h2>" + column_chart(
            cols, top, ticks, lambda t: f"{t} мин", legend_wl,
            avg=sum(durs) / len(durs), avg_label=f"среднее {s['avg_duration']}", label="Длительность карт"))

        kills = [g["total_kills"] for g in games]
        top, ticks = nice_ticks(max(kills), (10, 20, 25, 50))
        i_max, i_min = kills.index(max(kills)), kills.index(min(kills))
        cols = [{"segs": [(g["kills_against"], "opp"), (g["kills_for"], "w" if g["win"] else "lo")], "total": g["total_kills"],
                 "x": xlab(g), "cap": f"{g['kills_for']}:{g['kills_against']} ({g['total_kills']})" if i in (i_max, i_min) else "",
                 "tip": {"h": head_tip(g), "r": [[str(g["kills_for"]), "фраги команды", res_col(g)],
                                                 [str(g["kills_against"]), "фраги соперника", "var(--v-opp)"],
                                                 [str(g["total_kills"]), "всего на карте", ""]]}}
                for i, g in enumerate(games)]
        H.append("<h2>Фраги по картам</h2>" + column_chart(
            cols, top, ticks, str,
            legend_wl[:1] + [("var(--v-loss)", "Поражение"), ("var(--v-opp)", "Фраги соперника")],
            avg=s["avg_total_kills"], avg_label=f"в среднем {s['avg_total_kills']} за карту", label="Фраги по картам"))
        H.append("<div class=muted style='font-size:12px;margin-top:6px'>Нижняя часть столбика: фраги команды "
                 "(цвет показывает итог карты), серая часть: фраги соперника. Точные значения видны при наведении и в таблице «Карты».</div>")

    # карты
    H.append("<h2>Карты</h2><div class=card><table class=sortable><thead><tr>"
             "<th>Дата</th><th>Соперник</th><th>Сторона</th><th>Итог</th><th class=num>Время</th>"
             "<th class=num>Фраги</th><th>FB</th><th>Пики команды</th><th>Пики соперника</th><th>Ссылки</th></tr></thead><tbody>")
    for g in reversed(games):  # свежие карты сверху
        cls, res = ("w", "W") if g["win"] else ("lo", "L")
        H.append(f"<tr><td data-v={g['start_time']}>{date_link(g, match_links)}</td><td>{e(g['opponent'])}</td>"
                 f"<td>{g['side']}{' · FP' if g['first_pick'] else ''}</td><td><span class='pill {cls}'>{res}</span></td>"
                 f"<td class=num data-v={g['duration_sec']}>{g['duration']}</td>"
                 f"<td class=num data-v={g['total_kills']}>{g['kills_for']}:{g['kills_against']} ({g['total_kills']})</td>"
                 f"<td>{'✓' if g['first_blood'] else ''}</td>"
                 f"<td><div class=heroes>{''.join(himg(h) for h in g['picks'])}</div></td>"
                 f"<td><div class=heroes>{''.join(himg(h) for h in g['opp_picks'])}</div></td>"
                 f"<td class=links><a href='{g['dotabuff']}'>Dotabuff</a>"
                 + (f"<br><a href='{e(match_links[g['match_id']])}'>Детальная</a>" if g["match_id"] in (match_links or {}) else "")
                 + "</td></tr>")
    H.append("</tbody></table></div>")

    # игроки
    H.append("<h2>Игроки</h2><div class=card><table class=sortable><thead><tr>"
             "<th class=num>Поз.</th><th>Игрок</th><th class=num>K</th><th class=num>D</th><th class=num>A</th>"
             "<th class=num>KDA</th><th class=num>GPM</th><th class=num>XPM</th><th class=num>LH</th>"
             "<th class=num>Урон</th><th class=num>Варды</th><th>Герои (W/игр)</th></tr></thead><tbody>")
    for p in s["players"]:
        heroes = "".join(f"<span class=chip>{himg(h['hero'])}<b>{h['wins']}/{h['games']}</b></span>" for h in p["heroes"])
        H.append(f"<tr><td class=num>{p['position']}</td><td><b>{e(p['name'] or '')}</b></td>"
                 f"<td class=num>{p['avg_kills']}</td><td class=num>{p['avg_deaths']}</td><td class=num>{p['avg_assists']}</td>"
                 f"<td class=num>{p['kda']}</td><td class=num>{p['avg_gpm']}</td><td class=num>{p['avg_xpm']}</td>"
                 f"<td class=num>{p['avg_last_hits']}</td><td class=num>{p['avg_hero_damage']:,}".replace(",", " ") +
                 f"</td><td class=num>{p['avg_wards']}</td><td><div class=heroes style='flex-wrap:wrap;gap:4px'>{heroes}</div></td></tr>")
    H.append("</tbody></table></div>")

    # пики
    H.append("<h2>Пики команды</h2><div class=card><table class=sortable><thead><tr>"
             "<th>Герой</th><th class=num>Карты</th><th class=num>Победы</th><th class=num>Винрейт</th><th></th></tr></thead><tbody>")
    for h in s["hero_picks"]:
        H.append(f"<tr><td><div class=hcell>{himg(h['hero'])}{e(h['hero'])}</div></td><td class=num>{h['games']}</td>"
                 f"<td class=num>{h['wins']}</td><td class=num>{h['winrate']:.0f}%</td>"
                 f"<td><div class=bar><span style='width:{h['winrate']}%'></span></div></td></tr>")
    H.append("</tbody></table></div>")

    # баны
    def chips(items):
        return "<div class=chips>" + "".join(
            f"<span class=chip>{himg(h)}{e(h)} <b>×{c}</b></span>" for h, c in items) + "</div>"
    H.append("<div class=grid2><div><h2>Банит команда</h2><div class=card>" + chips(s["bans_by_team"]) +
             "</div></div><div><h2>Банят против команды</h2><div class=card>" + chips(s["bans_against_team"]) + "</div></div></div>")

    H.append(team_heroes_html(t, himg))

    # против героев
    H.append("<h2>Против каких героев играли</h2><div class=card><table class=sortable><thead><tr>"
             "<th>Герой соперника</th><th class=num>Карты</th><th class=num>Наши победы</th><th class=num>Наш винрейт</th></tr></thead><tbody>")
    for h in s["vs_heroes"]:
        H.append(f"<tr><td><div class=hcell>{himg(h['hero'])}{e(h['hero'])}</div></td><td class=num>{h['games']}</td>"
                 f"<td class=num>{h['our_wins']}</td><td class=num>{h['our_winrate']:.0f}%</td></tr>")
    H.append(f"</tbody></table></div></main><script>{SORT_JS}{TOTALS_JS}{VIZ_JS}</script></body></html>")
    return "\n".join(H)


TEAM_DIR = ROOT / "assets" / "teams"
# тёмные логотипы, которые не видно на светлом фоне — подкладываем чёрную плашку
DARK_LOGO = {7119388, 9964962, 2163}  # Team Spirit, GamerLegion, Team Liquid


def logo_cls(team_id):
    return "'logo dark'" if team_id in DARK_LOGO else "logo"
INDEX = ROOT / "index.html"


def league_page(league_id):
    """Адрес страницы турнира; для «всех турниров» — главная."""
    return INDEX if league_id == "all" else ROOT / "tournaments" / f"{league_id}.html"


def team_logo(team_id):
    """Логотип команды -> assets/teams/<id>.png (url берётся из raw/league_*_teams.json)."""
    path = TEAM_DIR / f"{team_id}.png"
    if path.exists():
        return path
    for f in (ROOT / "raw").glob("league_*_teams.json"):
        for t in json.loads(f.read_text(encoding="utf-8")):
            if t["team_id"] == team_id and t.get("logo_url"):
                try:
                    req = urllib.request.Request(t["logo_url"], headers={"User-Agent": "dota-stats/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        TEAM_DIR.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(r.read())
                    return path
                except Exception as ex:
                    print(f"  нет логотипа {team_id}: {ex}", file=sys.stderr)
    return None


def rel(p, out_path):
    return os.path.relpath(p, out_path.parent).replace(os.sep, "/")


def team_tags(league_id):
    """team_id -> короткий тег (PV, TSpirit…) для подписей оси графиков."""
    files = (sorted((ROOT / "raw").glob("league_*_teams.json")) if league_id == "all"
             else [ROOT / "raw" / f"league_{league_id}_teams.json"])
    tags = {}
    for f in files:
        if f.exists():
            tags.update({x["team_id"]: x.get("tag") or x["name"] for x in json.loads(f.read_text(encoding="utf-8"))})
    return tags


SWITCH_CSS = """
.scope{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;margin:14px 0 4px}
.scope .lbl{font:600 11.5px var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.scope .seg{display:flex;flex-wrap:wrap;gap:4px;background:var(--bar);padding:4px;border-radius:12px;max-width:100%}
.scope .seg a{font-size:13px;font-weight:600;padding:7px 14px;border-radius:8px;color:var(--muted);text-decoration:none;transition:background-color .2s,color .2s}
.scope .seg a:hover{color:var(--text)}.scope .seg a:active{transform:scale(.98)}
.scope .seg a[aria-current=page]{background:var(--card);color:var(--text);box-shadow:var(--shadow)}
.scope .seg small{font:11px var(--mono);opacity:.7;margin-left:6px}
"""


def scope_switch(t, out_path):
    """Переключатель «Все турниры / <турнир>» между страницами одной команды."""
    items = []
    for d in sorted((ROOT / "data").iterdir(), reverse=True):
        for f in d.glob("*.json"):
            tt = json.loads(f.read_text(encoding="utf-8"))
            if tt["team_id"] == t["team_id"]:
                name = json.loads((ROOT / "raw" / f"league_{d.name}.json").read_text(encoding="utf-8"))["name"]
                items.append((d.name, name, ROOT / "reports" / d.name / f"{f.stem}.html", tt["summary"]))
                break
    if not items:
        return ""
    allp = ROOT / "reports" / "all" / f"{items[0][2].stem}.html"
    parts = [("all", "Общая статистика", allp, None)] + items
    links = "".join(
        f"<a href='{escape(rel(p, out_path))}'{' aria-current=page' if key == str(t['league_id']) else ''}>{escape(n)}"
        + (f"<small>{sm['wins']}-{sm['losses']}</small>" if sm else "") + "</a>"
        for key, n, p, sm in parts)
    return f"<div class=scope><span class=lbl>Статистика</span><nav class=seg aria-label='Охват статистики'>{links}</nav></div>"


def match_pages(out_path):
    """match_id карты -> относительная ссылка на нашу страницу матча (если матч есть в расписании турнира)."""
    from render_schedule import find_series, series_results
    links = {}
    for sf in (ROOT / "odds").glob("*/schedule.json"):
        lid = sf.parent.name
        if not (ROOT / "raw" / f"league_{lid}_matches.json").exists():
            continue
        ser = series_results(lid, 3)
        for ev in json.loads(sf.read_text(encoding="utf-8"))["matches"]:
            s = find_series(ser, ev["a"], ev["b"], ev["start"]) if ev.get("event_id") else None
            for m in (s["maps"] if s else []):
                links[m["match_id"]] = rel(ROOT / "matches" / lid / f"{ev['event_id']}.html", out_path)
    return links


def write_html(t, league_name, out_path):
    logo = team_logo(t["team_id"])
    out_path.write_text(render(t, league_name, rel_imgs(load_heroes(), out_path),
                               logo=rel(logo, out_path) if logo else None,
                               back=rel(league_page(t["league_id"]), out_path),
                               tags=team_tags(t["league_id"]),
                               switch=scope_switch(t, out_path), match_links=match_pages(out_path)), encoding="utf-8")


if __name__ == "__main__":
    for path in sys.argv[1:]:
        t = json.loads(Path(path).read_text(encoding="utf-8"))
        league = json.loads((ROOT / "raw" / f"league_{t['league_id']}.json").read_text(encoding="utf-8"))
        out = ROOT / "reports" / str(t["league_id"]) / (Path(path).stem + ".html")
        write_html(t, league["name"], out)
        print(out)
