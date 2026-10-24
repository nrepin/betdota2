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
STAKES = {"явный": 200, "небольшой": 100, "слабый": 50}  # условная ставка по перевесу, $


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
FORM_W = 0.0           # вес формы (form.py) в вероятности победы: на картах базы не подтвердилась, пока только показ
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
    if not cands:  # перевеса нет нигде: ставим на фаворита карты (слабый перевес, ставка 50)
        for r in m["rows"]:
            if r["market"].startswith("Победа на карте") and r.get("est") is not None:
                p1 = min(0.95, max(0.05, r["est"] + info["adj"]))
                side, odds, p = ("1", r["k1"], p1) if p1 >= 0.5 else ("2", r["k2"], 1 - p1)
                cands.append(dict(cat="win", label="Победа на карте", edge=0.0, r=r, side=side, odds=odds, line=None,
                                  est=round(p, 3), n=r["n"], text=f"Победа на карте: {m['t1'] if side == '1' else m['t2']}",
                                  basis=f"перевеса над линией нет, фаворит по оценке ({p:.0%}; команды {r['est']:.0%}, линия {r['line']:.0%})"))
                break
    if not cands:
        return None, "в линии нет подходящих рынков"
    c = max(cands, key=lambda c: c["edge"] / EDGE[c["cat"]][1])
    signal = ("явный" if c["edge"] >= EDGE[c["cat"]][1] else "небольшой" if c["edge"] >= EDGE[c["cat"]][0] else "слабый")
    r = c["r"]
    pick = {"cat": c["cat"], "label": c["label"], "text": c["text"], "market": r["market"], "side": c["side"], "line": c["line"],
            "odds": c["odds"], "est": c["est"], "implied": round(1 / c["odds"], 3), "n": c["n"], "basis": c["basis"],
            "signal": signal, "ev": None, "stake": STAKES[signal], "hit": None}
    nm = lambda ids: [hero_names.get(str(h), {}).get("localized_name", "?") for h in ids]
    t1, t2 = nm(ids1), nm(ids2)
    note = (f"Прогноз в начале карты, когда выбраны все герои. {m['t1']}: {', '.join(t1)}. {m['t2']}: {', '.join(t2)}. "
            f"Оценка драфтов: темп карты {info['mean']:+g} мин, ожидаемая длительность ≈ {info['exp']:g} мин"
            + (f", убийств ≈ {info['exp_k']:g}" if info["exp_k"] else "")
            + f". Форма: {m['t1']} — {info['form'][0]['word']}" + (f" ({info['form'][0]['score']:+g})" if info['form'][0]['score'] is not None else "")
            + f", {m['t2']} — {info['form'][1]['word']}" + (f" ({info['form'][1]['score']:+g})" if info['form'][1]['score'] is not None else "")
            + f". Выбрано: {c['text']} (коэф {c['odds']}, {c['basis']}, перевес: {signal}). "
            f"Из трёх рынков взят один с наибольшим перевесом; героев с данными в базе: {n_known} из 10. "
            "Выборки малые, маржа букмекера около 8%: это разбор статистики, а не гарантия.")
    mno = map_no(m["map"])
    fc = {"event_id": f"{ev['event_id']}L{mno}", "match_event_id": str(ev["event_id"]), "league": lid, "live_bet": True,
          "created": datetime.datetime.now(MSK).strftime("%Y-%m-%d %H:%M"), "after_start": True,
          "t1": m["t1"], "t2": m["t2"], "t1_id": m["t1_id"], "t2_id": m["t2_id"], "start": ev["start"], "map_no": mno,
          "series_win": m.get("series_win") or [], "url": ev.get("url"), "picks": [pick], "note": note,
          "draft": {"t1": t1, "t2": t2}, "rows": m["rows"], "result": None}
    return fc, ""


def settle(lid):
    """Подставить результат карты и отметить попадания прогнозов."""
    ser = series_results(lid, 3)
    done = 0
    for f in sorted((DIR / lid).glob("*.json")) if (DIR / lid).exists() else []:
        fc = json.loads(f.read_text(encoding="utf-8"))
        if fc["result"] or not fc.get("live_bet"):
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
