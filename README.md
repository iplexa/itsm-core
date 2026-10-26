# itsm-core

[![Python package](https://github.com/OWNER/itsm-core/actions/workflows/package.yml/badge.svg)](https://github.com/OWNER/itsm-core/actions/workflows/package.yml)

Лицензия: GNU GPL версии 3 или более поздней — см. [LICENSE](LICENSE).

Небольшой асинхронный Python-клиент для Help/SimpleOne. В пакете оставлены
только общие возможности интеграции: авторизация, REST Table API, пагинация,
сбор условий, чтение заявок и ленты комментариев, создание и обновление записей.
Клиент не содержит групп, пользователей, статусов, кодов закрытия или правил
конкретного подразделения.

## Установка

Требуется Python 3.12 или новее.

Из клона репозитория:

```bash
python -m pip install .
```

Для разработки с редактируемой установкой:

```bash
python -m pip install -e .
```

Как зависимость из отдельного GitHub-репозитория:

```bash
python -m pip install "itsm-core @ git+https://github.com/OWNER/itsm-core.git@v0.1.0"
```

Замените `OWNER` на организацию или пользователя GitHub и укажите опубликованный
тег версии. Для приватного GitHub-репозитория настройте SSH-доступ либо токен
в CI/среде установки.

## Подключение

Скопируйте `.env.example` в `.env` и укажите адрес Help и сервисную учётную
запись. Переменные окружения перекрывают значения из `.env`.

```python
import asyncio
from datetime import datetime

from itsm_core import HelpClient, REMClient, Settings, SimpleOneTransport


async def main() -> None:
    settings = Settings(
        base_url="https://help.example.com",
        username="service-account",
        password="получить-из-хранилища-секретов",
        timeout=30,
    )
    async with HelpClient(SimpleOneTransport(settings)) as help_api:
        requests = await help_api.list_requests(
            created_after=datetime(2026, 1, 1),
            states=["1", "4"],
            assignment_group="GROUP_SYS_ID",
            limit=50,
        )
        if requests:
            record = await help_api.get_record("itsm_request", requests[0]["sys_id"])
            print(record)
            rem = REMClient(help_api.transport)
            printer_id = await rem.get_record_value(
                record,
                "printer",
                model_field="related_request_model",
            )
            print("printer sys_id:", printer_id)


asyncio.run(main())
```

Контекстный менеджер устанавливает сессию через `POST /v1/auth/login` и
закрывает HTTP-клиент при выходе. На 401/403 выполняется повторная авторизация;
временные сетевые ошибки и ответы 429/5xx повторяются ограниченное число раз.

## Операции

### Таблицы

```python
# Одна страница; condition — строка sysparm_query.
rows = await help_api.list_records(
    "sys_cmdb_ci_service", "active=1", limit=100, page=1
)

# Все страницы (с защитой от повторной страницы).
rows = await help_api.list_all_records(
    "sys_cmdb_ci_service", "active=1", page_size=100, max_records=1000
)

record = await help_api.get_record("itsm_request", "RECORD_SYS_ID")
created = await help_api.create_record("itsm_request", {"subject": "Тема"})
updated = await help_api.update_record(
    "itsm_request", "RECORD_SYS_ID", {"additional_comments": "Комментарий"}
)
```

### Условия запроса

```python
from itsm_core.query import Query

condition = (
    Query()
    .eq("active", "1")
    .in_("state", ["1", "2"])
    .order_by("sys_created_at", desc=True)
    .build()
)
rows = await help_api.list_records("itsm_request", condition)
```

Доступны `eq`, `ne`, `gt`, `lt`, `like`, `not_like`, `in_`, `is_empty`,
`is_not_empty`, `raw`, `order_by`. SimpleOne может молча проигнорировать
неизвестное имя поля и вернуть слишком широкий результат, поэтому проверяйте
выборку и корректность полей.

### Переписка

```python
replies = await help_api.get_replies(
    "RECORD_SYS_ID",
    since=datetime(2026, 1, 1),
    activity_type_id="ACTIVITY_TYPE_SYS_ID",
)
```

`activity_type_id` зависит от настройки конкретного Help-инстанса и передаётся
явно. Ответы возвращаются как список словарей с `author`, `message` и
`sys_created_at`.

## REM-атрибуты

REM-значения хранятся отдельно от обычных полей записи. `REMClient` находит
описание в `sys_re_attribute`, определяет тип через `sys_db_column_type`, затем
читает/обновляет строку в соответствующей `sys_re_attribute_value_<type>`:

```python
rem = REMClient(help_api.transport)
model_id = "MODEL_SYS_ID"
record_id = "REQUEST_SYS_ID"

definitions = await rem.list_definitions(model_id)
printer_sys_id = await rem.get_value(record_id, model_id, "printer")
users = await rem.get_value(record_id, model_id, "who_grant_access_to_printer")

# Значение передаётся как сырое значение SimpleOne. Для List это обычно
# sys_id через запятую; для Reference — один sys_id.
await rem.set_value(record_id, model_id, "printer", "PRINTER_SYS_ID")
```

Для записи с полем-ссылкой на модель можно использовать `get_record_value`;
по умолчанию это `related_request_model`. Сопоставление типов со storage-
таблицами содержит стандартные типы SimpleOne; также учитываются скалярные
типы, если они присутствуют в записи `sys_db_column_type`. Если инстанс
использует другое имя, передайте `value_table_map={"type name": "suffix"}`
при создании `REMClient`. Метаданные и значение доступны сервисной учётной
записи через Table API. REM-модели SimpleOne имеют ограничения по доступным
типам; для неподдерживаемого или неизвестного типа клиент сообщит об ошибке.

## Настройки

Можно передать `Settings` явно или использовать `get_settings()` для чтения
переменных окружения и `.env`:

```python
from itsm_core import HelpClient, SimpleOneTransport, get_settings

settings = get_settings()
async with HelpClient(SimpleOneTransport(settings)) as help_api:
    requests = await help_api.list_requests(limit=20)
```

| Переменная | Назначение |
| --- | --- |
| `HELP_BASE_URL` | Корневой URL Help, без завершающего `/` |
| `HELP_SERVICE_USERNAME` | Логин сервисной учётной записи |
| `HELP_SERVICE_PASSWORD` | Пароль сервисной учётной записи |
| `HELP_TIMEOUT` | Общий таймаут в секундах (по умолчанию 60) |

Не храните реальные пароли в исходном коде и не передавайте их в логах.
Сервисной учётной записи нужны права только на используемые таблицы и поля.

## Состав пакета

- `transport.py` — HTTP-транспорт, авторизация, retry и типы ошибок.
- `table_api.py` — Table API, CRUD и постраничная загрузка.
- `help_client.py` — простой интерфейс для интеграции и заявок.
- `rem.py` — универсальное чтение и запись типизированных REM-значений.
- `query.py` — построитель `sysparm_query`.
- `config.py` — настройки без сторонних зависимостей.

Пакет не кодирует локальные бизнес-правила Help. Состав полей записи, значения
состояний, идентификаторы групп, пользователей и специфичные действия следует
определять в приложении, которое использует клиент. Передавайте всю папку
`itsm-core`, исключая `.env` с реальными секретами.

## Подготовка релиза

Версия пакета задаётся в `pyproject.toml`. Для релиза обновите её, проверьте
сборку wheel, создайте git-тег вида `vX.Y.Z` и опубликуйте релиз в GitHub.
CI при push и pull request собирает wheel и проверяет импорт установленного
пакета. Перед загрузкой в отдельный репозиторий замените `OWNER` в бейдже на
имя пользователя или организации GitHub.
