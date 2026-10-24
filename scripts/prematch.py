"""Коэффициенты до матча: сохраняются отдельно, чтобы после старта оставались «открытие» и «закрытие» линии.

Файл odds/<league>/prematch/<event_id>.json:
  series — коэффициенты на серию (open — первый снимок, close — последний до старта);
  maps   — по номеру карты: open/close со строками рынков (победа на карте, время, убийства…), сохраняются, пока карта не идёт.
Пишет auto.py при каждом скачивании линии. Для уже накопленной истории снимков:

    python scripts/prematch.py --backfill        # восстановить из odds/<league>/<время>.json
"""
import argparse
import datetime
import json
import re

from render_html import ROOT

MSK = datetime.timezone(datetime.timedelta(hours=3))
LITE = ("market", "c1", "k1", "c2", "k2", "line")


def path(lid, eid):
    return ROOT / "odds" / lid / "prematch" / f"{eid}.json"


def load(lid, eid):
    f = path(lid, eid)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def map_no(name):
    m = re.search(r"(\d+)", name or "")
    return int(m.group(1)) if m else None


def update(lid, m, ts, may_map):
    """Занести матч из снимка линии (m) в файл до-матчевых коэффициентов. may_map — можно ли сохранять рынки карты."""
    eid = str(m.get("event_id") or "")
    if not eid or not m.get("t1_id"):
        return False
    d = load(lid, eid) or {"event_id": eid, "league": lid, "t1": m["t1"], "t2": m["t2"], "t1_id": m["t1_id"],
                           "t2_id": m["t2_id"], "start": m["start"], "url": m.get("url"), "series": {}, "maps": {}}
    d["start"] = m["start"]
    stamp = datetime.datetime.fromtimestamp(ts, MSK).strftime("%Y-%m-%d %H:%M")
    changed = False
    if m["start"] > ts and m.get("series_win") and all(m["series_win"]):
        one = {"ts": stamp, "odds": list(m["series_win"])}
        d["series"].setdefault("open", one)
        d["series"]["close"] = one
        changed = True
    n = map_no(m.get("map"))
    if n and may_map and m.get("rows"):
        one = {"ts": stamp, "rows": [{k: r[k] for k in LITE if k in r} for r in m["rows"]]}
        slot = d["maps"].setdefault(str(n), {})
        slot.setdefault("open", one)
        slot["close"] = one
        changed = True
    if changed:
        f = path(lid, eid)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return changed


def save(lid, snap, ts, live_eids):
    """Сохранить до-матчевые коэффициенты из свежего снимка. live_eids — события, у которых карта идёт сейчас
    (None — неизвестно: тогда рынки карт, кроме первой до старта, не пишем). Возвращает число обновлённых матчей."""
    n = 0
    for m in snap["matches"]:
        eid = str(m.get("event_id") or "")
        first = map_no(m.get("map")) == 1
        may_map = (m["start"] > ts) if first else (live_eids is not None and eid not in live_eids)
        n += update(lid, m, ts, may_map)
    return n


def backfill():
    """Восстановить из истории снимков (в хронологическом порядке); по каждому берём только состояние до старта."""
    n = 0
    for d in sorted((ROOT / "odds").iterdir()):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("20*.json")):
            snap = json.loads(f.read_text(encoding="utf-8"))
            ts = datetime.datetime.strptime(snap["fetched"], "%Y-%m-%d %H:%M").replace(tzinfo=MSK).timestamp()
            for m in snap["matches"]:
                first = map_no(m.get("map")) == 1
                n += update(d.name, m, ts, first and m["start"] > ts)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    a = ap.parse_args()
    if a.backfill:
        print("обновлений:", backfill())
