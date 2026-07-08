# CareerSignal HH

Локальный MVP для мониторинга открытых вакансий через официальный публичный
API HeadHunter. Приложение выполняет настроенные поиски, сохраняет вакансии в
SQLite, загружает подробности, рассчитывает прозрачный rule-based score,
создаёт автономные HTML/CSV/JSONL-экспорты и предоставляет локальный web UI
для daily workflow, очереди и настройки.

Проект ориентирован на два стартовых направления:

- AI / Automation / Systems Integration;
- Bitrix24 / 1C / CRM / Business Analyst.

> **Состояние API на 7 июля 2026:** live-режим подтверждён для авторизованного
> приложения и manual user OAuth token. В текущем окружении рабочие сценарии:
> `auth-check`, live `GET /me`, live `GET /vacancies` и smoke search. Анонимный
> доступ к поиску вакансий по-прежнему не является базовым режимом, поэтому
> проект ориентирован на `application_token` или `user_oauth`. При ошибках
> авторизации поиск завершает run рано и выводит понятную диагностику, не
> повторяя заведомо запрещённые обращения.

## Ограничения

CareerSignal HH не отправляет отклики, не делает auto-apply и не меняет данные
на hh.ru. OAuth V2 в текущей реализации ограничен read-only sync: профиль
пользователя, список резюме и переговоры сохраняются локально в SQLite без
скрытых side effects. В проекте нет парсинга страниц, браузерной автоматизации
откликов и фоновой очереди. Используются только endpoint'ы `https://api.hh.ru`;
локальный UI поднимает FastAPI только на машине пользователя.

`apply-assist` не нарушает это правило: команда только проверяет readiness,
логирует audit trail и может открыть vacancy URL в браузере после явного
`--approve`. Отправка отклика и фиксация `review apply` всегда остаются ручными.

## Текущее состояние

На 8 июля 2026 проект находится в состоянии **Phase 1 complete**:

- online-first baseline стабилизирован;
- Tail-0 и Epics A-H завершены;
- полный daily loop `search -> queue -> briefing -> apply-pack -> apply-assist -> manual apply`
  уже существует;
- `managed OAuth V2` реализован как additive read-only sync слой;
- локальный web UI и cockpit являются рабочей операционной поверхностью.

Короткий статус зафиксирован в:

- [docs/CURRENT_STATE_2026-07-08.md](C:/Dev/career-signal-hh/docs/CURRENT_STATE_2026-07-08.md)
- [docs/PHASE2_ROADMAP_2026-07-08.md](C:/Dev/career-signal-hh/docs/PHASE2_ROADMAP_2026-07-08.md)

Следующая реализационная волна должна идти не в ещё один "долгий хвост", а в
productization и operator maturity:

- Epic I — release hardening;
- Epic J — desktop packaging;
- Epic K — operator control plane in UI;
- Epic L — sync maturity.

## Установка

Требуется Python 3.11+.

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

В WSL/Linux активация окружения:

```bash
source .venv/bin/activate
```

Настройки `.env`:

```dotenv
HH_AUTH_MODE=application_token
HH_APP_ACCESS_TOKEN=
HH_USER_ACCESS_TOKEN=
HH_CLIENT_ID=
HH_CLIENT_SECRET=
HH_REDIRECT_URI=
HH_OAUTH_SCOPE=
HH_OAUTH_STORAGE=keyring
HH_USER_AGENT=IuriiVacancyMarketAnalytics/0.1 (your_email@example.com)
DB_PATH=data/vacancies.sqlite
HH_DELAY_MIN_SECONDS=0.7
HH_DELAY_MAX_SECONDS=1.5
HH_COOLDOWN_ON_429_SECONDS=120
HH_STOP_ON_429=true
HH_DETAIL_REFRESH_DAYS=7
```

Для `User-Agent` нужно указать уникальное название и реальный контакт или URL
проекта. Placeholder-адреса вроде `your-email@example.com` HH отклоняет как
`bad_user_agent/blacklisted`. При такой ошибке приложение завершает поиск после
первого запроса. Дополнительных runtime-зависимостей сверх заданных нет.
`pytest` включён в `requirements.txt` для простого локального MVP.

Режимы авторизации:

- `none` — не отправлять заголовок `Authorization`;
- `application_token` — отправлять `Bearer` token из `HH_APP_ACCESS_TOKEN`;
- `user_oauth` — отправлять `Bearer` token из `HH_USER_ACCESS_TOKEN`.

При `application_token` с пустым `HH_APP_ACCESS_TOKEN` приложение не падает
при импорте, но API-команды завершаются понятной конфигурационной ошибкой.
То же правило действует для `user_oauth` и `HH_USER_ACCESS_TOKEN`.

Managed OAuth V2 использует отдельные env-настройки `HH_CLIENT_ID`,
`HH_CLIENT_SECRET`, `HH_REDIRECT_URI` и secure local storage через
`HH_OAUTH_STORAGE=keyring`. Access/refresh токены не пишутся в `.env`;
manual `HH_USER_ACCESS_TOKEN` остаётся рабочим fallback для read-only sync.

## Guided Workflow (Wizard)

Вместо запоминания команд запустите мастер:

```powershell
python -m src.main wizard
```

Мастер показывает интерактивное меню с 7 опциями и проводит по шагам.

### Подкоманды

| Команда                              | Описание                                              |
|--------------------------------------|-------------------------------------------------------|
| `wizard`                             | Интерактивное меню (выбор 1–7)                       |
| `wizard first-run`                   | Проверка .env, токена, миграций, пресетов            |
| `wizard daily`                       | Health → backup → search → cockpit → review          |
| `wizard improve`                     | Quality → calibrate → suggest → validate             |
| `wizard apply`                       | Queue → explain → briefing → apply-pack → review set |

### Plan mode (неинтерактивный)

Все подкоманды поддерживают `--plan` — печатают план без выполнения:

```powershell
python -m src.main wizard daily --plan
python -m src.main wizard first-run --plan
python -m src.main wizard improve --plan
python -m src.main wizard apply --plan
```

### Wizard гарантии

- **Никогда не запускает deep mode** (только smoke/normal).
- **Не отправляет отклики** — wizard только генерирует briefing/apply-pack локально.
- **Не печатает токены** — только показывает «set» / «not set».
- **Опасные действия требуют подтверждения** (backup, search — Confirm.ask).
- **`--yes` пропускает подтверждения** для автоматизации.

## Search Intelligence Lab

Анализируйте и оптимизируйте поисковые запросы:

```powershell
python -m src.main search-lab terms --preset crm_systems_analyst_remote
python -m src.main search-lab suggest-terms --preset crm_systems_analyst_remote
python -m src.main search-lab compare --preset-a crm_systems_analyst_remote --preset-b integration_analyst_remote
python -m src.main search-lab dry-plan --preset no_code_automation_remote
python -m src.main search-lab export
```

### Команды

| Команда           | Описание                                                      |
|-------------------|--------------------------------------------------------------|
| `terms`           | Статистика по каждому search_term: avg score, strong, noise |
| `suggest-terms`   | Предлагает новые термины на основе high-score вакансий      |
| `compare`         | Сравнивает два пресета: overlap, keywords, employers        |
| `dry-plan`        | Оценка API-запросов без реального поиска                     |
| `export`          | Экспорт: search_lab_report.html + search_terms.csv + json   |

### Рекомендации

- **KEEP** — термин даёт много strong match и хороших исходов
- **REFINE** — низкий avg score или высокий found/loaded разрыв
- **REMOVE** — нет результатов или высокая доля rejected

## Scoring V3 — Confidence & Safe Matching

### Безопасный matching

Короткие ключевые слова (≤3 символов) — `ai`, `api`, `crm`, `qa` — проверяются
только как **целые токены**, а не подстроки:

```
"ai" in "detail"  → NO  (false positive prevented)
"ai" in "ai engineer" → YES (whole token)
"api" in "fastapi" → NO
"api" in "api integration" → YES
```

### Confidence & Noise

Каждая вакансия получает:

| Параметр      | Диапазон | Описание                                                |
|---------------|----------|--------------------------------------------------------|
| `confidence`  | 0–100    | Насколько уверенно мы считаем этот match хорошим       |
| `noise`       | 0–100    | Уровень шума: excludes, penalties, missing data        |
| `quality_flags` | list   | Метки: title_match, skills_match, missing_salary и др. |

### Decision logic

- `total_score` + `confidence` + `noise` = `decision`
- Высокий score но низкий confidence → `review_later` (не `strong_match`)
- Много excludes → увеличивает noise → снижает adjusted score
- Title+skills match → boost confidence на +35

### HTML фильтры

- **Скрыть low confidence** — скрывает вакансии с confidence < 40%
- **Скрыть high noise** — скрывает вакансии с noise > 50%

## Campaigns (Multi-Candidate)

Поддержка нескольких кампаний поиска в одной БД:

```powershell
python -m src.main campaigns list
python -m src.main campaigns show iurii_ai
python -m src.main campaigns daily iurii_ai --skip-search  # dry-run
python -m src.main campaigns queue iurii_bitrix
python -m src.main campaigns apply-pack iurii_ai --top 5
```

### config/campaigns.yaml

```yaml
campaigns:
  iurii_ai:
    enabled: true
    candidate_profile: ai       # references candidate.yaml profiles.ai
    presets:
      - ai_rag_remote
      - no_code_automation_remote
    default_lang: ru
    min_score: 70
    apply_template: ai_rag_remote
```

### Как работает

- `campaigns daily` — запускает autopilot для каждого пресета кампании
- `campaigns queue` — показывает очередь с min_score кампании
- `campaigns apply-pack` — использует candidate_profile кампании
- Без `campaigns.yaml` все существующие команды работают как раньше

## Безопасные режимы поиска (Safe Search Modes)

CareerSignal HH поддерживает три режима поиска для защиты API HH от избыточной
нагрузки и предотвращения блокировок.

### Режимы

| Режим   | max_pages | per_page | max_requests | max_details | Профили       | Подтверждение |
|---------|-----------|----------|-------------|------------|--------------|--------------|
| smoke   | 1         | 10       | 50          | 25         | Один (первый enabled) | Нет          |
| normal  | 2         | 25       | 250         | 150        | Все enabled  | Нет (если estimate ≤ budget) |
| deep    | 3*        | 50*      | 800         | 500        | Все enabled  | Да           |

\* Можно переопределить через `--max-pages` и `--per-page`. Бюджет при этом
не меняется и ограничивает прогон независимо от переопределений.

### Rate limiting

Перед каждым API-запросом приложение делает случайную паузу между
`HH_DELAY_MIN_SECONDS` и `HH_DELAY_MAX_SECONDS` (по умолчанию 0.7–1.5 сек).

При получении HTTP 429 (Too Many Requests):
- Если `HH_STOP_ON_429=true` (по умолчанию) — прогон останавливается,
  результаты сохраняются;
- Если `HH_STOP_ON_429=false` — ожидание `HH_COOLDOWN_ON_429_SECONDS` (120 сек)
  и одна повторная попытка. При повторном 429 — остановка.

### Request budget

Глобальный счётчик запросов ограничивает:
- `max_requests_per_run` — общее число API-запросов;
- `max_detail_fetches_per_run` — число запросов к `/vacancies/{id}`.

При превышении лимита поиск останавливается, выводится сообщение:
"Request budget reached. Partial results were saved."

### Smart detail fetching

Детальные данные вакансии (`/vacancies/{id}`) не запрашиваются, если:
- Вакансия уже есть в базе и `description_text` не пустой;
- `last_seen_at` новее `HH_DETAIL_REFRESH_DAYS` (по умолчанию 7 дней).

Детали запрашиваются если:
- Вакансия новая;
- `description_text` пустой;
- `last_seen_at` старше порога обновления.

Флаг `--force-details` принудительно обновляет детали, но в пределах budget.

### Run estimate

Перед запуском поиска выводится таблица:
- выбранные профили;
- количество запросов × областей;
- max_pages, per_page;
- оценочное число search-запросов;
- текущий budget;
- режим авторизации и rate limiting.

Для deep mode требуется явное подтверждение в консоли.

### Dry-run

```powershell
python -m src.main search --dry-run --mode smoke
```

Показывает estimate без выполнения сетевых запросов.

## Запуск

Рекомендуемый первый запуск без доступа к HH API:

```powershell
python -m src.main doctor
python -m src.main profiles
python -m src.main sample-export
python -m src.main export
```

`doctor` локально проверяет Python, файлы конфигурации, YAML, каталоги,
настройки авторизации, SQLite, rate limiting и основные импорты. Сетевых
запросов он не делает.

`profiles` показывает включённые поисковые профили, число запросов и регионов,
параметры schedule/experience и preview первых трёх запросов.

`sample-export` идемпотентно добавляет шесть демонстрационных вакансий в
настроенную SQLite-базу, рассчитывает scoring и создаёт HTML/CSV/JSONL. Это
позволяет проверить отчёт до одобрения доступа к HH API.

Показать запросы без обращения к API:

```powershell
python -m src.main search --dry-run
```

### Рекомендации по безопасному использованию

## Local UI

CareerSignal HH включает локальный веб-интерфейс для работы через браузер.

### Запуск

```powershell
python -m src.main ui --open-browser
```

Опции:

```
--host HOST         Bind address (default: 127.0.0.1)
--port PORT         Bind port (default: 8765)
--open-browser      Open browser automatically
--allow-lan         Allow binding to non-localhost addresses
--debug             Enable debug logging
```

### Безопасность

- UI слушает только 127.0.0.1 (localhost) по умолчанию.
- Для привязки к другим адресам требуется флаг `--allow-lan`.
- Токены **никогда не показываются** в UI.
- UI **не отправляет отклики** — все операции read-only или запускают
  существующие CLI-команды.
- CLI остаётся полностью доступным и независимым от UI.

### Первая страница

После открытия `http://127.0.0.1:8765` отображается Dashboard со:

- статусом базы данных и health check;
- счётчиками: всего вакансий, новых за 24h, pending queue, strong matches;
- статусами applied/interview/offer;
- последним search run, backup, export;
- pipeline counters: sourced, scored, shortlisted, briefed, drafted, applied, interview, offer;
- queue health: missing briefing, interesting without draft, follow-up due, risky queue, outbox pending/failed;
- risk buckets, preset performance и recent activity из `vacancy_events`;
- action context по strong matches без briefing и follow-up due вакансиям;
- кнопками действий: Health Check, Daily Autopilot, Review Queue,
  Export Cockpit, Generate Analytics, Settings.

### Технический стек

- Backend: FastAPI + Uvicorn
- Frontend: Server-rendered HTML (Jinja2) + vanilla JS + CSS
- Никаких CDN, React/Vite/Tauri — всё локально

### Job Manager и долгие операции

Долгие операции (autopilot, search, export, quality, calibration, apply-pack)
запускаются как фоновые jobs и не блокируют UI. На dashboard отображается
Active Job card с progress bar (0-100%), статусом и сообщением.
UI опрашивает статус каждые 2 секунды. Кнопка Cancel позволяет прервать
задачу. Только одна тяжёлая задача может выполняться одновременно.
Deep mode недоступен из UI для безопасности.

#### Review Queue UI

Страница  — основной интерфейс для ежедневной работы с вакансиями.

### Возможности

- Фильтры: min score, decision, review status, preset, remote/salary/risk/new/dedupe.
- Карточки вакансий с score circle, decision badge, keywords preview, risk flags.
- Кнопки статуса: Interesting, Maybe, Reject, Archive — одним кликом.
- Mark Applied — ручная отметка отклика с датой.
- Apply Pack — генерация cover letter для конкретной вакансии.
- Detail drawer — полное описание, keywords, заметки, действия.
- Inline note editor с сохранением.
- Bulk actions: Archive auto_hide, Reject score<35, Interesting 85+ — с confirmation modal.
- Защита applied/interview/offer от случайной перезаписи (force checkbox).

### Безопасность

- Нет кнопки «автоматический отклик».
- Mark Applied только фиксирует факт ручного отклика.
- Bulk действия требуют confirm=true и показывают confirmation modal.
- Токены не показываются в ответах API.

### Job endpoints

POST /api/jobs/autopilot-daily   - autopilot
POST /api/jobs/search-smoke      - smoke search
POST /api/jobs/export-all        - полный экспорт
POST /api/jobs/quality-cluster   - анализ качества
POST /api/jobs/calibrate-suggest - calibration
POST /api/jobs/apply-pack-top    - apply packs
GET  /api/jobs                   - список jobs
GET  /api/jobs/{id}              - статус job
POST /api/jobs/{id}/cancel       - отмена

## Universal Search Presets

CareerSignal HH поддерживает универсальные поисковые пресеты через
`config/search_presets.yaml`. Пресеты заменяют старые жёстко заданные профили
(`ai_automation`, `bitrix_1c`) и позволяют создавать произвольные поиски
без редактирования кода.

Текущая рабочая матрица поиска:

- `crm_systems_analyst_remote` — основной P0 пресет под CRM / systems analyst.
- `bitrix24_crm_remote` — Bitrix24 / CRM implementation и integration fit.
- `integration_analyst_remote` — API / webhook / CRM / 1C integration analyst.
- `one_c_integration_analyst_remote` — 1C / ERP / CRM интеграции без бухгалтерского шума.
- `no_code_automation_remote` — n8n / Make / low-code automation с CRM-контекстом.
- `ai_rag_remote` — только AI automation роли, где есть явный CRM/API/no-code сигнал.

### Отличия от legacy profiles

| Характеристика | Legacy profiles | Universal presets |
|---------------|----------------|-------------------|
| Конфиг | `config/search_profiles.yaml` + `scoring_rules.yaml` | `config/search_presets.yaml` |
| Страны | Заданы явно (area IDs) | `areas: []` = все страны |
| Remote | Опционально | По умолчанию `remote_only: true` |
| Scoring | Ключевые слова с весами | include/exclude/boost/penalties |
| Ad-hoc | Нет | `--adhoc --include "..." --exclude "..."` |
| Исключения | Хардкод в scoring_rules | Пользователь задаёт в YAML или CLI |

### Просмотр пресетов

```powershell
python -m src.main presets list
python -m src.main presets show crm_systems_analyst_remote
```

### Управление пресетами

```powershell
# Создать новый пресет
python -m src.main presets create my-preset --terms "Python,AI,LLM" --include "python,ai,llm" --exclude "qa,gambling"

# Клонировать
python -m src.main presets clone crm_systems_analyst_remote my-copy

# Добавить/удалить поисковый термин
python -m src.main presets add-term my-preset "RAG Engineer"
python -m src.main presets remove-term my-preset "Python"

# Добавить include/exclude ключевые слова
python -m src.main presets add-include my-preset "fastapi"
python -m src.main presets add-exclude my-preset "onsite"

# Включить/выключить
python -m src.main presets disable my-preset
python -m src.main presets enable my-preset

# Сохранить adhoc поиск как пресет
python -m src.main presets save-adhoc my-preset --include "RAG,LLM,Python" --exclude "QA,casino"

# Проверить конфигурацию
python -m src.main presets validate
```

Все операции создают бэкап в `config/backups/search_presets_*.yaml`.
Операции идемпотентны: повторное добавление не дублирует записи.

### Поиск по пресету

```powershell
python -m src.main search --preset crm_systems_analyst_remote --mode smoke
python -m src.main search --preset integration_analyst_remote --mode normal
```

По умолчанию (без --preset/--profile/--adhoc):
- **smoke** — только первый enabled preset
- **normal** — все enabled presets
- **deep** — все enabled presets, с подтверждением

Каждая вакансия скорится тем пресетом, по которому была найдена.
`best_profile` в scores равен имени пресета (например, `ai_rag_remote`).
`source_profile` используется для хранения идентификатора пресета.

### Ad-hoc поиск

```powershell
python -m src.main search --adhoc \
  --include "RAG,LLM,Python" \
  --exclude "QA,casino,onsite only" \
  --remote-only \
  --mode smoke
```

Ad-hoc создаёт временный пресет: include-ключевые слова становятся
поисковыми запросами и критериями include.any. exclude-ключевые слова
становятся exclude.any.

### По умолчанию

- `areas: []` означает **без ограничения страны** (area не отправляется в HH API).
- `remote_only: true` по умолчанию — ищутся только remote-вакансии.
- Исключения задаёт **пользователь**, а не код.
- Все страны и языки имеют равный приоритет.
- Зарплата даёт бонус к score, но не является обязательным фильтром.

### Legacy-профили продолжают работать

```powershell
python -m src.main search --profile ai_automation
python -m src.main profiles
```

Если `search_presets.yaml` отсутствует, поиск автоматически переключается
на старые профили из `search_profiles.yaml`.

### Рекомендации по безопасному использованию

**First real run:**

```powershell
python -m src.main search --mode smoke
python -m src.main top
python -m src.main export
```

**Normal daily run:**

```powershell
python -m src.main search --mode normal
python -m src.main review list --status new --min-score 70
python -m src.main export
```

**Deep run (использовать редко, с осторожностью):**

```powershell
python -m src.main search --mode deep --max-pages 3 --per-page 50
```

### Предупреждения

- **Не запускайте deep часто.** Это создаёт значительную нагрузку на API HH.
- **При 429 остановитесь и подождите.** Не уменьшайте задержки без необходимости.
- **Не коммитьте токены.** `.env` в `.gitignore`. Если токен попал в GitHub —
  перевыпустите его в кабинете HH.
- **Не уменьшайте `HH_DELAY_MIN_SECONDS` и `HH_DELAY_MAX_SECONDS`** ниже 0.5
  без явной необходимости. Это может привести к блокировке.

### Рабочий цикл

Первый поиск (для быстрой проверки лучше начать с одного профиля и страницы):

```powershell
python -m src.main search --profile ai_automation --max-pages 1 --per-page 20
```

Полный настроенный поиск и просмотр результатов:

```powershell
python -m src.main search
python -m src.main top
python -m src.main stats
python -m src.main export
python -m src.main auth-check
python -m src.main doctor
python -m src.main profiles
python -m src.main sample-export
```

Экспорт можно фильтровать:

```powershell
python -m src.main export --min-score 35 --profile ai_automation --days 14
```

Файлы создаются в:

- `exports/vacancies_report.html` — автономный тёмный отчёт с фильтрами;
- `exports/vacancies.csv` — таблица для ручного трекера;
- `exports/vacancies.jsonl` — нормализованные данные и scoring;
- `exports/briefings/` — 7-блочные vacancy briefings и batch index;
- `exports/apply_packs/` — cover letter packs и batch index;
- `data/vacancies.sqlite` — рабочая база;
- `data/sample_vacancies.sqlite` — база для sample-export;
- `backups/vacancies_YYYYMMDD_HHMMSS.sqlite` — бэкапы.

## Quality checks

```powershell
# Smoke test
python scripts/smoke_check.ps1  # Windows
bash scripts/smoke_check.sh      # Linux/Mac

# Lint
python -m ruff check src/

# Version
python -m src.main version

# Release checklist: RELEASE_CHECKLIST.md
```

## Data quality persistence

Duplicate detection and employer aliases are persisted in SQLite
(tables `vacancy_clusters`, `employer_aliases`).

```powershell
# Find and display duplicates
python -m src.main quality duplicates

# Save clusters + employer aliases to SQLite
python -m src.main quality cluster

# Full quality report (reads from DB if clusters are saved)
python -m src.main quality report

# Export CSVs and HTML report
python -m src.main quality export
```

Clusters are used by:

- **Review queue** `--dedupe` — показывает только лучшую вакансию
  из каждого кластера:
  ```powershell
  python -m src.main review queue --dedupe --min-score 70
  ```
- **HTML export** — добавляет `data-cluster` атрибут и чекбокс
  «Hide duplicates» в фильтры.
- **Cockpit** — показывает counts кластеров и employer aliases
  в секции Data Quality.

Re-run `quality cluster` при изменении данных — таблицы полностью
перезаписываются (идемпотентно).

## Поисковые профили

Запросы, регионы и параметры находятся в
`config/search_profiles.yaml`. Можно добавлять запросы, ID регионов и новые
профили без изменения клиента. Если отдельный регион не даёт результатов или
API отклоняет запрос, остальные поиски продолжатся.

Актуальные ID регионов можно проверить:

```powershell
python -c "from src.hh_client import HHClient; import os, json; from dotenv import load_dotenv; load_dotenv(); print(json.dumps(HHClient(os.getenv('HH_USER_AGENT','CareerSignalHH/0.1')).get_areas(), ensure_ascii=False, indent=2))"
```

Это вызывает публичный endpoint `GET /areas`. Справочники также доступны через
методы `get_dictionaries()` и `get_professional_roles()` класса `HHClient`.

Параметры `schedule` и `experience` отправляются как повторяющиеся query
parameters. Их допустимые значения следует сверять с `GET /dictionaries`.

## Apply Pack: подготовка к ручному отклику

Генерирует Markdown и HTML файлы с полным разбором вакансии,
fit analysis, рисками, чеклистом и cover letter через rule-based letter engine.
**Не отправляет отклики.** Только готовит материалы.

Letter engine:
- собирает письмо из vacancy-specific сигналов, matched keywords и candidate profile;
- добавляет AI case только для AI/LLM/n8n/Make вакансий;
- прогоняет deterministic validator до export/save-review;
- слабые письма не экспортируются и не сохраняются в review.

Шаблоны: `config/apply_templates.yaml` — preset-specific blueprints
с поддержкой short/medium/detailed стилей и ru/en языков.
Fallback: preset → default → builtin.

## Vacancy briefing

Standalone `briefing` использует уже сохранённые `vacancy + score_details + review`
и генерирует стабильный 7-блочный анализ для ручного решения по вакансии.

```powershell
# Для одной вакансии
python -m src.main briefing 123456789
python -m src.main briefing 123456789 --format json

# Для очереди
python -m src.main briefing --top 5 --decision strong_match --save-review
python -m src.main briefing --top 10 --min-score 70 --remote-only --format html
```

7 блоков briefing:
- **Vacancy Snapshot** — компания, роль, salary/schedule/employment, published
- **Score Verdict** — total, decision, confidence, noise, decision logic
- **Match Evidence** — matched keywords и score anchors
- **Gaps And Objections** — excluded keywords и честные interview phrases
- **Risk And Checks** — salary/remote/risk flags
- **Recruiter Questions** — вопросы для уточнения до отклика
- **Recommended Action** — apply / clarify / low priority

Сохранение и артефакты:
- `--save-review` сохраняет briefing в таблицу `briefing_reports` как отдельный артефакт;
- при сохранении briefing пишется событие `briefing_saved` и pending-запись в `integration_outbox`;
- файлы пишутся в `exports/briefings/<id>_<slug>.md|.html|.json`;
- для batch-режима создаётся `exports/briefings/index.html`;
- основной `export` подхватывает ссылки на briefing/apply-pack, если HTML-артефакты уже созданы.

```powershell
# Для одной вакансии (medium style по умолчанию)
python -m src.main apply-pack 123456789
python -m src.main apply-pack 123456789 --lang en --style short

# С явным шаблоном
python -m src.main apply-pack 123456789 --template ai_rag_remote --style detailed

# Для топ-10 strong_match вакансий
python -m src.main apply-pack --top 10 --decision strong_match --style medium
python -m src.main apply-pack --preset ai_rag_remote --limit 5

# С сохранением черновика в review
python -m src.main apply-pack 123456789 --save-review
python -m src.main apply-pack 123456789 --save-review --overwrite

# Показать validator diagnostics
python -m src.main apply-pack 123456789 --diagnostics
```

Секции apply-pack:
- **Vacancy + Score** — базовая информация и scoring
- **Fit Analysis** — verdict, why it fits, concerns, strategy
- **Questions to Ask** — вопросы рекрутеру
- **Contract / Remote Checks** — чеклист проверок
- **Risk Check** — excluded keywords и риски
- **Application Checklist** — пошаговый план отклика
- **Cover Letter Draft** — сгенерированный по шаблону

Draft management:
```powershell
# Посмотреть сохранённый черновик
python -m src.main review draft 123456789

# Очистить черновик
python -m src.main review clear-draft 123456789 --yes
```

Validator gate для письма:
- обязателен `company` и `vacancy title` в тексте;
- письмо должно быть коротким и стиль-зависимым по длине;
- минимум 2 vacancy anchors: matched keywords / key skills / title terms;
- запрещены generic фразы, markdown bullets и banned terms из `candidate.yaml`;
- AI Lead Intake блок обязателен только для AI-trigger вакансий и запрещён вне их.

Файлы создаются в `exports/apply_packs/<id>_<slug>.md` и `.html`.
При `--top`/`--limit` дополнительно создаётся `index.html`.

## Controlled Apply Assist

`apply-assist` отделяет draft readiness от реального ручного handoff в HH.

```powershell
# Проверка readiness без handoff
python -m src.main apply-assist 123456789

# Явный handoff в браузер после approve
python -m src.main apply-assist 123456789 --approve --open-browser
```

Граница намеренно жёсткая:
- `briefing` = аналитический контекст
- `apply-pack` = сохранённый draft и артефакты
- `apply-assist` = gating + operator handoff
- `review apply` = отдельная ручная фиксация уже выполненного отклика

Assist gates:
- `score >= 85`
- `confidence >= 60`
- `noise <= 35`
- `review.status == interesting`
- briefing уже сохранён
- draft уже сохранён
- letter validator проходит повторную проверку
- нет hard red flags в title/description
- есть `alternate_url` для ручного перехода

Что команда делает:
- печатает pass/block по каждому gate
- пишет `apply_assist_*` события в `vacancy_events`
- при `--approve --open-browser` открывает HH vacancy URL
- подсказывает точную команду `review apply`

Что команда не делает:
- не отправляет отклик
- не копирует письмо в буфер молча
- не открывает браузер без `--approve`
- не делает bulk assist
- не меняет статус на `applied` автоматически

## Daily review queue

Удобная очередь для ручного отбора лучших кандидатов.

```powershell
# Топ-15 новых сильных совпадений
python -m src.main review next-best

# Полная очередь с фильтрами
python -m src.main review queue --preset ai_rag_remote --limit 20
python -m src.main review queue --min-score 70 --decision strong_match,queue --new-only
python -m src.main review queue --remote-only --with-salary --limit 30

# Bulk-действия
python -m src.main review bulk-archive --decision auto_hide --yes
python -m src.main review bulk-reject --max-score 35 --yes
python -m src.main review bulk-interesting --min-score 85 --decision strong_match --yes
python -m src.main review bulk-set --new-status maybe --min-score 60 --max-score 69 --yes
```

Protected statuses (`applied`, `interview`, `offer`) не перезаписываются
без `--force`. Summary показывает matched/updated/skipped_protected.

## Daily autopilot

Одна команда для всей ежедневной рутины.
**Не фоновый сервис, не автоотклик.** Локальный CLI-оркестратор.

```powershell
# Полный daily цикл
python -m src.main autopilot daily --backup-first

# Только статус
python -m src.main autopilot status

# Быстрый прогон с конкретным пресетом
python -m src.main autopilot daily --preset ai_rag_remote --mode smoke --yes

# Dry-run: проверить конфигурацию без поиска
python -m src.main autopilot daily --skip-search --skip-auth-check
```

Safety:
- Deep mode запрещён без `--allow-deep`
- Doctor и auth check останавливают прогон при ошибках
- 429 останавливает поиск с сохранением результатов
- Токен никогда не выводится

Рекомендуемый workflow:
```powershell
python -m src.main autopilot daily --backup-first
python -m src.main review next-best
python -m src.main review set VACANCY_ID --status interesting
python -m src.main briefing VACANCY_ID --save-review
python -m src.main apply-pack VACANCY_ID --save-review
python -m src.main apply-assist VACANCY_ID --approve --open-browser
python -m src.main review apply VACANCY_ID --date today
```

## Cockpit (Daily Action Center)

Read-only HTML dashboard — «Что мне сделать сегодня?»

```powershell
# Сгенерировать cockpit
python -m src.main cockpit export
# → exports/cockpit.html

# Открыть в браузере
python -m src.main cockpit open
```

Секции cockpit:
- **Today's Action Plan** — приоритезированные карточки действий
  (autopilot, review next-best, apply-pack, bulk-archive, backup,
  dedupe queue, calibration) с reason и copy-paste командами.
- **Today's Queue** — таблица с score, decision, keywords, risks,
  cluster badge, apply-pack link, copyable review commands.
- **Pipeline** — sourced → scored → shortlisted → briefed → drafted → applied/interview/offer.
- **Queue Health** — pending new, strong new, missing briefing,
  interesting without draft, follow-up due, risky queue, outbox pending/failed.
- **Preset Performance** — эффективность пресетов.
- **Risk Buckets** — operational risk groups на основе `risk_flags_json`
  и `quality_flags_json` для текущей очереди.
- **Review Funnel** — воронка статусов.
- **Briefing & Sync** — coverage по `briefing_reports` и состояние `integration_outbox`.
- **Action Context** — top actionable vacancies: strong matches без briefing
  и applied/interview без следующего шага.
- **Generated Files** — статус всех export-файлов с датами
  и командами для регенерации.
- **Latest Search Runs** — последние 5 поисковых запусков.
- **Recent Activity** — последние события из `vacancy_events`.
- **Data Quality** — кластеры, дубликаты, aliases.

Без внешних зависимостей — весь CSS и JS инлайн, не требует
сервера, открывается из file://.

## Market analytics

Анализ рынка вакансий: навыки, работодатели, зарплаты, пресеты, воронка откликов.

```powershell
# Сводка
python -m src.main analytics summary

# Топ навыков с группировкой по пресетам
python -m src.main analytics skills

# Топ работодателей
python -m src.main analytics employers

# Зарплатная аналитика
python -m src.main analytics salary

# Эффективность пресетов
python -m src.main analytics presets

# Воронка откликов
python -m src.main analytics funnel

# Экспорт всех отчётов
python -m src.main analytics export
# → exports/analytics_report.html
# → exports/analytics_summary.json
# → exports/analytics_skills.csv
# → exports/analytics_employers.csv
```

## Calibration loop

Анализ review-данных для улучшения presets без ML.

Analyze:
- keywords по полям (title/skills/description/snippet/excluded);
- preset performance (good/bad rate);
- score bucket quality (0-24, 25-49, 50-69, 70-84, 85-100);
- search term / query performance.

```powershell
# Полный анализ
python -m src.main calibrate analyze

# Сгенерировать предложения (с дедупликацией)
python -m src.main calibrate suggest --preset ai_rag_remote

# Применить предложение (с бэкапом YAML и diff-like выводом)
python -m src.main calibrate apply --suggestion-id abc123 --yes

# Отклонить предложение
python -m src.main calibrate dismiss --suggestion-id abc123

# Экспорт отчёта (JSON + CSV + HTML с keyword lift table)
python -m src.main calibrate export
```

Suggestion types:
- `add_exclude` / `add_title_exclude` — убрать шумный keyword;
- `add_boost` / `add_penalty` — усилить или ослабить keyword;
- `add_title_include` — добавить keyword в include.title;
- `remove_search_term` — удалить неэффективный поисковый запрос;
- `lower_search_term_priority` — понизить приоритет запроса.

Статусы: `pending` → `applied` (после apply) или `dismissed`.
Дубликаты (preset + type + keyword + pending/applied) автоматически
пропускаются при suggest.

Рекомендуемый workflow:
```powershell
python -m src.main review bulk-reject --max-score 35 --yes
python -m src.main calibrate analyze
python -m src.main calibrate suggest --preset ai_rag_remote
python -m src.main calibrate export
```

Не применяет изменения автоматически — всегда требует `--yes`.
Бэкап YAML сохраняется в `config/backups/` перед каждым apply.

## Scoring v2 (explainable)

Новый scoring с полевыми весами, отслеживанием ключевых слов и decision labels.
Работает с universal presets и сохраняет детали в таблицу `score_details`.

### Field weights

| Поле | Вес |
|------|-----|
| title | 3.0× |
| skills | 2.0× |
| snippet | 1.5× |
| description | 1.0× |
| employer | 0.5× |

### Decision labels

| Label | Threshold |
|-------|----------|
| strong_match | ≥ 85 |
| queue | ≥ 70 |
| review_later | ≥ 50 |
| weak_match | ≥ 25 |
| auto_hide | < 25 |

### Категории score

- **include** — совпадения include.any/all/title с полевыми весами
- **boost** — явные boost из preset.boost.{title,skills,description}
- **exclude** — штрафы за exclude.any/title
- **penalties** — кастомные штрафы из preset.penalties
- **salary** — бонус за наличие зарплаты (+5), валюту USD/EUR (+2), высокую сумму (+1-3)
- **remote** — +10 за remote, +5 за hybrid, -5 за onsite/unknown
- **freshness** — 0-10 за свежесть

### Команды

```powershell
# Объяснить score вакансии
python -m src.main score explain VACANCY_ID

# Пересчитать score для существующих вакансий
python -m src.main score rescore --preset ai_rag_remote --limit 100
python -m src.main score rescore --limit 50
```

## Правила scoring (legacy)

`config/scoring_rules.yaml` содержит ключевые слова, веса и негативные флаги.
Профильный score ограничен диапазоном 0–90, затем к лучшему профилю добавляется
до 10 баллов за свежесть. Риски уменьшают оба профильных score. Итог всегда
находится в диапазоне 0–100.

Результат включает:

- `ai_automation_score` и `bitrix_1c_score`;
- `best_profile`: `ai_automation`, `bitrix_1c`, `mixed` или `low_match`;
- причины совпадения и risk flags;
- формат работы: remote, hybrid, relocation, onsite или unknown;
- нормализованные поля зарплаты.

Правила намеренно простые и объяснимые. На MVP-этапе LLM не используется.

## Устройство проекта

```
src/
  main.py              → тонкий entrypoint (5 строк)
  cli.py               → build_parser() + main()
  config.py            → SEARCH_MODES, _services(), _short_body()
  hh_client.py         → публичный HTTP API, budget, rate limiting
  storage.py           → SQLite, upsert, touch, detail_needed
  models.py            → Vacancy, ScoreResult (pydantic)
  scoring.py           → rule-based scoring
  search_profiles.py   → загрузка YAML-конфигов
  utils.py             → html_to_text, normalize, salary_to_str
  exporter_csv.py      → CSV + JSONL экспорт
  exporter_html.py     → автономный HTML-отчёт
  commands/
    auth.py            → auth-check
    db.py              → db info, migrate, integrity, backup, vacuum, optimize, purge-samples, cleanup-orphans
    doctor.py          → doctor
    export.py          → export
    notion_sync.py     → notion-sync status/push/dry-run/retry-failed/replay
    profiles.py        → profiles
    review.py          → review list/set/note/apply/next
    sample.py          → sample-export
    search.py          → search (с search-loop)
    stats.py           → top, stats
  services/
    notion_sync_service.py → webhook delivery, dry-run, retry-safe outbox push
    search_runner.py   → print_run_estimate, print_run_summary
    search_modes.py    → реэкспорт SEARCH_MODES
```

`src/hh_client.py` отвечает только за публичный HTTP API, `src/storage.py` —
за SQLite, idempotent upsert и event trail (`vacancy_events`, `integration_outbox`),
`src/scoring.py` — за правила, а экспортеры не зависят от сети. `first_seen_at`
при обновлении не перезаписывается; подробности и score пересчитываются.

Ключевые evented actions:

- `review set` / `review apply` / `review next` и bulk review actions пишут события в `vacancy_events`;
- сохранение draft через `apply-pack --save-review` пишет `review_draft_saved`;
- сохранение briefing пишет `briefing_saved`;
- интеграционно значимые события дополнительно кладутся в `integration_outbox`
  со статусом `pending` и target `external_sync`.

Одна ошибка запроса или вакансии записывается в `search_runs` и не останавливает
весь запуск.

## Notion / n8n outbox

Внешняя синхронизация идёт только через `integration_outbox`. Локальные review /
briefing действия не делают прямых webhook side effects.

Минимальный flow:

- storage пишет snapshot payload в `integration_outbox`;
- `python -m src.main notion-sync push` забирает pending rows oldest-first;
- webhook получает envelope с `delivery_key = cshh:<target>:<outbox_id>`;
- retry/replay используют тот же `delivery_key`, поэтому downstream может делать dedupe;
- при сетевой или HTTP-ошибке запись остаётся в локальной БД со статусом `failed`,
  счётчиком `attempts` и `last_error`.

Конфиг:

```yaml
# config/notion_sync.yaml
notion_sync:
  enabled: false
  provider: n8n_webhook
  target: external_sync
  webhook_url_env: JOB_TRACKER_WEBHOOK_URL
  webhook_secret_env: JOB_TRACKER_SECRET
  timeout_seconds: 10
  batch_size: 10
  verify_tls: true
```

```powershell
$env:JOB_TRACKER_WEBHOOK_URL = "https://n8n.example/webhook/job-tracker"
$env:JOB_TRACKER_SECRET = "replace-me"
```

Операторские команды:

```powershell
python -m src.main notion-sync status
python -m src.main notion-sync dry-run --limit 3
python -m src.main notion-sync push --limit 10
python -m src.main notion-sync retry-failed
python -m src.main notion-sync replay --outbox-id 42 --dry-run
python -m src.main notion-sync replay --outbox-id 42   # only for pending/failed
```

Как понять, что событие ушло или застряло:

- `status=sent` и `attempts >= 1` — webhook принял событие;
- `status=failed` + `last_error` — событие застряло и ждёт `retry-failed` или `replay`;
- `status=pending` — событие ещё не отправлялось;
- `notion-sync status` показывает totals, oldest pending/failed timestamps и последние записи.

## Данные: sample vs production

`sample-export` по умолчанию пишет в **отдельную базу** `data/sample_vacancies.sqlite`
и не загрязняет рабочую `data/vacancies.sqlite`.

```powershell
# По умолчанию → data/sample_vacancies.sqlite
python -m src.main sample-export

# Кастомный путь
python -m src.main sample-export --db data/custom_sample.sqlite
```

Если sample-вакансии ранее попали в рабочую базу, их можно удалить:

```powershell
python -m src.main db info              # проверить наличие sample-*
python -m src.main db purge-samples -y  # удалить без подтверждения
```

## Обслуживание базы данных

```powershell
# Информация о базе
python -m src.main db info

# Бэкап SQLite
python -m src.main db backup
# → backups/vacancies_YYYYMMDD_HHMMSS.sqlite

# Удаление sample-вакансий из рабочей базы
python -m src.main db purge-samples

# Миграции и целостность
python -m src.main db migrate        # применить ожидающие миграции
python -m src.main db integrity      # расширенная проверка целостности
python -m src.main db vacuum         # сжатие БД (с предварительным бэкапом)
python -m src.main db optimize       # оптимизация индексов
python -m src.main db cleanup-orphans  # удалить осиротевшие записи
```

### Миграции базы данных

Миграции управляются файлом `src/db_migrations.py`.
Каждая миграция имеет уникальный `version` и имя.
Миграции идемпотентны: повторный запуск `db migrate` безопасен и
пропустит уже применённые.

```powershell
python -m src.main db migrate
```

Команда выводит таблицу со статусом каждой миграции (`applied`,
`skipped`, `failed`) и код возврата:

- `0` — все миграции применены или пропущены (нет ошибок);
- `1` — есть failed-миграции.

Если миграция завершилась с `failed`:

1. Не удаляйте `data/vacancies.sqlite`.
2. Прочитайте сообщение об ошибке в столбце `Error` таблицы.
3. Устраните причину (например, конфликт схемы).
4. Запустите `db migrate` снова.

Неудачная миграция **не записывается** в `schema_migrations` —
система не считает её применённой, и при следующем запуске попробует
снова.

**Рекомендация**: перед `db migrate` делайте бэкап:

```powershell
python -m src.main db backup
python -m src.main db migrate
python -m src.main db integrity
```

### Расширенная проверка целостности

```powershell
python -m src.main db integrity
```

Проверяет:

- `PRAGMA integrity_check` — структурная целостность SQLite;
- Наличие таблицы `schema_migrations`;
- Текущую и ожидаемую версию схемы;
- Наличие колонки `work_format_flags_json` в `score_details`;
- Наличие обязательных индексов;
- Оценку необходимости `VACUUM` (свободные страницы);
- Количество orphan-записей, sample-вакансий, дубликатов URL,
  пропущенных scores/score_details/descriptions.

Рекомендуемый maintenance:

```powershell
python -m src.main db info
python -m src.main db backup
python -m src.main db purge-samples
```

## File maintenance (retention cleanup)

Управление старыми файлами: логи, бэкапы, exports, apply packs.
Политика хранения: `config/maintenance.yaml`.

```powershell
# Посмотреть отчёт — что подлежит удалению
python -m src.main maintenance report

# Dry-run (default) — показать, но не удалять
python -m src.main maintenance cleanup --dry-run

# Реальное удаление с подтверждением
python -m src.main maintenance cleanup --yes
```

Retention defaults:
- logs: 30 дней
- backups: 10 последних или 30 дней
- exports/vacancies_report.html: только текущий
- exports/briefings: 60 дней или 100 последних
- exports/apply_packs: 60 дней или 100 последних
- config/backups: 20 последних

Защищены от удаления:
- `data/*.sqlite`
- `.env`
- `data/calibration_suggestions.json`

Dry-run — безопасный default; `--yes` требуется для реального удаления.
Cleanup пишет maintenance log в `logs/`.

## Тесты

```powershell
python -m pytest
python -m src.main --help
python -m src.main search --dry-run --mode smoke
```

## OAuth V2 Read-Only Sync

Manual `user_oauth` bearer token mode остаётся как был: если в `.env` задан
`HH_USER_ACCESS_TOKEN`, существующий `HHClient` продолжает работать без
managed lifecycle. Новый V2-слой добавляет отдельные команды и secure storage,
не подменяя online-first search/export flow на app token.

Что поддерживается:

- `oauth status` — показать конфигурацию, наличие managed/manual токенов и metadata без печати секретов;
- `oauth login` — построить HH authorization URL и обменять `authorization_code` на локально сохранённые токены;
- `oauth refresh` — обновить managed access token через refresh token;
- `oauth revoke-local` — удалить managed access/refresh token из secure storage и очистить metadata;
- `hh-sync me` — read-only sync `/me`;
- `hh-sync resumes` — read-only sync `/resumes/mine`;
- `hh-sync negotiations` — read-only sync `/negotiations`;
- `hh-sync reconcile` — локальная сверка переговоров с уже сохранёнными HH vacancy id.

Что не поддерживается в этом epic:

- автоотклик, bulk apply, скрытая запись на hh.ru;
- управление резюме, отправка сообщений, изменение переговоров;
- неявный перенос manual токена из `.env` в managed storage.

Операторский сценарий:

```dotenv
HH_CLIENT_ID=
HH_CLIENT_SECRET=
HH_REDIRECT_URI=https://oauth.pstmn.io/v1/callback
HH_OAUTH_STORAGE=keyring
```

```powershell
python -m src.main oauth status
python -m src.main oauth login --open-browser
python -m src.main oauth login --code <authorization_code>
python -m src.main oauth refresh
python -m src.main hh-sync me
python -m src.main hh-sync resumes
python -m src.main hh-sync negotiations --status active
python -m src.main hh-sync reconcile
python -m src.main oauth revoke-local
```

Решение по хранению:

- managed access token и refresh token хранятся в OS keyring;
- в SQLite сохраняются только metadata и sync snapshots (`oauth_tokens_meta`, `hh_profiles`, `hh_resumes`, `hh_negotiations`);
- `oauth status` и все новые команды показывают только masked hints.

## Tail-0 Baseline: online-first workflow

Минимальный рабочий сценарий перед следующей волной разработки:

1. Подготовить окружение и токен:

   ```powershell
   Copy-Item .env.example .env
   ```

   ```dotenv
   HH_AUTH_MODE=application_token
   HH_APP_ACCESS_TOKEN=ваш_токен
   HH_USER_AGENT=CareerSignalHH/0.1 (real-email-or-url)
   ```

   Для manual OAuth пользователя:

   ```dotenv
   HH_AUTH_MODE=user_oauth
   HH_USER_ACCESS_TOKEN=ваш_oauth_токен
   ```

2. Проверить конфигурацию и live access:

   ```powershell
   python -m src.main doctor
   python -m src.main auth-check
   python -m src.main health
   ```

3. Прогнать минимальный online search cycle:

   ```powershell
   python -m src.main search --mode smoke
   python -m src.main top
   python -m src.main export
   ```

4. При необходимости открыть локальный UI:

   ```powershell
   python -m src.main ui
   ```

Это и есть текущий baseline online-first режима: live auth, smoke search,
локальное хранение, export и локальный web UI без автоотклика.

## Работа после одобрения заявки HH API

1. Откройте `https://dev.hh.ru/admin`.
2. Откройте приложение **Iurii Vacancy Market Analytics / CareerSignal HH**.
3. Сгенерируйте или посмотрите application access token.
4. Создайте `.env` из `.env.example`, если файл ещё не создан:

   ```powershell
   Copy-Item .env.example .env
   ```

5. Заполните параметры:

   ```dotenv
   HH_AUTH_MODE=application_token
   HH_APP_ACCESS_TOKEN=ваш_токен
   ```

   Или для OAuth пользователя:

   ```dotenv
   HH_AUTH_MODE=user_oauth
   HH_USER_ACCESS_TOKEN=ваш_oauth_токен
   ```

   Или для managed OAuth V2 read-only sync:

   ```dotenv
   HH_CLIENT_ID=ваш_client_id
   HH_CLIENT_SECRET=ваш_client_secret
   HH_REDIRECT_URI=https://oauth.pstmn.io/v1/callback
   HH_OAUTH_STORAGE=keyring
   ```

6. Проверьте доступ:

   ```powershell
   python -m src.main auth-check
   ```

   Команда показывает режим, наличие токена и User-Agent, затем проверяет
   `GET /me` и `GET /vacancies?text=python&per_page=1`. Сам токен не выводится.

   Для managed OAuth V2:

   ```powershell
   python -m src.main oauth status
   python -m src.main oauth login --open-browser
   python -m src.main oauth login --code <authorization_code>
   python -m src.main hh-sync me
   ```

7. Запустите рабочий цикл:

   ```powershell
   python -m src.main search --mode smoke
   python -m src.main top
   python -m src.main export
   ```

Не коммитьте `.env` и не вставляйте токен в README, issues, commits или
скриншоты. Если токен случайно попал в GitHub, перевыпустите его в кабинете HH.

## Manual review workflow

Вакансии можно локально сортировать по статусам, дополнять заметками и отмечать
факт ручного отклика:

```powershell
python -m src.main review list
python -m src.main review set <id> --status interesting
python -m src.main review note <id> --note "Проверить требования и зарплату"
python -m src.main review apply <id> --date today
python -m src.main review next <id> --action "Написать follow-up" --date 2026-06-20
```

Для списка доступны фильтры:

```powershell
python -m src.main review list --status interesting --min-score 40 --limit 30
python -m src.main review list --profile ai_automation
```

Допустимые статусы: `new`, `interesting`, `maybe`, `rejected`, `applied`,
`interview`, `offer`, `archived`. Если отдельной review-записи нет, вакансия
считается `new`.

Статус `applied` означает только то, что пользователь вручную отправил отклик
через интерфейс HH. CareerSignal HH не отправляет отклики. Review-статусы,
заметки, даты и следующие действия хранятся только локально в SQLite.

После изменения review-информации обновите отчёт:

```powershell
python -m src.main export
```

HTML поддерживает фильтр по review status и показывает priority, заметки,
дату ручного отклика и следующее действие. CSV и JSONL содержат те же поля.

## Тестирование

### Быстрые тесты (smoke-check перед commit)

```powershell
# Только тесты без сети и без тяжёлой DB — < 5 секунд
python -m pytest tests/ -m no_network -x -q

# Проверка стиля
python -m ruff check src/ tests/

# Health check проекта
python -m src.main health

# Сухой прогон maintenance
python -m src.main maintenance cleanup --dry-run
```

### Полный test suite

```powershell
# Все тесты
python -m pytest tests/ -v

# Только unit-тесты (без DB, без integration)
python -m pytest tests/ -m "not integration" -v

# Только integration + no_network
python -m pytest tests/ -m "integration and no_network" -v

# С отчётом о покрытии (если установлен pytest-cov)
python -m pytest tests/ --cov=src --cov-report=term-missing
```

### Маркеры тестов

| Маркер       | Назначение                                              |
|--------------|--------------------------------------------------------|
| `unit`       | Быстрые тесты без DB и сети                            |
| `integration`| Тесты с DB и/или несколькими модулями                  |
| `no_network` | Гарантированно без HTTP-запросов                       |
| `slow`       | Тесты длительнее нескольких секунд                     |

### Структура тестов

```
tests/
├── fixtures/                  # Реалистичные JSON/YAML фикстуры
│   ├── hh_vacancy_ai_good.json
│   ├── hh_vacancy_ai_bad_qa.json
│   ├── hh_vacancy_bitrix_good.json
│   ├── hh_vacancy_onsite_bad.json
│   ├── hh_vacancy_no_salary.json
│   ├── hh_vacancy_duplicate_1.json
│   ├── hh_vacancy_duplicate_2.json
│   ├── search_presets_valid.yaml
│   ├── search_presets_invalid.yaml
│   ├── candidate.yaml
│   └── apply_templates.yaml
├── helpers.py                 # Фабрики: make_storage, seed_vacancies, run_cli
├── test_cli_contracts.py      # Контракты парсинга CLI
├── test_e2e_local_workflow.py # End‑to‑end сценарий без сети
├── test_snapshots.py          # Структурные проверки HTML-экспорта
├── test_network_safety.py     # Команды не делают API-вызовов
└── ...                        # Остальные тесты
```

### Pre-commit checklist

```powershell
# 1. Все тесты
python -m pytest

# 2. Стиль
python -m ruff check src/ tests/

# 3. Health
python -m src.main health

# 4. DB integrity
python -m src.main db integrity

# 5. Maintenance preview
python -m src.main maintenance cleanup --dry-run
```
