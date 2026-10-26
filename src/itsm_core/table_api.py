"""Table REST API SimpleOne: /rest/v1/table/{table}.

Пагинация делается ТОЛЬКО через sysparm_page (нумерация с единицы).
sysparm_offset платформа принимает, отвечает 200 и молча игнорирует — каждая
«страница» приходит одинаковой, поэтому листание им даёт дубликаты вместо
следующих записей. На всякий случай ниже стоит и защита от повтора страницы.
"""

from __future__ import annotations

import logging
from typing import Any

from itsm_core.transport import ITSMResponseError, SimpleOneTransport

logger = logging.getLogger(__name__)

TABLE_PATH = "/rest/v1/table/{table}"
DEFAULT_PAGE_SIZE = 100
MAX_PAGES = 500


class TableAPI:
    """Тонкая обёртка CRUD поверх транспорта."""

    def __init__(self, transport: SimpleOneTransport) -> None:
        self._transport = transport

    @property
    def transport(self) -> SimpleOneTransport:
        return self._transport

    @staticmethod
    def _path(table: str, sys_id: str = "") -> str:
        base = TABLE_PATH.format(table=table)
        return f"{base}/{sys_id}" if sys_id else base

    async def list(
        self,
        table: str,
        condition: str = "",
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        page: int = 1,
        exclude_reference_link: bool = True,
    ) -> list[dict[str, Any]]:
        """Одна страница выборки."""
        params: dict[str, Any] = {"sysparm_limit": limit, "sysparm_page": page}
        if condition:
            params["sysparm_query"] = condition
        if exclude_reference_link:
            params["sysparm_exclude_reference_link"] = "true"
        return await self._transport.request("GET", self._path(table), params=params)

    async def list_all(
        self,
        table: str,
        condition: str = "",
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_records: int | None = None,
    ) -> list[dict[str, Any]]:
        """Полная выборка постранично, с защитой от повтора страницы."""
        collected: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1

        while page <= MAX_PAGES:
            rows = await self.list(table, condition, limit=page_size, page=page)
            if not rows:
                break

            fresh = [row for row in rows if str(row.get("sys_id", "")) not in seen]
            if not fresh:
                # Платформа вернула ту же страницу — дальше листать бессмысленно.
                logger.warning(
                    "Пагинация %s остановлена: страница %d повторяет предыдущие записи",
                    table,
                    page,
                )
                break

            for row in fresh:
                sys_id = str(row.get("sys_id", ""))
                if sys_id:
                    seen.add(sys_id)
                collected.append(row)
                if max_records is not None and len(collected) >= max_records:
                    return collected[:max_records]

            if len(rows) < page_size:
                break
            page += 1

        return collected

    async def get(self, table: str, sys_id: str) -> dict[str, Any]:
        rows = await self._transport.request("GET", self._path(table, sys_id))
        return rows[0] if rows else {}

    async def create(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST с плоским телом. Возвращает созданную запись."""
        rows = await self._transport.request("POST", self._path(table), json=payload)
        if not rows:
            raise ITSMResponseError(
                f"Создание записи в {table} не вернуло данных — sys_id неизвестен"
            )
        return rows[0]

    async def update(self, table: str, sys_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """PATCH с плоским телом; поля и правила валидации задаёт вызывающий код."""
        rows = await self._transport.request("PATCH", self._path(table, sys_id), json=payload)
        return rows[0] if rows else {}

    async def options(self, table: str, sys_id: str = "") -> str:
        """Разрешённые глаголы — для разведки прав на таблицу."""
        response = await self._transport.request_raw("OPTIONS", self._path(table, sys_id))
        return response.headers.get("allow", "") or response.headers.get("Allow", "")
