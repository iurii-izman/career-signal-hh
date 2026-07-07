# Техническое задание v1.1 FINAL
# Усиление `career-signal-hh` до личного HH Job Radar

**Проект:** `career-signal-hh`  
**Репозиторий:** `github.com/iurii-izman/career-signal-hh`  
**Дата:** 2026-07-07  
**Статус документа:** финальная версия для разработки  
**Назначение:** дать полное ТЗ для усиления текущего проекта без переписывания с нуля.

---

## 0. Executive Summary

`career-signal-hh` уже содержит сильный каркас личной системы поиска работы через HH API: поиск вакансий, SQLite-хранилище, safe search modes, скоринг, review queue, apply-pack, wizard, cockpit/export, analytics, search-lab и кампании.

Цель усиления — превратить проект в **личный HH Job Radar**:

```text
App token → безопасный сбор рынка
Scoring → отсечение мусора и ранжирование
Review queue → ручной отбор
Briefing → 7-блочный анализ вакансии
Apply pack → письмо + вопросы + follow-up
Manual apply → пользователь сам отправляет отклик
Tracker → локальный статус + Notion/n8n
Managed OAuth lifecycle → позже, только для read/sync и точечных подтверждённых действий
```

Ключевой принцип: **не строить спам-бота**. Проект должен ускорять поиск и качество откликов, но не обходить интерфейс HH, не кликать за пользователя, не отправлять массовые отклики и не нарушать безопасные лимиты.

---

## 1. Проверка текущего состояния репозитория

### 1.1. Уже реализовано и сохраняется

По текущему коду и README проекта подтверждены следующие блоки:

| Блок | Текущий статус | Решение |
|---|---|---|
| `HHClient` | есть `none` / `application_token`, request budget, delay, 429 handling | сохранить и усилить |
| App token search | есть поиск `/vacancies` и детали `/vacancies/{id}` | сохранить |
| Safe Search Modes | есть `smoke`, `normal`, `deep` | сохранить, deep только вручную |
| SQLite storage | есть `vacancies`, `scores`, `score_details`, `search_runs`, `vacancy_reviews` | расширить миграциями |
| Review queue | есть статусы, заметки, draft, applied date, next action | расширить событиями |
| Wizard | есть меню, first-run, daily, improve, apply | расширить briefing и Notion |
| Autopilot daily | есть health → backup → search → rescore → export → queue | сохранить как daily core |
| Apply-pack | есть MD/HTML, score, risks, checklist, draft save | переписать текстовую логику |
| Search presets | есть `ai_rag_remote`, `bitrix24_crm_remote` | расширить под профиль Юрия |
| Candidate config | есть базовый `candidate.yaml` | заменить на актуальный профиль |
| Templates | есть `apply_templates.yaml` | заменить, текущие тексты слабые |
| Analytics | есть summary / skills / employers / salary / presets / funnel | усилить KPI поиска |
| Search Lab | есть terms / suggest / compare / dry-plan / export | использовать для калибровки |
| Campaigns | есть несколько кампаний на одной БД | доработать под профили Юрия |
| UI | есть локальный web UI (`src/commands/ui.py`, `src/web/*`) | считать текущей baseline-частью, дальше развивать только packaging/installer |

### 1.2. Текущие ограничения

| Ограничение | Где проявляется | Решение |
|---|---|---|
| нет managed OAuth lifecycle | manual `user_oauth` bearer token mode уже работает, но нет `login` / `refresh` / `revoke-local` / keyring storage | вынести managed OAuth в этап V2 |
| шаблоны писем не соответствуют карьерной инструкции | `config/apply_templates.yaml` | заменить полностью |
| `candidate.yaml` слишком общий | фокус на RAG/AI Engineer | заменить на CRM/SA/AI automation профиль |
| нет команды `briefing` | анализ пока есть только в apply-pack | добавить отдельный 7-блочный briefing |
| нет outbox для Notion/n8n | интеграция есть в отдельном `n8nnotion` | добавить webhook outbox |
| нет синхронизации реальных откликов | manual token mode есть, но нет read-only sync и reconciliation flow | добавить read-only sync позже |
| нет строгой проверки писем | шаблоны могут нарушить ограничения | добавить validator |
| нет событийной модели | review хранит состояние, но не историю переходов | добавить `vacancy_events` |

---

## 2. Целевой пользователь и карьерный профиль

### 2.1. Пользователь

**Имя:** Юрий Изман  
**Профиль:** системный аналитик по CRM, интеграциям и AI-автоматизации  
**Опыт:** 6+ лет  
**Формат:** только remote  
**Английский:** B2  
**Гражданство:** Молдова + Россия  
**Не целевые роли:** PM, продажи, поддержка, ML Engineer.

### 2.2. Основной опыт для скоринга и писем

#### AXELSOFT — ведущий аналитик по CRM, интеграциям и автоматизации

- полный цикл: требования → ТЗ → постановка задач → контроль → верификация → сопровождение;
- Битрикс24: 5+ воронок, 50+ полей, 40+ роботов/триггеров, 3+ смарт-процесса, 8+ ролей;
- 20+ ручных операций автоматизировано;
- 5+ интеграций: 1С, сайт, формы, IP-телефония, почта, БД, ИТ-системы;
- AS-IS/TO-BE, карта автоматизации по бизнес-ценности;
- ТЗ, регламенты, схемы, инструкции, обучение 20+ пользователей.

#### RICHCODE — бизнес/системный аналитик CRM-проектов

- 15+ проектов Битрикс24;
- e-commerce, услуги, производство, торговля;
- обследование, AS-IS/TO-BE, настройка, интеграции, сдача, обучение;
- интеграции с 1С, телефонией, сайтами, формами, почтой, БД.

#### Реальный AI-кейс

Единственный AI-кейс, который можно писать как реализованный:

> AI Lead Intake для Битрикс24 — webhook-сценарий с LLM-классификацией входящих заявок и автосозданием сделок. Код открыт: `github.com/iurii-izman/ai-lead-intake-bitrix24`.

Использовать только если вакансия явно содержит AI/LLM/GPT/n8n/Make/AI automation.

### 2.3. Стек

```text
Битрикс24, REST API, Webhooks, 1С, Postman, SQL, PostgreSQL,
Python, Git, Docker, n8n, Make, BPMN, AS-IS/TO-BE,
Confluence, Jira, FastAPI, Pydantic, SQLite, OpenAPI
```

---

## 3. Целевые роли и приоритеты поиска

### 3.1. Главные роли

| Приоритет | Роль | Комментарий |
|---:|---|---|
| P0 | Системный аналитик CRM | главный профиль |
| P0 | Бизнес/системный аналитик Битрикс24 | высокая релевантность |
| P0 | CRM Automation Analyst | хороший международный/remote вектор |
| P0 | Integration Analyst | API/webhooks/1C/CRM |
| P1 | AI Automation Analyst | развиваемый фокус |
| P1 | No-code / low-code automation analyst | n8n/Make + CRM |
| P1 | 1C / ERP integration analyst | только если аналитика и интеграции, не бухгалтерия |
| P2 | Implementation Analyst / Consultant | если без продаж и поддержки |
| P2 | Technical Business Analyst | если есть API/CRM/process automation |

### 3.2. Исключаемые роли

Жёстко понижать или исключать:

- Sales Manager;
- Account Manager;
- Customer Support;
- Call-center;
- Project Manager без системной аналитики;
- Product Manager без CRM/API/process design;
- ML Engineer;
- Data Scientist;
- QA Automation;
- чистый PHP developer;
- frontend/backend developer без CRM/API/integration;
- офис без remote;
- частые командировки;
- cold calls;
- gambling/casino/high-risk verticals;
- стажировка без оплаты;
- “обучение за счёт компании” без ясной оплаты.

---

## 4. Целевой daily workflow

### 4.1. Основной сценарий

```text
1. Запуск wizard daily
2. Health check
3. DB backup
4. Safe search через App token
5. Detail refresh только если нужно
6. Scoring V2 по пресетам
7. Export cockpit
8. Review queue
9. Пользователь выбирает 3–8 вакансий
10. Briefing по каждой вакансии
11. Apply pack / письмо
12. Ручной отклик на HH
13. review apply / status update
14. Notion sync через n8n
```

### 4.2. Целевые метрики дня

```text
100–300 найденных вакансий
20–40 после базовой фильтрации
10–20 в review queue
3–8 с briefing и письмом
2–5 ручных откликов
0 автоматических массовых отправок
```

---

## 5. Архитектура целевого решения

```text
career-signal-hh
├─ config/
│  ├─ candidate.yaml
│  ├─ search_presets.yaml
│  ├─ apply_templates.yaml
│  ├─ briefing_templates.yaml          # новый
│  ├─ notion_sync.yaml                 # новый
│  └─ risk_policy.yaml                 # новый
│
├─ src/
│  ├─ hh_client.py                     # усилить auth/session/safety
│  ├─ hh_oauth.py                      # новый, V2
│  ├─ scoring_v2.py                    # сохранить, усилить профили
│  ├─ briefing/
│  │  ├─ generator.py                  # новый
│  │  ├─ letter.py                     # новый
│  │  ├─ validators.py                 # новый
│  │  ├─ gap.py                        # новый
│  │  ├─ interview.py                  # новый
│  │  └─ log_model.py                  # новый
│  ├─ commands/
│  │  ├─ briefing.py                   # новый
│  │  ├─ notion_sync.py                # новый
│  │  ├─ oauth.py                      # новый, V2
│  │  └─ ... existing commands
│  ├─ integrations/
│  │  ├─ notion_webhook.py             # новый
│  │  └─ telegram.py                   # optional, V3
│  ├─ storage.py                       # расширить
│  ├─ db_migrations.py                 # расширить
│  └─ tests/
│
├─ exports/
│  ├─ briefings/
│  ├─ apply_packs/
│  ├─ cockpit/
│  └─ reports/
│
└─ docs/
   ├─ HH_JOB_RADAR_TZ.md
   ├─ OAUTH_READONLY_PLAN.md
   ├─ SAFETY_POLICY.md
   └─ RUNBOOK_DAILY.md
```

---

## 6. Безопасность и ограничения

### 6.1. Абсолютные запреты

Проект не должен:

1. отправлять отклики без ручного подтверждения;
2. кликать по интерфейсу HH;
3. обходить капчи, тесты, лимиты или ограничения;
4. имитировать браузерные действия;
5. собирать публичную базу вакансий для третьих лиц;
6. сохранять токены в git;
7. выводить токены в логи, HTML, Markdown, JSONL, CSV;
8. хранить реальные client secrets в `config/*.yaml`;
9. использовать один шаблон письма для массовой рассылки;
10. придумывать опыт, цифры или коммерческие AI-кейсы.

### 6.2. Токены

| Токен | Назначение | Где использовать | Где хранить |
|---|---|---|---|
| App token | поиск вакансий, справочники, `/me` для приложения | V1 | `.env` / keyring |
| User OAuth access token | личные данные, резюме, переговоры | V2 | keyring предпочтительно |
| User OAuth refresh token | обновление user access token | V2 | keyring only |
| Client secret | OAuth exchange | V2 | keyring / env, не git |

### 6.3. Redaction rules

Любой вывод должен маскировать:

- `access_token`;
- `refresh_token`;
- `client_secret`;
- `HH_APP_ACCESS_TOKEN`;
- email/phone, если не требуется для письма;
- webhook URL с секретами;
- Notion token;
- n8n webhook secret.

Формат маски:

```text
abcd...wxyz
```

---

## 7. Этапы реализации

## Этап 0 — Baseline freeze

### Цель

Зафиксировать текущее состояние проекта перед изменениями.

### Задачи

1. Создать ветку:

```bash
feature/hh-job-radar-v1
```

2. Прогнать baseline:

```powershell
python -m src.main version
python -m src.main doctor
python -m src.main health
python -m src.main presets validate
python -m src.main search --dry-run --mode smoke
python -m src.main wizard daily --plan
python -m src.main wizard apply --plan
```

3. Сохранить отчёт:

```text
docs/baseline/hh_job_radar_baseline_2026-07-07.md
```

### Acceptance criteria

- baseline документ создан;
- текущие команды работают или ошибки задокументированы;
- дальнейшие изменения идут отдельными коммитами;
- `.env` и токены не попали в git.

---

## Этап 1 — Candidate Profile Refresh

### Цель

Заменить общий профиль кандидата на точный профиль Юрия под CRM/Bitrix24/API/AI automation.

### Файл

```text
config/candidate.yaml
```

### Новая структура

```yaml
candidate:
  name_ru: "Юрий Изман"
  name_en: "Iurii Izman"
  public_title_ru: "Системный аналитик по CRM, интеграциям и AI-автоматизации"
  public_title_en: "Systems Analyst — CRM, Integrations and AI Automation"

  work_format:
    remote_only: true
    relocation: false
    business_trips: false

  languages:
    ru: native
    en: B2
    ro: A2

  links:
    github: "https://github.com/iurii-izman"
    linkedin: "https://linkedin.com/in/iurii-izman"

  constraints:
    do_not_write_in_cover_letter:
      - Tiraspol
      - Moldova
      - citizenship
      - documents
      - leaving previous job
    avoid_roles:
      - sales
      - support
      - project_manager_without_analysis
      - ml_engineer
      - data_scientist
      - onsite_only
      - cold_calls

  experience:
    years_total: "6+"
    primary_stack:
      - Bitrix24
      - CRM
      - REST API
      - Webhooks
      - 1C integrations
      - Postman
      - SQL
      - PostgreSQL
      - Python
      - Docker
      - n8n
      - Make
      - BPMN
      - AS-IS/TO-BE
      - Jira
      - Confluence

  profiles:
    crm_sa:
      summary_ru: "Системный аналитик по CRM и интеграциям: Битрикс24, 1С, REST API, webhooks, AS-IS/TO-BE, ТЗ, автоматизация бизнес-процессов."
      summary_en: "Systems analyst focused on CRM and integrations: Bitrix24, 1C, REST API, webhooks, AS-IS/TO-BE, specifications and business process automation."

    bitrix24_integration:
      summary_ru: "Аналитик Битрикс24 и CRM-интеграций: воронки, поля, роботы, триггеры, смарт-процессы, роли, интеграции с 1С, сайтом, телефонией и БД."
      summary_en: "Bitrix24 and CRM integration analyst: pipelines, fields, automations, triggers, smart processes, roles and integrations with 1C, websites, telephony and databases."

    ai_automation:
      summary_ru: "CRM/AI automation analyst: webhook-сценарии, LLM-классификация заявок, n8n/Make, Bitrix24 REST API, human-in-the-loop проверки."
      summary_en: "CRM/AI automation analyst: webhook workflows, LLM-based lead classification, n8n/Make, Bitrix24 REST API and human-in-the-loop review."

  real_ai_case:
    trigger_keywords:
      - ai
      - llm
      - gpt
      - openai
      - n8n
      - make
      - automation
      - ai automation
      - artificial intelligence
      - нейросети
      - искусственный интеллект
    ru: "Из практики: реализовал AI Lead Intake для Битрикс24 — webhook-сценарий с LLM-классификацией входящих заявок и автосозданием сделок. Код открыт: github.com/iurii-izman/ai-lead-intake-bitrix24"
    en: "From practice: I implemented AI Lead Intake for Bitrix24 — a webhook workflow with LLM classification of incoming requests and automatic deal creation. Code: github.com/iurii-izman/ai-lead-intake-bitrix24"
```

### Acceptance criteria

- `candidate.yaml` больше не содержит формулировки “RAG Engineer” как основной профиль;
- письмо не подставляет локацию по умолчанию;
- AI-кейс добавляется только при наличии AI-триггеров в вакансии;
- роли PM/sales/support/ML Engineer попадают в риск или exclude.

---

## Этап 2 — Search Presets Refresh

### Цель

Расширить и откалибровать `config/search_presets.yaml` под реальные направления Юрия.

### Требуемые пресеты

#### 2.1. `crm_sa_remote`

```yaml
crm_sa_remote:
  enabled: true
  description: "Remote CRM / Systems Analyst roles"
  search_terms:
    - "системный аналитик CRM"
    - "бизнес аналитик CRM"
    - "CRM аналитик"
    - "аналитик CRM"
    - "systems analyst CRM"
    - "business analyst CRM"
  filters:
    remote_only: true
    schedule: [remote]
    experience: [between3And6, moreThan6]
  include:
    any:
      - crm
      - системный аналитик
      - бизнес аналитик
      - требования
      - тз
      - api
      - интеграции
      - бизнес-процессы
      - as-is
      - to-be
    all: []
  exclude:
    any:
      - холодные звонки
      - продажи
      - сопровождение пользователей 1 линии
      - call center
      - customer support
    title:
      - менеджер по продажам
      - account manager
      - project manager
      - product manager
      - support specialist
  boost:
    title:
      crm: 20
      системный аналитик: 22
      бизнес аналитик: 18
    skills:
      api: 12
      sql: 8
      postman: 8
      bpmn: 10
    description:
      интеграции: 15
      техническое задание: 12
      бизнес-процессы: 12
```

#### 2.2. `bitrix24_integration_remote`

```yaml
bitrix24_integration_remote:
  enabled: true
  description: "Remote Bitrix24 / CRM implementation / integration roles"
  search_terms:
    - "Битрикс24"
    - "Bitrix24"
    - "аналитик Битрикс24"
    - "системный аналитик Битрикс24"
    - "интегратор Битрикс24"
    - "CRM Битрикс24"
  filters:
    remote_only: true
    schedule: [remote]
  include:
    any:
      - битрикс24
      - bitrix24
      - crm
      - роботы
      - триггеры
      - смарт-процессы
      - воронки
      - REST API
      - webhook
      - 1с
      - интеграции
    all: []
  exclude:
    any:
      - холодные звонки
      - продажи
      - обзвон
      - техподдержка
    title:
      - менеджер по продажам
      - оператор
      - php developer
  boost:
    title:
      битрикс24: 25
      bitrix24: 25
      crm: 12
    description:
      смарт-процессы: 14
      роботы: 10
      триггеры: 10
      интеграции с 1с: 18
      rest api: 14
      webhook: 14
```

#### 2.3. `ai_automation_crm_remote`

```yaml
ai_automation_crm_remote:
  enabled: true
  description: "Remote AI automation roles with CRM/API/no-code fit"
  search_terms:
    - "AI automation"
    - "AI Automation Engineer"
    - "AI automation analyst"
    - "n8n automation"
    - "Make automation"
    - "GPT automation"
    - "LLM automation"
    - "AI аналитик"
    - "автоматизация с AI"
  filters:
    remote_only: true
    schedule: [remote]
  include:
    any:
      - ai automation
      - llm
      - gpt
      - n8n
      - make
      - webhook
      - api
      - crm
      - automation
      - python
      - fastapi
    all: []
  exclude:
    any:
      - machine learning research
      - computer vision
      - deep learning research
      - data scientist
      - mlops senior
    title:
      - ml engineer
      - data scientist
      - computer vision engineer
  boost:
    title:
      ai automation: 22
      automation analyst: 18
      n8n: 16
    description:
      webhook: 14
      api integration: 14
      crm: 12
      bitrix24: 16
      business process automation: 14
```

#### 2.4. `one_c_integration_analyst`

```yaml
one_c_integration_analyst:
  enabled: true
  description: "1C / ERP / CRM integration analyst roles"
  search_terms:
    - "аналитик 1С интеграции"
    - "системный аналитик 1С"
    - "бизнес аналитик 1С"
    - "аналитик ERP CRM"
    - "интеграции 1С CRM"
  filters:
    remote_only: true
    schedule: [remote]
  include:
    any:
      - 1с
      - erp
      - интеграции
      - crm
      - api
      - требования
      - тз
      - обмен данными
      - sql
    all: []
  exclude:
    any:
      - бухгалтерский учет
      - зарплата и кадры
      - регламентированная отчетность
      - консультации пользователей
    title:
      - консультант 1с бухгалтерия
      - программист 1с
  boost:
    title:
      аналитик 1с: 18
      системный аналитик: 18
    description:
      интеграции: 18
      обмен данными: 12
      crm: 10
      api: 10
```

#### 2.5. `no_code_automation_remote`

```yaml
no_code_automation_remote:
  enabled: true
  description: "No-code / low-code automation roles"
  search_terms:
    - "n8n"
    - "Make automation"
    - "low-code automation"
    - "no-code automation"
    - "автоматизация бизнес-процессов"
    - "интегратор CRM"
  filters:
    remote_only: true
    schedule: [remote]
  include:
    any:
      - n8n
      - make
      - webhook
      - api
      - crm
      - automation
      - бизнес-процессы
      - интеграции
    all: []
  exclude:
    any:
      - продажи
      - cold calls
      - only support
    title:
      - sales
      - support
```

### Acceptance criteria

- минимум 5 новых пресетов добавлены;
- `presets validate` проходит;
- `search --dry-run --mode smoke` показывает план без API-запросов;
- `search-lab dry-plan` работает для каждого нового пресета;
- старые пресеты не удалены без необходимости, но могут быть `enabled: false`.

---

## Этап 3 — Letter & Apply Pack Rewrite

### Цель

Заменить слабые шаблоны на письма по текущей карьерной логике.

### Проблема текущих шаблонов

Текущие шаблоны содержат фразы:

- “Меня заинтересовала вакансия”;
- “Буду рад”;
- “Looking forward”;
- общие формулировки без конкретной боли вакансии;
- подстановку локации и availability в письмо.

Это нужно убрать.

### Новые правила писем

#### Структура письма

1. Открытие: конкретная задача или боль из вакансии.
2. Кто я: 1 предложение.
3. Релевантный опыт: 2–3 факта под требования.
4. Закрытие gap: только если gap реальный.
5. AI-блок: только если вакансия содержит AI/LLM/GPT/n8n/Make/AI automation.
6. Следующий шаг: конкретно.
7. Подпись: Юрий Изман / Iurii Izman.

#### Ограничения

- 150–220 слов;
- не писать Тирасполь;
- не писать Молдова;
- не писать гражданство/документы;
- не писать причины ухода;
- не придумывать опыт;
- не писать AI-кейс, если вакансия не про AI/LLM/n8n/Make/GPT;
- не использовать запрещённые фразы.

#### Запрещённые фразы

```text
меня заинтересовала
я очень хочу
буду рад
надеюсь на сотрудничество
лидер рынка
динамично развивается
готов к вызовам
быстро обучаюсь
командный игрок
ответственный
целеустремлённый
богатый опыт
синергия
точка роста
уникальный специалист
```

### Новые шаблоны

Файл:

```text
config/apply_templates.yaml
```

Нужны шаблоны:

- `crm_sa_ru.medium`
- `crm_sa_en.medium`
- `bitrix24_ru.medium`
- `bitrix24_en.medium`
- `ai_automation_ru.medium`
- `ai_automation_en.medium`
- `generic_sa_ru.medium`
- `generic_sa_en.medium`

### Требование к генератору

`apply_pack.py` должен не просто вставлять `{fit_reasons}`. Он должен:

1. определить тип вакансии;
2. извлечь 2–3 ключевые боли из описания;
3. выбрать профиль кандидата;
4. проверить наличие AI-триггеров;
5. собрать письмо;
6. прогнать letter validator;
7. если письмо не прошло — вернуть ошибку с причиной.

### Letter validator

Новый файл:

```text
src/briefing/validators.py
```

Проверки:

| Проверка | Условие |
|---|---|
| word count | 150–220 слов |
| banned phrases | отсутствуют |
| forbidden location | нет Tiraspol/Moldova/документов |
| AI block | только при AI trigger |
| signature | есть имя |
| invented claims | только из `candidate.yaml` |
| language | RU для RU, EN для EN |
| no markdown bullets in letter | письмо выглядит как обычный текст |

### Acceptance criteria

- `apply-pack` больше не генерирует запрещённые фразы;
- письмо проходит validator;
- при вакансии без AI нет AI Lead Intake блока;
- при вакансии с AI/n8n/Make/GPT AI-блок добавляется корректно;
- draft сохраняется в `vacancy_reviews.cover_letter_draft`;
- HTML/MD export работают.

---

## Этап 4 — Команда `briefing`

### Цель

Добавить ключевую команду для 7-блочного анализа вакансии.

### Команда

```powershell
python -m src.main briefing VACANCY_ID
```

### Опции

```powershell
python -m src.main briefing VACANCY_ID --lang ru
python -m src.main briefing VACANCY_ID --lang en
python -m src.main briefing VACANCY_ID --format md
python -m src.main briefing VACANCY_ID --format html
python -m src.main briefing VACANCY_ID --save-review
python -m src.main briefing VACANCY_ID --export
python -m src.main briefing VACANCY_ID --sync-notion
python -m src.main briefing --top 5 --min-score 80
```

### Вывод — строго 7 блоков

#### 1. ОЦЕНКА

```markdown
## 1. ОЦЕНКА
Итог: X/100
- Соответствие стека: X/25 — пояснение
- Уровень позиции vs опыт: X/20 — пояснение
- AI/автоматизация: X/20 — пояснение
- Рыночность условий: X/20 — пояснение
- Риски для меня: X/15 — пояснение
Зарплата: указана X / не указана [ориентир одной строкой]
Вердикт: Откликаться / С оговорками / Не тратить время
Обоснование: 2 предложения, прямо.
```

#### 2. RED FLAGS + GAP

```markdown
## 2. RED FLAGS + GAP
🚩 Риски:
- [что] — [почему риск]

❌ Gap:
Требуется: ... | Статус: есть/частично/нет | На интервью: ...
```

#### 3. ПИСЬМО

150–220 слов. По правилам из этапа 3.

#### 4. ИНТЕРВЬЮ + ВОЗРАЖЕНИЯ

```markdown
## 4. ИНТЕРВЬЮ + ВОЗРАЖЕНИЯ
Топ-3 вопроса по вакансии:
❓ ...
💡 ...

Топ-2 возражения рекрутера:
⚠️ ... → ✅ ...
```

#### 5. КЛЮЧЕВЫЕ СЛОВА

```markdown
## 5. КЛЮЧЕВЫЕ СЛОВА
Технические: ...
Процессные: ...
Контекстные: ...
```

#### 6. FOLLOW-UP

3–4 предложения через 5–7 рабочих дней. Без “извините что беспокою”.

#### 7. LOG

```markdown
## 7. LOG
Вакансия: ... | Компания: ... | Ссылка: ...
Источник: HH | Канал: HH
Статус: Новая | Оценка: X/100 | Вердикт: ... | Приоритет: В/С/Н
Тип: Продукт/Интегратор/Консалтинг/Стартап/Корпорация/Не указано
Роль: CRM/SA/BA/AI/Integration/Bitrix24/Other
Формат: Remote/Hybrid/Office | Оформление: ТК/B2B/Deel/Не указано
Зарплата: ... | Стек: ... | Red flags: ... | Gap: ...
Письмо: [первые 30 слов + «...»]
Дата анализа: YYYY-MM-DD | Дата отклика: — | Follow-up: 5–7 р.д.
Рекрутер: не указано | Контакт: не указано | Комментарий: ...
```

### Новые файлы

```text
src/commands/briefing.py
src/briefing/generator.py
src/briefing/letter.py
src/briefing/validators.py
src/briefing/gap.py
src/briefing/interview.py
src/briefing/log_model.py
config/briefing_templates.yaml
```

### Acceptance criteria

- `briefing VACANCY_ID` работает для вакансии из БД;
- результат содержит все 7 блоков;
- письмо проходит validator;
- `--save-review` сохраняет briefing и draft в БД;
- `--export` создаёт `.md` и optional `.html`;
- `--top 5` генерирует briefings для очереди;
- если данных нет — пишет `не указано`, не придумывает.

---

## Этап 5 — Расширение хранилища

### Цель

Добавить историю событий, briefing reports и outbox для внешних интеграций.

### Новые таблицы

#### 5.1. `briefing_reports`

```sql
CREATE TABLE IF NOT EXISTS briefing_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'ru',
    total_score INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    priority TEXT NOT NULL,
    role_type TEXT NOT NULL,
    company_type TEXT NOT NULL,
    red_flags_json TEXT NOT NULL DEFAULT '[]',
    gaps_json TEXT NOT NULL DEFAULT '[]',
    keywords_json TEXT NOT NULL DEFAULT '{}',
    cover_letter TEXT NOT NULL,
    follow_up TEXT NOT NULL,
    log_line TEXT NOT NULL,
    full_markdown TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
);
```

#### 5.2. `vacancy_events`

```sql
CREATE TABLE IF NOT EXISTS vacancy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    old_status TEXT NULL,
    new_status TEXT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'local',
    FOREIGN KEY(vacancy_id) REFERENCES vacancies(id)
);
```

#### 5.3. `integration_outbox`

```sql
CREATE TABLE IF NOT EXISTS integration_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    vacancy_id TEXT NULL,
    payload_json TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

#### 5.4. `hh_negotiations` — V2

```sql
CREATE TABLE IF NOT EXISTS hh_negotiations (
    id TEXT PRIMARY KEY,
    vacancy_id TEXT NULL,
    resume_id TEXT NULL,
    state TEXT NULL,
    created_at TEXT NULL,
    updated_at TEXT NULL,
    last_message_at TEXT NULL,
    raw_json TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
```

#### 5.5. `oauth_tokens_meta` — без самих токенов

```sql
CREATE TABLE IF NOT EXISTS oauth_tokens_meta (
    provider TEXT PRIMARY KEY,
    user_id TEXT NULL,
    token_type TEXT NULL,
    expires_at TEXT NULL,
    scopes_json TEXT NOT NULL DEFAULT '[]',
    last_refresh_at TEXT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    updated_at TEXT NOT NULL
);
```

### Изменения в `vacancy_reviews`

Добавить поля:

```sql
ALTER TABLE vacancy_reviews ADD COLUMN briefing_id INTEGER NULL;
ALTER TABLE vacancy_reviews ADD COLUMN notion_page_id TEXT NULL;
ALTER TABLE vacancy_reviews ADD COLUMN source_channel TEXT NULL DEFAULT 'HH';
ALTER TABLE vacancy_reviews ADD COLUMN follow_up_at TEXT NULL;
ALTER TABLE vacancy_reviews ADD COLUMN last_synced_at TEXT NULL;
```

### Acceptance criteria

- миграции идемпотентны;
- старые данные не ломаются;
- `db integrity` проходит;
- `review set/apply/next` создают события в `vacancy_events`;
- briefing можно получить из БД после генерации.

---

## Этап 6 — Notion / n8n Sync

### Цель

Связать локальный tracker с Notion Job Tracker через n8n webhook.

### Принцип

`career-signal-hh` не должен напрямую зависеть от Notion SDK. Первый безопасный вариант — webhook outbox:

```text
briefing/apply/review event
→ integration_outbox
→ notion-sync push
→ n8n webhook
→ Notion database
```

### Команды

```powershell
python -m src.main notion-sync status
python -m src.main notion-sync push --limit 10
python -m src.main notion-sync push --vacancy-id VACANCY_ID
python -m src.main notion-sync retry-failed
python -m src.main notion-sync dry-run --vacancy-id VACANCY_ID
```

### Конфиг

Файл:

```text
config/notion_sync.yaml
```

```yaml
notion_sync:
  enabled: false
  target: n8n_webhook
  webhook_url_env: JOB_TRACKER_WEBHOOK_URL
  webhook_secret_env: JOB_TRACKER_SECRET
  timeout_seconds: 20
  max_attempts: 3
  payload_version: "1.0"
```

### Payload

```json
{
  "payload_version": "1.0",
  "source": "career-signal-hh",
  "event_type": "briefing_created",
  "vacancy": {
    "id": "123",
    "title": "Системный аналитик CRM",
    "company": "Company",
    "url": "https://hh.ru/vacancy/123",
    "salary": "не указано",
    "format": "Remote",
    "published_at": "2026-07-07"
  },
  "review": {
    "status": "interesting",
    "priority": "В",
    "applied_at": null,
    "follow_up_at": null
  },
  "briefing": {
    "score": 86,
    "verdict": "Откликаться",
    "red_flags": [],
    "gaps": [],
    "cover_letter": "...",
    "follow_up": "...",
    "markdown": "..."
  }
}
```

### Acceptance criteria

- `--dry-run` показывает payload без отправки;
- webhook secret не печатается;
- successful push меняет статус outbox на `sent`;
- failed push сохраняет ошибку;
- повторная отправка не дублирует Notion-карточку, если n8n настроен на dedupe по `vacancy.id`.

---

## Этап 7 — Cockpit 2.0

### Цель

Сделать локальный cockpit главным экраном ежедневного решения.

### Блоки cockpit

1. Summary:
   - найдено сегодня;
   - новых 24h;
   - strong_match;
   - queue;
   - applied;
   - follow-up due.

2. Top vacancies:
   - score;
   - confidence;
   - noise;
   - role type;
   - salary;
   - remote;
   - decision;
   - action buttons as CLI hints.

3. Risk buckets:
   - office/hybrid unclear;
   - salary missing;
   - PM/sales/support risk;
   - pure dev risk;
   - ML/Data Science risk.

4. Apply pipeline:
   - interesting;
   - draft ready;
   - applied;
   - HR replied;
   - interview;
   - rejected;
   - offer.

5. Preset performance:
   - preset;
   - found;
   - loaded;
   - avg score;
   - strong match rate;
   - rejected rate.

### Acceptance criteria

- cockpit HTML автономный;
- не содержит токены;
- имеет фильтры по score/status/preset/remote/salary;
- открывается через `cockpit open`;
- generated file не ломает текущий export.

---

## Этап 8 — OAuth V2: read-only sync first

### Цель

Подключить OAuth аккуратно. Сначала только чтение и синхронизация.

### Почему не раньше

Сейчас manual `user_oauth` bearer token mode уже реализован для авторизованных
`GET` запросов. Не реализован именно managed OAuth lifecycle с безопасным
хранением, refresh и явными пользовательскими командами. До появления
стабильного daily radar этот слой всё ещё не даёт основной ценности.

### V2.1. OAuth Token Manager

Новый файл:

```text
src/hh_oauth.py
```

Функции:

- build authorization URL;
- exchange code for token;
- refresh token;
- store token in keyring;
- update `oauth_tokens_meta`;
- mask token in all outputs.

Команды:

```powershell
python -m src.main oauth status
python -m src.main oauth login
python -m src.main oauth refresh
python -m src.main oauth revoke-local
```

### V2.2. Read-only sync

Команды:

```powershell
python -m src.main hh-sync me
python -m src.main hh-sync resumes
python -m src.main hh-sync negotiations --status active
python -m src.main hh-sync messages NEGOTIATION_ID
python -m src.main hh-sync reconcile
```

### V2.3. Что можно синхронизировать

- данные `/me`;
- список резюме;
- список откликов/приглашений;
- активные переговоры;
- сообщения в переговорах;
- статусы откликов;
- связку `vacancy_id ↔ negotiation_id`.

### V2.4. Что нельзя в первой OAuth-версии

- отправлять отклики через API;
- отправлять сообщения HR;
- скрывать отклики;
- массово менять статусы;
- обновлять резюме;
- делать действия без подтверждения.

### Acceptance criteria

- `oauth status` не печатает токены;
- `hh-sync negotiations --status active` сохраняет данные в `hh_negotiations`;
- `reconcile` обновляет локальные статусы только по понятным правилам;
- любые write-операции отсутствуют или заблокированы feature flag.

---

## Этап 9 — Controlled Apply Assist V3

### Цель

Добавить полуавтоматическую помощь в отклике без массовой рассылки.

### Правило

До V3 проект **не отправляет отклики**. В V3 возможны только controlled actions.

### Условия допуска вакансии к apply assist

Вакансия может попасть в apply assist, если:

- score ≥ 85;
- confidence ≥ 60;
- noise ≤ 35;
- status = `interesting` или `draft_ready`;
- письмо прошло validator;
- нет hard red flags;
- пользователь явно подтвердил `approve`.

### Безопасный вариант V3.1

Команда:

```powershell
python -m src.main apply-assist VACANCY_ID
```

Действия:

1. показать briefing;
2. скопировать письмо в clipboard;
3. открыть `alternate_url` в браузере;
4. напечатать чеклист;
5. после ручного отклика предложить:

```powershell
python -m src.main review apply VACANCY_ID --date today
```

### Потенциальный V3.2

API-отклик только если:

- подтверждено документацией HH;
- endpoint доступен кандидату;
- есть правильный resume_id;
- нет теста;
- нет обязательного письма, которое не прошло validator;
- пользователь подтверждает каждую отправку;
- нет bulk режима.

### Acceptance criteria

- без `--confirm` отклик не отправляется;
- bulk apply отсутствует;
- все apply attempts логируются;
- already_applied корректно обрабатывается;
- test_required останавливает процесс.

---

## Этап 10 — Тестирование

### 10.1. Unit tests

Добавить тесты:

```text
tests/test_candidate_profile.py
tests/test_letter_validator.py
tests/test_briefing_generator.py
tests/test_briefing_log.py
tests/test_notion_payload.py
tests/test_outbox.py
tests/test_oauth_masking.py
tests/test_search_presets_iurii.py
```

### 10.2. Golden fixtures

Создать fixtures:

```text
tests/fixtures/vacancies/
├─ bitrix24_strong.json
├─ crm_sa_strong.json
├─ ai_automation_strong.json
├─ pm_bad.json
├─ sales_bad.json
├─ ml_engineer_bad.json
├─ office_bad.json
├─ one_c_partial.json
└─ no_salary_ok.json
```

### 10.3. Проверки писем

Для каждого fixture:

- письмо 150–220 слов;
- нет banned phrases;
- нет Tiraspol/Moldova/documents;
- AI-блок только при AI-триггере;
- есть подпись;
- нет выдуманных цифр.

### 10.4. Integration smoke

```powershell
python -m src.main presets validate
python -m src.main search --dry-run --mode smoke
python -m src.main import vacancy --title "Системный аналитик CRM" --company "Test" --url "https://hh.ru/vacancy/test" --description "Битрикс24 REST API интеграции 1С"
python -m src.main score rescore
python -m src.main briefing test --save-review --export
python -m src.main review draft test
python -m src.main cockpit export
```

### Acceptance criteria

- все тесты проходят;
- smoke flow работает без реального API;
- briefing работает на импортированной вакансии;
- нет утечек секретов.

---

## 11. Изменения CLI

### Новые команды

```text
briefing VACANCY_ID
briefing --top N
briefing validate VACANCY_ID
notion-sync status
notion-sync push
notion-sync dry-run
notion-sync retry-failed
oauth status                 # V2
oauth login                  # V2
oauth refresh                # V2
hh-sync negotiations          # V2
hh-sync resumes               # V2
hh-sync reconcile             # V2
apply-assist VACANCY_ID       # V3
```

### Обновить wizard

#### wizard menu

Добавить пункты:

```text
7. Generate briefing
8. Sync Notion
9. OAuth sync status [V2]
10. Exit
```

#### wizard daily

Новая цепочка:

```text
health
→ backup
→ autopilot daily
→ cockpit export
→ review next-best
→ optional briefing top N
→ optional Notion sync
```

#### wizard apply

Новая цепочка:

```text
review queue
→ choose vacancy
→ score explain
→ briefing
→ validate letter
→ save review draft
→ manual apply checklist
```

---

## 12. Конфигурация `.env`

### V1

```dotenv
HH_AUTH_MODE=application_token
HH_APP_ACCESS_TOKEN=
HH_USER_AGENT=IuriiVacancyMarketAnalytics/0.1 (iuriiizman@gmail.com)
DB_PATH=data/vacancies.sqlite

HH_DELAY_MIN_SECONDS=0.7
HH_DELAY_MAX_SECONDS=1.5
HH_COOLDOWN_ON_429_SECONDS=120
HH_STOP_ON_429=true
HH_DETAIL_REFRESH_DAYS=7

JOB_TRACKER_WEBHOOK_URL=
JOB_TRACKER_SECRET=
```

### V2 OAuth

```dotenv
HH_CLIENT_ID=
HH_CLIENT_SECRET=
HH_REDIRECT_URI=https://oauth.pstmn.io/v1/callback
HH_OAUTH_STORAGE=keyring
HH_OAUTH_WRITE_ENABLED=false
```

### Запрет

`.env` не коммитить.  
`.env.example` должен содержать только пустые значения и комментарии.

---

## 13. Definition of Done

### V1 считается готовым, если:

- обновлены `candidate.yaml`, `search_presets.yaml`, `apply_templates.yaml`;
- `presets validate` проходит;
- `wizard daily --mode smoke` работает;
- `review queue` показывает релевантные вакансии;
- `briefing VACANCY_ID` генерирует 7 блоков;
- письмо проходит validator;
- `apply-pack` не использует старые слабые шаблоны;
- `cockpit export` создаёт полезный daily dashboard;
- Notion outbox работает через dry-run;
- токены не попадают в выводы;
- тесты проходят.

### V2 считается готовым, если:

- OAuth login/refresh/status работает;
- токены хранятся безопасно;
- negotiations sync работает read-only;
- local tracker reconciliation работает;
- write-действия заблокированы feature flag.

### V3 считается готовым, если:

- apply-assist не делает автоотклик;
- письмо копируется/открывается страница;
- пользователь вручную подтверждает apply;
- API apply, если когда-либо включается, требует точечного подтверждения и не имеет bulk режима.

---

## 14. Приоритетный backlog

### P0 — сделать первым

1. Baseline freeze.
2. Обновить `candidate.yaml`.
3. Добавить новые search presets.
4. Переписать apply templates.
5. Добавить letter validator.
6. Добавить `briefing` command.
7. Добавить `briefing_reports` и `vacancy_events`.
8. Прогнать smoke fixtures.

### P1 — следующий блок

1. Cockpit 2.0.
2. Notion outbox + sync.
3. Wizard enhancements.
4. Search-lab calibration for new presets.
5. Weekly report.
6. Better analytics by role type.

### P2 — после стабилизации

1. OAuth read-only.
2. Negotiations sync.
3. Resume sync.
4. Status reconciliation.
5. HR reply helper.

### P3 — только если нужно

1. Browser handoff to VacancyPilot.
2. Apply assist.
3. Telegram digest.
4. Multi-market expansion: Казахстан, LinkedIn manual import, TG channels.

---

## 15. Риски проекта

| Риск | Уровень | Митигирование |
|---|---|---|
| блокировка HH API из-за частых запросов | высокий | safe modes, budget, delay, stop on 429 |
| утечка токена | высокий | keyring, masking, `.env` в gitignore |
| слабые письма | высокий | validator, новые шаблоны, banned phrases |
| расползание в автоотклик | высокий | no-auto-apply policy, feature flags |
| слишком широкий поиск | средний | search-lab, preset calibration |
| много false positive AI/ML вакансий | средний | ML/Data Science exclude rules |
| Notion дубли | средний | dedupe by vacancy_id |
| OAuth сложность | средний | read-only first, V2 отдельно |
| выдуманные claims в письмах | высокий | candidate.yaml as source of truth |

---

## 16. Roadmap по коммитам

### Commit 1

```text
docs: add HH Job Radar final technical specification
```

### Commit 2

```text
config: refresh candidate profile for CRM and AI automation search
```

### Commit 3

```text
config: add career search presets for CRM, Bitrix24 and AI automation
```

### Commit 4

```text
feat: add cover letter validator
```

### Commit 5

```text
config: replace apply templates with role-specific letters
```

### Commit 6

```text
feat: add briefing generator and CLI command
```

### Commit 7

```text
db: add briefing reports, vacancy events and integration outbox
```

### Commit 8

```text
feat: save briefing reports and review drafts
```

### Commit 9

```text
feat: add Notion webhook outbox sync
```

### Commit 10

```text
feat: enhance cockpit dashboard for daily radar workflow
```

### Commit 11

```text
test: add golden fixtures for vacancy briefing and letter validation
```

---

## 17. Daily runbook после V1

```powershell
# 1. Проверить окружение
python -m src.main health

# 2. Ежедневный безопасный поиск
python -m src.main wizard daily --mode normal

# 3. Посмотреть очередь
python -m src.main review queue --min-score 70 --limit 20 --dedupe

# 4. Сделать briefing по лучшим
python -m src.main briefing --top 5 --min-score 80 --save-review --export

# 5. Открыть cockpit
python -m src.main cockpit open

# 6. Ручной отклик на HH
# после отправки:
python -m src.main review apply VACANCY_ID --date today

# 7. Follow-up
python -m src.main review next VACANCY_ID --action follow-up --date +7bd

# 8. Notion sync
python -m src.main notion-sync push --limit 10
```

---

## 18. Финальная целевая формула

Проект должен давать не “много откликов”, а управляемый поток качественных действий:

```text
найти быстрее
отфильтровать жёстче
оценить честнее
написать точнее
откликнуться вручную
не потерять follow-up
накопить аналитику рынка
```

Финальная модель:

```text
CareerSignal HH = backend radar + scoring + tracker
VacancyPilot = будущий браузерный read-only UI
n8nnotion = Notion delivery layer
OAuth = read-only sync, не автоотклик
```

---

## 19. Приложение A — формат briefing JSON

```json
{
  "vacancy_id": "123",
  "score": {
    "total": 86,
    "stack_fit": 23,
    "level_fit": 18,
    "ai_automation": 15,
    "market_fit": 16,
    "personal_risk": 14,
    "verdict": "Откликаться",
    "priority": "В"
  },
  "red_flags": [
    {"name": "salary_missing", "explanation": "Зарплата не указана"}
  ],
  "gaps": [
    {
      "requirement": "Power BI",
      "status": "частично",
      "interview_phrase": "Операционную отчётность в Битрикс24 закрывал, внешние BI-интеграции через API понимаю; нюансы конкретного BI закрою быстро."
    }
  ],
  "letter": "...",
  "interview_questions": [],
  "objections": [],
  "keywords": {
    "technical": [],
    "process": [],
    "context": []
  },
  "follow_up": "...",
  "log": {}
}
```

---

## 20. Приложение B — hard red flags

```yaml
hard_red_flags:
  title:
    - sales manager
    - менеджер по продажам
    - account manager
    - support specialist
    - специалист поддержки
    - call center
    - оператор
    - ml engineer
    - data scientist
    - qa automation
    - php developer
  description:
    - холодные звонки
    - обзвон
    - работа в офисе без удаленного формата
    - командировки обязательны
    - график 6/1
    - unpaid internship
    - стажировка без оплаты
    - casino
    - gambling
```

---

## 21. Приложение C — recommended first implementation sprint

### Sprint 1: 3–5 рабочих дней

#### День 1

- baseline freeze;
- обновить candidate.yaml;
- добавить search presets;
- presets validate;
- dry-run smoke.

#### День 2

- переписать apply templates;
- добавить letter validator;
- тесты banned phrases / word count / AI trigger.

#### День 3

- добавить briefing generator;
- добавить CLI command;
- экспорт markdown;
- save-review.

#### День 4

- миграции: briefing_reports, vacancy_events;
- golden fixtures;
- smoke flow.

#### День 5

- cockpit improvements;
- Notion outbox dry-run;
- документация runbook;
- финальный тест.

### Sprint 1 DoD

```powershell
python -m src.main doctor
python -m src.main health
python -m src.main presets validate
python -m src.main search --dry-run --mode smoke
python -m src.main import vacancy --title "Системный аналитик CRM" --company "Demo" --url "https://hh.ru/vacancy/demo" --description "Битрикс24 REST API интеграции 1С CRM"
python -m src.main score rescore
python -m src.main briefing demo --save-review --export
python -m src.main review draft demo
python -m src.main cockpit export
pytest -q
```

---

# Конец ТЗ
