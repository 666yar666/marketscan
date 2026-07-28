from __future__ import annotations

import logging
from rapidfuzz import fuzz
from models import ConditionType, ProductItem

logger = logging.getLogger(__name__)


class DataCleaner:
    """Class responsible for deduplication, noise filtering, price floor filtering, fuzzy matching, and condition classification."""

    STOP_WORDS = {
        "чехол", "чохол",
        "стекло", "скло",
        "плівка", "пленка",
        "кабель",
        "запчастини", "запчасти",
        "коробка",
        "ремонт",
        "комплект",
    }

    NEW_KEYWORDS = {"новий", "новый", "new", "запечатаний", "запечатанный"}
    PARTS_KEYWORDS = {"на запчастини", "на запчасти", "донор", "не робочий", "не рабочий", "розбитий", "разбитый"}

    def __init__(self, min_price: float = 3000.0, usd_rate: float = 41.5) -> None:
        self.min_price = min_price
        self.usd_rate = usd_rate

    def clean_data(self, items: list[ProductItem], min_price: float | None = None) -> list[ProductItem]:
        """Фильтрует мусор, определяет состояние и удаляет дубликаты.

        Добавлен min_price для отсечения чехлов и защитных стекол.
        USD-цены (eBay) конвертируются в UAH через self.usd_rate перед проверкой.
        """
        effective_min_price = min_price if min_price is not None else self.min_price
        cleaned_items = []
        seen_urls = set()

        for item in items:
            # 1. Отсекаем мусор по ключевым словам
            if self._is_garbage(item.title):
                continue

            # 2. Отсекаем аномально низкую цену (чехлы, пленки, коробки)
            # USD-цены приводим к UAH только для сравнения с порогом
            price_in_uah = (
                item.price * self.usd_rate
                if item.currency == "USD"
                else item.price
            )
            if price_in_uah < effective_min_price:
                continue

            # 3. Удаляем дубликаты по URL
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)

            # 4. Определяем состояние (new, used, parts)
            item.condition = self._determine_condition(item.title, item.source)

            # Убираем товары на запчасти
            if item.condition != "parts":
                cleaned_items.append(item)

        return cleaned_items

    def process(
        self,
        products: list[ProductItem],
        query: str = "",
        min_price: float | None = None,
    ) -> list[ProductItem]:
        """Main processing pipeline for raw product items."""
        effective_min_price = min_price if min_price is not None else self.min_price
        logger.info(
            f"Starting data cleaner process on {len(products)} products "
            f"(min_price={effective_min_price} UAH, usd_rate={self.usd_rate})."
        )
        
        # Apply clean_data logic with fuzzy query matching
        base_cleaned = self.clean_data(products, min_price=effective_min_price)
        
        fuzzy_matched = []
        for item in base_cleaned:
            if not query or fuzz.partial_ratio(query.lower(), item.title.lower()) >= 70.0:
                fuzzy_matched.append(item)

        logger.info(f"Data cleaner finished: {len(fuzzy_matched)} items remaining after processing.")
        return fuzzy_matched

    def _is_garbage(self, title: str) -> bool:
        title_lower = title.lower()
        words = set(title_lower.split())
        for stop_word in self.STOP_WORDS:
            if stop_word in words or stop_word in title_lower:
                return True
        return False

    def _determine_condition(self, title: str, source: str = "unknown") -> ConditionType:
        if source.lower() in ("prom", "rozetka"):
            return "new"

        title_lower = title.lower()
        for kw in self.NEW_KEYWORDS:
            if kw in title_lower:
                return "new"

        for kw in self.PARTS_KEYWORDS:
            if kw in title_lower:
                return "parts"

        return "used"
