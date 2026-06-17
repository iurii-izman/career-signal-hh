# CareerSignal HH

Локальный MVP для мониторинга открытых вакансий через официальный публичный
API HeadHunter. Приложение выполняет настроенные поиски, сохраняет вакансии в
SQLite, загружает подробности, рассчитывает прозрачный rule-based score и
создаёт автономный HTML-отчёт, CSV и JSONL.

Проект ориентирован на два стартовых направления:

- AI / Automation / Systems Integration;
- Bitrix24 / 1C / CRM / Business Analyst.

> **Состояние API на 12 июня 2026:** актуальная документация HH помечает поиск
> и получение вакансий как методы, доступные авторизованному приложению или
> работодателю. Из текущего окружения анонимный `GET /vacancies` возвращает
> `403 forbidden`. Поэтому код публичного режима готов, но живой поиск не
> сможет получить вакансии, пока HH не разрешит доступ приложению. Проект не
> обходит это ограничение и выводит понятную ошибку. Anonymous-справочники,
> локальный scoring, SQLite и экспорт работают без OAuth.
> При `403 forbidden` поиск останавливается после первого запроса, чтобы не
> повторять десятки заведомо запрещённых обращений.

## Ограничения

CareerSignal HH не отправляет отклики, не управляет резюме, не получает
переговоры и переписку, не обходит интерфейс HH и не работает с закрытыми
личными данными. В проекте нет парсинга страниц, браузерной автоматизации,
веб-сервера или фоновой очереди. Используются только публичные endpoint'ы
`https://api.hh.ru`.

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
- `user_oauth` — зарезервирован на будущее и пока не реализован.

При `application_token` с пустым `HH_APP_ACCESS_TOKEN` приложение не падает
при импорте, но API-команды завершаются понятной конфигурационной ошибкой.

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

## Universal Search Presets

CareerSignal HH поддерживает универсальные поисковые пресеты через
`config/search_presets.yaml`. Пресеты заменяют старые жёстко заданные профили
(`ai_automation`, `bitrix_1c`) и позволяют создавать произвольные поиски
без редактирования кода.

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
python -m src.main presets show ai_rag_remote
```

### Управление пресетами

```powershell
# Создать новый пресет
python -m src.main presets create my-preset --terms "Python,AI,LLM" --include "python,ai,llm" --exclude "qa,gambling"

# Клонировать
python -m src.main presets clone ai_rag_remote my-copy

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
python -m src.main search --preset ai_rag_remote --mode smoke
python -m src.main search --preset bitrix24_crm_remote --mode normal
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
fit analysis, рисками, чеклистом и cover letter по шаблону.
**Не отправляет отклики.** Только готовит материалы.

Шаблоны: `config/apply_templates.yaml` — preset-specific,
с поддержкой short/medium/detailed стилей и ru/en языков.
Fallback: preset → default → builtin.

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

Файлы создаются в `exports/apply_packs/<id>_<slug>.md` и `.html`.
При `--top`/`--limit` дополнительно создаётся `index.html`.

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
python -m src.main apply-pack --top 5 --decision strong_match
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
- **Preset Performance** — эффективность пресетов.
- **Review Funnel** — воронка статусов.
- **Generated Files** — статус всех export-файлов с датами
  и командами для регенерации.
- **Latest Search Runs** — последние 5 поисковых запусков.
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
    profiles.py        → profiles
    review.py          → review list/set/note/apply/next
    sample.py          → sample-export
    search.py          → search (с search-loop)
    stats.py           → top, stats
  services/
    search_runner.py   → print_run_estimate, print_run_summary
    search_modes.py    → реэкспорт SEARCH_MODES
```

`src/hh_client.py` отвечает только за публичный HTTP API, `src/storage.py` —
за SQLite и idempotent upsert, `src/scoring.py` — за правила, а экспортеры не
зависят от сети. `first_seen_at` при обновлении не перезаписывается; подробности
и score пересчитываются.

Одна ошибка запроса или вакансии записывается в `search_runs` и не останавливает
весь запуск.

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

## Тесты

```powershell
python -m pytest
python -m src.main --help
python -m src.main search --dry-run --mode smoke
```

## Будущий OAuth-режим

Публичный режим можно сохранить без изменений, добавив отдельный authorized
client, `client_id`/`client_secret`, безопасное token storage и явные команды
для разрешённых OAuth-операций. Авторизованный клиент не должен подменять
текущий `HHClient`: это позволит не ломать публичный поиск и экспорт.

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

6. Проверьте доступ:

   ```powershell
   python -m src.main auth-check
   ```

   Команда показывает режим, наличие токена и User-Agent, затем проверяет
   `GET /me` и `GET /vacancies?text=python&per_page=1`. Сам токен не выводится.

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
