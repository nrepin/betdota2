"""Прогнозы ИИ по картам: один прогноз на карту, в её начале, когда выбраны герои обеих команд.

Прогноз даётся на каждую карту: если перевес слабый, всё равно берётся лучший вариант со ставкой 50.
Источник героев — OpenDota /live (его читает auto.py). Из трёх рынков (победа на карте, время карты, тотал убийств)
выбирается один с наибольшим расхождением «оценка по драфтам против линии PARI»; если ни один не проходит порог,
прогноза нет. Файл forecasts/<league>/<event_id>L<карта>.json создаётся один раз и потом не перезаписывается.
Доматчевых прогнозов нет. Результат подставляется из raw/league_<id>_matches.json (settle).

    python scripts/forecast.py --league 20395                       # подставить результаты и пересобрать страницы
    python scripts/forecast.py --league 20395 --event 69039564L1 --note "разбор..."   # заменить текст
"""
import argparse
import datetime
import json
import re

from render_html import ROOT
from render_schedule import MSK, find_series, series_results, teams_of

DIR = ROOT / "forecasts"
STAKE = 100       # условная ставка на каждый прогноз, $
STAKES = {"явный": STAKE, "небольшой": STAKE, "слабый": STAKE}
MIN_ODDS = {"win": 1.4, "time": 1.7, "kills": 1.7}   # ставка ставится, только если коэффициент не ниже порога


def path(lid, eid):
    return DIR / lid / f"{eid}.json"


def load(lid, eid):
    f = path(lid, eid)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def save(lid, fc):
    f = path(lid, fc["event_id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(fc, ensure_ascii=False, indent=1), encoding="utf-8")


def line_of(market):
    m = re.search(r"([\d.]+)(?: мин)?$", market)
    return float(m.group(1)) if m else None


# пороги расхождения «оценка − линия»: (небольшой — ставка 100, явный — 200); ниже малого порога — «слабый», ставка 50
EDGE = {"time": (3.0, 6.0), "kills": (6.0, 10.0), "win": (0.08, 0.15)}   # минуты, убийства, вероятность
LIVE_SAFE_LEFT = 300   # до линии времени должно оставаться не меньше 5 мин игры
HERO_K = 8             # сглаживание винрейта героя (как n/(n+K))
FORM_W = 0.08          # вес формы (form.py) в вероятности победы на карте (на картах базы эффект не подтверждён: малая выборка)
HERO_W = 0.1           # вес разницы винрейтов драфтов в вероятности победы


def map_no(name):
    m = re.search(r"(\d+)", name or "")
    return int(m.group(1)) if m else None


def draft_power(ids, st):
    """Сумма сглаженных отклонений винрейта героев драфта от 50% (по сыгранным картам базы)."""
    t = 0.0
    for h in ids:
        x = st["heroes"].get(h)
        if x:
            t += (x["wr"] * x["n"] + 0.5 * HERO_K) / (x["n"] + HERO_K) - 0.5
    return t


FORM_SHOW_W = FORM_W   # вес формы в прогнозе по драфту, показываемом на странице


def draft_win(ta, tb, ids_a, ids_b, st, at=None):
    """Прогноз победы на карте по драфту: команды (винрейт, log5) + герои (HERO_W) + форма (FORM_SHOW_W).
    ta/tb — id команд, ids_* — герои, at — время карты (None — сейчас). None, если героев меньше пяти."""
    import form
    import time
    ids_a, ids_b = [h for h in ids_a if h], [h for h in ids_b if h]
    at = at or time.time()
    base = form.model_p(ta, tb, at)
    # неполные пики: сумма отклонений героев приводится к пяти героям (среднее × 5), без героев вклад 0
    pw = lambda ids: draft_power(ids, st) * 5 / len(ids) if ids else 0.0
    hero = HERO_W * (pw(ids_a) - pw(ids_b))
    fa, fb = form.form(ta, at), form.form(tb, at)
    fd = FORM_SHOW_W * (fa["score"] - fb["score"]) if fa["score"] is not None and fb["score"] is not None else 0.0
    p = min(0.95, max(0.05, base + hero + fd))
    return {"a": ta, "b": tb, "base": base, "hero": hero, "form": fd, "p": p,
            "form_a": fa["word"], "form_b": fb["word"], "na": len(ids_a), "nb": len(ids_b)}


def team_kpm(team_id):
    """Убийств в минуту (обе команды) на картах команды, все турниры."""
    import heroes_stats
    gs = heroes_stats.team_all_games(team_id)
    mins = sum(g["duration_sec"] for g in gs) / 60
    return sum(g["total_kills"] for g in gs) / mins if mins else None


def _better(edge, odds, best, cat):
    """Строка лучше текущей: среди тех, что прошли малый порог, — с большим коэффициентом; иначе — с большим перевесом."""
    ok, bok = edge >= EDGE[cat][0], best[2] >= EDGE[cat][0]
    if ok != bok:
        return ok
    return odds > best[1] if ok else edge > best[2]


def draft_candidates(m, g, st, ids1, ids2):
    """Кандидаты прогноза по драфтам (время, убийства, победа). ids1/ids2 — герои первой/второй команды линии."""
    import heroes_stats
    evd = heroes_stats.draft_eval(ids1, ids2, st)
    if not evd:
        return [], None
    exp = evd["exp"]
    k1, k2 = team_kpm(m["t1_id"]), team_kpm(m["t2_id"])
    exp_k = round((k1 + k2) / 2 * exp, 1) if k1 and k2 else None
    adv = draft_power(ids1, st) - draft_power(ids2, st)
    import form
    f1, f2 = form.form(m["t1_id"], g.get("start_time")), form.form(m["t2_id"], g.get("start_time"))
    fd = (f1["score"] - f2["score"]) if f1["score"] is not None and f2["score"] is not None else 0.0
    adj = HERO_W * adv + FORM_W * fd
    out = []
    best = None
    for r in m["rows"]:
        if r["market"].startswith("Время карты больше"):
            N = line_of(r["market"])
            if N * 60 - g["game_time"] < LIVE_SAFE_LEFT:
                continue
            for side, odds, edge in (("Да", r["k1"], exp - N), ("нет", r["k2"], N - exp)):
                if edge > 0 and (best is None or _better(edge, odds, best, "time")):
                    best = (side, odds, edge, r, N)
    if best:
        side, odds, edge, r, N = best
        out.append(dict(cat="time", label="Время карты", edge=edge, r=r, side=side, odds=odds, line=N, est=None,
                        text=f"Время карты {'больше' if side == 'Да' else 'меньше'} {N:g} мин",
                        basis=f"драфты: ожидание {exp:g} мин, линия {N:g}", n=0))
    best = None
    for r in m["rows"]:
        if exp_k is not None and r["market"].startswith("Тотал убийств больше"):
            N = line_of(r["market"])
            for side, odds, edge in (("Б", r["k1"], exp_k - N), ("М", r["k2"], N - exp_k)):
                if edge > 0 and (best is None or _better(edge, odds, best, "kills")):
                    best = (side, odds, edge, r, N)
    if best:
        side, odds, edge, r, N = best
        out.append(dict(cat="kills", label="Убийства", edge=edge, r=r, side=side, odds=odds, line=N, est=None,
                        text=f"Убийства {'больше' if side == 'Б' else 'меньше'} {N:g}",
                        basis=f"драфты: ожидание {exp:g} мин × {(k1 + k2) / 2:.2f} уб/мин = {exp_k:g}, линия {N:g}", n=0))
    for r in m["rows"]:
        if r["market"].startswith("Победа на карте") and r.get("est") is not None:
            p1 = min(0.95, max(0.05, r["est"] + adj))
            for side, odds, p, imp in (("1", r["k1"], p1, r["line"]), ("2", r["k2"], 1 - p1, 1 - r["line"])):
                if p - imp > 0 and p * odds - 1 > 0:
                    out.append(dict(cat="win", label="Победа на карте", edge=p - imp, r=r, side=side, odds=odds, line=None,
                                    est=round(p, 3), n=r["n"],
                                    text=f"Победа на карте: {m['t1'] if side == '1' else m['t2']}",
                                    basis=f"команды {r['est']:.0%} (по картам), с учётом героев {p1:.0%}, линия {r['line']:.0%}"))
    return out, {"exp": exp, "exp_k": exp_k, "adv": adv, "adj": adj, "mean": evd["mean"], "form": (f1, f2)}


def total_candidates(m, g, exp, exp_k):
    """Кандидаты прогноза на тотал карты — время и убийства, больше/меньше. По каждому рынку и стороне берётся строка
    с наименьшим коэффициентом из тех, что не ниже MIN_ODDS; результат — по убыванию перевеса (в долях порога EDGE)."""
    cands = []
    for r in m["rows"]:
        if r["market"].startswith("Время карты больше"):
            N = line_of(r["market"])
            if N * 60 - g["game_time"] < LIVE_SAFE_LEFT:
                continue
            for side, odds, edge, word in (("Да", r["k1"], exp - N, "больше"), ("нет", r["k2"], N - exp, "меньше")):
                if edge > 0:
                    cands.append(dict(cat="time", label="Время карты", edge=edge, r=r, side=side, odds=odds, line=N, est=None,
                                      text=f"Время карты {word} {N:g} мин", basis=f"драфты: ожидание {exp:g} мин, линия {N:g}", n=0))
        elif exp_k is not None and r["market"].startswith("Тотал убийств больше"):
            N = line_of(r["market"])
            for side, odds, edge, word in (("Б", r["k1"], exp_k - N, "больше"), ("М", r["k2"], N - exp_k, "меньше")):
                if edge > 0:
                    cands.append(dict(cat="kills", label="Убийства", edge=edge, r=r, side=side, odds=odds, line=N, est=None,
                                      text=f"Убийства {word} {N:g}", basis=f"драфты: ожидание {exp_k:g} убийств, линия {N:g}", n=0))
    best = {}
    for c in cands:
        if c["odds"] < MIN_ODDS[c["cat"]]:
            continue
        key = (c["cat"], c["side"])
        if key not in best or c["odds"] < best[key]["odds"]:
            best[key] = c
    return sorted(best.values(), key=lambda c: -c["edge"] / EDGE[c["cat"]][1])


def from_draft(lid, ev, g, m, st, hero_names):
    """Единственный прогноз на идущую карту: (fc, "") или (None, причина). g — запись /live, m — матч из снимка линии."""
    sides = [[p["hero_id"] for p in g["players"] if p["team"] == t and p["hero_id"]] for t in (0, 1)]
    if min(len(sides[0]), len(sides[1])) < 5:
        return None, "герои выбраны не все"
    if m is None or not m.get("rows"):
        return None, "в линии нет рынков по этой карте"
    n_known = sum(1 for h in sides[0] + sides[1] if st["heroes"].get(h, {}).get("label") not in (None, "мало данных"))
    rad_is_t1 = g["team_id_radiant"] == m["t1_id"]
    ids1, ids2 = (sides[0], sides[1]) if rad_is_t1 else (sides[1], sides[0])
    cands, info = draft_candidates(m, g, st, ids1, ids2)
    if not info:
        return None, "нет данных по героям"
    # три события, прогноз по каждому показывается всегда: тотал убийств, продолжительность, победитель
    pool = total_candidates(m, g, info["exp"], info["exp_k"])
    ev3 = {}
    for cat, name, exp, unit in (("kills", "тотал убийств", info["exp_k"], ""), ("time", "продолжительность", info["exp"], "мин")):
        cc = next((x for x in pool if x["cat"] == cat), None)
        if cc is None:   # нет рынка с нужным коэффициентом: только ожидание по драфтам
            cc = next((x for x in sorted((x for x in cands if x["cat"] == cat), key=lambda x: abs(x["odds"] - MIN_ODDS[cat]))), None)
        ev3[cat] = ({"text": cc["text"], "market": cc["r"]["market"], "side": cc["side"], "line": cc["line"], "odds": cc["odds"],
                     "basis": cc["basis"], "edge": cc["edge"], "hit": None} if cc else
                    {"text": f"{name}: ожидание по драфтам ≈ {exp:g} {unit}".strip() if exp else f"{name}: нет данных", "market": None,
                     "side": None, "line": None, "odds": None, "basis": "", "edge": None, "hit": None})
    win = None
    for r in m["rows"]:
        if r["market"].startswith("Победа на карте") and r.get("est") is not None:
            p1 = min(0.95, max(0.05, r["est"] + info["adj"]))
            side, odds, p, imp = ("1", r["k1"], p1, r["line"]) if p1 >= 0.5 else ("2", r["k2"], 1 - p1, 1 - r["line"])
            win = {"text": f"Победа на карте: {m['t1'] if side == '1' else m['t2']}", "market": r["market"], "side": side, "line": None,
                   "odds": odds, "est": round(p, 3), "implied": round(imp, 3), "edge": p - imp, "n": r["n"], "hit": None,
                   "basis": f"команды {r['est']:.0%} (по картам), с учётом героев и формы {p1:.0%}, линия {r['line']:.0%}"}
            break
    # ставка — на одно из трёх событий с наибольшим перевесом; коэффициент не ниже MIN_ODDS (победа 1.4, тоталы 1.7)
    cand3 = [(c, ev3[c]) for c in ("kills", "time") if ev3[c]["odds"] and ev3[c]["odds"] >= MIN_ODDS[c]]
    if win and win["odds"] >= MIN_ODDS["win"]:
        cand3.append(("win", win))
    cat, picks, pick = None, [], None
    if cand3:
        cat, c = max(cand3, key=lambda x: x[1]["edge"] / EDGE[x[0]][1])
        signal = ("явный" if c["edge"] >= EDGE[cat][1] else "небольшой" if c["edge"] >= EDGE[cat][0] else "слабый")
        pick = {"cat": cat, "label": {"kills": "Убийства", "time": "Время карты", "win": "Победа на карте"}[cat], "text": c["text"],
                "market": c["market"], "side": c["side"], "line": c["line"], "odds": c["odds"], "est": c.get("est"),
                "implied": round(1 / c["odds"], 3), "n": c.get("n", 0), "basis": c["basis"], "signal": signal, "ev": None,
                "stake": STAKE, "hit": None}
        picks = [pick]
    elif not (win or any(ev3[c]["odds"] for c in ("kills", "time"))):
        return None, "в линии нет подходящих рынков"
    nm = lambda ids: [hero_names.get(str(h), {}).get("localized_name", "?") for h in ids]
    t1, t2 = nm(ids1), nm(ids2)
    note = (f"Прогноз в начале карты, когда выбраны все герои. {m['t1']}: {', '.join(t1)}. {m['t2']}: {', '.join(t2)}. "
            f"Оценка драфтов: темп карты {info['mean']:+g} мин, ожидаемая длительность ≈ {info['exp']:g} мин"
            + (f", убийств ≈ {info['exp_k']:g}" if info["exp_k"] else "")
            + f". Форма: {m['t1']} — {info['form'][0]['word']}" + (f" ({info['form'][0]['score']:+g})" if info['form'][0]['score'] is not None else "")
            + f", {m['t2']} — {info['form'][1]['word']}" + (f" ({info['form'][1]['score']:+g})" if info['form'][1]['score'] is not None else "")
            + ". " + (f"Ставка на одно из трёх событий (победитель, тотал убийств, время) — с наибольшим перевесом: "
                      f"{pick['text']} (коэф {pick['odds']}, {pick['basis']}, перевес: {pick['signal']}). " if pick else
                      "Ставки нет: коэффициент ни одного события не дотягивает до минимума. ")
            + f"Минимальный коэффициент ставки: победа {MIN_ODDS['win']}, тоталы {MIN_ODDS['time']}. "
            f"Героев с данными в базе: {n_known} из 10. "
            "Выборки малые, маржа букмекера около 8%: это разбор статистики, а не гарантия.")
    mno = map_no(m["map"])
    after = {"exp": info["exp"], "exp_k": info["exp_k"], "time": ev3["time"], "kills": ev3["kills"], "win": win, "bet": cat}
    dw = draft_win(m["t1_id"], m["t2_id"], ids1, ids2, st)
    fc = {"event_id": f"{ev['event_id']}L{mno}", "match_event_id": str(ev["event_id"]), "league": lid, "live_bet": True,
          "created": datetime.datetime.now(MSK).strftime("%Y-%m-%d %H:%M"), "after_start": True,
          "t1": m["t1"], "t2": m["t2"], "t1_id": m["t1_id"], "t2_id": m["t2_id"], "start": ev["start"], "map_no": mno,
          "series_win": m.get("series_win") or [], "url": ev.get("url"), "picks": picks, "note": note,
          "draft": {"t1": t1, "t2": t2}, "draft_win": dw, "after_draft": after, "rows": m["rows"], "result": None}
    return fc, ""


def fill_totals(fc, dur, kills, winner_id=None):
    """Итоги трёх прогнозов после драфтов (тотал убийств, продолжительность, победитель). True, если что-то проставлено."""
    changed = False
    a = fc.get("after_draft") or {}
    for cat, ok in (("time", lambda t: (dur > t["line"]) == (t["side"] == "Да")),
                    ("kills", lambda t: (kills > t["line"]) == (t["side"] == "Б"))):
        t = a.get(cat)
        if t and t["hit"] is None and t.get("line") is not None:
            t["hit"] = ok(t)
            changed = True
    w = a.get("win")
    if w and w["hit"] is None and winner_id is not None:
        w["hit"] = (winner_id == (fc["t1_id"] if w["side"] == "1" else fc["t2_id"]))
        changed = True
    return changed


def settle(lid):
    """Подставить результат карты и отметить попадания прогнозов (включая тоталы после драфтов, и у уже закрытых карт)."""
    ser = series_results(lid, 3)
    done = 0
    for f in sorted((DIR / lid).glob("*.json")) if (DIR / lid).exists() else []:
        fc = json.loads(f.read_text(encoding="utf-8"))
        if not fc.get("live_bet"):
            continue
        if fc["result"]:   # карта закрыта раньше: добить итоги, которых не хватает
            if fill_totals(fc, fc["result"]["duration"], fc["result"]["kills"], fc["result"]["winner_id"]):
                save(lid, fc)
            continue
        s = find_series(ser, fc["t1_id"], fc["t2_id"], fc["start"])
        if not s or len(s["maps"]) < fc["map_no"]:
            continue
        mp = s["maps"][fc["map_no"] - 1]
        win_id = mp["radiant_team_id"] if mp["radiant_win"] else mp["dire_team_id"]
        kills, dur = mp["radiant_score"] + mp["dire_score"], mp["duration"] / 60
        for p in fc["picks"]:
            if p["cat"] == "win":
                p["hit"] = (win_id == (fc["t1_id"] if p["side"] == "1" else fc["t2_id"]))
            elif p["cat"] == "time":
                p["hit"] = (dur > p["line"]) == (p["side"] == "Да")
            else:
                p["hit"] = (kills > p["line"]) == (p["side"] == "Б")
        fill_totals(fc, dur, kills, win_id)
        fc["result"] = {"match_id": mp["match_id"], "winner_id": win_id, "kills": kills,
                        "kills_for": {"t1": mp["radiant_score"] if mp["radiant_team_id"] == fc["t1_id"] else mp["dire_score"],
                                      "t2": mp["radiant_score"] if mp["radiant_team_id"] == fc["t2_id"] else mp["dire_score"]},
                        "duration": round(dur, 1), "start_time": mp["start_time"],
                        "series": {str(k): v for k, v in s["w"].items()}, "series_done": s["done"]}
        save(lid, fc)
        done += 1
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--event")
    ap.add_argument("--note")
    a = ap.parse_args()
    if a.event and a.note:
        fc = load(a.league, a.event)
        fc["note"] = a.note
        save(a.league, fc)
        print("текст разбора обновлён")
    print("результатов подставлено:", settle(a.league))
    import render_index
    render_index.main()


if __name__ == "__main__":
    main()
