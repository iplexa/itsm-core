"""Сборка condition-строк SimpleOne.

Синтаксис подсмотрен в боевых запросах: термы соединяются `^`, значения для
`IN` — через `@`, сортировка приписывается суффиксом `ORDERBY`/`ORDERBYDESC`.

ВАЖНО: платформа не проверяет имена полей. Запрос с опечаткой в имени поля
возвращает НЕотфильтрованный набор записей вместо ошибки, поэтому результат
любого поиска обязан перепроверяться на стороне клиента.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"


def fmt_datetime(value: datetime) -> str:
    return value.strftime(DATETIME_FORMAT)


def fmt_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


class Query:
    """Накопитель термов условия. Методы возвращают self для цепочек."""

    def __init__(self) -> None:
        self._terms: list[str] = []
        self._order: str = ""

    def eq(self, field: str, value: str) -> Query:
        self._terms.append(f"{field}={value}")
        return self

    def ne(self, field: str, value: str) -> Query:
        self._terms.append(f"{field}!={value}")
        return self

    def gt(self, field: str, value: str) -> Query:
        self._terms.append(f"{field}>{value}")
        return self

    def lt(self, field: str, value: str) -> Query:
        self._terms.append(f"{field}<{value}")
        return self

    def like(self, field: str, value: str) -> Query:
        self._terms.append(f"{field}LIKE{value}")
        return self

    def not_like(self, field: str, value: str) -> Query:
        self._terms.append(f"{field}NOTLIKE{value}")
        return self

    def in_(self, field: str, values: Iterable[str]) -> Query:
        joined = "@".join(str(v) for v in values)
        self._terms.append(f"{field}IN{joined}")
        return self

    def is_empty(self, field: str) -> Query:
        self._terms.append(f"{field}ISEMPTY")
        return self

    def is_not_empty(self, field: str) -> Query:
        self._terms.append(f"{field}ISNOTEMPTY")
        return self

    def raw(self, term: str) -> Query:
        self._terms.append(term)
        return self

    def order_by(self, field: str, *, desc: bool = False) -> Query:
        self._order = f"ORDERBYDESC{field}" if desc else f"ORDERBY{field}"
        return self

    def build(self) -> str:
        parts = list(self._terms)
        if self._order:
            parts.append(self._order)
        return "^".join(parts)

    def __str__(self) -> str:
        return self.build()
