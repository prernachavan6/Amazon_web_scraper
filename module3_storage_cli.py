"""
========================================================
MODULE 3 — STORAGE, EXPORT & CLI RUNNER
========================================================
Handles: saving results to CSV / JSON / Markdown,
SQLite persistence, duplicate detection, a simple
CLI with argparse, and a comparison report generator.
========================================================
"""

import csv
import json
import sqlite3
import logging
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

# Sibling modules
from module1_scraper_engine import scrape_products_by_query, RawProduct
from module2_summariser import (
    summarise_many,
    format_batch_markdown,
    format_quick_links,
    ProductSummary,
)

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ─── Directories ─────────────────────────────────────────
OUTPUT_DIR = Path("amazon_scraper_output")
OUTPUT_DIR.mkdir(exist_ok=True)

DB_PATH = OUTPUT_DIR / "products.db"


# ─────────────────────────────────────────────────────────
#  SECTION A — SQLite persistence
# ─────────────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    """Open (or create) the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the products table if it does not exist."""
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                asin          TEXT PRIMARY KEY,
                title         TEXT,
                short_title   TEXT,
                price         TEXT,
                price_tier    TEXT,
                rating        TEXT,
                review_count  TEXT,
                availability  TEXT,
                product_url   TEXT,
                image_url     TEXT,
                summary       TEXT,
                highlights    TEXT,   -- JSON array
                pros          TEXT,   -- JSON array
                cons          TEXT,   -- JSON array
                verdict       TEXT,
                scraped_at    TEXT
            )
        """)
        conn.commit()
    logger.info("Database ready: %s", DB_PATH)


def save_to_db(summaries: list[ProductSummary]) -> int:
    """
    Upsert ProductSummary rows into SQLite.

    Returns:
        Number of rows inserted / updated.
    """
    now = datetime.utcnow().isoformat()
    rows = []
    for s in summaries:
        rows.append((
            s.asin, s.title, s.short_title, s.price, s.price_tier,
            s.rating, s.review_count, s.availability, s.product_url,
            s.image_url, s.summary,
            json.dumps(s.highlights),
            json.dumps(s.pros),
            json.dumps(s.cons),
            s.verdict, now,
        ))

    with _get_connection() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO products VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, rows)
        conn.commit()

    logger.info("Saved %d product(s) to database.", len(rows))
    return len(rows)


def load_from_db(asin: str | None = None) -> list[dict]:
    """
    Load products from SQLite.

    Args:
        asin: If provided, fetch only that ASIN; otherwise fetch all.

    Returns:
        List of product dicts.
    """
    with _get_connection() as conn:
        if asin:
            rows = conn.execute(
                "SELECT * FROM products WHERE asin = ?", (asin,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM products ORDER BY scraped_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def is_duplicate(asin: str) -> bool:
    """Check if an ASIN is already in the database."""
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM products WHERE asin = ?", (asin,)
        ).fetchone()
    return row is not None


# ─────────────────────────────────────────────────────────
#  SECTION B — Export helpers
# ─────────────────────────────────────────────────────────

def _timestamped(stem: str, suffix: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{stem}_{ts}{suffix}"


def export_csv(summaries: list[ProductSummary], filepath: Path | None = None) -> Path:
    """
    Export summaries to a flat CSV file.

    Columns include all scalar fields plus the Amazon link.
    """
    path = filepath or _timestamped("products", ".csv")
    fieldnames = [
        "asin", "title", "price", "price_tier",
        "rating", "review_count", "availability",
        "summary", "verdict", "product_url",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for s in summaries:
            writer.writerow(asdict(s))
    logger.info("CSV exported → %s", path)
    return path


def export_json(summaries: list[ProductSummary], filepath: Path | None = None) -> Path:
    """Export summaries to JSON (full fidelity, all arrays preserved)."""
    path = filepath or _timestamped("products", ".json")
    data = [asdict(s) for s in summaries]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("JSON exported → %s", path)
    return path


def export_markdown(summaries: list[ProductSummary], filepath: Path | None = None) -> Path:
    """
    Export a human-readable Markdown report with:
    - Quick link list at the top
    - Full product cards below
    """
    path = filepath or _timestamped("report", ".md")

    header = (
        f"# Amazon Product Report\n"
        f"_Generated {datetime.now().strftime('%d %b %Y %H:%M')}_\n\n"
        f"## Quick Links\n\n"
        f"{format_quick_links(summaries)}\n\n"
        f"---\n\n"
        f"## Full Product Cards\n\n"
    )

    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(format_batch_markdown(summaries))

    logger.info("Markdown report exported → %s", path)
    return path


# ─────────────────────────────────────────────────────────
#  SECTION C — Comparison table
# ─────────────────────────────────────────────────────────

def generate_comparison_table(summaries: list[ProductSummary]) -> str:
    """
    Build a Markdown comparison table across multiple products.

    Columns: Title | Price | Tier | Rating | Reviews | Link
    """
    header = (
        "| # | Product | Price | Tier | Rating | Reviews | Amazon Link |\n"
        "|---|---------|-------|------|--------|---------|-------------|\n"
    )
    rows = ""
    for i, s in enumerate(summaries, 1):
        rows += (
            f"| {i} | {s.short_title} | {s.price or '–'} | {s.price_tier} "
            f"| {s.rating or '–'} | {s.review_count or '–'} "
            f"| [View ↗]({s.product_url}) |\n"
        )
    return header + rows


# ─────────────────────────────────────────────────────────
#  SECTION D — Full pipeline runner
# ─────────────────────────────────────────────────────────

def run_pipeline(
    query: str,
    max_products: int = 5,
    max_pages: int = 1,
    currency: str = "INR",
    skip_duplicates: bool = True,
    export_formats: list[str] | None = None,
) -> list[ProductSummary]:
    """
    End-to-end pipeline:
      1. Scrape Amazon search results (Module 1)
      2. Summarise each product (Module 2)
      3. Save to DB + export files (Module 3)

    Args:
        query:           Search keyword(s).
        max_products:    Maximum products to scrape.
        max_pages:       Search result pages to scan.
        currency:        ISO currency code for price tiers.
        skip_duplicates: Skip ASINs already in the database.
        export_formats:  Any subset of ['csv', 'json', 'markdown'].

    Returns:
        List of ProductSummary objects.
    """
    export_formats = export_formats or ["csv", "json", "markdown"]

    print(f"\n🔍  Searching Amazon for: '{query}'")
    print(f"    max_products={max_products}  max_pages={max_pages}\n")

    # Step 1 — Scrape
    raw_products: list[RawProduct] = scrape_products_by_query(
        query,
        max_pages=max_pages,
        max_products=max_products,
    )

    if not raw_products:
        print("⚠️  No products scraped. Check network or anti-bot measures.")
        return []

    # Step 2 — Filter duplicates
    if skip_duplicates:
        init_db()
        before = len(raw_products)
        raw_products = [p for p in raw_products if not is_duplicate(p.asin)]
        skipped = before - len(raw_products)
        if skipped:
            print(f"⏭️  Skipped {skipped} duplicate ASIN(s) already in DB.")

    # Step 3 — Summarise
    summaries = summarise_many(raw_products, currency=currency)

    if not summaries:
        print("Nothing new to save.")
        return []

    # Step 4 — Persist
    init_db()
    save_to_db(summaries)

    # Step 5 — Export
    exported: list[Path] = []
    if "csv" in export_formats:
        exported.append(export_csv(summaries))
    if "json" in export_formats:
        exported.append(export_json(summaries))
    if "markdown" in export_formats:
        exported.append(export_markdown(summaries))

    # Step 6 — Print summary to stdout
    print("\n" + "=" * 60)
    print("📦  SCRAPED PRODUCTS — QUICK LINKS")
    print("=" * 60)
    print(format_quick_links(summaries))
    print("\n" + "=" * 60)
    print("📊  COMPARISON TABLE")
    print("=" * 60)
    print(generate_comparison_table(summaries))

    if exported:
        print("\n📁  Exported files:")
        for p in exported:
            print(f"    {p}")

    return summaries


# ─────────────────────────────────────────────────────────
#  SECTION E — CLI entry point
# ─────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amazon_scraper",
        description="Amazon product scraper with AI-style summarisation.",
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="wireless earbuds",
        help="Product search keyword(s)  (default: 'wireless earbuds')",
    )
    parser.add_argument(
        "-n", "--max-products",
        type=int, default=5,
        metavar="N",
        help="Maximum number of products to scrape  (default: 5)",
    )
    parser.add_argument(
        "-p", "--pages",
        type=int, default=1,
        metavar="P",
        help="Number of search result pages to scan  (default: 1)",
    )
    parser.add_argument(
        "-c", "--currency",
        type=str, default="INR",
        metavar="CURRENCY",
        help="ISO currency code for price tier (INR/USD/GBP/EUR)  (default: INR)",
    )
    parser.add_argument(
        "--no-skip-dupes",
        action="store_true",
        help="Re-scrape even if ASIN already exists in DB",
    )
    parser.add_argument(
        "--export",
        nargs="+",
        choices=["csv", "json", "markdown"],
        default=["csv", "json", "markdown"],
        help="Export format(s) to generate  (default: all three)",
    )
    parser.add_argument(
        "--list-db",
        action="store_true",
        help="Print all stored ASINs from the local database and exit",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.list_db:
        init_db()
        rows = load_from_db()
        if not rows:
            print("Database is empty.")
        else:
            print(f"\n{'ASIN':<14} {'Title':<55} Scraped at")
            print("-" * 90)
            for r in rows:
                print(
                    f"{r['asin']:<14} "
                    f"{r['short_title']:<55} "
                    f"{r['scraped_at']}"
                )
        return

    run_pipeline(
        query=args.query,
        max_products=args.max_products,
        max_pages=args.pages,
        currency=args.currency,
        skip_duplicates=not args.no_skip_dupes,
        export_formats=args.export,
    )


if __name__ == "__main__":
    main()
