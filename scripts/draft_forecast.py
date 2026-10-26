"""Прогноз ИИ по драфту сейчас, вручную: для каждой идущей карты турнира (выбраны все 10 героев) считает прогноз
на победу, время и убийства и сохраняет его в forecasts/<лига>/<event_id>L<карта>.json.

В отличие от автопилота не смотрит на запомненный отказ (auto_state.json → live_bets) и на лимит «первые 7 минут игры».

    python scripts/draft_forecast.py --league 20395
    python scripts/draft_forecast.py --league 20395 --no-odds     # не скачивать линию, взять последний снимок
"""
import argparse
import json
import time

import auto
import collect_odds
import render_index
import render_schedule
from render_html import ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--no-odds", action="store_true", help="не скачивать линию заново")
    a = ap.parse_args()
    lid = a.league
    auto.setup_log()
    if not auto.take_lock():
        print("автопилот сейчас в тике (.auto.lock) — повторите через минуту")
        return 1
    try:
        now = time.time()
        st = auto.load_state()
        s = st.setdefault(lid, {})
        teams = render_schedule.teams_of(lid)
        ser = render_schedule.series_results(lid, 3)
        events = [m for m in auto.schedule_of(lid) if m.get("event_id")
                  and not (render_schedule.find_series(ser, m["a"], m["b"], m["start"]) or {}).get("done")
                  and m["start"] - auto.LIVE_BEFORE <= now <= m["start"] + auto.LIVE_AFTER]
        if not events:
            print("нет матчей в окне лайва: серия ещё не началась или уже закончена")
            return 0
        if a.no_odds:
            f = ROOT / "odds" / lid / "latest.json"
            snap = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        else:
            snap = auto.refresh_odds(lid, s, now, False)
        auto.LATE_AFTER = 10 ** 9                      # без лимита по времени игры
        s["live_bets"] = {}                            # забыть прошлые отказы
        found = auto.do_live(lid, s, now, events, snap, teams, False)
        if not found:
            print("лайв OpenDota не видит идущую карту (драфт ещё идёт или лайв отстаёт) — попробуйте через минуту")
        for k, v in s["live_bets"].items():
            print(f"карта {k}: {v}")
        auto.save_state(st)
        render_index.main()
    finally:
        auto.LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
