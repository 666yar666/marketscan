from __future__ import annotations

import logging
import urllib.parse
from curl_cffi.requests import AsyncSession
from models import ProductItem
from parsers.base import BaseParser

logger = logging.getLogger(__name__)


class RozetkaParser(BaseParser):
    """Parser implementation for Rozetka using two-stage official frontend API

    (common-api.rozetka.com.ua catalog search + product details) via curl_cffi.
    """

    SEARCH_API_URL = "https://common-api.rozetka.com.ua/v1/api/catalog/search"
    DETAILS_API_URL = "https://common-api.rozetka.com.ua/v1/api/product/details"

    def __init__(self, max_pages: int = 3, max_items: int = 50) -> None:
        super().__init__(max_pages=max_pages, max_items=max_items)
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
            "Origin": "https://rozetka.com.ua",
            "Referer": "https://rozetka.com.ua/ua/",
        }

    async def fetch_data(self, query: str) -> list[ProductItem]:
        clean_query = query.strip()
        items: list[ProductItem] = []

        try:
            async with AsyncSession(impersonate="chrome124", headers=self.headers) as session:
                for page in range(1, self.max_pages + 1):
                    if len(items) >= self.max_items:
                        break

                    search_params = {
                        "country": "UA",
                        "lang": "ua",
                        "page": str(page),
                        "platform": "desktop",
                        "text": clean_query,
                    }

                    # Stage 1: Search for product IDs
                    search_res = await session.get(self.SEARCH_API_URL, params=search_params, timeout=10)
                    if search_res.status_code != 200:
                        logger.warning(f"[Rozetka] Search API HTTP status {search_res.status_code}")
                        break

                    data = search_res.json().get("data", {})
                    goods = data.get("goods", [])
                    if not goods:
                        logger.info(f"[Rozetka] No items in search API on page {page}.")
                        break

                    product_ids = [str(g["id"]) for g in goods if "id" in g]
                    if not product_ids:
                        break

                    # Stage 2: Fetch detailed product information
                    details_params = {
                        "country": "UA",
                        "lang": "ua",
                        "ids": ",".join(product_ids),
                    }

                    details_res = await session.get(self.DETAILS_API_URL, params=details_params, timeout=10)
                    if details_res.status_code != 200:
                        logger.warning(f"[Rozetka] Details API HTTP status {details_res.status_code}")
                        break

                    products_data = details_res.json().get("data", [])
                    for prod in products_data:
                        title = prod.get("title", "")
                        raw_price = prod.get("price", 0.0)
                        try:
                            price = float(raw_price)
                        except (ValueError, TypeError):
                            price = 0.0

                        href = prod.get("href", "")

                        if title and price > 0:
                            items.append(
                                ProductItem(
                                    title=title,
                                    price=price,
                                    currency="UAH",
                                    source="rozetka",
                                    url=href or "",
                                    condition="new",
                                )
                            )

                        if len(items) >= self.max_items:
                            break

                logger.info(f"[Rozetka] Successfully parsed {len(items)} items for query '{clean_query}'.")
                return items

        except Exception as e:
            logger.error(f"[Rozetka] Exception fetching data: {e}")
            return []
