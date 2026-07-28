from __future__ import annotations

import logging
import urllib.parse
import aiohttp
from bs4 import BeautifulSoup
from models import ProductItem
from parsers.base import BaseParser

logger = logging.getLogger(__name__)


class PromParser(BaseParser):
    """Parser implementation for Prom.ua marketplace using HTML scraping."""

    BASE_URL = "https://prom.ua/ua/search?search_term={query}"

    async def fetch_data(self, query: str) -> list[ProductItem]:
        """Asynchronously parses products from Prom.ua for a given search query.

        Args:
            query: The search term to query on Prom.ua.

        Returns:
            A list of ProductItem instances parsed from Prom.ua.
        """
        encoded_query = urllib.parse.quote(query.strip().lower())
        items: list[ProductItem] = []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://prom.ua/ua/",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            for page in range(1, self.max_pages + 1):
                if len(items) >= self.max_items:
                    break

                url = self.BASE_URL.format(query=encoded_query)
                if page > 1:
                    url += f"&page={page}"

                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                        if response.status != 200:
                            logger.warning(
                                f"[Prom] Non-200 HTTP status ({response.status}) received for URL: {url}"
                            )
                            break
                        html = await response.text()
                except Exception as exc:
                    logger.error(f"[Prom] Network or parsing exception encountered for URL {url}: {exc}")
                    break

                page_items = self._parse_html(html)
                if not page_items:
                    logger.info(f"[Prom] No product items found on page {page}. Halting pagination.")
                    break

                for item in page_items:
                    items.append(item)
                    if len(items) >= self.max_items:
                        break

        logger.info(f"[Prom] Successfully parsed {len(items)} items for query '{query}'.")
        return items

    def _parse_html(self, html: str) -> list[ProductItem]:
        soup = BeautifulSoup(html, "html.parser")
        
        # Primary container selector matching product cards on Prom.ua
        cards = soup.select(
            'div[data-qaid="product_block"], '
            'div[data-qa="product_card"], '
            'div[data-qaid="product_presence"], '
            'article[data-qaid="product_card"]'
        )

        # Fallback to broader card containers if specific data-qa attributes differ
        if not cards:
            cards = soup.select('div[js-productad], div[data-product-id]')

        results: list[ProductItem] = []

        for card in cards:
            title_elem = (
                card.select_one('[data-qaid="product_name"]')
                or card.select_one('a[data-qaid="product_link"]')
                or card.select_one('a[title]')
            )
            price_elem = (
                card.select_one('[data-qaid="product_price"]')
                or card.select_one('[data-qaid="price_element"]')
                or card.select_one('span[data-qaid="price"]')
            )
            link_elem = (
                card.select_one('a[data-qaid="product_link"]')
                or card.select_one('a[href]')
            )

            if not title_elem or not price_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True)
            if not title and title_elem.has_attr("title"):
                title = title_elem["title"].strip()

            raw_price = price_elem.get_text(strip=True)
            parsed_price, currency = self._parse_price(raw_price)

            if parsed_price is None or not title:
                continue

            href = link_elem.get("href", "")
            full_url = href if href.startswith("http") else f"https://prom.ua{href}"

            results.append(
                ProductItem(
                    title=title,
                    price=parsed_price,
                    currency=currency,
                    source="prom",
                    url=full_url,
                    condition="new",
                )
            )

        return results

    @staticmethod
    def _parse_price(price_str: str) -> tuple[float | None, str]:
        cleaned = (
            price_str.replace(" ", "")
            .replace("\xa0", "")
            .replace("&nbsp;", "")
            .lower()
        )
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
