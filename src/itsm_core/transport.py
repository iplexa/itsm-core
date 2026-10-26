"""HTTP-транспорт до SimpleOne.

Авторизация — POST /v1/auth/login логином и паролём; сессия живёт в cookie
клиента httpx, тело ответа не парсится. На 401/403 делается один перелогин и
один повтор запроса.
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Any

import httpx

from itsm_core.config import Settings, get_settings

logger = logging.getLogger(__name__)

RETRIABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 3


class ITSMError(RuntimeError):
    """Базовая ошибка работы с ITSM."""


class ITSMAuthError(ITSMError):
    """Не удалось авторизоваться."""


class ITSMResponseError(ITSMError):
    """Платформа ответила ошибкой в конверте либо неразбираемым телом."""


def ref_id(value: Any) -> str:
    """sys_id из ссылочного поля.

    Table API возвращает ссылки как {"value": sys_id, "link": url}, а форменный
    API — как {"database_value": ..., "display_value": ...}. Принимаем оба.
    """
    if isinstance(value, dict):
        return str(value.get("value") or value.get("database_value") or "")
    return str(value or "")


def display_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("display_value") or value.get("value") or "")
    return str(value or "")


def rows_of(body: Any) -> list[dict[str, Any]]:
    """Разбирает конверт {"status", "data", "errors"} в список записей."""
    data = body.get("data") if isinstance(body, dict) else body
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


class SimpleOneTransport:
    """Асинхронный клиент с cookie-сессией и реактивным перелогином."""

    def __init__(self, settings: Settings | None = None, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self._authenticated = client is not None
        self._login_lock = asyncio.Lock()

    @property
    def settings(self) -> Settings:
        return self._settings

    async def __aenter__(self) -> SimpleOneTransport:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.base_url,
                timeout=httpx.Timeout(self._settings.timeout, connect=15.0),
                headers={"Accept": "application/json, text/plain, */*"},
            )
            self._owns_client = True
        if not self._authenticated:
            await self.login()

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None
        self._authenticated = False

    async def login(self) -> None:
        username, password = self._settings.require_credentials()
        client = self._require_client()
        try:
            response = await client.post(
                "/v1/auth/login",
                json={"username": username, "password": password},
            )
        except httpx.HTTPError as exc:
            raise ITSMAuthError(f"Не удалось выполнить вход: {exc}") from exc
        if response.status_code >= 400:
            raise ITSMAuthError(
                f"Вход отклонён ({response.status_code}). Проверьте "
                f"HELP_SERVICE_USERNAME / HELP_SERVICE_PASSWORD."
            )
        self._authenticated = True
        logger.debug("Авторизация в ITSM выполнена")

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise ITSMError("Транспорт не подключён — вызовите connect()")
        return self._client

    async def request_raw(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Запрос с перелогином на 401/403 и повторами на 5xx."""
        client = self._require_client()
        if not self._authenticated:
            await self.login()

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES - 1:
                    raise ITSMError(f"{method} {url}: {exc}") from exc
                await asyncio.sleep(2**attempt)
                continue

            if response.status_code in {401, 403}:
                # Сессия истекла — один перелогин и один повтор.
                async with self._login_lock:
                    await self.login()
                response = await client.request(method, url, **kwargs)

            if response.status_code in RETRIABLE_STATUS and attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2**attempt)
                continue

            return response

        raise ITSMError(f"{method} {url}: исчерпаны попытки") from last_exc

    async def request(self, method: str, url: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Запрос с разбором конверта в список записей."""
        response = await self.request_raw(method, url, **kwargs)
        if response.status_code >= 400:
            raise ITSMResponseError(
                f"{method} {url} → {response.status_code}: {response.text[:500]}"
            )
        if not response.content:
            return []
        try:
            body = response.json()
        except ValueError as exc:
            raise ITSMResponseError(
                f"{method} {url}: ответ не является JSON: {response.text[:200]}"
            ) from exc
        if isinstance(body, dict) and body.get("status") == "ERROR":
            raise ITSMResponseError(str(body.get("errors") or body))
        return rows_of(body)
