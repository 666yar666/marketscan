import logging
from typing import Any
import pandas as pd
from models import ProductItem

logger = logging.getLogger(__name__)


class MarketAnalyzer:
    """Class for statistical analysis of product market price data using Pandas."""

    def analyze(self, products: list[ProductItem]) -> dict[str, Any]:
        """Calculates statistical price metrics grouped by condition after removing outliers via IQR.

        Args:
            products: List of processed ProductItem objects.

        Returns:
            Dictionary containing descriptive statistics for each condition group.
        """
        if not products:
            logger.warning("No products provided for analysis.")
            return {}

        df = pd.DataFrame([vars(p) for p in products])
        df_clean = self._remove_outliers_iqr(df)

        stats: dict[str, Any] = {}
        grouped = df_clean.groupby("condition")

        for condition, group in grouped:
            prices = group["price"]
            stats[str(condition)] = {
                "count": int(prices.count()),
                "median_price": round(float(prices.median()), 2) if not prices.empty else 0.0,
                "min_price": round(float(prices.min()), 2) if not prices.empty else 0.0,
                "max_price": round(float(prices.max()), 2) if not prices.empty else 0.0,
                "std_dev": round(float(prices.std()), 2) if len(prices) > 1 else 0.0,
            }

        return stats

    def _remove_outliers_iqr(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "price" not in df.columns:
            return df

        cleaned_groups = []
        for condition, group in df.groupby("condition"):
            if len(group) < 4:
                cleaned_groups.append(group)
                continue

            q1 = group["price"].quantile(0.25)
            q3 = group["price"].quantile(0.75)
            iqr = q3 - q1

            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            filtered = group[(group["price"] >= lower_bound) & (group["price"] <= upper_bound)]
            cleaned_groups.append(filtered)

        return pd.concat(cleaned_groups, ignore_index=True) if cleaned_groups else df
