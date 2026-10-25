"""Резервный источник лайва: hawk.live (когда игры нет в OpenDota /api/live).

У hawk.live сайт на Inertia.js: любая страница отдаёт JSON с props, если послать заголовок X-Inertia. Главная содержит
seriesList (идущие серии со slug), страница серии — seriesPageData.matches[]: герои обеих сторон, счёт, время игры.
Обычный HTTP GET, без ключей и без входа; robots.txt разрешает (закрыты только /login и /logout).
Игра приводится к виду записи OpenDota /api/live, чтобы остальной код (прогноз, лайв) работал без изменений.

    python scripts/hawk.py            # что сейчас идёт на hawk.live (по расписанию лиг из odds/)
"""
import json
import re
import sys
import urllib.error
import urllib.request

import netutil

BASE = "https://hawk.live"
UA = "Mozilla/5.0 (dota-stats)"
_version = [None]


def _norm(s):
    return re.sub(r"[^0-9a-zа-я]", "", (s or "").lower())


def _page_version(html):
    import html as h
    m = re.search(r'data-page="([^"]*)"', html)
    return json.loads(h.unescape(m.group(1))).get("version") if m else None


def get(path):
    """JSON props страницы. Версия ресурсов берётся с главной; при 409 (версия сменилась) обновляется и запрос повторяется."""
    for attempt in range(2):
        if _version[0] is None:
            with netutil.urlopen(urllib.request.Request(BASE + "/", headers={"User-Agent": UA}), timeout=30) as r:
                _version[0] = _page_version(r.read().decode("utf-8", "replace"))
        req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "X-Inertia": "true",
                                                           "X-Inertia-Version": _version[0] or ""})
        try:
            with netutil.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))["props"]
        except urllib.error.HTTPError as ex:
            if ex.code == 409 and attempt == 0:
                _version[0] = None
                continue
            raise


def live_series():
    """Идущие сейчас серии: [{slug, championship: {slug, name}, team1: {name}, team2: {name}, ...}]."""
    return get("/").get("seriesList", [])


def _game(lid, ev, teams, sp):
    """Текущая карта серии в виде записи /api/live (None, если карты нет или она закончилась)."""
    t1, t2 = sp["team1"]["name"], sp["team2"]["name"]
    ids = {_norm(teams[ev["a"]]["name"]): ev["a"], _norm(teams[ev["b"]]["name"]): ev["b"]}
    i1, i2 = ids.get(_norm(t1)), ids.get(_norm(t2))
    cur = [m for m in sp.get("matches", []) if m.get("isRadiantWinner") is None]
    if not (i1 and i2 and cur):
        return None
    m = max(cur, key=lambda x: x["number"])
    if not m["picks"]:
        return None
    rad1 = bool(m["isTeam1Radiant"])
    rid, did = (i1, i2) if rad1 else (i2, i1)
    rname, dname = (t1, t2) if rad1 else (t2, t1)
    st = max(m["states"], key=lambda s: s["id"]) if m.get("states") else {}
    return {
        "match_id": f"hawk{m['id']}", "league_id": int(lid), "source": "hawk.live",
        "team_id_radiant": rid, "team_id_dire": did, "team_name_radiant": rname, "team_name_dire": dname,
        "game_time": st.get("gameTime", 0), "radiant_score": st.get("radiantScore", 0), "dire_score": st.get("direScore", 0),
        "radiant_lead": st.get("radiantNetWorthAdvantage", 0), "deactivate_time": 0, "map_no": m["number"],
        "players": [{"team": 0 if p["isRadiant"] else 1, "hero_id": p["hero"]["id"]} for p in m["picks"]],
    }


def extra_games(games, lid, events, teams):
    """Игры событий, которых нет в games (/api/live): берём с hawk.live. Сбой источника не ломает автопилот."""
    have = {frozenset((x.get("team_id_radiant"), x.get("team_id_dire"))) for x in games
            if str(x.get("league_id")) == lid and not x.get("deactivate_time")}
    need = [ev for ev in events if frozenset((ev["a"], ev["b"])) not in have]
    if not need:
        return []
    out = []
    try:
        series = live_series()
        for ev in need:
            na, nb = _norm(teams[ev["a"]]["name"]), _norm(teams[ev["b"]]["name"])
            s = next((x for x in series if {_norm(x["team1"]["name"]), _norm(x["team2"]["name"])} == {na, nb}), None)
            if not s:
                continue
            sp = get(f"/dota-2/matches/{s['championship']['slug']}/{s['slug']}").get("seriesPageData") or {}
            g = _game(lid, ev, teams, sp)
            if g:
                out.append(g)
    except Exception as ex:
        print(f"hawk.live: {ex}", file=sys.stderr)
    return out


if __name__ == "__main__":
    from render_html import ROOT
    import render_schedule
    for d in sorted((ROOT / "odds").iterdir()):
        sf = d / "schedule.json"
        if not sf.exists():
            continue
        teams = render_schedule.teams_of(d.name)
        evs = [m for m in json.loads(sf.read_text(encoding="utf-8"))["matches"] if m.get("event_id")]
        for g in extra_games([], d.name, evs, teams):
            n = [sum(1 for p in g["players"] if p["team"] == t) for t in (0, 1)]
            print(f"[{d.name}] карта {g['map_no']}: {g['team_name_radiant']} – {g['team_name_dire']}, "
                  f"{g['game_time']} с, убийства {g['radiant_score']}:{g['dire_score']}, героев {n}")
