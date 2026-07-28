from dataclasses import dataclass
from typing import Literal

ConditionType = Literal['new', 'used', 'parts', 'unknown']


@dataclass
class ProductItem:
    """Structure representing a single product item parsed from a marketplace."""
    title: str
    price: float
    currency: str
    source: str
    url: str
    condition: ConditionType = 'unknown'
