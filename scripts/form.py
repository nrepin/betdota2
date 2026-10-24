"""Форма команды: результаты против ожиданий.

Для каждой сыгранной карты берём вероятность победы команды ДО карты:
  • из сохранённых до-матчевых коэффициентов (odds/<league>/prematch, рынок «Победа на карте», без маржи букмекера);
  • если их нет — из модели: винрейт команд по предыдущим картам базы (со сглаживанием) и формула log5.
Очко карты = результат (1/0) − ожидаемая вероятность победы. Фаворит проиграл (−0.7) — форма падает сильно,
фаворит выиграл (+0.3) — растёт слабо, андердог выиграл (+0.7) — растёт сильно.
Форма = взвешенное среднее очков последних N_LAST карт (более свежие весят больше). Диапазон −1…+1.

На сыгранных картах базы прибавка от формы к вероятности победы не подтверждается (Brier не улучшается),
поэтому в прогноз она входит с весом FORM_W (forecast.py), по умолчанию 0: только показ.
"""
import json

from render_html import ROOT

N_LAST = 8
DECAY = 0.85
GOOD, BAD = 0.12, -0.12
PRIOR = 4          # сглаживание винрейта: как 4 карты на 50%
SHRINK_SERIES = 0.6
WINDOW = 14 * 3600

_cache = {}


def _games():
    """{team_id: [(start_time, win, opponent_id, opponent_name, match_id), ...]} по всем турнирам базы."""
    if "g" in _cache:
        return _cache["g"]
    out = {}
    for f in (ROOT / "data").glob("*/*.json"):
        t = json.loads(f.read_text(encoding="utf-8"))
        d = out.setdefault(t["team_id"], {})
        for g in t["games"]:
            d[g["match_id"]] = (g["start_time"], int(g["win"]), g["opponent_id"], g["opponent"], g["match_id"])
    _cache["g"] = {k: sorted(v.values()) for k, v in out.items()}
    return _cache["g"]


def _prematch():
    if "p" in _cache:
        return _cache["p"]
    idx = {}
    for f in (ROOT / "odds").glob("*/prematch/*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        idx.setdefault(frozenset((d["t1_id"], d["t2_id"])), []).append(d)
    _cache["p"] = idx
    return idx


def reset():
    _cache.clear()


def _wr(tid, time):
    xs = [g[1] for g in _games().get(tid, []) if g[0] < time]
    return (sum(xs) + PRIOR * 0.5) / (len(xs) + PRIOR)


def model_p(tid, opp, time):
    a, b = _wr(tid, time), _wr(opp, time)
    return a * (1 - b) / (a * (1 - b) + b * (1 - a))


def odds_p(tid, opp, time):
    """(вероятность, источник) по до-матчевым коэффициентам или None."""
    for d in _prematch().get(frozenset((tid, opp)), []):
        if abs(d["start"] - time) > WINDOW:
            continue
        sib = [g for g in _games().get(tid, []) if g[2] == opp and abs(g[0] - d["start"]) <= WINDOW]
        n = 1 + sum(1 for g in sib if g[0] < time)
        cl = (d["maps"].get(str(n)) or {}).get("close")
        for r in (cl or {}).get("rows", []):
            if r["market"].startswith("Победа на карте") and r.get("line") is not None:
                return (r["line"] if tid == d["t1_id"] else 1 - r["line"]), "линия карты"
        so = (d.get("series") or {}).get("close")
        if so:
            k1, k2 = so["odds"]
            p1 = (1 / k1) / (1 / k1 + 1 / k2)
            p1 = 0.5 + SHRINK_SERIES * (p1 - 0.5)
            return (p1 if tid == d["t1_id"] else 1 - p1), "линия серии"
    return None


def expected(tid, opp, time):
    r = odds_p(tid, opp, time)
    return r if r else (model_p(tid, opp, time), "модель")


def word(score):
    return "нет данных" if score is None else "хорошая" if score >= GOOD else "плохая" if score <= BAD else "ровная"


def form(tid, before=None):
    """Форма команды перед моментом before (None — сейчас)."""
    gl = [g for g in _games().get(tid, []) if before is None or g[0] < before][-N_LAST:]
    rows, num, den = [], 0.0, 0.0
    for j, g in enumerate(reversed(gl)):
        p, src = expected(tid, g[2], g[0])
        pts = g[1] - p
        w = DECAY ** j
        num += w * pts
        den += w
        rows.append({"start": g[0], "opp": g[3], "opp_id": g[2], "win": bool(g[1]), "p": round(p, 3), "src": src,
                     "pts": round(pts, 2), "match_id": g[4]})
    score = round(num / den, 2) if len(gl) >= 3 else None
    fav = [r for r in rows if r["p"] >= 0.55]
    return {"score": score, "word": word(score), "n": len(rows), "games": list(reversed(rows)),   # от старых к новым
            "fav_n": len(fav), "fav_lost": sum(1 for r in fav if not r["win"]),
            "dog_n": sum(1 for r in rows if r["p"] <= 0.45), "dog_won": sum(1 for r in rows if r["p"] <= 0.45 and r["win"]),
            "odds_n": sum(1 for r in rows if r["src"] != "модель")}


def html(f, name=""):
    """Блок формы: сводка и таблица последних карт (от новых к старым)."""
    import datetime
    from html import escape as e
    if f["score"] is None:
        return f"<div class=card style='padding:14px 16px'>{e(name)}: мало сыгранных карт для оценки формы (нужно ≥ 3).</div>"
    cls = "w" if f["score"] >= GOOD else "lo" if f["score"] <= BAD else ""
    msk = datetime.timezone(datetime.timedelta(hours=3))
    h = [f"<div class=card><div style='padding:14px 16px 6px'><b>{e(name)}</b> форма <span class='pill {cls}'>{e(f['word'])} "
         f"{f['score']:+.2f}</span> <span class=muted style='font-size:12.5px'>· фавориты (≥55%): проиграно {f['fav_lost']} из {f['fav_n']}; "
         f"андердоги (≤45%): выиграно {f['dog_won']} из {f['dog_n']}; по линии букмекера {f['odds_n']} из {f['n']} карт</span></div>"
         "<table><thead><tr><th>Дата</th><th>Соперник</th><th>Итог</th><th class=num>Ожидание победы</th><th>Источник</th>"
         "<th class=num>Очки</th></tr></thead><tbody>"]
    for r in reversed(f["games"]):
        d = datetime.datetime.fromtimestamp(r["start"], datetime.timezone.utc).astimezone(msk).strftime("%d.%m")
        res, c = ("W", "w") if r["win"] else ("L", "lo")
        h.append(f"<tr><td>{d}</td><td>{e(r['opp'])}</td><td><span class='pill {c}'>{res}</span></td>"
                 f"<td class=num>{r['p']:.0%}</td><td class=muted>{e(r['src'])}</td>"
                 f"<td class='num {c}'>{r['pts']:+.2f}</td></tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


NOTE = ("Форма: очко карты = результат − ожидаемая вероятность победы до карты (линия букмекера без маржи, а если её не сохранили — "
        "модель по винрейтам). Фаворит проиграл — сильный минус, фаворит выиграл — небольшой плюс, андердог выиграл — большой плюс. "
        f"Форма — взвешенное среднее последних {N_LAST} карт (свежие весят больше). В прогноз пока не входит: на сыгранных картах базы "
        "она не улучшает оценку победы.")
