"""Статистика команд за все турниры: объединяет карты команды из data/<league>/*.json.

Результат: страницы reports/all/<team>.html (тот же отчёт, что у турнира, но по всем картам)
и данные для режима «Все турниры» на index.html.
"""
import json

from render_html import ROOT, write_html


def leagues():
    return sorted(p.name for p in (ROOT / "data").iterdir() if p.is_dir())


def league_name(lid):
    f = ROOT / "raw" / f"league_{lid}.json"
    return json.loads(f.read_text(encoding="utf-8"))["name"] if f.exists() else lid


def all_teams():
    """team_id -> {team, team_id, league_id:'all', leagues:[...], games, summary, stem}."""
    from collect_team import summarize  # поздний импорт: collect_team сам импортирует модули отрисовки

    merged = {}
    for lid in leagues():
        for f in (ROOT / "data" / lid).glob("*.json"):
            t = json.loads(f.read_text(encoding="utf-8"))
            m = merged.setdefault(t["team_id"], {"team_id": t["team_id"], "team": t["team"], "league_id": "all",
                                                 "leagues": [], "games": [], "stem": f.stem})
            m["leagues"].append(lid)
            m["games"] += t["games"]
    for m in merged.values():
        m["games"].sort(key=lambda g: g["start_time"])
        m["summary"] = summarize(m["games"])
    return merged


def build_pages():
    out_dir = ROOT / "reports" / "all"
    out_dir.mkdir(parents=True, exist_ok=True)
    teams = all_teams()
    for t in teams.values():
        names = ", ".join(league_name(l) for l in t["leagues"])
        write_html(t, names, out_dir / f"{t['stem']}.html")
    return teams
