"""Линия PARI против статистики команд: скачивает коэффициенты на матчи турнира и сравнивает
вероятности линии (без маржи) с частотами по картам команд на турнире.

Использование:
    python scripts/collect_odds.py --league 19102          # скачать линию, сохранить снимок, пересобрать анализ

Источник (без браузера и без авторизации, JSON):
    {API}/events/listBase?lang=ru&scopeMarket=2300              — вся линия: события, основные коэффициенты
    {API}/events/event?lang=ru&version=0&eventId=<id>&scopeMarket=2300 — все рынки серии и её карт
    {API}/line/factorsCatalog/tables?version=0&lang=ru&sysId=21 — каталог: код коэффициента -> название
Ответы бывают gzip. Запросы редкие (несколько на запуск) — не запускать чаще раза в несколько минут.

Результат: odds/<league>/latest.json (+ odds/<league>/<время>.json — история), таблица на странице анализа
через плейсхолдер <!--odds--> в analysis/<league>.html. Матчи ищутся по названиям команд лиги и по
разделу PARI из analysis/<league>.json ("pari_segment").
"""
import argparse
import datetime
import gzip
import json
import math
import re
import sys
import time
import urllib.request

import netutil
from html import escape as e

from render_html import ROOT

API = "https://line-vk01-w.pb06e2-resources.ru"
MSK = datetime.timezone(datetime.timedelta(hours=3))
ODDS = ROOT / "odds"


# ---------------- загрузка ----------------
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Origin": "https://pari.ru", "Referer": "https://pari.ru/"})
    with netutil.urlopen(req, timeout=60) as r:
        raw = r.read()
    if raw[:2] == bytes([0x1F, 0x8B]):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def catalog():
    """Код коэффициента -> (название рынка, колонка). Каталог кешируется на сутки в raw/pari_tables.json."""
    f = ROOT / "raw" / "pari_tables.json"
    if not f.exists() or time.time() - f.stat().st_mtime > 86400:
        f.write_text(json.dumps(get(f"{API}/line/factorsCatalog/tables?version=0&lang=ru&sysId=21"), ensure_ascii=False), encoding="utf-8")
    tables = json.loads(f.read_text(encoding="utf-8"))
    names = {}

    def walk(o):
        if isinstance(o, dict):
            if "rows" in o:
                rows = o["rows"]
                head = [c.get("name", "") for c in rows[0]] if rows and all("name" in c and "kind" not in c for c in rows[0]) else []
                for r in (rows[1:] if head else rows):
                    lab = " ".join(c.get("name", "") for c in r if "name" in c and "kind" not in c)
                    for i, c in enumerate(r):
                        if c.get("kind") == "value":
                            names.setdefault(c["factorId"], (o.get("name") or lab or "?", head[i] if i < len(head) else ""))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(tables)
    return names


def norm(name):
    s = re.sub(r"[^a-z0-9а-я]", "", (name or "").lower())
    for w in ("team", "gaming", "esports"):
        s = s.replace(w, "")
    return s


# ---------------- статистика карт команды ----------------
def team_maps(lid, tid, pool=False):
    """Показатели каждой карты команды на турнире (из data/ и raw/matches); pool — по всем турнирам."""
    games = []
    for d in sorted((ROOT / "data").iterdir()):
        if not pool and d.name != lid:
            continue
        for f in d.glob("*.json"):
            t = json.loads(f.read_text(encoding="utf-8"))
            if t["team_id"] == tid:
                games += t["games"]
    t = {"games": games}
    out = []
    for g in t["games"]:
        m = json.loads((ROOT / "raw" / "matches" / f"{g['match_id']}.json").read_text(encoding="utf-8"))
        is_rad = m["radiant_team_id"] == tid
        side = 2 if is_rad else 3  # objectives: 2 = Radiant, 3 = Dire
        obj = m.get("objectives") or []
        rosh = [o for o in obj if o["type"] == "CHAT_MESSAGE_ROSHAN_KILL"]
        towers = [o for o in obj if o["type"] == "building_kill" and "tower" in (o.get("key") or "")]
        mk, streak = {}, 0
        for p in m["players"]:
            for n, c in (p.get("multi_kills") or {}).items():
                mk[int(n)] = mk.get(int(n), 0) + c
            streak = max([streak] + [int(n) for n in (p.get("kill_streaks") or {})])
        loser_rax = m["barracks_status_dire"] if m["radiant_win"] else m["barracks_status_radiant"]
        out.append({
            "win": g["win"], "dur": m["duration"] / 60, "kills": g["total_kills"],
            "fb": g["first_blood"],
            "first_rosh": (rosh[0]["team"] == side) if rosh else None, "rosh": len(rosh),
            # разрушена башня соперника (badguys для Radiant) = первая башня наша
            "first_tower": (("badguys" in towers[0]["key"]) == is_rad) if towers else None, "towers": len(towers),
            "mega": loser_rax == 0, "rampage": mk.get(5, 0) > 0, "ultra": any(k >= 4 for k in mk), "godlike": streak >= 10,
        })
    return out


def freq(rows, fn):
    vals = [fn(r) for r in rows if fn(r) is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


# ---------------- сравнение ----------------
def compare(markets, maps1, maps2, t1, t2):
    """Строки таблицы для карты. markets: (рынок, параметр) -> {колонка: коэф}."""
    both = maps1 + maps2
    rows = []

    def add(title, key, cols, est, n, basis):
        odds = markets.get(key)
        if not odds or est is None or not all(c in odds for c in cols):
            return
        k1, k2 = odds[cols[0]], odds[cols[1]]
        s = 1 / k1 + 1 / k2
        line = (1 / k1) / s
        diff = est - line
        se = math.sqrt(max(est * (1 - est), 0.05) / max(n, 1))
        ev = est * k1 - 1 if diff >= 0 else (1 - est) * k2 - 1
        rows.append({"market": title, "c1": cols[0], "k1": k1, "c2": cols[1], "k2": k2, "line": line, "est": est, "n": n,
                     "basis": basis, "diff": diff, "margin": s - 1, "ev": ev, "ev_side": cols[0] if diff >= 0 else cols[1],
                     "signal": "нет перевеса" if abs(diff) < se else ("небольшой" if abs(diff) < 2 * se else "явный")})

    def pick(prefix, param=""):
        return next((k for k in markets if k[0].startswith(prefix) and k[1] == param), None)

    # победа на карте: log5 по винрейтам карт (не учитывает силу соперников)
    w1, n1 = freq(maps1, lambda r: r["win"])
    w2, n2 = freq(maps2, lambda r: r["win"])
    if w1 is not None and w2 is not None and 0 < w1 < 1 and 0 < w2 < 1:
        p = w1 * (1 - w2) / (w1 * (1 - w2) + w2 * (1 - w1))
        add(f"Победа на карте: {t1}", ("Исходы", ""), ["1", "2"], p, min(n1, n2), f"винрейт {w1:.0%} / {w2:.0%}")

    for title, prefix, fn in (("Первая кровь", "Кто прольет первую", lambda r: r["fb"]),
                              ("Первый Рошан", "Первый Рошан", lambda r: r["first_rosh"]),
                              ("Первая башня", "Кто разрушит перву", lambda r: r["first_tower"])):
        a, na = freq(maps1, fn)
        b, nb = freq(maps2, fn)
        key = next((k for k in markets if k[0].startswith(prefix) and set(markets[k]) >= {"1", "2"}), None)
        if a is not None and b is not None:
            add(f"{title}: {t1}", key, ["1", "2"], (a + 1 - b) / 2, min(na, nb), f"{t1} {a:.0%}, {t2} {b:.0%}")

    for k in sorted({k for k in markets if k[0] == "Тотал" and k[1]}, key=lambda k: float(k[1])):
        est, n = freq(both, lambda r, L=float(k[1]): r["kills"] > L)
        add(f"Тотал убийств больше {k[1]}", k, ["Б", "М"], est, n, f"{round(est * n)} из {n} карт")
    for k in sorted({k for k in markets if k[0].startswith("Продолжительность карты больше") and k[1]}, key=lambda k: float(k[1])):
        est, n = freq(both, lambda r, L=float(k[1]): r["dur"] > L)
        add(f"Время карты больше {k[1]} мин", k, ["Да", "нет"], est, n, f"{round(est * n)} из {n} карт")
    for title, prefix, fn, params in (("Тотал Рошанов больше", "Тотал убийств Роша", lambda r, L: r["rosh"] > L, True),
                                      ("Тотал башен больше", "Тотал разрушеных", lambda r, L: r["towers"] > L, True),
                                      ("Будут мегакрипы", "Будут мегакрипы", lambda r, L: r["mega"], False),
                                      ("Будет Ultrakill", "Будет Ultrakill", lambda r, L: r["ultra"], False),
                                      ("Будет Rampage", "Будет Rampage", lambda r, L: r["rampage"], False),
                                      ("Будет Beyond Godlike", "Будет Beyond Godli", lambda r, L: r["godlike"], False)):
        keys = sorted({k for k in markets if k[0].startswith(prefix)}, key=lambda k: float(k[1] or 0))
        for k in keys:
            L = float(k[1] or 0)
            est, n = freq(both, lambda r, L=L, fn=fn: fn(r, L))
            add(f"{title} {k[1]}".strip() if params else title, k, ["Да", "нет"], est, n, f"{round(est * n)} из {n} карт")
    return rows


def league_cfg(lid):
    """pari_segment и aliases: analysis/<lid>.schedule.json, затем analysis/<lid>.json."""
    cfg = {}
    for name in (f"{lid}.json", f"{lid}.schedule.json"):
        f = ROOT / "analysis" / name
        if f.exists():
            cfg.update(json.loads(f.read_text(encoding="utf-8")))
    return cfg


def find_segments(keyword=""):
    """Dota-разделы линии PARI (id, название, число матчей) — поиск нужного турнира."""
    base = get(f"{API}/events/listBase?lang=ru&scopeMarket=2300")
    cnt = {}
    for ev in base["events"]:
        if ev.get("level") == 1 and ev.get("team2"):
            cnt[ev["sportId"]] = cnt.get(ev["sportId"], 0) + 1
    return [(s["id"], s["name"], cnt.get(s["id"], 0)) for s in base["sports"]
            if "Dota" in s.get("name", "") and keyword.lower() in s["name"].lower()]


def collect(lid, segment=None):
    meta = league_cfg(lid)
    segment = segment if segment is not None else meta.get("pari_segment", "")
    teams = {norm(t["name"]): t for t in json.loads((ROOT / "raw" / f"league_{lid}_teams.json").read_text(encoding="utf-8"))}
    for k, v in meta.get("aliases", {}).items():
        if norm(v) in teams:
            teams[norm(k)] = teams[norm(v)]
    names = catalog()
    base = get(f"{API}/events/listBase?lang=ru&scopeMarket=2300")
    segs = {s["id"]: s["name"] for s in base["sports"] if "Dota" in s.get("name", "") and segment.lower() in s.get("name", "").lower()}
    matches = []
    for ev in base["events"]:
        if ev.get("sportId") not in segs or ev.get("level") != 1 or not ev.get("team2"):
            continue
        a, b = teams.get(norm(ev.get("team1"))), teams.get(norm(ev.get("team2")))
        if not a or not b:
            continue
        full = get(f"{API}/events/event?lang=ru&version=0&eventId={ev['id']}&scopeMarket=2300")
        evs = {x["id"]: x for x in full["events"]}
        per_event = {}
        for blk in full["customFactors"]:
            en = evs.get(blk["e"], {}).get("name") or "серия"
            mk = per_event.setdefault(en, {})
            for f in blk["factors"]:
                market, col = names.get(f["f"], (f"#{f['f']}", ""))
                mk.setdefault((market, f.get("pt", "")), {})[col] = f["v"]
        maps1, maps2 = team_maps(lid, a["team_id"]), team_maps(lid, b["team_id"])
        if min(len(maps1), len(maps2)) < 6:  # на турнире мало карт — берём все турниры
            maps1, maps2 = team_maps(lid, a["team_id"], True), team_maps(lid, b["team_id"], True)
        map_name = next((n for n in sorted(per_event) if n != "серия"), None)
        rows = compare(per_event.get(map_name, {}), maps1, maps2, a["name"], b["name"]) if map_name else []
        series = per_event.get("серия", {})
        res = series.get(("Исходы", ""), {})
        matches.append({
            "event_id": ev["id"], "segment": segs[ev["sportId"]], "start": ev.get("startTime"),
            "t1": a["name"], "t2": b["name"], "t1_id": a["team_id"], "t2_id": b["team_id"],
            "map": map_name, "rows": rows, "series_win": [res.get("1"), res.get("2")],
            "url": f"https://pari.ru/esports/category/dota2/{ev['sportId']}/{ev['id']}",
        })
        time.sleep(1)
    snap = {"fetched": datetime.datetime.now(MSK).strftime("%Y-%m-%d %H:%M"), "league": lid, "matches": matches}
    out = ODDS / lid
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / (snap["fetched"].replace(":", "-").replace(" ", "_") + ".json")).write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return snap


# ---------------- отрисовка для страницы анализа ----------------
ODDS_CSS = """
.odds-m{margin-bottom:20px}
.odds-m .oh{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px;padding:14px 16px;border-bottom:1px solid var(--line)}
.odds-m .oh b{font-size:16px}.odds-m .oh span{font-size:12.5px;color:var(--muted)}
.odds-m td,.odds-m th{padding:9px 12px}
.odds-m td.k{font-family:var(--mono);white-space:nowrap}
.odds-m td.k i{font-style:normal;color:var(--muted);font-size:11.5px;margin-right:4px}
.odds-m tr.noise td{color:var(--muted)}
.odds-m tr.strong td.sig{font-weight:700}
.odds-m td.d.pos{color:var(--win)}.odds-m td.d.neg{color:var(--loss)}
.odds-note{font-size:12.5px;color:var(--muted);max-width:80ch;margin-top:8px}
"""


def odds_html(lid):
    f = ODDS / lid / "latest.json"
    if not f.exists():
        return "<div class=muted>Линия ещё не скачана: <code>python scripts/collect_odds.py --league " + e(lid) + "</code></div>"
    snap = json.loads(f.read_text(encoding="utf-8"))
    if not snap["matches"]:
        return f"<div class=muted>На {e(snap['fetched'])} МСК в линии PARI нет матчей турнира.</div>"
    H = []
    for m in snap["matches"]:
        start = datetime.datetime.fromtimestamp(m["start"], MSK).strftime("%d.%m %H:%M") if m.get("start") else ""
        sw = m["series_win"]
        H.append(f"<div class='card odds-m'><div class=oh><b>{e(m['t1'])} - {e(m['t2'])}</b>"
                 f"<span>начало {start} МСК</span><span>серия: {sw[0]} / {sw[1]}</span>"
                 f"<span>рынки: {e(m['map'] or 'нет карт в линии')}</span><span><a href='{e(m['url'])}'>PARI</a></span></div>")
        if not m["rows"]:
            H.append("<div class=muted style='padding:14px 16px'>Нет рынков по картам.</div></div>")
            continue
        H.append("<table><thead><tr><th>Рынок</th><th>Коэффициенты</th><th class=num>Линия</th><th class=num>Наши данные</th>"
                 "<th class=num>Разница</th><th>Основание</th><th>Перевес</th><th class=num>Ожидание</th></tr></thead><tbody>")
        for r in m["rows"]:
            cls = "noise" if r["signal"] == "нет перевеса" else ("strong" if r["signal"] == "явный" else "")
            d = r["diff"] * 100
            ev = (f"{r['ev_side']} {r['ev'] * 100:+.0f}%" if r["ev"] > 0 else "нет")
            H.append(f"<tr class='{cls}'><td>{e(r['market'])}</td>"
                     f"<td class=k><i>{e(r['c1'])}</i>{r['k1']} <i>{e(r['c2'])}</i>{r['k2']}</td>"
                     f"<td class=num>{r['line'] * 100:.0f}%</td><td class=num>{r['est'] * 100:.0f}%</td>"
                     f"<td class='num d {'pos' if d > 0 else 'neg'}'>{d:+.0f} п.п.</td><td>{e(r['basis'])}</td>"
                     f"<td class=sig>{r['signal']}</td><td class=num>{ev}</td></tr>")
        H.append("</tbody></table></div>")
    H.append(f"<div class=odds-note>Снимок линии PARI на {e(snap['fetched'])} МСК. «Линия» — вероятность первого исхода "
             f"(Больше, Да или первая команда) без маржи букмекера (на картах около 8%). «Наши данные» — частота по картам обеих "
             f"команд на турнире; для «кто первым» — среднее из доли первой команды и доли второй команды отдавать это событие. "
             f"«Перевес»: нет перевеса — разница меньше одной статистической погрешности выборки, небольшой — до двух, явный — больше. "
             f"«Ожидание» — средний результат ставки на сторону с перевесом, если наши частоты верны. Выборка 13-15 карт на "
             f"команду, соперники у команд разные. Это разбор статистики, а не совет делать ставки.</div>")
    return "".join(H)


def recommend(snap):
    """Текстовый разбор: победа, время, убийства — лучшие по перевесу строки каждого матча."""
    rank = {"явный": 2, "небольшой": 1, "нет перевеса": 0}
    for m in snap["matches"]:
        start = datetime.datetime.fromtimestamp(m["start"], MSK).strftime("%d.%m %H:%M") if m.get("start") else ""
        print(f"\n== {m['t1']} - {m['t2']}  ({start} МСК)  серия {m['series_win'][0]} / {m['series_win'][1]}")
        if not m["rows"]:
            print("  нет рынков по картам")
            continue
        for title, pref in (("Победа", "Победа на карте"), ("Время", "Время карты"), ("Убийства", "Тотал убийств больше")):
            rows = [r for r in m["rows"] if r["market"].startswith(pref)]
            rows.sort(key=lambda r: (-rank[r["signal"]], -abs(r["diff"])))
            for r in rows[:2]:
                side = r["ev_side"]
                print(f"  {title}: {r['market']} — коэф {r['c1']} {r['k1']} / {r['c2']} {r['k2']}, линия {r['line']:.0%}, "
                      f"по статистике {r['est']:.0%} ({r['basis']}), ставка на {side} (EV {r['ev']:+.0%}), перевес: {r['signal']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", help="id лиги OpenDota/Dotabuff")
    ap.add_argument("--find", metavar="СЛОВО", nargs="?", const="", help="показать Dota-разделы линии PARI и выйти")
    ap.add_argument("--segment", help="часть названия раздела PARI (иначе pari_segment из analysis/)")
    ap.add_argument("--text", action="store_true", help="напечатать разбор: победа, время, убийства")
    args = ap.parse_args()
    if args.find is not None:
        for sid, name, n in find_segments(args.find):
            print(f"{sid}\t{n} матч.\t{name}")
        return
    if not args.league:
        ap.error("нужен --league (или --find)")
    snap = collect(args.league, args.segment)
    for m in snap["matches"]:
        print(f"{m['t1']} - {m['t2']}: {len(m['rows'])} рынков ({m['map']})")
    if args.text:
        recommend(snap)
    if (ROOT / "analysis" / f"{args.league}.html").exists():
        import render_analysis
        render_analysis.main()


if __name__ == "__main__":
    main()
