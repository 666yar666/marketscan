from abc import ABC, abstractmethod
import logging
from models import ProductItem

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """Abstract Base Class for marketplace parsers."""

    def __init__(self, max_pages: int = 3, max_items: int = 50) -> None:
        self.max_pages = max_pages
        self.max_items = max_items

    @abstractmethod
    async def fetch_data(self, query: str) -> list[ProductItem]:
        """Asynchronously fetches product items matching the search query.

        Args:
            query: Search query string.

        Returns:
            List of ProductItem instances.
        """
        pass
