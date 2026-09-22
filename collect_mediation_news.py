#!/usr/bin/env python3
"""Collect conflict/peace mediation news from public RSS feeds.

Only Python's standard library plus the widely available ``requests`` package
is required. The script is deliberately self-contained and safe to re-run.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: install requests with: python -m pip install requests", file=sys.stderr)
    raise

DEFAULT_SOURCES = [
    ("UN News", "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml", "en"),
    ("Crisis Group", "https://www.crisisgroup.org/rss.xml", "en"),
    ("ReliefWeb", "https://reliefweb.int/updates/rss.xml", "en"),
    ("Google News — conflict mediation", "https://news.google.com/rss/search?q=conflict+mediation&hl=en-US&gl=US&ceid=US:en", "en"),
    ("Google News — peace mediation", "https://news.google.com/rss/search?q=peace+mediation&hl=en-US&gl=US&ceid=US:en", "en"),
    ("Google News — peace talks", "https://news.google.com/rss/search?q=peace+talks&hl=en-US&gl=US&ceid=US:en", "en"),
    ("Google Actualités — médiation de conflit", "https://news.google.com/rss/search?q=m%C3%A9diation+de+conflit&hl=fr&gl=FR&ceid=FR:fr", "fr"),
    ("Google Actualités — négociations de paix", "https://news.google.com/rss/search?q=n%C3%A9gociations+de+paix&hl=fr&gl=FR&ceid=FR:fr", "fr"),
]
USER_AGENT = "MediationNewsCollector/1.0 (RSS; educational open-source tool)"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return re.sub(r"\s+", " ", value).strip()


def norm_title(title: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def parse_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        # Some Atom feeds use ISO 8601.
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            return ""


def tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def first_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(element):
        if tag_name(child.tag) in names:
            if tag_name(child.tag) == "link" and child.attrib.get("href"):
                return child.attrib["href"]
            return "".join(child.itertext())
    return ""


def parse_feed(payload: bytes, source: str, language: str) -> list[dict]:
    root = ET.fromstring(payload)
    entries = [e for e in root.iter() if tag_name(e.tag) in {"item", "entry"}]
    result = []
    for entry in entries:
        title = clean_text(first_text(entry, ("title",)))
        link = first_text(entry, ("link",)).strip()
        if not link:
            guid = first_text(entry, ("guid", "id")).strip()
            link = guid if guid.startswith(("http://", "https://")) else ""
        summary = clean_text(first_text(entry, ("description", "summary", "content", "encoded")))
        published = parse_date(first_text(entry, ("pubdate", "published", "updated", "date")))
        if title and link.startswith(("http://", "https://")):
            result.append({"titre": title, "source": source, "date_publication": published,
                           "lien": link, "resume": summary, "langue": language})
    return result


def fetch_source(source: str, url: str, language: str, timeout: int = 25) -> list[dict]:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return parse_feed(response.content, source, language)


def init_db(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titre TEXT NOT NULL,
        source TEXT NOT NULL,
        date_publication TEXT,
        lien TEXT NOT NULL UNIQUE,
        resume TEXT,
        langue TEXT,
        date_ajout TEXT NOT NULL,
        titre_normalise TEXT NOT NULL
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_articles_date ON articles(date_publication DESC, id DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_articles_title ON articles(titre_normalise)")
    connection.commit()


def upsert_articles(connection: sqlite3.Connection, candidates: list[dict]) -> int:
    added = 0
    seen_urls, seen_titles = set(), set()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for article in candidates:
        title_key = norm_title(article["titre"])
        if article["lien"] in seen_urls or (title_key and title_key in seen_titles):
            continue
        seen_urls.add(article["lien"]); seen_titles.add(title_key)
        cursor = connection.execute("""INSERT OR IGNORE INTO articles
            (titre, source, date_publication, lien, resume, langue, date_ajout, titre_normalise)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (article["titre"], article["source"], article["date_publication"], article["lien"],
             article["resume"], article["langue"], now, title_key))
        added += cursor.rowcount
    connection.commit()
    return added


def export_data(connection: sqlite3.Connection, output_dir: Path) -> int:
    rows = connection.execute("""SELECT id, titre, source, date_publication, lien, resume, langue, date_ajout
        FROM articles ORDER BY COALESCE(date_publication, date_ajout) DESC, id DESC""").fetchall()
    columns = ["id", "titre", "source", "date_publication", "lien", "resume", "langue", "date_ajout"]
    records = [dict(zip(columns, row)) for row in rows]
    with (output_dir / "articles.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns); writer.writeheader(); writer.writerows(records)
    with (output_dir / "articles.json").open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    html_rows = []
    for r in records:
        date = (r["date_publication"] or r["date_ajout"]).replace("T", " ").replace("+00:00", " UTC")
        excerpt = r["resume"][:360] + ("…" if len(r["resume"]) > 360 else "")
        html_rows.append(f'''<article><h2><a href="{html.escape(r["lien"], quote=True)}" target="_blank" rel="noopener">{html.escape(r["titre"])}</a></h2><p class="meta">{html.escape(r["source"])} · {html.escape(date)} · {html.escape(r["langue"].upper())}</p><p>{html.escape(excerpt or "Résumé non fourni par le flux.")}</p></article>''')
    page = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Veille — médiation de conflits</title><style>body{{font-family:system-ui,-apple-system,sans-serif;max-width:980px;margin:0 auto;padding:2rem 1rem;color:#17202a;background:#f5f7fa}}header,article{{background:white;border:1px solid #dfe5ec;border-radius:10px;padding:1.1rem 1.3rem;margin-bottom:1rem;box-shadow:0 2px 8px #17202a0b}}h1{{margin:.1rem 0 .3rem;color:#173b57}}h2{{font-size:1.15rem;margin:.1rem 0 .35rem}}a{{color:#1266a8}}.meta{{color:#5d6d7e;font-size:.88rem;margin:.2rem 0 .6rem}}article p:last-child{{line-height:1.5;margin-bottom:.1rem}}footer{{color:#687785;font-size:.82rem;text-align:center;margin:1.5rem}}</style></head><body><header><h1>Veille — médiation de conflits</h1><p>{len(records)} article(s), triés du plus récent au plus ancien. Mise à jour : {dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}.</p></header>{"".join(html_rows)}<footer>Sources RSS publiques · Les liens ouvrent les articles originaux.</footer></body></html>'''
    (output_dir / "index.html").write_text(page, encoding="utf-8")
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args(); output_dir = args.output_dir.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    db_path = (args.db or output_dir / "mediation_news.db").resolve(); db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path); init_db(connection)
    candidates, failures = [], []
    for source, url, language in DEFAULT_SOURCES:
        try:
            items = fetch_source(source, url, language, args.timeout); candidates.extend(items)
            print(f"OK   {source}: {len(items)} article(s)")
        except Exception as exc:
            failures.append(f"{source}: {exc}"); print(f"WARN {source}: {exc}", file=sys.stderr)
        time.sleep(0.15)
    added = upsert_articles(connection, candidates); total = export_data(connection, output_dir); connection.close()
    print(json.dumps({"articles_recus": len(candidates), "articles_inseres": added, "articles_total": total,
                      "flux_en_echec": len(failures), "db": str(db_path)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
