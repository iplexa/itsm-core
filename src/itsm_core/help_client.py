"""Convenience client for Help/SimpleOne tables and request records."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from itsm_core.query import Query
from itsm_core.table_api import TableAPI
from itsm_core.transport import SimpleOneTransport, ref_id


class HelpClient:
    """Async Help/SimpleOne client. Use as an async context manager."""

    def __init__(self, transport: SimpleOneTransport) -> None:
        self.transport = transport
        self.api = TableAPI(transport)

    async def __aenter__(self) -> HelpClient:
        await self.transport.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.transport.close()

    async def list_records(
        self,
        table: str,
        condition: str = "",
        *,
        limit: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        return await self.api.list(table, condition, limit=limit, page=page)

    async def list_all_records(
        self,
        table: str,
        condition: str = "",
        *,
        page_size: int = 100,
        max_records: int | None = None,
    ) -> list[dict[str, Any]]:
        return await self.api.list_all(
            table, condition, page_size=page_size, max_records=max_records
        )

    async def get_record(self, table: str, sys_id: str) -> dict[str, Any]:
        return await self.api.get(table, sys_id)

    async def create_record(self, table: str, fields: dict[str, Any]) -> dict[str, Any]:
        return await self.api.create(table, fields)

    async def update_record(
        self, table: str, sys_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.api.update(table, sys_id, fields)

    async def list_requests(
        self,
        *,
        table: str = "itsm_request",
        created_after: datetime | None = None,
        states: list[str] | None = None,
        assignment_group: str | None = None,
        limit: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        query = Query()
        if created_after:
            query.gt("sys_created_at", created_after.strftime("%Y-%m-%d %H:%M:%S"))
        if states:
            query.in_("state", states)
        if assignment_group:
            query.eq("assignment_group", assignment_group)
        query.order_by("sys_created_at", desc=True)
        return await self.api.list(table, query.build(), limit=limit, page=page)

    async def get_replies(
        self,
        record_sys_id: str,
        *,
        since: datetime,
        activity_type_id: str,
        table: str = "sys_activity_feed_item",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read comment feed entries; activity_type_id is instance-specific."""
        condition = (
            f"record_id={record_sys_id}^type_id={activity_type_id}"
            f"^sys_created_at>{since:%Y-%m-%d %H:%M:%S}^ORDERBYsys_created_at"
        )
        rows = await self.api.list(table, condition, limit=limit)
        replies = []
        for row in rows:
            raw = row.get("content")
            try:
                content = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                continue
            if isinstance(content, dict) and "message" in content:
                replies.append({
                    "author": str(content.get("author") or ""),
                    "message": str(content.get("message") or ""),
                    "sys_created_at": row.get("sys_created_at"),
                })
        return replies


__all__ = ["HelpClient", "ref_id"]
