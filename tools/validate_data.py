"""Validate data/sermons.json and data/churches.json against data/books.json.

Usage:  uv run tools/validate_data.py      (or: python3 tools/validate_data.py)
Exits non-zero on errors so it can gate a GitHub Action.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
REQUIRED = ("title", "church", "url", "refs")


def main() -> int:
    books = {b["id"]: b for b in json.loads((DATA / "books.json").read_text())["books"]}
    churches = json.loads((DATA / "churches.json").read_text())
    raw = json.loads((DATA / "sermons.json").read_text())
    sermons = raw if isinstance(raw, list) else raw.get("sermons", [])

    errors: list[str] = []
    warnings: list[str] = []

    church_ids = [c.get("id") for c in churches]
    for dup in {c for c in church_ids if church_ids.count(c) > 1}:
        errors.append(f"churches.json: duplicate id '{dup}'")
    for c in churches:
        if not c.get("id") or not c.get("name"):
            errors.append(f"churches.json: entry missing id/name: {c}")

    seen_urls: dict[str, int] = {}
    for i, s in enumerate(sermons):
        tag = f"sermons[{i}] '{s.get('title', '?')}'"
        for key in REQUIRED:
            if not s.get(key):
                errors.append(f"{tag}: missing '{key}'")
        if s.get("church") and s["church"] not in church_ids:
            errors.append(f"{tag}: church '{s['church']}' not in churches.json")
        url = s.get("url", "")
        if url and not re.match(r"^https?://", url):
            errors.append(f"{tag}: url must start with http(s)://")
        if url in seen_urls:
            warnings.append(f"{tag}: same url as sermons[{seen_urls[url]}]")
        seen_urls.setdefault(url, i)
        if s.get("date"):
            try:
                date.fromisoformat(s["date"])
            except ValueError:
                errors.append(f"{tag}: date '{s['date']}' is not YYYY-MM-DD")
        elif not s.get("year"):
            warnings.append(f"{tag}: no date (sorts last)")

        for r in s.get("refs", []):
            book = books.get(r.get("book"))
            if not book:
                errors.append(f"{tag}: unknown book id '{r.get('book')}' (use ids from books.json, e.g. '1-samuel')")
                continue
            start, end = r.get("start"), r.get("end", r.get("start"))
            if start is None:
                continue  # whole-book sermon
            if not (1 <= start <= book["chapters"]) or not (start <= end <= book["chapters"]):
                errors.append(f"{tag}: {book['name']} {start}-{end} out of range (1-{book['chapters']})")

    for w in warnings:
        print(f"warn  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"\n{len(sermons)} sermons, {len(churches)} churches: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
