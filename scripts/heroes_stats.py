"""Статистика героев по длительности карт — только по сыгранным матчам (raw/matches, карты команд из data/).

Для героя считается: пики, средняя/медианная длительность, доля быстрых и затяжных карт, винрейт на быстрых и
затяжных. «Темп» героя = (средняя длительность карт с ним) − (средняя по всем картам), со сглаживанием на малую
выборку (n/(n+K)). Быстрый ≤ −TILT мин, затяжной ≥ +TILT мин, при n < MIN_N — «мало данных».

    python scripts/heroes_stats.py        # пересобрать heroes.html
"""
import json
import statistics
from html import escape as e

from render_html import ROOT, SORT_JS, load_heroes, rel

TOWER_T = 0.3    # порог индекса урона по вышкам: ≥ +0.3 — быстро ломает, ≤ −0.3 — медленно
MIN_N = 4        # меньше пиков — «мало данных»
TILT = 2.0       # порог темпа, минут
SMOOTH = 4       # K сглаживания
OUT = ROOT / "heroes.html"


def played_matches():
    """Сыгранные карты команд из data/<league>/*.json (без повторов) вместе с файлами матчей."""
    ids = set()
    for f in (ROOT / "data").glob("*/*.json"):
        ids |= {g["match_id"] for g in json.loads(f.read_text(encoding="utf-8"))["games"]}
    out = []
    for mid in sorted(ids):
        p = ROOT / "raw" / "matches" / f"{mid}.json"
        if p.exists():
            m = json.loads(p.read_text(encoding="utf-8"))
            if m.get("duration") and m.get("players"):
                out.append(m)
    return out


def stats():
    ms = played_matches()
    durs = sorted(m["duration"] / 60 for m in ms)
    overall = statistics.mean(durs)
    lo, hi = durs[len(durs) // 3], durs[2 * len(durs) // 3]  # терцили: быстрая / затяжная карта
    per = {}
    for m in ms:
        d = m["duration"] / 60
        for p in m["players"]:
            h = per.setdefault(p["hero_id"], {"d": [], "w": []})
            h["d"].append(d)
            h["w"].append(bool(p["isRadiant"]) == bool(m["radiant_win"]))
    heroes = {}
    for hid, h in per.items():
        n = len(h["d"])
        avg = statistics.mean(h["d"])
        short = [w for d, w in zip(h["d"], h["w"]) if d < lo]
        long_ = [w for d, w in zip(h["d"], h["w"]) if d >= hi]
        tilt = (avg - overall) * n / (n + SMOOTH)
        label = ("мало данных" if n < MIN_N else "затяжной" if tilt >= TILT else "быстрый" if tilt <= -TILT else "нейтральный")
        heroes[hid] = {"n": n, "avg": round(avg, 1), "median": round(statistics.median(h["d"]), 1),
                       "short_share": round(len([1 for d in h["d"] if d < lo]) / n, 2),
                       "long_share": round(len([1 for d in h["d"] if d >= hi]) / n, 2),
                       "wr": round(sum(h["w"]) / n, 2),
                       "short_wr": round(sum(short) / len(short), 2) if short else None, "short_n": len(short),
                       "long_wr": round(sum(long_) / len(long_), 2) if long_ else None, "long_n": len(long_),
                       "tilt": round(tilt, 1), "label": label}
    tower = tower_stats(ms, heroes)
    return {"maps": len(ms), "overall": round(overall, 1), "lo": round(lo, 1), "hi": round(hi, 1), "heroes": heroes,
            "tower": tower}


def tower_stats(ms, heroes):
    """Урон по вышкам в минуту у героев и связь драфта с длительностью/убийствами.

    Индекс героя = среднее (урон по вышкам/мин − средний урон/мин на той же позиции) / средний урон/мин игрока,
    со сглаживанием n/(n+K): позиция учитывается, чтобы керри не выглядели «ломателями» просто из-за роли.
    Связь драфта с исходом проверяется без утечки: индекс героя считается без самой карты (leave-one-out)."""
    rows = [(m["match_id"], p["hero_id"], p.get("position_est"), p["tower_damage"] / (m["duration"] / 60))
            for m in ms for p in m["players"] if p.get("tower_damage") is not None]
    if not rows:
        return {"mean": 0, "corr_dur": None, "corr_kills": None}
    allm = statistics.mean(r[3] for r in rows)
    pm = {}
    for _, _, pos, v in rows:
        if pos:
            pm.setdefault(pos, []).append(v)
    pm = {k: statistics.mean(v) for k, v in pm.items()}
    delta = lambda r: (r[3] - pm.get(r[2], allm)) / allm
    byh = {}
    for r in rows:
        byh.setdefault(r[1], []).append(r)
    for hid, h in heroes.items():
        rs = byh.get(hid, [])
        n = len(rs)
        h["td"] = round(statistics.mean(r[3] for r in rs)) if rs else 0
        h["tidx"] = round(sum(delta(r) for r in rs) / (n + SMOOTH), 2) if rs else 0.0
        h["tlabel"] = ("мало данных" if n < MIN_N else "быстро ломает" if h["tidx"] >= TOWER_T
                       else "медленно ломает" if h["tidx"] <= -TOWER_T else "средне")
    xs, ds, ks = [], [], []
    for m in ms:
        t = []
        for p in m["players"]:
            rs = [r for r in byh.get(p["hero_id"], []) if r[0] != m["match_id"]]
            t.append(sum(delta(r) for r in rs) / (len(rs) + SMOOTH))
        xs.append(statistics.mean(t))
        ds.append(m["duration"] / 60)
        ks.append(m["radiant_score"] + m["dire_score"])

    def corr(a, b):
        ma, mb = statistics.mean(a), statistics.mean(b)
        den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
        return round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / den, 2) if den else None

    return {"mean": round(allm), "corr_dur": corr(xs, ds), "corr_kills": corr(xs, ks), "n": len(xs)}


def draft_towers(hero_ids, st):
    """Средний индекс урона по вышкам набора героев (только известные, n ≥ MIN_N)."""
    t = [st["heroes"][h]["tidx"] for h in hero_ids if h in st["heroes"] and st["heroes"][h]["tlabel"] != "мало данных"]
    return round(sum(t) / len(t), 2) if len(t) >= 3 else None


def tower_word(t):
    return "нет данных" if t is None else "быстро ломает вышки" if t >= 0.15 else "медленно ломает вышки" if t <= -0.15 else "средне по вышкам"


def tower_note(st):
    """Оговорка: есть ли на нашей выборке связь драфта по вышкам с длительностью и убийствами."""
    tw = st["tower"]
    cd, ck = tw.get("corr_dur"), tw.get("corr_kills")
    if cd is None:
        return ""
    weak = abs(cd) < 0.2 and abs(ck) < 0.2
    return (f"связь с длительностью r={cd:+g}, с убийствами r={ck:+g} по {tw['n']} картам" + (" — не подтверждена, на оценку не влияет" if weak else ""))


def team_hero_stats(team_id, exclude_match=None):
    """{hero_id: [пиков, побед]} — сколько раз команда брала героя в сыгранных картах базы (все турниры).
    exclude_match — не считать эту карту (чтобы драфт оценивался так, как до неё)."""
    names = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    by_name = {h["localized_name"]: h["id"] for h in names.values()}
    out = {}
    for f in (ROOT / "data").glob("*/*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        if t["team_id"] != team_id:
            continue
        for g in t["games"]:
            if g["match_id"] == exclude_match:
                continue
            for nm in g["picks"]:
                hid = by_name.get(nm)
                if hid:
                    r = out.setdefault(hid, [0, 0])
                    r[0] += 1
                    r[1] += bool(g["win"])
    return out


def team_all_games(team_id):
    """Все карты команды из data/ (все турниры)."""
    games = []
    for f in (ROOT / "data").glob("*/*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        if t["team_id"] == team_id:
            games += t["games"]
    return games


def team_heroes(games_scope, games_all):
    """Герои команды в двух срезах: scope (турнир или все) и all (все турниры).
    Возвращает ({имя: {label, tilt, scope:{n,w,min}, all:{n,w,min}}}, {scope: сводка, all: сводка}).
    Сводка: средний темп драфтов команды и доли быстрых/затяжных героев среди пиков."""
    st = stats()
    hnames = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    by_name = {h["localized_name"]: h["id"] for h in hnames.values()}
    rows, summ = {}, {}

    def count(games, key):
        tilts, labels = [], {"быстрый": 0, "затяжной": 0, "нейтральный": 0, "мало данных": 0}
        for g in games:
            for nm in g["picks"]:
                hid = by_name.get(nm)
                h = st["heroes"].get(hid)
                r = rows.setdefault(nm, {"label": h["label"] if h else "мало данных", "tilt": h["tilt"] if h else 0.0,
                                         "tlabel": h["tlabel"] if h else "мало данных",
                                         "scope": {"n": 0, "w": 0, "dur": 0.0}, "all": {"n": 0, "w": 0, "dur": 0.0}})
                c = r[key]
                c["n"] += 1
                c["w"] += bool(g["win"])
                c["dur"] += g["duration_sec"] / 60
                if h:
                    tilts.append(h["tilt"])
                labels[r["label"]] += 1
        n = sum(labels.values())
        summ[key] = {"tempo": round(sum(tilts) / len(tilts), 1) if tilts else None, "picks": n, "maps": len(games),
                     "fast": labels["быстрый"] / n if n else 0, "long": labels["затяжной"] / n if n else 0}

    count(games_scope, "scope")
    count(games_all, "all")
    return rows, summ


def draft_tempo(hero_ids, st):
    """Средний сглаженный темп набора героев (минут относительно средней карты)."""
    t = [st["heroes"][h]["tilt"] for h in hero_ids if h in st["heroes"]]
    return round(sum(t) / len(t), 1) if t else None


def draft_eval(ids_a, ids_b, st):
    """Оценка пары драфтов: темп каждой команды, общий темп карты и ожидаемая длительность (мин)."""
    ta, tb = draft_tempo(ids_a, st), draft_tempo(ids_b, st)
    if ta is None or tb is None:
        return None
    mean = round((ta + tb) / 2, 1)
    tw = draft_towers(list(ids_a) + list(ids_b), st)
    return {"a": ta, "b": tb, "mean": mean, "exp": round(st["overall"] + mean, 1), "word": tempo_word(mean),
            "tw": tw, "tw_word": tower_word(tw), "tw_note": tower_note(st)}


def tempo_word(t):
    return "нет данных" if t is None else "затяжной" if t >= 1.0 else "быстрый" if t <= -1.0 else "средний"


HEROES_CSS = """
.hh{display:flex;align-items:center;gap:10px;font-weight:600}.hh img{width:44px;height:25px;border-radius:4px;object-fit:cover}
.tag{display:inline-block;padding:2px 8px;border-radius:6px;font:600 11.5px var(--mono);background:var(--bar);color:var(--muted)}
.tag.fast{background:var(--win-bg);color:var(--win)}.tag.long{background:var(--loss-bg);color:var(--loss)}.tag.tf{background:#e0f2e6;color:#1d7a3e}.tag.ts{background:#fdefd6;color:#9a6200}
.hero-t{margin-top:12px}.hero-t td.n,.hero-t th.n{text-align:right;font-family:var(--mono);white-space:nowrap}
.hero-t th{cursor:pointer}.hero-t tr.low td{color:var(--muted)}
"""


def ttag(label):
    cls = {"быстро ломает": "tf", "медленно ломает": "ts"}.get(label, "")
    return f"<span class='tag {cls}'>{e(label)}</span>"


def tag(label):
    cls = {"затяжной": "long", "быстрый": "fast"}.get(label, "")
    return f"<span class='tag {cls}'>{e(label)}</span>"


def render_page():
    import render_index
    st = stats()
    names = json.loads((ROOT / "raw" / "heroes.json").read_text(encoding="utf-8"))
    imgs = load_heroes()
    body = [f"<div class=page-h><h2>Герои: быстрые и затяжные</h2><div class=sub>Только сыгранные карты турниров из базы: "
            f"{st['maps']} карт, средняя {st['overall']} мин. Быстрая карта — короче {st['lo']} мин, затяжная — от {st['hi']} мин. "
            f"Темп = средняя длительность карт с героем минус средняя по всем (со сглаживанием на малую выборку). "
            f"Герои с числом пиков меньше {MIN_N} помечены «мало данных». "
            f"Вышки: урон по строениям в минуту; индекс — отклонение от среднего на той же позиции (быстро ломает ≥ +{TOWER_T}, "
            f"медленно ≤ −{TOWER_T}); {tower_note(st)}.</div></div>",
            "<div class='card hero-t'><table class=sortable><thead><tr><th>Герой</th><th class=n>Пики</th><th class=n>Ср. мин</th>"
            "<th class=n>Темп</th><th>Вывод</th><th class=n>Вышки/мин</th><th>Вышки</th><th class=n>Быстрые карты</th><th class=n>Затяжные карты</th>"
            "<th class=n>WR быстр.</th><th class=n>WR затяж.</th></tr></thead><tbody>"]
    order = {"быстрый": 0, "затяжной": 1, "нейтральный": 2, "мало данных": 3}
    # группы: быстрые (самые быстрые первыми) → затяжные (самые затяжные первыми) → нейтральные → мало данных
    rows = sorted(st["heroes"].items(), key=lambda kv: (order[kv[1]["label"]], kv[1]["tilt"] if kv[1]["label"] != "затяжной" else -kv[1]["tilt"]))
    for hid, h in rows:
        nm = names[str(hid)]["localized_name"]
        img = imgs.get(nm)
        pic = f"<img src='{e(rel(img, OUT))}' alt='' loading=lazy>" if img else ""
        wr = lambda v, n: f"{v:.0%} <span class=muted>({n})</span>" if v is not None else "—"
        body.append(f"<tr class='{'low' if h['label'] == 'мало данных' else ''}'><td><span class=hh>{pic}{e(nm)}</span></td>"
                    f"<td class=n>{h['n']}</td><td class=n>{h['avg']}</td><td class=n data-v='{h['tilt']}'>{h['tilt']:+.1f}</td>"
                    f"<td>{tag(h['label'])}</td><td class=n data-v='{h['tidx']}'>{h['td']}</td><td>{ttag(h['tlabel'])}</td>"
                    f"<td class=n>{h['short_share']:.0%}</td><td class=n>{h['long_share']:.0%}</td>"
                    f"<td class=n data-v='{h['short_wr'] if h['short_wr'] is not None else -1}'>{wr(h['short_wr'], h['short_n'])}</td>"
                    f"<td class=n data-v='{h['long_wr'] if h['long_wr'] is not None else -1}'>{wr(h['long_wr'], h['long_n'])}</td></tr>")
    body.append("</tbody></table></div>")
    render_index.page(OUT, "Герои: быстрые и затяжные", "Статистика героев по длительности карт на турнирах",
                      "heroes", "".join(body), SORT_JS, extra_css=HEROES_CSS)


if __name__ == "__main__":
    render_page()
