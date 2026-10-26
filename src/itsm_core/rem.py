"""Generic access to SimpleOne Record Extended Model (REM) attributes."""

from __future__ import annotations

from typing import Any

from itsm_core.table_api import TableAPI
from itsm_core.transport import SimpleOneTransport, ref_id

ATTRIBUTE_TABLE = "sys_re_attribute"
ATTRIBUTE_TYPE_TABLE = "sys_db_column_type"
MODEL_COLLECTION_TABLE = "sys_re_model_collection"
VALUE_TABLE_PREFIX = "sys_re_attribute_value_"

# Logical attribute type -> scalar storage table suffix. Deployments can extend
# or override this map because SimpleOne versions and configured types vary.
DEFAULT_VALUE_TABLES = {
    "reference": "int8",
    "field name": "int8",
    "image": "int8",
    "record class": "int8",
    "list": "varchar",
    "string": "varchar",
    "translated text": "varchar",
    "choice": "varchar",
    "password": "varchar",
    "url": "varchar",
    "encrypted password": "varchar",
    "text": "text",
    "html": "text",
    "script": "text",
    "conditions": "text",
    "template": "json",
    "boolean": "boolean",
    "true/false": "boolean",
    "small integer": "int2",
    "integer": "int4",
    "big integer": "int8",
    "float": "double",
    "decimal": "decimal",
    "date": "date",
    "date/time": "timestamp",
    "datetime": "timestamp",
    "time": "time",
}


class REMError(RuntimeError):
    """REM metadata or value could not be read or written safely."""


class REMClient:
    """Read and write REM values by model and attribute system name.

    ``value_table_map`` allows an instance/version-specific storage mapping.
    Values are passed through as raw SimpleOne scalar values; reference/list
    identifiers should be supplied as sys_id strings (lists as comma-separated
    sys_ids unless the instance documents another encoding).
    """

    def __init__(
        self,
        transport: SimpleOneTransport,
        *,
        value_table_map: dict[str, str] | None = None,
    ) -> None:
        self._transport = transport
        self._api = TableAPI(transport)
        self._value_tables = {**DEFAULT_VALUE_TABLES, **(value_table_map or {})}
        self._definitions: dict[str, dict[str, dict[str, Any]]] = {}
        self._type_names: dict[str, str] = {}
        self._type_records: dict[str, dict[str, Any]] = {}

    async def get_definition(self, model_id: str, attribute_name: str) -> dict[str, Any]:
        definitions = await self._load_definitions(model_id)
        definition = definitions.get(attribute_name)
        if definition is None:
            raise REMError(
                f"REM-атрибут {attribute_name!r} не найден в модели {model_id}"
            )
        return definition

    async def list_definitions(self, model_id: str) -> list[dict[str, Any]]:
        """Return active attribute definitions for a model."""
        return list((await self._load_definitions(model_id)).values())

    async def get_record_value(
        self,
        record: dict[str, Any],
        attribute_name: str,
        *,
        model_field: str = "related_request_model",
    ) -> Any | None:
        """Read an attribute when the record contains the REM model reference."""
        model_id = ref_id(record.get(model_field))
        record_id = str(record.get("sys_id") or "")
        if not model_id or not record_id:
            raise REMError(f"Не удалось определить sys_id записи или модели ({model_field})")
        return await self.get_value(record_id, model_id, attribute_name)

    async def _load_definitions(self, model_id: str) -> dict[str, dict[str, Any]]:
        definitions = self._definitions.get(model_id)
        if definitions is None:
            container_ids = [model_id]
            collections = await self._api.list(
                MODEL_COLLECTION_TABLE, f"re_model_id={model_id}", limit=1000
            )
            container_ids.extend(
                collection_id
                for row in collections
                if (collection_id := ref_id(row.get("re_collection_id")))
            )
            definitions = {}
            for container_id in dict.fromkeys(container_ids):
                rows = await self._api.list(
                    ATTRIBUTE_TABLE,
                    f"re_container_id={container_id}^active=true",
                    limit=1000,
                )
                definitions.update({
                    str(row.get("column_name")): row
                    for row in rows
                    if row.get("column_name")
                })
            self._definitions[model_id] = definitions
        return definitions

    async def get_value(
        self,
        record_id: str,
        model_id: str,
        attribute_name: str,
    ) -> Any | None:
        definition = await self.get_definition(model_id, attribute_name)
        table = await self._value_table(definition)
        rows = await self._api.list(
            table,
            f"record_id={record_id}^re_attribute_id={definition.get('sys_id', '')}",
            limit=10,
        )
        if len(rows) > 1:
            raise REMError(
                f"Для REM-атрибута {attribute_name!r} найдено несколько значений"
            )
        return rows[0].get("value") if rows else None

    async def set_value(
        self,
        record_id: str,
        model_id: str,
        attribute_name: str,
        value: Any,
    ) -> dict[str, Any]:
        """Create or update one REM value row using its typed storage table."""
        definition = await self.get_definition(model_id, attribute_name)
        table = await self._value_table(definition)
        condition = (
            f"record_id={record_id}^re_attribute_id={definition.get('sys_id', '')}"
        )
        rows = await self._api.list(table, condition, limit=10)
        if len(rows) > 1:
            raise REMError(
                f"Для REM-атрибута {attribute_name!r} найдено несколько значений"
            )
        payload = {
            "record_id": record_id,
            "re_attribute_id": str(definition.get("sys_id") or ""),
            "value": value,
        }
        if rows:
            row_id = str(rows[0].get("sys_id") or "")
            if not row_id:
                raise REMError("У существующей строки REM-значения отсутствует sys_id")
            return await self._api.update(table, row_id, {"value": value})
        return await self._api.create(table, payload)

    async def _value_table(self, definition: dict[str, Any]) -> str:
        type_id = ref_id(definition.get("column_type_id"))
        if not type_id:
            raise REMError("У REM-атрибута отсутствует column_type_id")
        type_name = self._type_names.get(type_id)
        type_record = self._type_records.get(type_id)
        if type_record is None:
            type_record = await self._api.get(ATTRIBUTE_TYPE_TABLE, type_id)
            self._type_records[type_id] = type_record
            type_name = str(type_record.get("name") or type_record.get("title") or type_record.get("label") or "").strip()
            if not type_name:
                raise REMError(f"Не удалось определить тип REM-атрибута ({type_id})")
            self._type_names[type_id] = type_name
        else:
            type_name = type_name or str(type_record.get("name") or "")
        scalar_type = str(
            type_record.get("scalar_type")
            or type_record.get("database_type")
            or type_record.get("db_type")
            or type_record.get("value_type")
            or type_record.get("column_type")
            or ""
        ).casefold().strip()
        suffix = scalar_type or self._value_tables.get(type_name.casefold())
        if not suffix:
            # Some instances expose the scalar storage name as the type name.
            scalar_names = {
                "int2", "int4", "int8", "varchar", "text", "double",
                "decimal", "boolean", "date", "timestamp", "time", "json",
            }
            if type_name.casefold() in scalar_names:
                suffix = type_name.casefold()
        if not suffix or not suffix.replace("_", "").isalnum():
            raise REMError(
                f"Тип REM {type_name!r} не сопоставлен таблице значений; "
                "передайте value_table_map в REMClient"
            )
        return f"{VALUE_TABLE_PREFIX}{suffix}"


__all__ = ["DEFAULT_VALUE_TABLES", "REMClient", "REMError"]
