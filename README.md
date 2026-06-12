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
HH_USER_AGENT=CareerSignalHH/0.1 (contact: your-email@example.com)
DB_PATH=data/vacancies.sqlite
REQUEST_DELAY_MIN=0.3
REQUEST_DELAY_MAX=0.7
```

Для `User-Agent` желательно указать реальный контакт согласно рекомендациям
API. Дополнительных runtime-зависимостей сверх заданных нет. `pytest` включён
в `requirements.txt` для простого локального MVP.

## Запуск

Показать запросы без обращения к API:

```powershell
python -m src.main search --dry-run
```

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
```

Экспорт можно фильтровать:

```powershell
python -m src.main export --min-score 35 --profile ai_automation --days 14
```

Файлы создаются в:

- `exports/vacancies_report.html` — автономный тёмный отчёт с фильтрами;
- `exports/vacancies.csv` — таблица для ручного трекера;
- `exports/vacancies.jsonl` — нормализованные данные и scoring;
- `data/vacancies.sqlite` — локальная база.

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

## Правила scoring

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

`src/hh_client.py` отвечает только за публичный HTTP API, `src/storage.py` —
за SQLite и idempotent upsert, `src/scoring.py` — за правила, а экспортеры не
зависят от сети. `first_seen_at` при обновлении не перезаписывается; подробности
и score пересчитываются.

Одна ошибка запроса или вакансии записывается в `search_runs` и не останавливает
весь запуск. При HTTP 429 клиент делает до двух повторов с backoff.

## Тесты

```powershell
python -m pytest
python -m src.main --help
python -m src.main search --dry-run --profile ai_automation --max-pages 1
```

## Будущий OAuth-режим

Публичный режим можно сохранить без изменений, добавив отдельный authorized
client, `client_id`/`client_secret`, безопасное token storage и явные команды
для разрешённых OAuth-операций. Авторизованный клиент не должен подменять
текущий `HHClient`: это позволит не ломать публичный поиск и экспорт.
