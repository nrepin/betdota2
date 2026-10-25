"""Страница матча: matches/<league>/<event_id>.html — коэффициенты, прогноз ИИ, результат.

Матчи берутся из odds/<league>/schedule.json (id события PARI), коэффициенты — из odds/<league>/latest.json
(а если матч уже ушёл из линии — из сохранённого прогноза), прогноз и результат — из forecasts/<league>/.
"""
import datetime
import json
from html import escape as e

import forecast
import heroes_stats
import netutil
import urllib.request
from render_html import CSS, ROOT, head, load_heroes, logo_cls, rel, team_logo
from render_schedule import MSK, SCHEDULE_CSS, find_series, series_results, teams_of

MATCH_CSS = """
.mh{display:grid;grid-template-columns:1fr auto 1fr;gap:16px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-top:16px}
.mh .t{display:flex;flex-direction:column;align-items:center;gap:8px;text-align:center;color:inherit;text-decoration:none;font-weight:650;font-size:18px}
.mh .t img{width:72px;height:72px;object-fit:contain}.mh .t img.dark{background:#111;border-radius:12px;padding:6px}
.mh .t:hover span{text-decoration:underline}.mh .t.win{color:var(--win)}
.mh .mid{text-align:center;font:600 13px var(--mono);color:var(--muted)}.mh .mid b{display:block;font-size:32px;color:var(--text);letter-spacing:.02em}
.mh .mid .st{display:inline-block;margin-top:6px;padding:3px 8px;border-radius:6px;background:var(--bar)}
.mh .mid .st.live{background:var(--accent);color:var(--on-accent)}
@media (max-width:620px){.mh{grid-template-columns:1fr;gap:10px}.mh .t{flex-direction:row;justify-content:center}.mh .t img{width:44px;height:44px}}
.mlinks{display:flex;flex-wrap:wrap;gap:14px;margin:10px 0 0;font-size:13px}
.fc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-top:10px}
.fc .meta{font:11.5px var(--mono);color:var(--muted);margin-bottom:10px}
.fc .note{font-size:14px;line-height:1.55;max-width:80ch;margin:12px 0 0}
.pk{display:grid;grid-template-columns:90px 1fr auto auto auto auto;gap:6px 16px;align-items:center;padding:10px 0;border-top:1px solid var(--line);font-size:14px}
.pk:first-of-type{border-top:0}.pk .c{font:600 11.5px var(--mono);text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.pk .tx{font-weight:650}.pk .n{font:13px var(--mono);white-space:nowrap}.pk .n i{font-style:normal;color:var(--muted);margin-right:4px}
.mark{display:inline-block;min-width:74px;white-space:nowrap;text-align:center;padding:3px 10px;border-radius:6px;font:600 12px var(--mono);background:var(--bar);color:var(--muted)}
.mark.ok{background:var(--win-bg);color:var(--win)}.mark.no{background:var(--loss-bg);color:var(--loss)}
.pk .mark{grid-column:6}
@media (max-width:700px){.pk{grid-template-columns:1fr auto}.pk .c{grid-column:1/-1}.pk .mark{grid-column:auto}}
.res{display:flex;flex-wrap:wrap;gap:8px 28px;font-size:14px;margin-top:2px}.res b{font-family:var(--mono)}
.mt{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:10px}
.mt table{width:100%;border-collapse:collapse;font-size:13.5px}
.mt th{font:600 11.5px var(--mono);text-transform:uppercase;letter-spacing:.05em;color:var(--muted);text-align:left;padding:10px 12px;border-bottom:1px solid var(--line)}
.mt td{padding:9px 12px;border-bottom:1px solid var(--line)}.mt tr:last-child td{border-bottom:0}
.mt td.k{font-family:var(--mono);white-space:nowrap}.mt td.k i{font-style:normal;color:var(--muted);font-size:11.5px;margin:0 4px 0 8px}.mt td.k i:first-child{margin-left:0}
.mt td.num,.mt th.num{text-align:right;font-family:var(--mono);white-space:nowrap}
.mt tr.pick td{background:var(--hover);font-weight:600}.mt tr.noise td{color:var(--muted)}
.mt td.d.pos{color:var(--win)}.mt td.d.neg{color:var(--loss)}
"""

HERO_CSS = """
.dr{display:grid;grid-template-columns:90px 1fr;gap:8px 14px;align-items:center;padding:10px 0;border-top:1px solid var(--line)}
.dr:first-of-type{border-top:0}.dr .c{font:600 11.5px var(--mono);text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.dr .side{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px}.dr .side b{font-size:13px;min-width:110px}
.hc{display:inline-flex;flex-direction:column;align-items:center;gap:2px;font:600 10.5px var(--mono)}
.hc img{width:56px;height:32px;border-radius:4px;object-fit:cover;border:2px solid transparent}
.hc.fast img{border-color:var(--win)}.hc.long img{border-color:var(--loss)}.hc.fast i{color:var(--win)}.hc.long i{color:var(--loss)}
.dr .side b .cup{width:16px;height:16px;vertical-align:-3px;margin-left:5px}.hc{position:relative}.dr .side .hc b.tw{min-width:0;width:auto;position:absolute;top:-4px;right:-4px;font:700 9px/1 var(--mono);padding:2px 3px;border-radius:4px;color:#fff}.hc b.tw.f{background:#1d7a3e}.hc b.tw.s{background:#b36b00}
.hc i{font-style:normal;color:var(--muted)}.hc s{text-decoration:none;font-weight:500;color:var(--text);white-space:nowrap}
.verdict{font-size:13px;background:var(--hover);border:1px solid var(--line);border-radius:6px;padding:6px 10px}.tempo{font:600 12px var(--mono);margin-left:auto;color:var(--muted)}
.livebox .meta{font:11.5px var(--mono);color:var(--muted);margin-bottom:6px}
@media (max-width:700px){.dr{grid-template-columns:1fr}}
"""
LIVE_JS = """
const H=__HEROES__,T=[__A__,__B__],box=document.getElementById('live');
const OV=__OVERALL__;
const sg=v=>(v>0?'+':'')+v;
const TW=__TWNOTE__;
const TH=__TH__;
const W=__WIN__;
const chip=(id,tid)=>{const h=H[id];if(!h)return '<span class=hc><i>?</i></span>';const r=(TH[tid]||{})[id]||[0,0];
const tl=r[0]?r[0]+'× · '+Math.round(100*r[1]/r[0])+'%':'0×';
return '<span class="hc '+h.l+'" title="'+h.n+': ср. '+h.a+' мин, темп '+sg(h.t)+'; команда брала героя '+r[0]+' раз, побед '+r[1]+'"><img src="'+h.i+'" alt="'+h.n+'">'+(h.w?'<b class="tw '+h.w+'">'+(h.w=='f'?'▲':'▼')+'</b>':'')+'<i>'+sg(h.t)+'</i><s>'+tl+'</s></span>'};
const mm=t=>Math.floor(t/60)+':'+String(Math.abs(t)%60).padStart(2,'0');
async function tick(){try{const r=await fetch('https://api.opendota.com/api/live');const L=await r.json();
const g=L.find(x=>T.includes(x.team_id_radiant)&&T.includes(x.team_id_dire)&&x.league_id==__LG__&&!x.deactivate_time);
if(!g){box.innerHTML='<div class=meta>сейчас карта не идёт · обновлено '+new Date().toLocaleTimeString('ru-RU')+'</div>';return}
const side=t=>g.players.filter(p=>p.team===t);const nm=t=>t==0?g.team_name_radiant:g.team_name_dire;
box.innerHTML='<div class=meta>карта идёт: '+mm(g.game_time)+' · убийства '+g.radiant_score+':'+g.dire_score+' · золото '+nm(g.radiant_lead>0?0:1)+' +'+Math.abs(g.radiant_lead)+' · обновлено '+new Date().toLocaleTimeString('ru-RU')+'</div>'+
[0,1].map(t=>'<div class=dr><span class=c>'+(t==0?'Radiant':'Dire')+'</span><div class=side><b>'+nm(t)+'</b>'+side(t).map(p=>chip(p.hero_id,t==0?g.team_id_radiant:g.team_id_dire)).join('')+'</div></div>').join('')+verdict(g.players)+winrow(g)}catch(e){}}
function winrow(g){const ids=t=>g.players.filter(p=>p.team===t&&p.hero_id).map(p=>p.hero_id);
const pw=a=>a.length?a.reduce((s,h)=>s+(W.pw[h]||0),0)*5/a.length:0;const ra=ids(0),di=ids(1);
const base=g.team_id_radiant==T[0]?W.pa:1-W.pa;const hero=W.hw*(pw(ra)-pw(di));
const fr=W.f[g.team_id_radiant]||[null,'нет данных'],fd=W.f[g.team_id_dire]||[null,'нет данных'];
const fm=(fr[0]!==null&&fd[0]!==null)?W.fw*(fr[0]-fd[0]):0;const p=Math.min(.95,Math.max(.05,base+hero+fm));
const win=p>=.5?g.team_name_radiant:g.team_name_dire,pc=Math.round(100*Math.max(p,1-p));const sp=v=>(v>=0?'+':'')+Math.round(v*100);
const part=Math.min(ra.length,di.length)<5?' <i class=muted>(пики не завершены: выбрано '+ra.length+' + '+di.length+' героев из 5 + 5)</i>':'';
return '<div class=dr><span class=c></span><div class=side><span class=verdict>Прогноз по драфту: победит <b>'+win+'</b>, '+pc+'%. Команды '+Math.round(100*base)+'% ('+g.team_name_radiant+'), герои '+sp(hero)+' п.п., форма '+sp(fm)+' п.п. (форма: '+g.team_name_radiant+' — '+fr[1]+', '+g.team_name_dire+' — '+fd[1]+').'+part+'</span></div></div>'}
function verdict(ps){const t=ps.map(p=>H[p.hero_id]).filter(Boolean).map(h=>h.t);if(t.length<6)return '';
const m=Math.round(t.reduce((a,b)=>a+b,0)/t.length*10)/10,w=m>=1?'затяжная':m<=-1?'быстрая':'средняя';
const q=ps.map(p=>H[p.hero_id]).filter(Boolean),f=q.filter(h=>h.w=='f').length,s=q.filter(h=>h.w=='s').length;
return '<div class=dr><span class=c></span><div class=side><span class=verdict>Оценка драфтов: карта <b>'+w+'</b> (темп '+sg(m)+'), ожидаемая длительность ≈ '+(OV+m).toFixed(1)+' мин. Вышки: быстро ломают '+f+', медленно '+s+' героев; '+TW+'.</span></div></div>'}
tick();setInterval(tick,30000);
"""


DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def page_path(lid, eid):
    return ROOT / "matches" / lid / f"{eid}.html"


def hero_table(imgs, st, names, out):
    """{hero_id: {n, i, a, t, l}} для чипов героев (цвет рамки = темп героя)."""
    r = {}
    for hid, h in st["heroes"].items():
        nm = names[str(hid)]["localized_name"]
        r[hid] = {"n": nm, "i": rel(imgs[nm], out) if nm in imgs else "", "a": h["avg"], "t": h["tilt"],
                  "w": "f" if h["tlabel"] == "быстро ломает" else "s" if h["tlabel"] == "медленно ломает" else "", "td": h["td"],
                  "l": "long" if h["label"] == "затяжной" else "fast" if h["label"] == "быстрый" else ""}
    return r


def team_line(th, hid):
    """«3 · 67%» — сколько раз команда брала героя и её винрейт с ним."""
    n, w = (th or {}).get(hid, (0, 0))
    return (f"{n}× · {w / n:.0%}" if n else "0×"), n, w


def chip(hid, ht, th=None):
    h = ht.get(hid)
    if not h:
        return "<span class=hc><i>?</i></span>"
    tl, n, w = team_line(th, hid)
    tt = f"; команда брала героя {n} раз, побед {w}" if th is not None else ""
    extra = f"<s>{tl}</s>" if th is not None else ""
    tw = {"f": "▲", "s": "▼"}.get(h["w"], "")
    twt = {"f": "быстро ломает вышки", "s": "медленно ломает вышки"}.get(h["w"], "вышки: средне")
    return (f"<span class='hc {h['l']}' title='{e(h['n'])}: ср. {h['a']} мин, темп {h['t']:+g}; {twt} ({h['td']}/мин){tt}'>"
            f"<img src='{e(h['i'])}' alt='{e(h['n'])}'>" + (f"<b class='tw {h['w']}'>{tw}</b>" if tw else "")
            + f"<i>{h['t']:+g}</i>{extra}</span>")


def win_html(win, na, nb, radiant_win=None):
    """Строка «Прогноз по драфту»: кто победит с учётом команд, героев и формы; для сыгранной карты — сверка."""
    if not win:
        return ""
    p = win["p"]
    fav, pf, fname = (na, p, win["a"]) if p >= 0.5 else (nb, 1 - p, win["b"])
    sgn = lambda v: f"{v * 100:+.0f}"
    part = (f" <i class=muted>(пики не завершены: выбрано {win['na']} + {win['nb']} героев из 5 + 5)</i>"
            if min(win["na"], win["nb"]) < 5 else "")
    chk = ""
    if radiant_win is not None:
        chk = (" <span class='mark ok'>✓ сбылся</span>" if (p >= 0.5) == radiant_win else " <span class='mark no'>✗ не сбылся</span>")
    return (f"<div class=dr><span class=c></span><div class=side><span class=verdict>Прогноз по драфту: победит <b>{e(fav)}</b>, "
            f"{pf:.0%}. Команды {win['base']:.0%} ({e(na)}), герои {sgn(win['hero'])} п.п., форма {sgn(win['form'])} п.п. "
            f"(форма: {e(na)} — {e(win['form_a'])}, {e(nb)} — {e(win['form_b'])}).{chk}{part}</span></div></div>")


def frozen_win_html(fc):
    """Прогноз победителя по драфту, зафиксированный в начале карты (не пересчитывается), со сверкой после игры."""
    w = fc.get("draft_win")
    if not w:
        return ""
    p = w["p"]
    fav, pf = (fc["t1"], p) if p >= 0.5 else (fc["t2"], 1 - p)
    sgn = lambda v: f"{v * 100:+.0f}"
    res = fc.get("result")
    chk = ("<span class=mark>ждём</span>" if not res else
           ("<span class='mark ok'>✓ сбылся</span>" if res["winner_id"] == (fc["t1_id"] if p >= 0.5 else fc["t2_id"])
            else "<span class='mark no'>✗ не сбылся</span>"))
    return (f"<div class=pk><span class=c>Прогноз по драфту</span><span class=tx>победит {e(fav)}, {pf:.0%} "
            f"(команды {w['base']:.0%} за {e(fc['t1'])}, герои {sgn(w['hero'])} п.п., форма {sgn(w['form'])} п.п.; "
            f"форма: {e(fc['t1'])} — {e(w['form_a'])}, {e(fc['t2'])} — {e(w['form_b'])})</span>{chk}</div>")


def totals_html(fc):
    """Три прогноза после драфтов — тотал убийств, продолжительность, победитель — всегда, с коэффициентом и итогом.
    Ставка — на одно из трёх (строка «Ставка» выше)."""
    a = fc.get("after_draft")
    if not a:
        return ""
    res = fc.get("result")
    bet = a.get("bet")

    def mark(hit, fact=""):
        if hit is None:
            return "<span class=mark>ждём</span>"
        return ((f"<span class=n><i>итог</i>{fact}</span>" if fact else "") +
                ("<span class='mark ok'>✓ сбылся</span>" if hit else "<span class='mark no'>✗ не сбылся</span>"))

    def row(label, cat, text, odds, hit, fact, extra=""):
        star = " <i class=muted>(ставка)</i>" if bet == cat else ""
        cf = f"<span class=n><i>коэф</i>{odds}</span>" if odds else "<span></span>"
        return f"<div class=pk><span class=c>{label}</span><span class=tx>{text}{star}{extra}</span>{cf}{mark(hit, fact if res else '')}</div>"
    out = []
    k, t = a.get("kills"), a.get("time")
    if k:
        exp = f" <i class=muted>(ожидание по драфтам ≈ {a['exp_k']:g})</i>" if a.get("exp_k") else ""
        out.append(row("Прогноз по тоталу", "kills", e(k["text"]), k["odds"], k["hit"], f"{res['kills']} уб." if res else "", exp))
    if t:
        exp = f" <i class=muted>(ожидание по драфтам ≈ {a['exp']:g} мин)</i>" if a.get("exp") else ""
        out.append(row("Прогноз по времени", "time", e(t["text"]), t["odds"], t["hit"], f"{res['duration']:g} мин" if res else "", exp))
    dw = fc.get("draft_win")
    w = a.get("win")
    if dw or w:
        if dw:
            p = dw["p"]
            fav, pf = (fc["t1"], p) if p >= 0.5 else (fc["t2"], 1 - p)
            sg = lambda v: f"{v * 100:+.0f}"
            text = (f"победит {e(fav)}, {pf:.0%} <i class=muted>(команды {dw['base']:.0%} за {e(fc['t1'])}, герои {sg(dw['hero'])} п.п., "
                    f"форма {sg(dw['form'])} п.п.; форма: {e(fc['t1'])} — {e(dw['form_a'])}, {e(fc['t2'])} — {e(dw['form_b'])})</i>")
            hit = None if not res else (res["winner_id"] == (fc["t1_id"] if p >= 0.5 else fc["t2_id"]))
        else:
            text, hit = e(w["text"]), w["hit"]
        out.append(row("Прогноз по победителю", "win", text, w["odds"] if w else None, hit, "", ""))
    return "".join(out)


def eval_html(ev, win_row=""):
    if not ev:
        return win_row
    w = {"затяжной": "затяжная", "быстрый": "быстрая", "средний": "средняя"}[ev["word"]]
    tw = (f" Вышки: драфты <b>{ev['tw_word']}</b>" + (f" (индекс {ev['tw']:+g})" if ev["tw"] is not None else "")
          + (f"; {ev['tw_note']}" if ev.get("tw_note") else "") + ".")
    return (f"<div class=dr><span class=c></span><div class=side><span class=verdict>Оценка драфтов: карта <b>{w}</b> "
            f"(темп {ev['mean']:+g}), ожидаемая длительность ≈ {ev['exp']:g} мин.{tw}</span></div></div>" + win_row)


def draft_row(m, teams, ht, st, label, out):
    """Две строки (Radiant/Dire) героев сыгранной карты + оценка драфтов."""
    rows = []
    for rad in (True, False):
        tid = m["radiant_team_id"] if rad else m["dire_team_id"]
        ids = [p["hero_id"] for p in m["players"] if bool(p["isRadiant"]) == rad]
        t = heroes_stats.draft_tempo(ids, st)
        th = heroes_stats.team_hero_stats(tid, m["match_id"])
        tw = f"темп драфта: {heroes_stats.tempo_word(t)}" + ("" if t is None else f" ({t:+g})")
        won = bool(m["radiant_win"]) == rad
        cup = (f"<img class=cup src='{e(rel(ROOT / 'assets' / 'trophy.svg', out))}' alt='Победитель' title='Победитель карты'>"
               if won else "")
        rows.append(f"<div class=dr><span class=c>{label if rad else ''}</span><div class=side><b>"
                    f"{e(teams.get(tid, {}).get('name', ''))}{cup}</b>" + "".join(chip(h, ht, th) for h in ids)
                    + f"<span class=tempo>{tw}</span></div></div>")
    ids = lambda rad: [p["hero_id"] for p in m["players"] if bool(p["isRadiant"]) == rad]
    import forecast
    wn = forecast.draft_win(m["radiant_team_id"], m["dire_team_id"], ids(True), ids(False), st, m["start_time"])
    nm = lambda rad: teams.get(m["radiant_team_id"] if rad else m["dire_team_id"], {}).get("name", "")
    rows.append(eval_html(heroes_stats.draft_eval(ids(True), ids(False), st), win_html(wn, nm(True), nm(False), m["radiant_win"])))
    return "".join(rows)


def live_snapshot(lid, ev):
    """Текущая карта серии из OpenDota /live (None, если не идёт или нет связи)."""
    try:
        req = urllib.request.Request("https://api.opendota.com/api/live", headers={"User-Agent": "dota-stats/1.0"})
        live = json.loads(netutil.urlopen(req, timeout=30).read())
    except Exception:
        return None
    for g in live:
        if (g.get("league_id") == int(lid) and {g.get("team_id_radiant"), g.get("team_id_dire")} == {ev["a"], ev["b"]}
                and not g.get("deactivate_time")):
            return g
    return None


def hit_mark(h):
    return "<span class='mark ok'>✓ зашло</span>" if h else ("<span class='mark no'>✗ не зашло</span>" if h is False
                                                           else "<span class=mark>ждём</span>")


def prematch_html(lid, eid, a, b):
    """Блок «Коэффициенты до матча»: открытие и закрытие линии на серию и на каждую карту (из odds/<лига>/prematch)."""
    import prematch
    d = prematch.load(lid, eid)
    if not d:
        return ("<h2>Коэффициенты до матча</h2><div class=fc>Пока не сохранены: они пишутся автопилотом при каждом "
                "скачивании линии до старта матча.</div>")
    n1, n2 = e(d["t1"]), e(d["t2"])
    H = ["<h2>Коэффициенты до матча</h2><div class=mt><table><thead><tr><th>Рынок</th><th>Открытие</th><th>Закрытие</th></tr></thead><tbody>"]
    s = d.get("series") or {}
    if s.get("close"):
        o, c = s["open"], s["close"]
        H.append(f"<tr><td>Победа в серии</td><td>{n1} {o['odds'][0]} · {n2} {o['odds'][1]}<div class=muted>{e(o['ts'])} МСК</div></td>"
                 f"<td>{n1} {c['odds'][0]} · {n2} {c['odds'][1]}<div class=muted>{e(c['ts'])} МСК</div></td></tr>")

    def fmt(rows):
        out = []
        for r in rows:
            if r["market"].startswith(("Победа на карте", "Тотал убийств", "Время карты")):
                out.append(f"{e(r['market'])}: {r['k1']} / {r['k2']}")
        return "<br>".join(out)
    for n in sorted(d.get("maps") or {}):
        mp = d["maps"][n]
        H.append(f"<tr><td>Карта {n}</td><td>{fmt(mp['open']['rows'])}<div class=muted>{e(mp['open']['ts'])} МСК</div></td>"
                 f"<td>{fmt(mp['close']['rows'])}<div class=muted>{e(mp['close']['ts'])} МСК</div></td></tr>")
    H.append("</tbody></table></div><div class=sch-note>Открытие — первый снимок линии, закрытие — последний до старта матча (карты). "
             "Сохраняется навсегда, после старта линия в PARI меняется на лайвовую.</div>")
    return "".join(H)


def render(lid, ev, teams, ser, snap_rows, stems):
    out = page_path(lid, ev["event_id"])
    eid = str(ev["event_id"])
    fcs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted((ROOT / "forecasts" / lid).glob(f"{eid}L*.json"))]
    fc = fcs[-1] if fcs else None
    a, b = teams.get(ev["a"], {}), teams.get(ev["b"], {})
    now = datetime.datetime.now(MSK).timestamp()
    s = find_series(ser, ev["a"], ev["b"], ev["start"])
    dt = datetime.datetime.fromtimestamp(ev["start"], MSK)
    when = f"{dt:%d.%m} {DAYS[dt.weekday()]} {dt:%H:%M} МСК"
    if s and s["done"]:
        status, cls = "завершён", ""
    elif s or ev["start"] <= now:
        status, cls = "идёт", " live"
    else:
        status, cls = "ожидается", ""
    score = f"{s['w'][ev['a']]}:{s['w'][ev['b']]}" if s else "vs"
    winner = None
    if s and s["done"]:
        winner = max(s["w"], key=s["w"].get)

    def team(tid, t):
        logo = team_logo(tid)
        img = f"<img class={logo_cls(tid)} src='{e(rel(logo, out))}' alt=''>" if logo else ""
        href = rel(ROOT / "reports" / lid / f"{stems[tid]}.html", out) if tid in stems else ""
        w = " win" if winner == tid else ""
        inner = f"{img}<span>{e(t.get('name', str(tid)))}</span>"
        return f"<a class='t{w}' href='{e(href)}'>{inner}</a>" if href else f"<div class='t{w}'>{inner}</div>"

    H = [head(f"{a.get('name')} – {b.get('name')}", f"Матч {a.get('name')} – {b.get('name')}: коэффициенты, прогноз ИИ и результат")
         + f"<style>{CSS}{SCHEDULE_CSS}{MATCH_CSS}{HERO_CSS}</style></head><body><main class=wrap>",
         f"<a class=back href='{e(rel(ROOT / 'tournaments' / f'{lid}.html', out))}'>← страница турнира</a>",
         f"<div class=mh>{team(ev['a'], a)}<div class=mid>{e(when)}<b>{score}</b><span class='st{cls}'>{status}</span></div>"
         f"{team(ev['b'], b)}</div>",
         f"<div class=mlinks>" + (f"<a href='{e(ev['url'])}'>Матч на PARI</a>" if ev.get("url") else "")
         + f"<a href='https://www.dotabuff.com/esports/leagues/{lid}'>Турнир на Dotabuff</a></div>"]

    # прогноз: один на карту, даётся в начале карты, когда выбраны герои обеих команд
    hide_fc = bool(s and s["done"]) and not fcs   # у завершённого матча без прогноза блока нет
    if not hide_fc:
        H.append("<h2>Прогноз ИИ после драфтов</h2>")
    for f in fcs:
        hits = [p["hit"] for p in f["picks"] if p["hit"] is not None]
        tot = f" · зашло {sum(hits)} из {len(hits)}" if hits else ""
        H.append(f"<div class=fc><div class=meta>карта {f['map_no']} · в начале карты, {e(f['created'])} МСК{tot}"
                 + (f" · <a href='https://www.dotabuff.com/matches/{f['result']['match_id']}'>карта {f['map_no']} на Dotabuff</a>"
                    if f.get("result") else "") + "</div>")
        for p in f["picks"]:
            est = f"<span class=n><i>оценка / линия</i>{p['est']:.0%} / {p['implied']:.0%}</span>" if p.get("est") is not None else ""
            dog = (" <i class=muted>(андердог: ставка на перевес над линией, а не на победителя)</i>"
                   if p["cat"] == "win" and p.get("est") is not None and p["est"] < 0.5 else "")
            H.append(f"<div class=pk><span class=c>Ставка</span><span class=tx>{e(p['text'])}{dog}</span>"
                     f"<span class=n><i>коэф</i>{p['odds']}</span>{est}"
                     f"<span class=n><i>ставка</i>{p['stake']} $</span>{hit_mark(p['hit'])}</div>")
        H.append(totals_html(f))
        H.append(f"<p class=note>{e(f['note'])}</p></div>")
    if not fcs and not hide_fc:
        H.append("<div class=fc>Прогноз будет дан в начале карты, когда обе команды выберут героев: "
                 "три прогноза (победитель, тотал убийств, время) и ставка 100 $ на один из них: победа — от коэффициента 1.4, тоталы — от 1.7.</div>")

    # результат
    r = fc["result"] if fc else None
    if r or s:
        H.append("<h2>Результат</h2><div class=fc>")
        if s:
            H.append(f"<div class=res><div>Серия: <b>{score}</b>{'' if s['done'] else ' (идёт)'}</div></div><div class=series style='margin-top:10px'>")
            for i, m in enumerate(s["maps"], 1):
                w = m["radiant_team_id"] if m["radiant_win"] else m["dire_team_id"]
                tn = teams.get(w, {}).get("name", "")
                H.append(f"<div class=ser><span class='pill w'>карта {i}</span>{e(tn)}, {m['duration'] // 60}:{m['duration'] % 60:02d}, "
                         f"убийств {m['radiant_score'] + m['dire_score']} "
                         f"(<a href='https://www.dotabuff.com/matches/{m['match_id']}'>Dotabuff</a>)</div>")
            H.append("</div>")
        if r:
            H.append(f"<div class=res style='margin-top:10px'><div>Карта {fc['map_no']} (прогноз): время <b>{r['duration']:g} мин</b></div>"
                     f"<div>убийства <b>{r['kills']}</b></div></div>")
        H.append("</div>")

    # герои по картам и лайв
    st = heroes_stats.stats()
    names = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    ht = hero_table(load_heroes(), st, names, out)
    H.append("<h2>Герои по картам</h2><div class=fc>")
    show_live = not (s and s["done"]) and ev["start"] <= now + 1800
    if show_live:
        g = live_snapshot(lid, ev)
        init = "<div class=meta>сейчас карта не идёт</div>"
        if g:
            import forecast
            ths = {t: heroes_stats.team_hero_stats(g["team_id_radiant"] if t == 0 else g["team_id_dire"]) for t in (0, 1)}

            def side(t):
                return "".join(chip(p["hero_id"], ht, ths[t]) for p in g["players"] if p["team"] == t)
            init = (f"<div class=meta>карта идёт: {g['game_time'] // 60}:{g['game_time'] % 60:02d} · убийства "
                    f"{g['radiant_score']}:{g['dire_score']} · снимок на момент сборки страницы</div>"
                    + "".join(f"<div class=dr><span class=c>{'Radiant' if t == 0 else 'Dire'}</span><div class=side><b>"
                              f"{e(g['team_name_radiant'] if t == 0 else g['team_name_dire'])}</b>{side(t)}</div></div>" for t in (0, 1))
                    + eval_html(heroes_stats.draft_eval(*[[p["hero_id"] for p in g["players"] if p["team"] == t] for t in (0, 1)], st),
                                win_html(forecast.draft_win(g["team_id_radiant"], g["team_id_dire"],
                                                            *[[p["hero_id"] for p in g["players"] if p["team"] == t] for t in (0, 1)], st),
                                         g["team_name_radiant"], g["team_name_dire"])))
        H.append(f"<h3 style='margin:0 0 6px;font-size:15px'>Лайв</h3><div id=live class=livebox>{init}</div>")
    if s:
        for i, m in enumerate(s["maps"], 1):
            f = ROOT / "raw" / "matches" / f"{m['match_id']}.json"
            if f.exists():
                H.append(draft_row(json.loads(f.read_text(encoding="utf-8")), teams, ht, st, f"карта {i}", out))
            else:
                H.append(f"<div class=dr><span class=c>карта {i}</span><div class=side>матч не загружен: "
                         "<code>collect_team.py --refresh</code></div></div>")
    elif not show_live:
        H.append("<div class=meta>Карты ещё не сыграны.</div>")
    H.append("<div class=sch-note>Рамка: <b style='color:var(--win)'>синяя</b> — герой быстрый, "
             "<b style='color:var(--loss)'>красная</b> — затяжной (по сыгранным картам турниров, "
             f"{st['maps']} карт); число — темп героя в минутах относительно средней карты. "
             "Значок в углу: <b style='color:#1d7a3e'>▲</b> — герой быстро ломает вышки, <b style='color:#b36b00'>▼</b> — медленно (урон по вышкам в минуту относительно позиции). "
             "Подробнее на странице «Герои».</div></div>")

    # предварительный прогноз до матча (сохраняется один раз, пока матч не начался)
    import preview
    pv = preview.ensure(lid, ev, teams, now, bool(s and s['done']))
    if pv:
        H.append(preview.html(pv, winner, (s or {}).get("maps", [])))

    # коэффициенты до матча и форма команд
    H.append(prematch_html(lid, eid, a, b))
    import form
    H.append("<h2>Форма команд</h2>")
    for tid, tm in ((ev["a"], a), (ev["b"], b)):
        H.append(form.html(form.form(tid, ev["start"]), tm.get("name") or str(tid)).replace("<div class=card>", "<div class=card style='margin-bottom:10px'>", 1))
    H.append(f"<div class=sch-note>{form.NOTE}</div>")

    # коэффициенты
    rows = snap_rows if snap_rows is not None else (fc["rows"] if fc else [])
    H.append("<h2>Коэффициенты</h2>")
    if rows:
        picks = {p["market"] for f in fcs for p in f["picks"]}
        H.append("<div class=mt><table><thead><tr><th>Рынок</th><th>Коэффициенты</th><th class=num>Линия</th>"
                 "<th class=num>Статистика</th><th class=num>Разница</th><th>Основание</th><th>Перевес</th></tr></thead><tbody>")
        for x in rows:
            d = x["diff"] * 100
            c = "pick" if x["market"] in picks else ("noise" if x["signal"] == "нет перевеса" else "")
            H.append(f"<tr class='{c}'><td>{e(x['market'])}</td><td class=k><i>{e(x['c1'])}</i>{x['k1']}<i>{e(x['c2'])}</i>{x['k2']}</td>"
                     f"<td class=num>{x['line'] * 100:.0f}%</td><td class=num>{x['est'] * 100:.0f}%</td>"
                     f"<td class='num d {'pos' if d > 0 else 'neg'}'>{d:+.0f} п.п.</td><td>{e(x['basis'])}</td><td>{x['signal']}</td></tr>")
        H.append("</tbody></table></div><div class=sch-note>«Линия» — вероятность первого исхода без маржи букмекера; "
                 "«Статистика» — частота по картам обеих команд. Выделена строка прогноза. "
                 "Это разбор статистики, не гарантия исхода.</div>")
    else:
        H.append("<div class=fc>Линия по картам для этого матча не открыта или уже снята.</div>")
    script = ""
    if show_live:
        hjs = json.dumps({str(k): v for k, v in ht.items()}, ensure_ascii=False)
        script = "<script>" + (LIVE_JS.replace("__HEROES__", hjs).replace("__A__", str(ev["a"]))
                               .replace("__B__", str(ev["b"])).replace("__TH__", json.dumps({str(t): {str(k): v for k, v in heroes_stats.team_hero_stats(t).items()} for t in (ev["a"], ev["b"])})).replace("__LG__", str(int(lid))).replace("__WIN__", win_js(ev, st, now)).replace("__OVERALL__", str(st["overall"])).replace("__TWNOTE__", json.dumps(heroes_stats.tower_note(st), ensure_ascii=False))) + "</script>"
    H.append(f"</main>{script}</body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(H), encoding="utf-8")


def win_js(ev, st, now):
    """Данные для расчёта прогноза по драфту в браузере: база команд, вклад героев, форма."""
    import forecast
    import form
    f = {}
    for t in (ev["a"], ev["b"]):
        x = form.form(t, now)
        f[str(t)] = [x["score"], x["word"]]
    pw = {str(h): (v["wr"] * v["n"] + 0.5 * forecast.HERO_K) / (v["n"] + forecast.HERO_K) - 0.5 for h, v in st["heroes"].items()}
    return json.dumps({"pa": form.model_p(ev["a"], ev["b"], now), "hw": forecast.HERO_W, "fw": forecast.FORM_SHOW_W,
                       "pw": pw, "f": f}, ensure_ascii=False)


def build(lid):
    """Страницы всех матчей лиги из odds/<lid>/schedule.json."""
    sf = ROOT / "odds" / lid / "schedule.json"
    if not sf.exists():
        return
    teams, ser = teams_of(lid), series_results(lid, 3)
    stems = {}
    for f in (ROOT / "data" / lid).glob("*.json"):
        stems[json.loads(f.read_text(encoding="utf-8"))["team_id"]] = f.stem
    lf = ROOT / "odds" / lid / "latest.json"
    latest = {str(m["event_id"]): m["rows"] for m in json.loads(lf.read_text(encoding="utf-8"))["matches"]} if lf.exists() else {}
    for ev in json.loads(sf.read_text(encoding="utf-8"))["matches"]:
        if ev.get("event_id"):
            render(lid, ev, teams, ser, latest.get(str(ev["event_id"])) or None, stems)
