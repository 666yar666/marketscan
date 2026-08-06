"""parsers/ebay.py — Parser for ebay.com using curl_cffi + BeautifulSoup4.

Strategy:
  - Visit homepage first to obtain cookies (anti-bot warm-up).
  - Search via /sch/i.html with LH_BIN=1 (Buy It Now only) and _sop=12
    (sort by price + shipping: lowest first).
  - Each product card (li.s-card) contains:
      * img[alt] — product title (title attribute of thumbnail image)
      * [class*="price"] — price string like "$139.99"
      * a[href*="/itm/"] — canonical item link
      * span text "Pre-Owned" / "Brand New" / etc. — condition
"""
from __future__ import annotations

import logging
import re
import urllib.parse

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from models import ProductItem
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

_PRICE_RE = re.compile(r"\$\s*([0-9,]+(?:\.[0-9]+)?)")
_ITM_RE = re.compile(r"/itm/(\d+)")

_NEW_KEYWORDS = frozenset({"brand new", "new", "sealed", "factory sealed", "new other"})
_USED_KEYWORDS = frozenset({"pre-owned", "used", "refurbished", "open box", "great condition", "good condition", "excellent condition", "for parts"})

_SKIP_TITLES = frozenset({"shop on ebay", ""})


def _detect_condition(text: str) -> str:
    lower = text.lower()
    for kw in _USED_KEYWORDS:
        if kw in lower:
            return "used"
    for kw in _NEW_KEYWORDS:
        if kw in lower:
            return "new"
    return "used"  # safe default for second-hand marketplace


class EbayParser(BaseParser):
    """Парсер для eBay (Buy It Now, lowest price first)."""

    HOMEPAGE = "https://www.ebay.com"
    SEARCH_URL = "https://www.ebay.com/sch/i.html"

    def __init__(self, max_pages: int = 2, max_items: int = 30) -> None:
        super().__init__(max_pages=max_pages, max_items=max_items)
        self._base_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_data(self, query: str) -> list[ProductItem]:
        clean_query = query.strip()
        items: list[ProductItem] = []

        try:
            async with AsyncSession(
                impersonate="chrome124",
                headers=self._base_headers,
            ) as session:
                # Warm-up: visit homepage to receive session cookies
                await session.get(self.HOMEPAGE, timeout=8)
                search_headers = {**self._base_headers, "Referer": f"{self.HOMEPAGE}/"}

                for page in range(1, self.max_pages + 1):
                    if len(items) >= self.max_items:
                        break

                    params: dict[str, str] = {
                        "_nkw": clean_query,
                        "LH_BIN": "1",        # Buy It Now only
                        "_sop": "12",          # Sort: price + shipping, lowest first
                        "_pgn": str(page),
                    }

                    response = await session.get(
                        self.SEARCH_URL,
                        params=params,
                        headers=search_headers,
                        timeout=15,
                    )

                    if response.status_code != 200:
                        logger.warning(
                            "[eBay] HTTP %s on page %s for query '%s'",
                            response.status_code,
                            page,
                            clean_query,
                        )
                        break

                    page_items = self._parse_page(response.text)
                    if not page_items:
                        logger.info("[eBay] No items on page %s, stopping.", page)
                        break

                    items.extend(page_items)
                    logger.debug("[eBay] Page %s: got %s items.", page, len(page_items))

        except Exception as exc:  # noqa: BLE001
            logger.error("[eBay] Exception for query '%s': %s", clean_query, exc)

        result = items[: self.max_items]
        logger.info(
            "[eBay] Done — %s items returned for query '%s'.", len(result), clean_query
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_page(self, html: str) -> list[ProductItem]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("li.s-card")
        items: list[ProductItem] = []

        for card in cards:
            item = self._parse_card(card)
            if item is not None:
                items.append(item)

        return items

    def _parse_card(self, card) -> ProductItem | None:  # type: ignore[override]
        # --- Title via thumbnail alt attribute ---
        img = card.select_one("img[alt]")
        if img is None:
            return None
        title = img.get("alt", "").strip()
        if not title or title.lower() in _SKIP_TITLES:
            return None

        # --- Price ---
        price_elem = card.select_one("[class*='price']")
        if price_elem is None:
            return None
        raw_price = price_elem.get_text(strip=True)
        if "to" in raw_price.lower():
            matches = _PRICE_RE.findall(raw_price)
            if not matches:
                return None
            price = float(matches[0].replace(",", ""))
        else:
            price_match = _PRICE_RE.search(raw_price)
            if not price_match:
                return None
            price = float(price_match.group(1).replace(",", ""))

        # --- Href ---
        link_elem = card.select_one("a[href*='/itm/']")
        if link_elem is None:
            return None
        href = link_elem.get("href", "")

        # --- Condition ---
        # Look for condition span text in the card
        cond_text = ""
        for span in card.select("span"):
            txt = span.get_text(strip=True)
            lower = txt.lower()
            if any(kw in lower for kw in _USED_KEYWORDS | _NEW_KEYWORDS):
                cond_text = txt
                break
        condition = _detect_condition(cond_text)

        return ProductItem(
            title=title,
            price=price,
            currency="USD",
            source="ebay",
            url=href,
            condition=condition,
        )
