"""Турнирная сетка для страницы турнира (index.html): плей-офф, стыковые матчи, группы.

Структура пишется руками в analysis/<league_id>.bracket.json (кто с кем и куда проходит победитель),
счёт серий подставляется автоматически из raw/league_<id>_matches.json. Если серия ещё не сыграна —
карточка показывает «ожидается»; пустой соперник (b: null) заполняется победителем матча,
у которого next указывает на эту карточку.
"""
import datetime
import json
from collections import defaultdict
from html import escape as e

from render_html import DARK_LOGO, ROOT, rel

MSK = datetime.timedelta(hours=3)

BRACKET_CSS = """
.bsec{margin-top:28px}.bsec>h3{margin:0 0 4px;font-size:18px;letter-spacing:-.01em}.bsec>.muted{font-size:12.5px;margin-bottom:12px}
.br-scroll{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.br{position:relative;display:grid;grid-template-columns:repeat(var(--cols),minmax(196px,1fr));column-gap:40px;row-gap:6px;
padding:18px 20px 20px;min-width:calc(var(--cols)*236px)}
.br svg{position:absolute;inset:0;pointer-events:none;overflow:visible}
.br svg path{fill:none;stroke:var(--v-axis);stroke-width:1.5}
.br .lane{font-size:12.5px;font-weight:600;color:var(--muted);padding-top:6px}
.br .rnd{display:flex;flex-direction:column}
.br .rnd h4{margin:0 0 8px;font-size:12px;font-weight:500;color:var(--muted)}
.br .ms{flex:1;display:flex;flex-direction:column;justify-content:space-around;gap:12px}
.bm{position:relative;z-index:1;background:var(--card);border:1px solid var(--line);border-radius:6px;overflow:hidden}
.bm .bt{display:grid;grid-template-columns:22px 1fr auto;align-items:center;gap:8px;padding:6px 10px;font-size:13px}
.bm .bt+.bt{border-top:1px solid var(--line)}
.bm .bt img{width:22px;height:22px;object-fit:contain}.bm .bt img.dark{background:#111;border-radius:4px;padding:2px}
.bm .bt .q{width:22px;height:22px;border-radius:4px;border:1px dashed var(--v-axis)}
.bm .bt a,.bm .bt span.n{color:inherit;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bm .bt a:hover{text-decoration:underline}
.bm .bt b{font:600 13px var(--mono,ui-monospace);min-width:12px;text-align:right}
.bm .bt.w{font-weight:650}.bm .bt.w b{color:var(--win)}.bm .bt.l{color:var(--muted)}
.bm .bt.tbd{color:var(--muted)}
.bm .md{font-size:11px;color:var(--muted);padding:3px 10px 5px;border-top:1px solid var(--line);background:var(--hover)}
.bm.next{border-color:color-mix(in srgb,var(--text) 40%,transparent)}
.bdec{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.bgr{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.bg{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.bg h4{margin:0;padding:10px 14px;font-size:13px;border-bottom:1px solid var(--line)}
.bg table{width:100%;border-collapse:collapse;font-size:13px}
.bg td{padding:7px 14px;border-bottom:1px solid var(--line)}.bg tr:last-child td{border-bottom:0}
.bg td.p{width:18px;color:var(--muted);font:500 12px var(--mono,ui-monospace)}
.bg td.r{text-align:right;font-family:var(--mono,ui-monospace);color:var(--muted);white-space:nowrap}
.bg tr.adv td.p{color:var(--win);font-weight:700}.bg tr.out td:not(.p){color:var(--muted)}
.bg .tn{display:flex;align-items:center;gap:8px}.bg .tn img{width:20px;height:20px;object-fit:contain}
.bg .tn img.dark{background:#111;border-radius:4px;padding:2px}.bg .tn a{color:inherit;text-decoration:none}.bg .tn a:hover{text-decoration:underline}
"""

BRACKET_JS = """
document.querySelectorAll('.br').forEach(br=>{const path=br.querySelector('svg path');
const draw=()=>{const r=br.getBoundingClientRect();let d='';
 br.querySelectorAll('[data-next]').forEach(m=>{const n=document.getElementById(m.dataset.next);if(!n)return;
  const a=m.getBoundingClientRect(),b=n.getBoundingClientRect();
  const x1=a.right-r.left,y1=a.top+a.height/2-r.top,x2=b.left-r.left,y2=b.top+b.height/2-r.top,xm=x2-20;
  d+=`M${x1} ${y1}H${xm}V${y2}H${x2}`});path.setAttribute('d',d)};
draw();addEventListener('resize',draw);if(document.fonts)document.fonts.ready.then(draw);});
"""


def _day(ts):
    return (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc) + MSK).date()


def load_series(lid):
    """Серии лиги: матчи одной пары команд с одним series_id (или подряд в пределах 8 часов)."""
    ms = sorted(json.loads((ROOT / "raw" / f"league_{lid}_matches.json").read_text(encoding="utf-8")),
                key=lambda m: m["start_time"])
    out = []
    for m in ms:
        pair = frozenset((m["radiant_team_id"], m["dire_team_id"]))
        cur = next((x for x in reversed(out) if x["pair"] == pair and m["start_time"] - x["end"] < 8 * 3600
                    and (m["series_id"] is None or x["sid"] in (None, m["series_id"]))), None)
        if cur is None:
            cur = {"pair": pair, "sid": m["series_id"], "type": m["series_type"], "start": m["start_time"],
                   "end": m["start_time"], "wins": defaultdict(int), "maps": 0}
            out.append(cur)
        cur["end"] = m["start_time"]
        cur["sid"] = cur["sid"] or m["series_id"]
        if cur["type"] is None:
            cur["type"] = m["series_type"]
        cur["wins"][m["radiant_team_id"] if m["radiant_win"] else m["dire_team_id"]] += 1
        cur["maps"] += 1
    for x in out:
        need = {0: 1, 1: 2, 2: 3}.get(x["type"], 2)  # bo1 / bo3 / bo5
        x["winner"] = next((t for t, w in x["wins"].items() if w >= need), None)
    return out


def find_series(series, a, b, frm=None, to=None):
    if a is None or b is None:
        return None
    frm = datetime.date.fromisoformat(frm) if frm else None
    to = datetime.date.fromisoformat(to) if to else None
    for x in series:
        d = _day(x["start"])
        if x["pair"] == frozenset((a, b)) and (frm is None or d >= frm) and (to is None or d <= to):
            return x
    return None


class Ctx:
    def __init__(self, lid):
        self.lid = lid
        self.teams = {t["team_id"]: t for t in json.loads((ROOT / "raw" / f"league_{lid}_teams.json").read_text(encoding="utf-8"))}
        self.pages = {}
        for f in (ROOT / "data" / lid).glob("*.json"):
            self.pages[json.loads(f.read_text(encoding="utf-8"))["team_id"]] = f.stem
        self.series = load_series(lid)

    def team(self, tid, base, cls="", score=None):
        """Строка команды: логотип, имя (ссылка на страницу команды), счёт."""
        if tid is None:
            return f"<div class='bt tbd'><i class=q></i><span class=n>Определится</span><b></b></div>"
        t = self.teams.get(tid, {"name": str(tid)})
        logo = ROOT / "assets" / "teams" / f"{tid}.png"
        img = (f"<img{' class=dark' if tid in DARK_LOGO else ''} src='{rel(logo, base)}' alt='Логотип {e(t['name'])}'>"
               if logo.exists() else "<i class=q></i>")
        name = e(t["name"])
        if tid in self.pages:
            name = f"<a href='{rel(ROOT / 'reports' / self.lid / (self.pages[tid] + '.html'), base)}'>{name}</a>"
        else:
            name = f"<span class=n>{name}</span>"
        return f"<div class='bt {cls}'>{img}{name}<b>{'' if score is None else score}</b></div>"

    def match(self, a, b, base, frm=None, to=None, mid=None, nxt=None, note=""):
        s = find_series(self.series, a, b, frm, to)
        attrs = (f" id='b{self.lid}-{mid}'" if mid else "") + (f" data-next='b{self.lid}-{nxt}'" if nxt else "")
        if s:
            w = s["winner"]
            ca = "w" if w == a else ("l" if w else "")
            cb = "w" if w == b else ("l" if w else "")
            meta = _day(s["start"]).strftime("%d.%m") + ("" if w else ", идёт")
            rows = self.team(a, base, ca, s["wins"].get(a, 0)) + self.team(b, base, cb, s["wins"].get(b, 0))
            cls = "bm"
        else:
            meta = "ожидается"
            rows = self.team(a, base) + self.team(b, base)
            cls = "bm next" if a is not None and b is not None else "bm"
        if note:
            meta += f". {note}"
        return f"<div class='{cls}'{attrs}>{rows}<div class=md>{e(meta)}</div></div>", (s["winner"] if s else None)


def playoff_html(cfg, ctx, base):
    p = cfg["playoff"]
    frm = p.get("from")
    upper, lower = p["upper"], p["lower"]
    # победители по id — чтобы заполнить пустые слоты (гранд-финал и т.п.)
    rounds = upper + lower
    by_id = {m["id"]: m for r in rounds for m in r["matches"]}
    winners = {}
    for r in rounds:
        for m in r["matches"]:
            s = find_series(ctx.series, m.get("a"), m.get("b"), frm)
            if s and s["winner"]:
                winners[m["id"]] = s["winner"]
    for m in by_id.values():
        for slot in ("a", "b"):
            if m.get(slot) is None:
                feeders = [winners.get(x["id"]) for x in by_id.values() if x.get("next") == m["id"]]
                cand = [t for t in feeders if t and t not in (m.get("a"), m.get("b"))]
                if cand:
                    m[slot] = cand[0]

    final = upper[-1]
    up_cols = upper[:-1]
    cols = max(len(up_cols), len(lower) + 1) + 1

    def rnd(r, col, row, span=1):
        ms = "".join(ctx.match(m.get("a"), m.get("b"), base, frm, mid=m["id"], nxt=m.get("next"))[0] for m in r["matches"])
        return (f"<div class=rnd style='grid-column:{col};grid-row:{row} / span {span}'>"
                f"<h4>{e(r['name'])}</h4><div class=ms>{ms}</div></div>")

    H = [f"<div class=br-scroll><div class=br style='--cols:{cols}'><svg aria-hidden=true><path/></svg>",
         f"<div class=lane style='grid-column:1 / {cols};grid-row:1'>Верхняя сетка</div>"]
    H += [rnd(r, i + 1, 2) for i, r in enumerate(up_cols)]
    H.append(f"<div class=lane style='grid-column:1 / {cols};grid-row:3'>Нижняя сетка</div>")
    H += [rnd(r, i + 2, 4) for i, r in enumerate(lower)]
    H.append(rnd(final, cols, 2, 3))
    H.append("</div></div>")
    return "".join(H)


def deciders_html(cfg, ctx, base):
    d = cfg["deciders"]
    cards = "".join(ctx.match(m["a"], m["b"], base, d.get("from"), d.get("to"), note=m.get("note", ""))[0] for m in d["matches"])
    return f"<div class=bdec>{cards}</div>"


def groups_html(cfg, ctx, base):
    g = cfg["groups"]
    frm = datetime.date.fromisoformat(g["from"])
    to = datetime.date.fromisoformat(g["to"])
    H = ["<div class=bgr>"]
    for grp in g["list"]:
        ids = set(grp["teams"])
        st = {t: {"sw": 0, "sl": 0, "mw": 0, "ml": 0} for t in ids}
        for x in ctx.series:
            if x["pair"] <= ids and frm <= _day(x["start"]) <= to and x["winner"]:
                a, b = tuple(x["pair"])
                for t, o in ((a, b), (b, a)):
                    st[t]["mw"] += x["wins"].get(t, 0)
                    st[t]["ml"] += x["wins"].get(o, 0)
                    st[t]["sw" if x["winner"] == t else "sl"] += 1
        order = sorted(ids, key=lambda t: (-st[t]["sw"], st[t]["sl"], -(st[t]["mw"] - st[t]["ml"])))
        H.append(f"<div class=bg><h4>{e(grp['name'])}</h4><table>")
        for i, t in enumerate(order, 1):
            row = ctx.team(t, base)
            # из .bt берём только логотип+имя: в таблице своя разметка
            name = row.split("<b>")[0].replace("<div class='bt '>", "")
            cls = "adv" if i <= g.get("advance", 2) else "out"
            H.append(f"<tr class={cls}><td class=p>{i}</td><td><div class=tn>{name}</div></td>"
                     f"<td class=r>{st[t]['sw']}-{st[t]['sl']} ({st[t]['mw']}-{st[t]['ml']})</td></tr>")
        H.append("</table></div>")
    H.append("</div>")
    return "".join(H)


def bracket_parts(lid, base):
    """(плей-офф, остальное) для страницы турнира; пустые строки, если структуры нет."""
    f = ROOT / "analysis" / f"{lid}.bracket.json"
    if not f.exists():
        return "", ""
    cfg = json.loads(f.read_text(encoding="utf-8"))
    ctx = Ctx(lid)
    top = ""
    if "playoff" in cfg:
        top = ("<div class=bsec><h3>Плей-офф</h3><div class=muted>Двойное выбывание. Счёт по сериям, клик по команде открывает её статистику.</div>"
               + playoff_html(cfg, ctx, base) + "</div>")
    rest = ""
    if "deciders" in cfg:
        rest += (f"<div class=bsec><h3>{e(cfg['deciders']['name'])}</h3><div class=muted>Победители групп разыгрывают места в плей-офф, "
                 f"вторые места играют на вылет.</div>" + deciders_html(cfg, ctx, base) + "</div>")
    if "groups" in cfg:
        rest += ("<div class=bsec><h3>Групповой этап</h3><div class=muted>Двойное выбывание внутри группы (GSL). "
                 "Серии и в скобках карты. Первые два места проходят дальше.</div>" + groups_html(cfg, ctx, base) + "</div>")
    return top, rest
