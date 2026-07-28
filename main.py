import asyncio
import logging
from typing import Sequence
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from analyzer import MarketAnalyzer
from cleaner import DataCleaner
from models import ProductItem
from parsers.olx import OLXParser
from parsers.prom import PromParser
from parsers.rozetka import RozetkaParser
from parsers.hotline import HotlineParser
from parsers.ebay import EbayParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
console = Console()

TRANSLATION_MAP = {
    "айфон": "iphone",
    "телефон": "телефон",
    "ноутбук": "ноутбук",
    "навушники": "наушники",
    "наушники": "навушники",
}


def build_search_queries(query: str) -> list[str]:
    queries = [query.strip()]
    query_lower = query.strip().lower()
    if query_lower in TRANSLATION_MAP:
        translated = TRANSLATION_MAP[query_lower]
        if translated not in queries:
            queries.append(translated)
    return queries


async def run_parsers_for_query(query: str) -> list[ProductItem]:
    parsers = [OLXParser(), PromParser(), RozetkaParser(), HotlineParser(), EbayParser()]
    tasks = [parser.fetch_data(query) for parser in parsers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_products: list[ProductItem] = []
    for res in results:
        if isinstance(res, list):
            all_products.extend(res)
        elif isinstance(res, Exception):
            console.print(f"[bold red]Parser error:[/bold red] {res}")

    return all_products


async def main() -> None:
    console.print(Panel.fit("[bold cyan]Marketplace Price Analyzer & Scraper[/bold cyan]", border_style="cyan"))

    search_term = "iPhone 13"
    queries = build_search_queries(search_term)

    console.print(f"[yellow]Executing search queries:[/yellow] {queries}")

    raw_items: list[ProductItem] = []
    with console.status("[bold green]Parsing marketplaces in parallel...[/bold green]"):
        for q in queries:
            items = await run_parsers_for_query(q)
            raw_items.extend(items)

    console.print(f"[green]✓ Total raw items collected:[/green] {len(raw_items)}")

    cleaner = DataCleaner()
    with console.status("[bold blue]Cleaning and deduplicating data...[/bold blue]"):
        cleaned_items = cleaner.process(raw_items, query=search_term)

    console.print(f"[green]✓ Items remaining after cleaning:[/green] {len(cleaned_items)}")

    analyzer = MarketAnalyzer()
    stats = analyzer.analyze(cleaned_items)

    table = Table(title=f"Market Statistics for '{search_term}'", show_header=True, header_style="bold magenta")
    table.add_column("Condition", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Median Price (UAH)", justify="right")
    table.add_column("Min Price (UAH)", justify="right")
    table.add_column("Max Price (UAH)", justify="right")
    table.add_column("Std Dev", justify="right")

    for condition, metrics in stats.items():
        table.add_row(
            condition.upper(),
            str(metrics["count"]),
            f"{metrics['median_price']:,.2f}",
            f"{metrics['min_price']:,.2f}",
            f"{metrics['max_price']:,.2f}",
            f"{metrics['std_dev']:,.2f}",
        )

    console.print(table)


if __name__ == "__main__":
    asyncio.run(main())
