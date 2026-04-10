# 🛒 Amazon Web Scraper — 3-Module Architecture

A feature-rich Amazon scraper with automatic product summaries,
direct product links, export to CSV / JSON / Markdown, and SQLite persistence.

---

## 📁 Project Structure

```
amazon_web_scraper/
├── module1_scraper_engine.py   ← HTTP + HTML extraction
├── module2_summariser.py       ← Summary, pros/cons, link formatting
├── module3_storage_cli.py      ← DB, exports, CLI runner
├── amazon_scraper_output/      ← Auto-created on first run
│   ├── products.db             ← SQLite store
│   ├── products_<ts>.csv
│   ├── products_<ts>.json
│   └── report_<ts>.md
├── templates/                 
│   ├── index.html
│   ├── results.html
│   ├── history.html
├── static/                   
│   └── style.css
├── requirements.txt   
└── README.md
```

---

## 🧩 Module Overview

### Module 1 — Scraper Engine (`module1_scraper_engine.py`)
| Feature | Detail |
|---------|--------|
| Anti-bot headers | Rotating User-Agent pool |
| Retry logic | 3 retries + exponential back-off |
| Search scraping | Collects ASINs from result pages |
| Detail scraping | Title, price, rating, reviews, availability, image, bullets, description |
| Data model | `RawProduct` dataclass |

### Module 2 — Summariser (`module2_summariser.py`)
| Feature | Detail |
|---------|--------|
| Auto-summary | 2-3 sentence narrative per product |
| Price classification | Budget / Mid-range / Premium (INR/USD/GBP/EUR) |
| Pros/Cons extraction | Keyword-scored bullet analysis |
| Verdict | One-liner buy recommendation |
| Amazon link | Clean `product_url` preserved in every output |
| Export formats | Markdown card · JSON · quick-link list |

### Module 3 — Storage & CLI (`module3_storage_cli.py`)
| Feature | Detail |
|---------|--------|
| SQLite persistence | Upsert by ASIN, timestamp tracked |
| Duplicate detection | Skips already-stored ASINs |
| CSV export | Flat, spreadsheet-ready |
| JSON export | Full nested structure |
| Markdown report | Quick-links + full product cards |
| Comparison table | Side-by-side Markdown table |
| CLI | `python module3_storage_cli.py "query" -n 5 --export csv json markdown` |

---

## ⚙️ Installation

```bash
pip install requests beautifulsoup4
```

No other dependencies required (stdlib: `re`, `csv`, `json`, `sqlite3`, `argparse`, `dataclasses`, `pathlib`).

---

## 🚀 Quick Start

### Run from CLI
```bash
# Scrape 5 wireless earbuds, save everything
python module3_storage_cli.py "wireless earbuds" -n 5

# Scrape 10 laptops, USD pricing, markdown only
python module3_storage_cli.py "gaming laptop" -n 10 -c USD --export markdown

# Scrape 2 pages of results
python module3_storage_cli.py "smartphone" -n 20 -p 2

# List all stored products
python module3_storage_cli.py --list-db
```

### Run from Python
```python
from module3_storage_cli import run_pipeline

summaries = run_pipeline(
    query="noise cancelling headphones",
    max_products=5,
    currency="INR",
    export_formats=["csv", "markdown"],
)

for s in summaries:
    print(s.short_title, "→", s.product_url)
    print("Summary:", s.summary)
    print("Pros:", s.pros)
    print("Verdict:", s.verdict)
```

### Use individual modules
```python
# Module 1 only — raw scraping
from module1_scraper_engine import scrape_products_by_query
products = scrape_products_by_query("yoga mat", max_products=3)

# Module 2 only — summarise a RawProduct
from module2_summariser import summarise_product, format_as_markdown
summary = summarise_product(products[0])
print(format_as_markdown(summary))
```

---

## 📄 Sample Markdown Output

```markdown
---
## 🛒 Sony WF-1000XM5 Truly Wireless Noise Cancelling…

| Field     | Value                                    |
|-----------|------------------------------------------|
| ASIN      | `B0BDHQFL5G`                            |
| Price     | ₹19,990 (Premium)                       |
| Rating    | 4.5 out of 5 stars — 3,821 reviews      |
| Stock     | In Stock                                |
| Link      | [View on Amazon](https://amazon.in/dp/…)|

### 📝 Summary
The Sony WF-1000XM5 is a premium-tier product priced at ₹19,990,
with an exceptional customer rating from 3,821 reviews.
Standout feature: Industry-leading noise cancellation with the
Integrated Processor V2. Currently in stock and ready to ship.

### 👍 Pros
  - ✅ Industry-leading noise cancellation
  - ✅ Up to 24 hours total battery life
  - ✅ Hi-Res Audio and LDAC support

### 🏆 Verdict
> A exceptional premium choice — ideal for buyers who want
> top-of-the-line specs without compromise.
```

---

## ⚠️ Legal & Ethical Notes

- Amazon's Terms of Service restrict automated scraping.
  Use this for **educational / personal research** only.
- Add meaningful delays (`delay` param) to avoid overloading servers.
- Consider using the **Amazon Product Advertising API** for production use.
- Never store or redistribute scraped data commercially.

---

## 🗺️ Data Flow

```
Query
  │
  ▼
[Module 1] build_search_url → _get_page → scrape_search_results
                                              │  (ASINs)
                                              ▼
                           scrape_product_detail × N
                                              │  (RawProduct[])
                                              ▼
[Module 2]             summarise_many → ProductSummary[]
                                              │
                         ┌────────────────────┤
                         ▼                    ▼
                  format_as_markdown    format_as_json
                  format_quick_links
                         │
                         ▼
[Module 3]    save_to_db  export_csv  export_json  export_markdown
```
