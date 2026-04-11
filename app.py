"""
app.py — Flask web interface for the Amazon Product Scraper
Run:  python app.py
Then open:  http://127.0.0.1:5000
"""

from flask import Flask, render_template, request, jsonify
import logging
import traceback

# ── Module imports ──────────────────────────────────────
from module1_scraper_engine import scrape_products_by_query
from module2_summariser import summarise_many, format_quick_links
from module3_storage_cli import (
    init_db,
    save_to_db,
    load_from_db,
    export_csv,
    export_json,
    export_markdown,
    generate_comparison_table,
)

# ── App setup ───────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure DB exists on startup
init_db()


# ── Routes ──────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    """Landing / search page."""
    return render_template("index.html")


@app.route("/search", methods=["POST"])
def search():
    """
    Handle search form submission.
    Scrapes Amazon, summarises, saves to DB, returns results page.
    """
    try:
        query        = request.form.get("query", "").strip() or "wireless earbuds"
        max_products = int(request.form.get("max_products", 5))
        pages        = int(request.form.get("pages", 1))
        currency     = request.form.get("currency", "INR")
        export_fmts  = request.form.getlist("export")   # ['csv','json','markdown']

        # Clamp values to safe range
        max_products = max(1, min(max_products, 20))
        pages        = max(1, min(pages, 3))

        logger.info("Search: query=%r max=%d pages=%d", query, max_products, pages)

        # ── Step 1: Scrape ──────────────────────────────
        raw_products = scrape_products_by_query(
            query,
            max_pages=pages,
            max_products=max_products,
        )

        if not raw_products:
            return render_template(
                "results.html",
                summaries=[],
                query=query,
                error="No products found. Amazon may have blocked the request — try again in a moment.",
                comparison_table="",
                quick_links="",
            )

        # ── Step 2: Summarise ───────────────────────────
        summaries = summarise_many(raw_products, currency=currency)

        # ── Step 3: Persist ─────────────────────────────
        save_to_db(summaries)

        # ── Step 4: Export (optional) ───────────────────
        exported_files = []
        if "csv"      in export_fmts: exported_files.append(str(export_csv(summaries)))
        if "json"     in export_fmts: exported_files.append(str(export_json(summaries)))
        if "markdown" in export_fmts: exported_files.append(str(export_markdown(summaries)))

        # ── Step 5: Render ──────────────────────────────
        comparison_table = generate_comparison_table(summaries)
        quick_links      = format_quick_links(summaries)

        return render_template(
            "results.html",
            summaries=summaries,
            query=query,
            currency=currency,
            comparison_table=comparison_table,
            quick_links=quick_links,
            exported_files=exported_files,
            error=None,
        )

    except Exception as exc:
        logger.error("Search error: %s", traceback.format_exc())
        return render_template(
            "results.html",
            summaries=[],
            query=request.form.get("query", ""),
            error=f"An error occurred: {exc}",
            comparison_table="",
            quick_links="",
        )


@app.route("/history")
def history():
    """Show all previously scraped products from SQLite."""
    rows = load_from_db()
    return render_template("history.html", rows=rows)

@app.route('/clear-history')
def clear_history():
    from flask import redirect, url_for
    import sqlite3
    from module3_storage_cli import DB_PATH

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM products")
        conn.commit()
        conn.close()

    except Exception as e:
        print("Clear history error:", e)

    return redirect(url_for('history'))

import zipfile
import os
from flask import send_file

@app.route('/download-all')
def download_all():
    import zipfile
    import os
    from flask import send_file

    folder = "amazon_scraper_output"
    zip_path = os.path.join(folder, "exports.zip")

    try:
        valid_ext = (".csv", ".json", ".md")

        # Get only valid files
        files = [
            f for f in os.listdir(folder)
            if f.endswith(valid_ext)
            and not f.startswith('.')   # ignore hidden files
        ]

        # Sort by latest modified
        files = sorted(
            files,
            key=lambda x: os.path.getmtime(os.path.join(folder, x)),
            reverse=True
        )[:3]   # only latest 3 files

        # Create zip
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file in files:
                full_path = os.path.join(folder, file)

                # Extra safety check
                if os.path.isfile(full_path) and file.endswith(valid_ext):
                    zipf.write(full_path, file)

        return send_file(zip_path, as_attachment=True)

    except Exception as e:
        return f"Download error: {e}"
