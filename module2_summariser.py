"""
========================================================
MODULE 2 — PRODUCT SUMMARISER & LINK FORMATTER
========================================================
Handles: AI-style rule-based summarisation, pros/cons
extraction, price-tier classification, clean product
cards with direct Amazon links, and markdown / JSON
export formats.
No paid API required — pure rule-based NLP + heuristics.
========================================================
"""

import re
import json
import textwrap
import logging
from dataclasses import dataclass, asdict
from typing import Optional

# Module 1 data model
from module1_scraper_engine import RawProduct

logger = logging.getLogger(__name__)


# ─── Summary data model ──────────────────────────────────
@dataclass
class ProductSummary:
    asin: str
    title: str
    short_title: str             # truncated for display
    price: Optional[str]
    price_tier: str              # Budget / Mid-range / Premium
    rating: Optional[str]
    review_count: Optional[str]
    availability: Optional[str]
    image_url: Optional[str]
    product_url: str
    summary: str                 # ✨ Key feature narrative
    highlights: list[str]        # top 3 bullet points
    pros: list[str]
    cons: list[str]
    verdict: str                 # one-liner recommendation


# ─── Text helpers ────────────────────────────────────────
def _truncate(text: str, length: int = 65) -> str:
    return text if len(text) <= length else text[:length].rstrip() + "…"


def _clean(text: str) -> str:
    """Strip extra whitespace and unicode junk."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _sentence_count(text: str) -> int:
    return len(re.findall(r"[.!?]+", text))


# ─── Price tier classifier ───────────────────────────────
_PRICE_PATTERNS = re.compile(r"[\₹\$\£\€]?\s*([\d,]+)")

def _parse_price_value(price_str: Optional[str]) -> Optional[float]:
    if not price_str:
        return None
    match = _PRICE_PATTERNS.search(price_str)
    if match:
        return float(match.group(1).replace(",", ""))
    return None


def classify_price_tier(price_str: Optional[str], currency: str = "INR") -> str:
    """
    Classify a price string into Budget / Mid-range / Premium.

    Thresholds (INR):
        Budget    < 1 000
        Mid-range 1 000 – 10 000
        Premium   > 10 000

    For USD multiply thresholds by ~0.012; adjust currency param.
    """
    value = _parse_price_value(price_str)
    if value is None:
        return "Unknown"

    thresholds = {
        "INR": (1_000, 10_000),
        "USD": (15, 150),
        "GBP": (12, 120),
        "EUR": (14, 140),
    }
    low, high = thresholds.get(currency.upper(), (1_000, 10_000))

    if value < low:
        return "Budget"
    elif value <= high:
        return "Mid-range"
    else:
        return "Premium"


# ─── Feature bullet scorer ───────────────────────────────
_PRO_KEYWORDS = {
    "fast", "quick", "powerful", "long battery", "durable", "waterproof",
    "wireless", "noise cancel", "clear", "crisp", "lightweight", "compact",
    "premium", "excellent", "high quality", "great", "best", "comfortable",
    "easy", "simple", "affordable", "value", "strong", "reliable", "smooth",
    "hd", "4k", "8k", "ultra", "pro", "plus", "max", "super", "advanced",
}

_CON_KEYWORDS = {
    "no", "not", "without", "lack", "limited", "only", "basic", "heavy",
    "bulky", "expensive", "difficult", "slow", "weak", "poor", "cheap",
    "fragile", "complicated", "short battery", "no warranty",
}


def _score_bullet(bullet: str) -> int:
    """
    Return +1 (positive), -1 (negative), 0 (neutral) for a feature bullet.
    """
    lower = bullet.lower()
    pros = sum(1 for kw in _PRO_KEYWORDS if kw in lower)
    cons = sum(1 for kw in _CON_KEYWORDS if kw in lower)
    if pros > cons:
        return 1
    elif cons > pros:
        return -1
    return 0


def extract_pros_cons(
    features: list[str],
    description: Optional[str] = None,
) -> tuple[list[str], list[str]]:
    """
    Split feature bullets into pros and cons lists.

    Args:
        features:    Bullet-point strings from product page.
        description: Optional description text for extra context.

    Returns:
        (pros_list, cons_list)  – each capped at 4 items.
    """
    pros: list[str] = []
    cons: list[str] = []

    for bullet in features:
        score = _score_bullet(bullet)
        if score > 0:
            pros.append(_truncate(bullet, 90))
        elif score < 0:
            cons.append(_truncate(bullet, 90))

    # If we couldn't find any cons from bullets, look in description
    if not cons and description:
        sentences = re.split(r"(?<=[.!?])\s+", description)
        for sent in sentences:
            if _score_bullet(sent) < 0:
                cons.append(_truncate(_clean(sent), 90))
                if len(cons) >= 2:
                    break

    return pros[:4], cons[:4]


# ─── Summary generator ───────────────────────────────────
_RATING_LABELS = {
    5: "exceptional",
    4: "very good",
    3: "decent",
    2: "below average",
    1: "poor",
}

def _rating_label(rating_str: Optional[str]) -> str:
    if not rating_str:
        return "unrated"
    match = re.search(r"([\d.]+)", rating_str)
    if match:
        score = float(match.group(1))
        return _RATING_LABELS.get(round(score), "average")
    return "rated"


def _build_summary(product: RawProduct, tier: str) -> str:
    """
    Generate a concise 2-3 sentence narrative summary from raw data.
    No external API needed – structured rule-based generation.
    """
    name = _truncate(product.title, 50)
    rating_lbl = _rating_label(product.rating)
    price_part = f"priced at {product.price}" if product.price else "with unlisted pricing"

    # Pull first meaningful feature bullet as the USP
    usp = ""
    for bullet in product.features:
        if len(bullet) > 20:
            usp = _truncate(bullet, 80)
            break

    sentences: list[str] = []

    # Sentence 1 – identity
    sentences.append(
        f"The {name} is a {tier.lower()}-tier product {price_part}, "
        f"with an {rating_lbl} customer rating"
        + (f" from {product.review_count} reviews" if product.review_count else "")
        + "."
    )

    # Sentence 2 – key feature / USP
    if usp:
        sentences.append(f"Standout feature: {usp}.")
    elif product.description:
        excerpt = _truncate(_clean(product.description), 100)
        sentences.append(excerpt + ".")

    # Sentence 3 – availability nudge
    if product.availability:
        avail = product.availability.lower()
        if "in stock" in avail:
            sentences.append("Currently in stock and ready to ship.")
        elif "out of stock" in avail:
            sentences.append("Note: currently out of stock.")

    return " ".join(sentences)


def _build_verdict(tier: str, rating_str: Optional[str], pros: list[str]) -> str:
    """Single-line recommendation verdict."""
    rating_lbl = _rating_label(rating_str)
    if tier == "Budget":
        return (
            f"A {rating_lbl} budget pick — great for cost-conscious buyers "
            "looking for reliable everyday performance."
        )
    elif tier == "Premium":
        return (
            f"A {rating_lbl} premium choice — ideal for buyers who want "
            "top-of-the-line specs without compromise."
        )
    else:
        return (
            f"A solid mid-range option with {rating_lbl} reviews — "
            "balances price and performance well."
        )


# ─── Main summariser ─────────────────────────────────────
def summarise_product(
    product: RawProduct,
    currency: str = "INR",
) -> ProductSummary:
    """
    Convert a RawProduct into a rich ProductSummary.

    Args:
        product:  RawProduct from Module 1.
        currency: ISO currency code for price classification.

    Returns:
        ProductSummary dataclass.
    """
    tier = classify_price_tier(product.price, currency)
    pros, cons = extract_pros_cons(product.features, product.description)
    summary_text = _build_summary(product, tier)
    verdict = _build_verdict(tier, product.rating, pros)
    highlights = [_truncate(f, 80) for f in product.features[:3]]

    return ProductSummary(
        asin=product.asin,
        title=product.title,
        short_title=_truncate(product.title, 65),
        price=product.price,
        price_tier=tier,
        rating=product.rating,
        review_count=product.review_count,
        availability=product.availability,
        image_url=product.image_url,
        product_url=product.product_url,
        summary=summary_text,
        highlights=highlights,
        pros=pros,
        cons=cons,
        verdict=verdict,
    )


def summarise_many(
    products: list[RawProduct],
    currency: str = "INR",
) -> list[ProductSummary]:
    """Batch summarise a list of RawProducts."""
    summaries = [summarise_product(p, currency) for p in products]
    logger.info("Summarised %d products.", len(summaries))
    return summaries


# ─── Formatters ──────────────────────────────────────────
def format_as_markdown(summary: ProductSummary) -> str:
    """
    Render a ProductSummary as a rich Markdown product card
    complete with a clickable Amazon link.
    """
    pros_md = "\n".join(f"  - ✅ {p}" for p in summary.pros) or "  - N/A"
    cons_md = "\n".join(f"  - ⚠️ {c}" for c in summary.cons) or "  - N/A"
    highlights_md = "\n".join(f"  - {h}" for h in summary.highlights) or "  - N/A"

    card = textwrap.dedent(f"""
    ---
    ## 🛒 {summary.short_title}

    | Field         | Value                          |
    |---------------|-------------------------------|
    | **ASIN**      | `{summary.asin}`              |
    | **Price**     | {summary.price or 'N/A'} ({summary.price_tier}) |
    | **Rating**    | {summary.rating or 'N/A'} — {summary.review_count or '?'} reviews |
    | **Stock**     | {summary.availability or 'N/A'} |
    | **Link**      | [View on Amazon]({summary.product_url}) |

    ### 📝 Summary
    {summary.summary}

    ### ✨ Highlights
    {highlights_md}

    ### 👍 Pros
    {pros_md}

    ### 👎 Cons
    {cons_md}

    ### 🏆 Verdict
    > {summary.verdict}
    """).strip()

    return card


def format_as_json(summary: ProductSummary) -> str:
    """Serialise a ProductSummary to pretty-printed JSON."""
    return json.dumps(asdict(summary), indent=2, ensure_ascii=False)


def format_batch_markdown(summaries: list[ProductSummary]) -> str:
    """Render multiple product cards separated by dividers."""
    return "\n\n".join(format_as_markdown(s) for s in summaries)


def format_quick_links(summaries: list[ProductSummary]) -> str:
    """
    Return a compact link list — useful for a quick reference table.

    Example output:
        1. Sony WF-1000XM5 — ₹19,990 [View ↗](https://...)
        2. boAt Airdopes 141 — ₹1,299 [View ↗](https://...)
    """
    lines = []
    for i, s in enumerate(summaries, 1):
        price_part = f"— {s.price} " if s.price else ""
        lines.append(
            f"{i}. **{s.short_title}** {price_part}"
            f"[View on Amazon ↗]({s.product_url})"
        )
    return "\n".join(lines)


# ─── Quick test ──────────────────────────────────────────
if __name__ == "__main__":
    # Simulate a RawProduct for offline testing
    from module1_scraper_engine import RawProduct

    dummy = RawProduct(
        asin="B0BDHQFL5G",
        title="Sony WF-1000XM5 Truly Wireless Noise Cancelling Headphones",
        price="₹19,990",
        rating="4.5 out of 5 stars",
        review_count="3,821 ratings",
        availability="In Stock",
        image_url=None,
        product_url="https://www.amazon.in/dp/B0BDHQFL5G",
        features=[
            "Industry-leading noise cancellation with the Integrated Processor V2",
            "Crystal-clear calls with Precise Voice Pickup Technology",
            "Up to 24 hours total battery life with charging case",
            "Comfortable lightweight design at just 5.9 g per earbud",
            "Hi-Res Audio and LDAC support for wireless high-quality sound",
        ],
        description=(
            "Experience the world around you in a completely new way. "
            "These earbuds feature the most advanced noise cancelling "
            "technology Sony has ever developed."
        ),
    )

    summary = summarise_product(dummy)
    print(format_as_markdown(summary))
    print("\n\n=== JSON ===\n")
    print(format_as_json(summary))
