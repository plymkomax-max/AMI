"""Сопоставление объявления с моделью товара и извлечение характеристик.

Правила:
* сравнение идёт по нормализованному тексту (регистр, ё, пунктуация);
* бренд берётся из словаря синонимов (Apple/эпл, Samsung/самсунг, ...);
* модель ищется как фраза из справочника products;
* объём памяти уточняет выбор между вариантами одной модели;
* при неоднозначности (два кандидата с близким счётом) объявление
  остаётся несопоставленным — лучше «не знаю», чем неверная модель.

LLM здесь не используется: только правила и данные справочника.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logger import get_logger
from app.models.product import Product

log = get_logger("services.matcher")

# Синонимы брендов: ключ — нормализованное имя в справочнике.
BRAND_ALIASES: dict[str, tuple[str, ...]] = {
    "apple": ("apple", "эпл", "аппл", "аппле"),
    "samsung": ("samsung", "самсунг", "самсунг", "galaxy", "галакси"),
    "xiaomi": ("xiaomi", "сяоми", "ксиоми", "redmi", "редми", "poco", "поко"),
    "huawei": ("huawei", "хуавей", "хуавэй", "honor", "хонор"),
    "honor": ("honor", "хонор"),
    "google": ("google", "гугл", "pixel", "пиксель"),
    "oneplus": ("oneplus", "ванплас", "1plus"),
    "realme": ("realme", "реалми"),
    "oppo": ("oppo", "оппо"),
    "vivo": ("vivo", "виво"),
    "sony": ("sony", "сони", "playstation", "плейстейшн", "ps5", "ps4"),
    "microsoft": ("microsoft", "майкрософт", "xbox", "иксбокс"),
    "nintendo": ("nintendo", "нинтендо", "switch", "свитч"),
    "asus": ("asus", "асус"),
    "acer": ("acer", "асер"),
    "lenovo": ("lenovo", "леново"),
    "hp": ("hp", "hewlett", "хп"),
    "dell": ("dell", "делл"),
    "msi": ("msi", "мси"),
    "gigabyte": ("gigabyte", "гигабайт"),
    "nvidia": ("nvidia", "нвидиа"),
    "amd": ("amd", "амд"),
    "intel": ("intel", "интел"),
    "logitech": ("logitech", "логитек"),
    "razer": ("razer", "рейзер"),
    "dyson": ("dyson", "дайсон"),
    "bosch": ("bosch", "бош"),
    "lg": ("lg", "элджи"),
    "philips": ("philips", "филипс"),
}

COLOR_ALIASES: dict[str, tuple[str, ...]] = {
    "black": ("черный", "черная", "черное", "black", "графит", "graphite"),
    "white": ("белый", "белая", "белое", "white", "серебристый", "silver"),
    "gray": ("серый", "серая", "gray", "grey", "space gray", "серый космос"),
    "gold": ("золотой", "gold", "золото"),
    "blue": ("синий", "синяя", "blue", "голубой"),
    "red": ("красный", "красная", "red"),
    "green": ("зеленый", "зеленая", "green"),
    "purple": ("фиолетовый", "purple", "lavender"),
    "titanium": ("титан", "titanium", "титановый"),
}

DEFECT_PATTERNS = (
    "не работает",
    "не включается",
    "не заряжается",
    "не грузится",
    "неисправ",
    "разбит",
    "треснул",
    "битые пиксели",
    "нет изображения",
    "не держит заряд",
)

_CAPACITY_RE = re.compile(r"(\d{1,4})\s*(tb|тб|gb|гб|g|г)\b", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d")


def normalize_text(value: str | None) -> str:
    """Нижний регистр, ё→е, пунктуация → пробел, без двойных пробелов."""
    text = (value or "").lower().replace("ё", "е")
    text = re.sub(r"[^0-9a-zа-я]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(value: str | None) -> set[str]:
    return set(normalize_text(value).split())


def _has_phrase(normalized_text: str, phrase: str) -> bool:
    """Ищет фразу по границам слов, а не по подстроке."""
    if not phrase:
        return False
    return f" {phrase} " in f" {normalized_text} "


def _brand_aliases(brand: str | None) -> tuple[str, ...]:
    key = normalize_text(brand)
    if not key:
        return ()
    aliases = BRAND_ALIASES.get(key)
    if aliases:
        return tuple(normalize_text(alias) for alias in aliases)
    return (key,)


def _capacity_gb(value: Any) -> int | None:
    """'128GB', '128', '1TB' → число гигабайт."""
    text = normalize_text(str(value) if value is not None else "")
    if not text:
        return None
    match = _CAPACITY_RE.search(text) or re.search(r"(\d{1,4})", text)
    if not match:
        return None
    number = int(match.group(1))
    unit = (match.group(2) or "gb").lower() if match.lastindex and match.lastindex >= 2 else "gb"
    if unit in ("tb", "тб"):
        return number * 1024
    return number


def _capacities(text: str) -> Iterable[tuple[int, int, int]]:
    for match in _CAPACITY_RE.finditer(text):
        number = int(match.group(1))
        unit = match.group(2).lower()
        gigabytes = number * 1024 if unit in ("tb", "тб") else number
        yield gigabytes, match.start(), match.end()


def _near_ram(text: str, start: int, end: int) -> bool:
    """Проверяет, относится ли число к ОЗУ, а не к накопителю."""
    prefix = text[max(0, start - 8): start].lower()
    after = text[end: end + 16].lower()
    if re.search(r"(озу|ram|оператив)\s*$", prefix):
        return True
    return bool(re.match(r"\s*(gb|гб|g|г)?\s*(ram|озу|оператив)", after))


def extract_storage(text: str) -> str | None:
    """Наибольший объём, похожий на накопитель (не ОЗУ)."""
    candidates = [
        gb for gb, start, end in _capacities(text) if not _near_ram(text, start, end)
    ]
    candidates = [gb for gb in candidates if gb >= 32]
    if not candidates:
        return None
    gb = max(candidates)
    if gb >= 1024 and gb % 1024 == 0:
        return f"{gb // 1024}TB"
    return f"{gb}GB"


def extract_ram(text: str) -> str | None:
    for gb, start, end in _capacities(text):
        if _near_ram(text, start, end) and gb <= 64:
            return f"{gb}GB"
    return None


def extract_color(text: str) -> str | None:
    normalized = normalize_text(text)
    for canonical, aliases in COLOR_ALIASES.items():
        for alias in aliases:
            if _has_phrase(normalized, normalize_text(alias)):
                return canonical
    return None


def extract_defect_mentions(text: str) -> list[str]:
    normalized = normalize_text(text)
    return [pattern for pattern in DEFECT_PATTERNS if _has_phrase(normalized, normalize_text(pattern))]


def extract_attributes(title: str | None, description: str | None) -> dict[str, Any]:
    """Достаёт из текста то, что можно хранить без домыслов."""
    text = f"{title or ''} {description or ''}"
    attributes: dict[str, Any] = {}
    storage = extract_storage(text)
    ram = extract_ram(text)
    color = extract_color(text)
    defects = extract_defect_mentions(text)
    if storage:
        attributes["storage"] = storage
    if ram:
        attributes["ram"] = ram
    if color:
        attributes["color"] = color
    if defects:
        attributes["defect_mentions"] = defects
    return attributes


@dataclass
class MatchResult:
    product_id: int | None
    confidence: float
    method: str  # auto | manual | none | ambiguous | disabled
    attributes: dict[str, Any] = field(default_factory=dict)
    best_candidate: int | None = None


@dataclass
class _ProductEntry:
    product_id: int
    brand_aliases: tuple[str, ...]
    model_phrases: tuple[str, ...]
    storage_gb: int | None
    name_tokens: set[str]


class ProductMatcher:
    """Сопоставляет текст объявления со справочником products."""

    def __init__(self, products: Sequence[Product]):
        self.entries: list[_ProductEntry] = []
        for product in products:
            phrases: set[str] = set()
            model = normalize_text(product.model)
            if model:
                phrases.add(model)
            name = normalize_text(product.name)
            if name:
                phrases.add(name)
                without_capacity = _CAPACITY_RE.sub(" ", name)
                cleaned = normalize_text(without_capacity)
                if cleaned:
                    phrases.add(cleaned)
            # Слишком короткие/общие фразы не используем
            phrases = {p for p in phrases if len(p) >= 4 and not p.isdigit()}
            if not phrases:
                continue
            self.entries.append(
                _ProductEntry(
                    product_id=product.id,
                    brand_aliases=_brand_aliases(product.brand),
                    model_phrases=tuple(sorted(phrases, key=len, reverse=True)),
                    storage_gb=_capacity_gb(product.storage_capacity),
                    name_tokens=tokenize(product.name),
                )
            )

    @classmethod
    async def load(
        cls,
        db: AsyncSession,
        category_id: int | None = None,
    ) -> "ProductMatcher":
        stmt = select(Product)
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        products = list((await db.scalars(stmt)).all())
        return cls(products)

    def match(self, title: str | None, description: str | None = None) -> MatchResult:
        attributes = extract_attributes(title, description)
        if not settings.auto_match_enabled:
            return MatchResult(None, 0.0, "disabled", attributes)
        if not self.entries:
            return MatchResult(None, 0.0, "none", attributes)

        text = normalize_text(f"{title or ''} {description or ''}")
        if not text:
            return MatchResult(None, 0.0, "none", attributes)

        text_tokens = set(text.split())
        storage = attributes.get("storage")
        listing_gb = _capacity_gb(storage) if storage else None

        scored: list[tuple[float, int]] = []

        for entry in self.entries:
            model_hit = next(
                (phrase for phrase in entry.model_phrases if _has_phrase(text, phrase)),
                None,
            )
            if not model_hit:
                continue

            brand_hit = any(_has_phrase(text, alias) for alias in entry.brand_aliases)
            distinctive = bool(_DIGIT_RE.search(model_hit)) and len(model_hit) >= 6
            if brand_hit:
                score = 0.72
            elif distinctive:
                score = 0.60
            else:
                continue

            if entry.name_tokens:
                overlap = len(entry.name_tokens & text_tokens) / len(entry.name_tokens)
                score += 0.08 * overlap

            if listing_gb and entry.storage_gb:
                if listing_gb == entry.storage_gb:
                    score += 0.15
                else:
                    # Явное несовпадение объёма — сильный минус
                    score -= 0.30

            score = round(min(1.0, max(0.0, score)), 3)
            if score >= settings.match_min_confidence:
                scored.append((score, entry.product_id))

        if not scored:
            return MatchResult(None, 0.0, "none", attributes)

        scored.sort(reverse=True)
        top_score, top_id = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0

        # Неоднозначность: два варианта почти равны — не угадываем
        if runner_up and top_score - runner_up < 0.05 and top_score < 0.95:
            log.debug(
                "Неоднозначное сопоставление: %s vs %s (%.2f/%.2f)",
                top_id,
                scored[1][1],
                top_score,
                runner_up,
            )
            return MatchResult(None, top_score, "ambiguous", attributes, best_candidate=top_id)

        return MatchResult(top_id, top_score, "auto", attributes, best_candidate=top_id)
