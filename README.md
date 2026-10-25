# Dota 2 — статистика турниров, линия PARI и лайв

Все команды запускать из папки проекта (`betdota2`). Нужны Python 3 и интернет. Для вывода с кириллицей:

```bash
export PYTHONIOENCODING=utf-8      # PowerShell: $env:PYTHONIOENCODING = "utf-8"
```

## 0. Развёртывание на новом компьютере

```bash
git clone <репозиторий> && cd betdota2
python scripts/auto.py --loop
```

Папка `raw/` (кеш OpenDota, ~34 МБ) лежит в репозитории, поэтому ничего докачивать не нужно.
После новых матчей кеш пополняется сам; закоммитить его: `git add -A && git commit`.

## Windows: постоянная работа без «спячки»

- Запуск: двойной клик по `start_auto.bat` (или `start_auto.bat` в cmd). Он перезапускает автопилот, если тот упал.
  Файла нет в git (он в `.gitignore`): на новом компьютере его нужно создать, см. ниже.
- `auto.py --loop` сам запрещает компьютеру уходить в сон, пока работает, и выключает «быстрое выделение» консоли
  (раньше клик мышью по окну ставил скрипт на паузу до нажатия Esc).
- Не закрывайте окно и не выходите из системы (Win+L можно). Крышку ноутбука при закрытии лучше настроить на «Ничего не делать»:
  `powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0` и `powercfg /setactive SCHEME_CURRENT`.
- Автозапуск при входе в Windows (один раз, в PowerShell):
  `schtasks /Create /TN DotaAuto /SC ONLOGON /TR "<путь к проекту>\start_auto.bat" /RL LIMITED`
  Удалить: `schtasks /Delete /TN DotaAuto /F`.
- Если лайв пишет `WinError 10061` — отключился VPN или прокси, через который идёт интернет.

### Как создать `start_auto.bat` на новом компьютере

Файл кладётся в корень проекта (рядом с `README.md` и папкой `scripts`). Содержимое — только латиница, без русских букв
(cmd читает `.bat` в своей кодировке и портит кириллицу):

```bat
@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
title Dota auto
:loop
python scripts\auto.py --loop
echo [%date% %time%] auto.py stopped, restart in 10 sec. Close this window to stop.
if exist .auto.lock del .auto.lock
timeout /t 10 /nobreak >nul
goto loop
```

Способы создать:

1. **Блокнот.** Открыть Блокнот, вставить текст выше, «Файл → Сохранить как», тип файла «Все файлы», имя `start_auto.bat`,
   кодировка ANSI или UTF-8, папка проекта. Проверить, что файл называется именно `start_auto.bat`, а не `start_auto.bat.txt`
   (в проводнике включить «Расширения имён файлов»).
2. **PowerShell** (в папке проекта), создаст файл целиком:

```powershell
@"
@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
title Dota auto
:loop
python scripts\auto.py --loop
echo [%date% %time%] auto.py stopped, restart in 10 sec. Close this window to stop.
if exist .auto.lock del .auto.lock
timeout /t 10 /nobreak >nul
goto loop
"@ | Set-Content -Encoding Ascii start_auto.bat
```

Требования: установленный Python 3 (команда `python` в PATH). Запуск — двойной клик; остановка — закрыть окно.
Если нужен автозапуск при входе в Windows — команда `schtasks` выше.

## 1. Сайт (просмотр страниц)

```bash
npx -y serve -l 8895 .
```

Открыть http://localhost:8895 — главная, `matches/<лига>/<event_id>.html` (страница матча с блоком «Лайв»),
`analysis/<лига>.html` (линия против статистики), `forecasts.html`, `heroes.html`.

## 2. Автопилот (всё само: линия, лайв, прогнозы, результаты)

```bash
python scripts/auto.py --loop              # работает постоянно, тик каждые 30 с
python scripts/auto.py --once              # один тик (для планировщика, раз в минуту)
python scripts/auto.py --once --dry        # показать, что было бы сделано, ничего не писать
python scripts/auto.py --loop --league 20395   # только один турнир
```

Что делает:

- скачивает линию PARI и расписание (раз в 3–20 мин в зависимости от близости матча);
- в окне матча раз в минуту тянет лайв OpenDota, оценивает драфты;
- до матча сохраняет предварительный прогноз (`previews/`): фаворит, длительность, убийства — виден на странице матча;
- на каждую карту, как только выбраны 10 героев, показывает три прогноза (победитель, тотал убийств, время) и ставит на один из них (слабый перевес 50 $, небольшой 75 $, явный 100 $) — с наибольшим перевесом над линией: победа от коэффициента 1.4, тоталы от 1.7 → `forecasts/`;
- после матча закрывает прогнозы и пересобирает страницы.

Опции: `--after "команда"` (например `git add -A && git commit && git push` после тика с изменениями),
переменные `TG_TOKEN` и `TG_CHAT` — уведомления в Telegram.
Состояние хранится в `auto_state.json`. Автопилот берёт турниры, у которых есть `analysis/<id>.schedule.json`.

## 3. Только лайв

```bash
python scripts/live.py                     # лайвы всех турниров из data/
python scripts/live.py --league 20395      # один турнир
python scripts/live.py --league 20395 --watch 60   # обновлять каждые 60 с
```

Печатает герои, время, убийства, золото, темп драфтов (быстрый / затяжной) и ожидаемую длительность, затем
обновляет блок «Лайв» на странице матча. Если лайвов нет — между картами серии он пропадает на несколько минут.

## 4. Линия PARI и разбор

```bash
python scripts/collect_odds.py --find pari          # найти раздел турнира в линии
python scripts/collect_odds.py --league 20395 --text   # скачать коэффициенты и напечатать разбор
python scripts/render_schedule.py --league 20395    # обновить расписание и таблицу
python scripts/forecast.py --league 20395           # подставить результаты в прогнозы
```

Связка турнира лежит в `analysis/<лига>.schedule.json`:

```json
{"pari_segment": "часть названия раздела PARI", "aliases": {"1w team": "1win"}, "bo": 3}
```

Если скрипт пишет «не сопоставлено: A - B» — добавить алиасы.

Предварительный прогноз вручную: `python scripts/preview.py --league 20395`. Считается один раз, пока матч не начался;
после игры на странице матча он сверяется с результатом (фаворит выиграл или нет).

## 5. Статистика команд

```bash
python scripts/collect_team.py --league 20395 --all            # все команды турнира (долго)
python scripts/collect_team.py --league 20395 --all --refresh  # подтянуть новые матчи
```

Подробности — [instruction/TEAM_STATS_GUIDE.md](instruction/TEAM_STATS_GUIDE.md). Dotabuff не парсить (403), данные идут из OpenDota.

## 6. Через Claude Code

В проекте есть скиллы `/dota [турнир]` (линия и рекомендации) и `/live [турнир]` (текущий лайв).

## Оговорки

Это разбор статистики, а не гарантия исхода. Маржа букмекера ~8%, выборки малы, лайв OpenDota может отставать.
