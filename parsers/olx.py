from __future__ import annotations

import logging
import urllib.parse
import aiohttp
from bs4 import BeautifulSoup
from models import ProductItem
from parsers.base import BaseParser

logger = logging.getLogger(__name__)


class OLXParser(BaseParser):
    """Parser implementation for OLX.ua marketplace."""

    BASE_URL = "https://www.olx.ua/d/uk/list/q-{query}/"

    async def fetch_data(self, query: str) -> list[ProductItem]:
        encoded_query = urllib.parse.quote(query.strip().lower())
        items: list[ProductItem] = []
        
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            for page in range(1, self.max_pages + 1):
                if len(items) >= self.max_items:
                    break

                url = self.BASE_URL.format(query=encoded_query)
                if page > 1:
                    url += f"?page={page}"

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            logger.warning(f"[OLX] Received status code {response.status} for URL: {url}")
                            break
                        html = await response.text()
                except Exception as exc:
                    logger.error(f"[OLX] Error fetching URL {url}: {exc}")
                    break

                page_items = self._parse_html(html)
                if not page_items:
                    logger.info(f"[OLX] No items found on page {page}. Stopping pagination.")
                    break

                for item in page_items:
                    items.append(item)
                    if len(items) >= self.max_items:
                        break

        logger.info(f"[OLX] Parsed {len(items)} items for query '{query}'.")
        return items

    def _parse_html(self, html: str) -> list[ProductItem]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select('div[data-cy="l-card"]')
        results: list[ProductItem] = []

        for card in cards:
            title_elem = card.select_one("h6, h4")
            price_elem = card.select_one('[data-testid="ad-price"]')
            link_elem = card.select_one("a[href]")

            if not title_elem or not price_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True)
            raw_price = price_elem.get_text(strip=True)
            parsed_price, currency = self._parse_price(raw_price)

            if parsed_price is None:
                continue

            href = link_elem.get("href", "")
            full_url = href if href.startswith("http") else f"https://www.olx.ua{href}"

            card_text = card.get_text().lower()
            condition = "unknown"
            if "нове" in card_text or "новое" in card_text or "новий" in card_text or "новый" in card_text:
                condition = "new"
            elif "б/в" in card_text or "б/у" in card_text or "вживане" in card_text:
                condition = "used"

            results.append(
                ProductItem(
                    title=title,
                    price=parsed_price,
                    currency=currency,
                    source="olx",
                    url=full_url,
                    condition=condition,
                )
            )

        return results

    @staticmethod
    def _parse_price(price_str: str) -> tuple[float | None, str]:
        cleaned = price_str.replace(" ", "").replace("\xa0", "").lower()
        currency = "UAH"
        if "$" in cleaned or "usd" in cleaned:
            currency = "USD"
        elif "€" in cleaned or "eur" in cleaned:
            currency = "EUR"

        digits = "".join([c for c in cleaned if c.isdigit() or c == "." or c == ","]).replace(",", ".")
        try:
            return float(digits), currency
        except ValueError:
            return None, currency
