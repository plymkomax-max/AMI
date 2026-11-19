"""Импорт объявлений из CSV и Excel.

Поддерживаются:
* UTF-8 (с BOM и без), cp1251 (Excel в русской локали);
* разделители ``,``, ``;``, tab, ``|``;
* русские и английские заголовки;
* даты в форматах ISO и ``dd.mm.yyyy``;
* строковые числа и цены вида ``12 500 ₽``;
* .xlsx (первый лист, первая строка — заголовки).

Каждая строка импортируется в отдельном SAVEPOINT: ошибка одной строки
не отравляет сессию и не роняет весь запрос.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logger import get_logger
from app.services.listing_service import (
    as_int,
    as_list,
    normalize_price,
    parse_datetime,
    upsert_listing,
)
from app.services.matcher import ProductMatcher

log = get_logger("services.importer")

# Синонимы колонок -> каноническое поле.
COLUMN_MAP: dict[str, list[str]] = {
    "external_id": ["external_id", "item_id", "listing_id", "id", "номер"],
    "title": ["title", "name", "заголовок", "название"],
    "description": ["description", "описание", "desc"],
    "price": ["price", "цена", "стоимость", "cost", "amount"],
    "currency": ["currency", "валюта"],
    "condition": ["condition", "состояние", "state"],
    "usage_time": ["usage_time", "срок_использования", "usage"],
    "city": ["city", "город", "location"],
    "region": ["region", "регион"],
    "url": ["url", "link", "ссылка"],
    "published_at": ["published_at", "дата", "date", "дата_публикации"],
    "expired_at": ["expired_at", "снято", "дата_снятия"],
    "defects": ["defects", "дефекты", "неисправности"],
    "includes": ["includes", "комплектация"],
    "seller_type": ["seller_type", "продавец", "тип_продавца"],
    "view_count": ["view_count", "просмотры", "views"],
    "fav_count": ["fav_count", "в_избранном", "favorites"],
    "product_id": ["product_id", "id_товара", "модель_id"],
}


def _normalize_header(value: str) -> str:
    """'Цена (руб.)' -> 'цена_руб'."""
    text = (value or "").strip().lower().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    # cp1251 декодирует любые байты; используем как последний вариант
    return content.decode("cp1251", errors="replace")


def detect_delimiter(sample: str) -> str:
    """Определяет разделитель CSV; по умолчанию — запятая."""
    sample = sample[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {delimiter: sample.count(delimiter) for delimiter in ",;\t|"}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","


def _find_col(headers: list[str], aliases: list[str]) -> str | None:
    """Ищет колонку по синонимам: сначала точное совпадение, затем префикс."""
    normalized = [(_normalize_header(header), header) for header in headers]
    normalized_aliases = [_normalize_header(alias) for alias in aliases]

    for alias in normalized_aliases:
        for header_norm, original in normalized:
            if header_norm == alias:
                return original

    for alias in normalized_aliases:
        for header_norm, original in normalized:
            if header_norm.startswith(alias + "_"):
                return original
    return None


def _build_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for field, aliases in COLUMN_MAP.items():
        column = _find_col(headers, aliases)
        if column:
            mapping[field] = column
    return mapping


def _parse_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field, column in mapping.items():
        raw = row.get(column)
        if raw is None:
            continue
        if isinstance(raw, str):
            value: Any = raw.strip()
        else:
            value = raw
        if value == "":
            continue

        if field in ("includes", "defects"):
            data[field] = as_list(value)
        elif field == "price":
            data[field] = normalize_price(value)
        elif field in ("published_at", "expired_at"):
            data[field] = parse_datetime(value, field)
        elif field in ("view_count", "fav_count"):
            data[field] = as_int(value)
        elif field == "product_id":
            try:
                data[field] = int(float(value))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Некорректный product_id: {value!r}") from exc
        else:
            data[field] = str(value).strip()
    return data


def _generated_external_id(data: dict[str, Any], source: str) -> str:
    """Стабильный id для выгрузки без external_id.

    Цена намеренно не входит в ключ: при повторной выгрузке с новой ценой
    объявление обновится, а не продублируется.
    """
    title = re.sub(r"\s+", " ", str(data.get("title") or "").strip().lower())
    key = "|".join(
        [
            source,
            title,
            str(data.get("city") or "").strip().lower(),
            str(data.get("seller_type") or "").strip().lower(),
        ]
    )
    return "gen_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _records_from_rows(
    rows: Iterable[dict[str, Any]],
    mapping: dict[str, str],
    source: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: dict[str, int] = {}

    for index, row in enumerate(rows, start=1):
        if index > settings.max_csv_rows:
            raise ValueError(f"Файл содержит больше {settings.max_csv_rows} строк")

        data = _parse_row(row, mapping)
        if not data.get("title") and not data.get("external_id"):
            continue
        if not data.get("external_id"):
            data["external_id"] = _generated_external_id(data, source)

        external_id = str(data["external_id"])
        # Внутри одного файла дубликаты схлопываем: побеждает последняя строка
        if external_id in seen:
            records[seen[external_id]] = data
        else:
            seen[external_id] = len(records)
            records.append(data)

    return records


def parse_csv_content(content: str | bytes, source: str = "csv") -> list[dict[str, Any]]:
    """Разбирает CSV в список записей для upsert."""
    if isinstance(content, bytes):
        if len(content) > settings.max_csv_bytes:
            raise ValueError(
                f"Файл больше лимита {settings.max_csv_bytes // (1024 * 1024)} МБ"
            )
        content = _decode(content)

    if not content.strip():
        return []

    delimiter = detect_delimiter(content)
    reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
    if not reader.fieldnames:
        return []

    headers = [header.strip().lstrip("\ufeff") for header in reader.fieldnames if header]
    mapping = _build_mapping(headers)

    if "external_id" not in mapping:
        log.warning("CSV не содержит колонки external_id — будет сгенерирован стабильный id")
    if "price" not in mapping:
        log.warning("CSV не содержит колонки price")

    return _records_from_rows(reader, mapping, source)


def parse_xlsx_content(content: bytes, source: str = "excel") -> list[dict[str, Any]]:
    """Разбирает первый лист .xlsx (первая строка — заголовки)."""
    if len(content) > settings.max_csv_bytes:
        raise ValueError(f"Файл больше лимита {settings.max_csv_bytes // (1024 * 1024)} МБ")

    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise RuntimeError(
            "Для импорта Excel установите openpyxl: pip install openpyxl"
        ) from exc

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header_row = next(rows, None)
        if not header_row:
            return []

        headers = [str(value).strip() if value is not None else "" for value in header_row]
        mapping = _build_mapping([header for header in headers if header])

        def dict_rows() -> Iterable[dict[str, Any]]:
            for values in rows:
                yield {
                    headers[index]: values[index]
                    for index in range(min(len(headers), len(values)))
                    if headers[index]
                }

        return _records_from_rows(dict_rows(), mapping, source)
    finally:
        workbook.close()


async def import_records(
    db: AsyncSession,
    records: list[dict[str, Any]],
    source: str = "csv",
) -> dict[str, Any]:
    """Импортирует записи через upsert в одной транзакции.

    Матчер строится один раз на весь пакет. Ошибки строк собираются,
    но не прерывают импорт. Commit делает get_db.
    """
    matcher = await ProductMatcher.load(db)
    imported = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    for index, record in enumerate(records):
        try:
            async with db.begin_nested():
                _, created = await upsert_listing(db, record, source=source, matcher=matcher)
            if created:
                imported += 1
            else:
                updated += 1
        except Exception as exc:  # noqa: BLE001 - одна плохая строка не должна ронять импорт
            skipped += 1
            if len(errors) < 20:
                errors.append(f"строка {index + 1}: {exc}")
            log.warning("Строка %s пропущена: %s", index + 1, exc)

    if errors:
        log.warning("Импорт: %s ошибок из %s записей", skipped, len(records))

    return {
        "total_rows": len(records),
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
