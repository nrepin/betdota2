"""Предварительный прогноз ИИ до матча: фаворит, длительность и убийства по статистике команд.

Считается один раз, пока матч не начался, и сохраняется в previews/<лига>/<event_id>.json — после игры
прогноз остаётся прежним и сверяется с результатом. Источники: винрейт карт со сглаживанием и log5 (form.model_p),
длительность, убийства, первая кровь и первая башня по картам команд (collect_odds.team_maps; если на турнире
у команды меньше MIN_MAPS карт — берутся карты со всех турниров). Это оценка по статистике, а не гарантия.

    python scripts/preview.py --league 20395
"""
import argparse
import datetime
import json
from html import escape as e
from math import comb

import collect_odds
import form
from render_html import ROOT
from render_schedule import cfg, teams_of

MSK = datetime.timezone(datetime.timedelta(hours=3))
MIN_MAPS = 6
THRESHOLDS = (30, 35, 40, 45, 50)
LONG, SHORT = 3.0, -3.0      # отклонение длительности от среднего по турниру, мин
BLOODY, QUIET = 5.0, -5.0    # отклонение убийств, шт.


def path(lid, eid):
    return ROOT / "previews" / lid / f"{eid}.json"


def load(lid, eid):
    f = path(lid, eid)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def series_p(p, bo):
    need = bo // 2 + 1
    return sum(comb(need - 1 + k, k) * p ** need * (1 - p) ** k for k in range(need))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def league_avg(lid):
    ms = json.loads((ROOT / "raw" / f"league_{lid}_matches.json").read_text(encoding="utf-8"))
    return mean(m["duration"] / 60 for m in ms), mean(m["radiant_score"] + m["dire_score"] for m in ms)


def team_block(lid, tid, name):
    mp = collect_odds.team_maps(lid, tid)
    pooled = len(mp) < MIN_MAPS
    if pooled:
        mp = collect_odds.team_maps(lid, tid, pool=True)
    frac = lambda fn: mean(1.0 if fn(m) else 0.0 for m in mp if fn(m) is not None)
    return {"id": tid, "name": name, "n": len(mp), "pooled": pooled,
            "dur": mean(m["dur"] for m in mp), "kills": mean(m["kills"] for m in mp),
            "over": {str(t): frac(lambda m, t=t: m["dur"] > t) for t in THRESHOLDS},
            "fb": frac(lambda m: m["fb"]), "tower": frac(lambda m: m["first_tower"]),
            "winrate": frac(lambda m: m["win"]), "durs": [round(m["dur"], 1) for m in mp]}


def compute(lid, ev, teams):
    a, b = ev["a"], ev["b"]
    ta = team_block(lid, a, teams[a]["name"])
    tb = team_block(lid, b, teams[b]["name"])
    bo = (cfg(lid) or {}).get("bo", 3)
    pm = form.model_p(a, b, ev["start"])
    ps = series_p(pm, bo)
    avg_d, avg_k = league_avg(lid)
    ok = ta["dur"] is not None and tb["dur"] is not None
    dur = (ta["dur"] + tb["dur"]) / 2 if ok else None
    kills = (ta["kills"] + tb["kills"]) / 2 if ok else None
    over = {t: (ta["over"][t] + tb["over"][t]) / 2 for t in ta["over"] if ta["over"][t] is not None and tb["over"][t] is not None}
    fav = a if pm >= 0.5 else b
    return {"event_id": str(ev["event_id"]), "league": lid, "a": ta, "b": tb, "bo": bo, "start": ev["start"],
            "created": datetime.datetime.now(MSK).strftime("%Y-%m-%d %H:%M"),
            "p_map_a": pm, "p_series_a": ps, "fav": fav, "dur": dur, "kills": kills, "over": over,
            "league_dur": avg_d, "league_kills": avg_k, "min_n": min(ta["n"], tb["n"])}


def ensure(lid, ev, teams, now, done=False):
    """Сохранить прогноз, если файла нет. До старта — обычный; у идущего матча (done=False) — с пометкой late;
    у завершённого без файла прогноза нет (иначе в статистику попали бы его карты). Возвращает прогноз или None."""
    d = load(lid, ev["event_id"])
    if d or done or ev["a"] not in teams or ev["b"] not in teams:
        return d
    d = compute(lid, ev, teams)
    d["late"] = ev["start"] <= now
    f = path(lid, ev["event_id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return d


def time_html(d, maps):
    """Статистика по времени карты: средняя длительность и доли карт длиннее порогов у каждой команды, факт по сыгранным картам."""
    H = ["<h3 style='margin:12px 0 6px;font-size:15px'>Статистика по времени карты</h3>"]
    for t in (d["a"], d["b"]):
        if t["dur"] is None:
            continue
        shares = ", ".join(f"> {n} мин {t['over'][str(n)]:.0%}" for n in THRESHOLDS if t["over"].get(str(n)) is not None)
        H.append(f"<div class=pk><span class=c>{e(t['name'])}</span><span class=tx>в среднем {t['dur']:.1f} мин за {t['n']} карт: {shares}</span></div>")
    for i, m in enumerate(maps, 1):
        H.append(f"<div class=pk><span class=c>карта {i}</span><span class=tx>фактически {m['duration'] / 60:.1f} мин "
                 f"(ожидание ≈ {d['dur']:.0f} мин)</span></div>")
    return "".join(H)


def verdicts(d):
    """Текстовые выводы: фаворит, затяжные ли карты, убийства."""
    a, b = d["a"], d["b"]
    fa = d["fav"] == a["id"]
    fav, dog = (a, b) if fa else (b, a)
    pm = d["p_map_a"] if fa else 1 - d["p_map_a"]
    ps = d["p_series_a"] if fa else 1 - d["p_series_a"]
    gap = abs(d["p_map_a"] - 0.5)
    force = "явный фаворит" if gap >= 0.15 else "небольшое преимущество" if gap >= 0.06 else "равные команды"
    out = [("Фаворит", f"{fav['name']}: {force}. Карта {pm:.0%}, серия BO{d['bo']} {ps:.0%} (против {dog['name']})")]
    if d["dur"] is not None:
        diff = d["dur"] - d["league_dur"]
        kind = "затяжные" if diff >= LONG else "быстрые" if diff <= SHORT else "средние по длине"
        o = d["over"]
        out.append(("Длительность", f"ожидаются {kind} карты: в среднем {d['dur']:.0f} мин (по турниру {d['league_dur']:.0f}); "
                    + ", ".join(f"> {t} мин {o[str(t)]:.0%}" for t in THRESHOLDS if str(t) in o)))
        kd = d["kills"] - d["league_kills"]
        kk = "кровавые" if kd >= BLOODY else "осторожные, мало убийств" if kd <= QUIET else "обычные по убийствам"
        out.append(("Убийства", f"{kk}: ожидается {d['kills']:.0f} за карту (по турниру {d['league_kills']:.0f})"))
    for k, key in (("Первая кровь", "fb"), ("Первая башня", "tower")):
        if a[key] is not None and b[key] is not None:
            out.append((k, f"{a['name']} {a[key]:.0%} · {b['name']} {b[key]:.0%} карт"))
    return out


def html(d, winner=None, maps=None):
    """Блок для страницы матча. winner — id победителя серии, если она завершена."""
    a, b = d["a"], d["b"]
    H = ["<h2>Предварительный прогноз ИИ</h2><div class=fc>"
         f"<div class=meta>{'после старта матча' if d.get('late') else 'до матча'}, {e(d['created'])} МСК · выборка {a['n']} / {b['n']} карт"
         + (" · мало карт, надёжность низкая" if d["min_n"] < MIN_MAPS else "") + "</div>"]
    for k, t in verdicts(d):
        H.append(f"<div class=pk><span class=c>{e(k)}</span><span class=tx>{e(t)}</span></div>")
    if winner:
        ok = winner == d["fav"]
        name = a["name"] if winner == a["id"] else b["name"]
        H.append(f"<div class=pk><span class=c>Итог</span><span class=tx>победил {e(name)}</span>"
                 + ("<span class='mark ok'>✓ фаворит выиграл</span>" if ok else "<span class='mark no'>✗ фаворит проиграл</span>") + "</div>")
    H.append(time_html(d, maps or []))
    notes = [t["name"] for t in (a, b) if t["pooled"]]
    note = (f" Для {', '.join(notes)} на турнире мало карт — взяты карты со всех турниров." if notes else "")
    H.append("<p class=note>Оценка по статистике команд (винрейт карт, log5, длительность и убийства); состав и драфт не учтены. "
             "Не гарантия исхода: выборки малы." + e(note) + "</p></div>")
    return "".join(H)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    lid = ap.parse_args().league
    teams = teams_of(lid)
    sch = json.loads((ROOT / "odds" / lid / "schedule.json").read_text(encoding="utf-8"))["matches"]
    now = datetime.datetime.now(MSK).timestamp()
    for ev in sch:
        if ev.get("event_id") and ev["start"] > now:
            d = ensure(lid, ev, teams, now)
            if d:
                print(f"{d['a']['name']} – {d['b']['name']}")
                for k, t in verdicts(d):
                    print(f"  {k}: {t}")


if __name__ == "__main__":
    main()
