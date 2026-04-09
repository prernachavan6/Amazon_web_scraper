"""
========================================================
MODULE 1 — AMAZON SCRAPER ENGINE
========================================================
Handles: HTTP sessions, anti-bot headers, HTML fetching,
raw product data extraction (title, price, rating, ASIN,
product URL, image, availability).
========================================================
"""

import re
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ─── Data model ──────────────────────────────────────────
@dataclass
class RawProduct:
    """Raw scraped data before summarisation."""
    asin: str
    title: str
    price: Optional[str]
    rating: Optional[str]
    review_count: Optional[str]
    availability: Optional[str]
    image_url: Optional[str]
    product_url: str
    features: list[str] = field(default_factory=list)   # bullet points
    description: Optional[str] = None                   # "About this item" blob


# ─── Rotating user-agents ────────────────────────────────
USER_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/124.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Version/17.4.1 Safari/605.1.15"),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:125.0) "
     "Gecko/20100101 Firefox/125.0"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) "
     "Version/17.4 Mobile/15E148 Safari/604.1"),
]

BASE_URL = "https://www.amazon.in"   # change to .com / .co.uk as needed


# ─── Session factory ─────────────────────────────────────
def build_session() -> requests.Session:
    """Create a requests.Session with rotating headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return session


# ─── Fetch helpers ───────────────────────────────────────
def _get_page(
    session: requests.Session,
    url: str,
    retries: int = 3,
    delay_range: tuple[float, float] = (1.5, 3.5),
) -> Optional[BeautifulSoup]:
    """
    Fetch a URL with retry + random delay to avoid rate-limiting.

    Returns:
        BeautifulSoup object or None on failure.
    """
    for attempt in range(1, retries + 1):
        try:
            # Rotate User-Agent on every retry
            session.headers["User-Agent"] = random.choice(USER_AGENTS)
            resp = session.get(url, timeout=15)

            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")

            elif resp.status_code == 503:
                logger.warning(
                    "Amazon returned 503 (attempt %d/%d). "
                    "Possible bot detection – waiting longer…",
                    attempt, retries
                )
                time.sleep(random.uniform(5.0, 9.0))

            else:
                logger.warning(
                    "HTTP %d for %s (attempt %d/%d)",
                    resp.status_code, url, attempt, retries
                )

        except requests.RequestException as exc:
            logger.error("Request error on attempt %d: %s", attempt, exc)

        if attempt < retries:
            time.sleep(random.uniform(*delay_range))

    logger.error("Failed to fetch: %s", url)
    return None


# ─── ASIN helpers ────────────────────────────────────────
def extract_asin_from_url(url: str) -> Optional[str]:
    """Extract ASIN from any Amazon product URL."""
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
    return match.group(1) if match else None


def build_product_url(asin: str) -> str:
    return f"{BASE_URL}/dp/{asin}"


def build_search_url(query: str, page: int = 1) -> str:
    """Build a search URL for the given keyword query."""
    safe_query = requests.utils.quote(query)
    return f"{BASE_URL}/s?k={safe_query}&page={page}"


# ─── Search result scraper ───────────────────────────────
def scrape_search_results(
    query: str,
    max_pages: int = 1,
    max_products: int = 10,
    session: Optional[requests.Session] = None,
) -> list[str]:
    """
    Scrape Amazon search results for a query.

    Args:
        query:        Search keyword(s).
        max_pages:    Number of result pages to crawl.
        max_products: Cap on total ASINs collected.
        session:      Optional pre-built requests.Session.

    Returns:
        List of ASINs found.
    """
    session = session or build_session()
    asins: list[str] = []

    for page in range(1, max_pages + 1):
        url = build_search_url(query, page)
        logger.info("Scraping search page %d: %s", page, url)

        soup = _get_page(session, url)
        if soup is None:
            break

        # Amazon wraps each result in a div with data-asin attribute
        cards = soup.select("div[data-asin]")
        for card in cards:
            asin = card.get("data-asin", "").strip()
            if asin and asin not in asins:
                asins.append(asin)
            if len(asins) >= max_products:
                return asins

        logger.info("  → collected %d ASINs so far", len(asins))
        time.sleep(random.uniform(2.0, 4.0))   # polite crawl delay

    return asins


# ─── Product detail scraper ──────────────────────────────
def scrape_product_detail(
    asin: str,
    session: Optional[requests.Session] = None,
) -> Optional[RawProduct]:
    """
    Scrape a single Amazon product page by ASIN.

    Args:
        asin:    10-character Amazon ASIN.
        session: Optional pre-built requests.Session.

    Returns:
        RawProduct dataclass or None if scraping fails.
    """
    session = session or build_session()
    url = build_product_url(asin)
    logger.info("Scraping product: %s", url)

    soup = _get_page(session, url)
    if soup is None:
        return None

    # ── Title ──────────────────────────────────────────
    title_tag = soup.select_one("#productTitle")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    # ── Price ──────────────────────────────────────────
    price = None
    for selector in [
        "span.a-price > span.a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price .a-price-whole",
    ]:
        price_tag = soup.select_one(selector)
        if price_tag:
            price = price_tag.get_text(strip=True)
            break

    # ── Rating & reviews ───────────────────────────────
    rating_tag = soup.select_one("span[data-hook='rating-out-of-text']")
    rating = rating_tag.get_text(strip=True) if rating_tag else None

    review_tag = soup.select_one("span#acrCustomerReviewText")
    review_count = review_tag.get_text(strip=True) if review_tag else None

    # ── Availability ───────────────────────────────────
    avail_tag = soup.select_one("#availability span")
    availability = avail_tag.get_text(strip=True) if avail_tag else None

    # ── Image ──────────────────────────────────────────
    image_url = None
    img_tag = soup.select_one("#imgTagWrapperId img, #landingImage")
    if img_tag:
        image_url = img_tag.get("src") or img_tag.get("data-old-hires")

    # ── Feature bullets ────────────────────────────────
    features: list[str] = []
    for li in soup.select("#feature-bullets ul li span.a-list-item"):
        text = li.get_text(strip=True)
        if text:
            features.append(text)

    # ── Description blob ──────────────────────────────
    desc_tag = soup.select_one("#productDescription p")
    description = desc_tag.get_text(strip=True) if desc_tag else None

    return RawProduct(
        asin=asin,
        title=title,
        price=price,
        rating=rating,
        review_count=review_count,
        availability=availability,
        image_url=image_url,
        product_url=url,
        features=features,
        description=description,
    )
# ─── Batch scraper ───────────────────────────────────────
def scrape_amazon_products(
    query: str,
    max_pages: int = 1,
    max_products: int = 5,
    delay: float = 2.5,
) -> list[RawProduct]:
    """
    End-to-end: search → collect ASINs → scrape each detail page.

    Args:
        query:        Product keyword(s).
        max_pages:    Search pages to scan.
        max_products: Max product detail pages to scrape.
        delay:        Extra wait (seconds) between detail requests.

    Returns:
        List of RawProduct objects.
    """
    session = build_session()
    asins = scrape_search_results(query, max_pages, max_products, session)
    logger.info("Found %d ASINs for query '%s'", len(asins), query)

    products: list[RawProduct] = []
    for asin in asins:
        product = scrape_product_detail(asin, session)
        if product:
            products.append(product)
        time.sleep(delay + random.uniform(0.5, 1.5))

    logger.info("Scraped %d product(s).", len(products))
    return products


# ─── Quick test ──────────────────────────────────────────
if __name__ == "__main__":
    results = scrape_products_by_query("wireless earbuds", max_products=3)
    for p in results:
        print(f"\n{'='*60}")
        print(f"ASIN : {p.asin}")
        print(f"Title: {p.title}")
        print(f"Price: {p.price}")
        print(f"Rating: {p.rating}  ({p.review_count})")
        print(f"URL  : {p.product_url}")
def scrape_products_by_query(query, max_products=5, max_pages=1):
    return scrape_amazon_products(query, max_products, max_pages)