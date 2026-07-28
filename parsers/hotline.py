"""parsers/hotline.py — Parser for hotline.ua using curl_cffi + BeautifulSoup4."""
from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from models import ProductItem
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

_NOISE_WORDS = {"відгуки", "порівняти", "акції", "всі", "ціни", "пропозиції"}


def _clean_price(raw: str) -> float | None:
    """Extract the lower bound of a price range string like '14 999 – 26 999 ₴'."""
    part = raw.split("–")[0]
    digits = re.sub(r"[^\d]", "", part)
    return float(digits) if digits else None


class HotlineParser(BaseParser):
    """Парсер для hotline.ua.

    Hotline — агрегатор цін, тому кожна картка у видачі відповідає групі
    пропозицій одного товару. Повертаємо мінімальну ціну з діапазону.
    """

    BASE_SEARCH_URL = "https://hotline.ua/ua/sr/?q={query}"

    def __init__(self, max_pages: int = 2, max_items: int = 30) -> None:
        super().__init__(max_pages=max_pages, max_items=max_items)
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_data(self, query: str) -> list[ProductItem]:
        clean_query = query.strip()
        encoded = urllib.parse.quote_plus(clean_query)
        items: list[ProductItem] = []

        try:
            async with AsyncSession(
                impersonate="chrome124",
                headers=self._headers,
            ) as session:
                for page in range(1, self.max_pages + 1):
                    if len(items) >= self.max_items:
                        break

                    page_param = f"&p={page}" if page > 1 else ""
                    url = self.BASE_SEARCH_URL.format(query=encoded) + page_param

                    response = await session.get(url, timeout=12)
                    if response.status_code != 200:
                        logger.warning(
                            "[Hotline] HTTP %s on page %s for query '%s'",
                            response.status_code,
                            page,
                            clean_query,
                        )
                        break

                    page_items = self._parse_page(response.text)
                    if not page_items:
                        logger.info("[Hotline] No items on page %s, stopping.", page)
                        break

                    items.extend(page_items)
                    logger.debug("[Hotline] Page %s: got %s items.", page, len(page_items))

        except Exception as exc:  # noqa: BLE001
            logger.error("[Hotline] Exception for query '%s': %s", clean_query, exc)

        result = items[: self.max_items]
        logger.info(
            "[Hotline] Done — %s items returned for query '%s'.", len(result), clean_query
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_page(self, html: str) -> list[ProductItem]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.list-item")
        items: list[ProductItem] = []

        for card in cards:
            item = self._parse_card(card)
            if item is not None:
                items.append(item)

        return items

    def _parse_card(self, card: Any) -> ProductItem | None:
        # --- Title & href ---
        title = ""
        href = ""
        for link in card.select("a[href]"):
            text = link.get_text(strip=True)
            if not text or len(text) < 5:
                continue
            if any(w in text.lower() for w in _NOISE_WORDS):
                continue
            title = text
            raw_href = link.get("href", "")
            href = (
                raw_href
                if raw_href.startswith("http")
                else f"https://hotline.ua{raw_href}"
            )
            break

        if not title or not href:
            return None

        # --- Price ---
        price_elem = card.select_one(".price__value, .list-item__value, .price")
        if price_elem is None:
            return None

        price = _clean_price(price_elem.get_text(strip=True))
        if price is None or price <= 0:
            return None

        return ProductItem(
            title=title,
            price=price,
            currency="UAH",
            source="hotline",
            url=href,
            condition="new",
        )
