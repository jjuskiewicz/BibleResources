"""Convert scraping/keller_episodes.json (from gil_scrape.py) into site sermon records.

Usage:
    uv run scraping/convert_gil.py

Writes:
    data/sources/keller.json     sermons with a scripture ref
    scraping/keller_review.csv   every sermon + extracted refs, for spot checks
Reads (optional):
    scraping/keller_overrides.json   {"<wp_id>": {"refs": [...], "passage": "...", "exclude": true, ...}}

The site's Scripture field is already structured ("Esther 3:1-6; 6:1-10"), so refs come from that field only,
with the book carried across ";"-separated parts that omit it. Displayed passage = the site's text verbatim.
Excluded: other speakers, and talks that aren't sermons (open forums, Q&A, leader talks, seminars, conferences...).
Dates: exact when gil_scrape.py --dates found them; otherwise only the year is known, kept in "year"
(no "date", so these sort after dated sermons).
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from convert_spotify import BOOK_BY_ID, dedupe_refs, find_refs  # noqa: E402

CHURCH = "keller"
SRC = HERE / "keller_episodes.json"
OVERRIDES = HERE / "keller_overrides.json"
OUT = ROOT / "data" / "sources" / f"{CHURCH}.json"
REVIEW = HERE / f"{CHURCH}_review.csv"


SPEAKER = "Tim Keller"
# Talks that aren't sermons: Q&A, open forums, leader training, seminars, conferences, retreats, outreach events.
NOT_SERMON = re.compile(
    r"open forum|\bq\s*(?:&|and)\s*a\b|leader talks?|seminar|conference|retreat|center for faith and work"
    r"|questioning christianity|interarts|tolkien|hope for new york",
    re.I,
)


def exclude_reason(r: dict) -> str:
    if r["speaker"] != SPEAKER:
        return f"speaker: {r['speaker'] or 'none'}"
    if not r["year"] and r["title"].strip().lower() == "sermons":
        return "junk entry"
    m = NOT_SERMON.search(f"{r['title']} | {r['series']}")
    return f"not a sermon: {m.group(0)}" if m else ""


def scripture_refs(text: str) -> list[dict]:
    """'Matthew 18:21-35; 1 Corinthians 13:4,6' / 'Esther 3:1-6; 6:1-10' -> refs (book carried forward)."""
    refs, book_name = [], None
    for part in re.split(r"\s*;\s*", text):
        found = find_refs(part)
        if found:
            refs += found
            book_name = BOOK_BY_ID[found[-1]["book"]]["name"]
        elif book_name and re.match(r"\d{1,3}\b", part):
            refs += find_refs(f"{book_name} {part}")
    return dedupe_refs(refs)


def whole_book(text: str) -> list[dict]:
    """Scripture field that is just a book name -> whole-book ref (no chapters)."""
    key = re.sub(r"[^a-z0-9]", "", text.lower())
    for b in BOOK_BY_ID.values():
        names = [b["name"], b["id"], *b.get("aliases", [])]
        if key in {re.sub(r"[^a-z0-9]", "", n.lower()) for n in names}:
            return [{"book": b["id"]}]
    return []


def main() -> None:
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    out, review = [], []
    for r in rows:
        key = str(r["wp_id"])
        ov = overrides.get(key, {})
        refs = scripture_refs(r["scripture"]) if r["scripture"] else []
        if not refs and r["scripture"]:  # whole-book scripture: "Proverbs", "Ephesians"
            refs = whole_book(r["scripture"])
        if not refs:  # leader talks titled by passage: "1 Corinthians 6-7"
            refs = dedupe_refs(find_refs(r["title"]))
        status = "mapped" if refs else "unmapped"
        reason = "override" if ov.get("exclude") else exclude_reason(r)
        if ov.get("include"):  # override wins over the automatic rules
            reason = ""
        if reason:
            status = "excluded"
        rec = {
            "id": f"{CHURCH}-{key}",
            "title": r["title"],
            "church": CHURCH,
            "speaker": r["speaker"] or "Tim Keller",
            **({"date": r["date"]} if r.get("date") else {}),
            "year": r["year"],
            "series": r["series"],
            "passage": r["scripture"],
            "refs": [{k: v for k, v in x.items() if not k.startswith("_")} for x in refs],
            "url": r["url"],
            "audio": r["audio"],
            "tags": [],
            "source": "gospelinlife",
            "refSource": "site",
        }
        rec.update({k: v for k, v in ov.items() if k not in ("exclude", "include")})
        if ov.get("refs") and not reason:
            status = "override"
        review.append({"wp_id": key, "status": status, "reason": reason, "speaker": r["speaker"], "year": r["year"], "title": r["title"], "series": r["series"],
                       "scripture": r["scripture"], "refs": "; ".join(f"{x['book']} {x.get('start', '')}-{x.get('end', '')}"
                                                                   for x in rec["refs"]), "url": r["url"]})
        if status in ("mapped", "override"):
            out.append(rec)

    out.sort(key=lambda s: (s.get("date") or str(s.get("year") or "")), reverse=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    with REVIEW.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(review[0]))
        w.writeheader()
        w.writerows(review)
    counts = {s: sum(1 for x in review if x["status"] == s) for s in ("mapped", "override", "unmapped", "excluded")}
    print(f"{len(rows)} sermons: {counts} -> {OUT.relative_to(ROOT)} ({len(out)}), {REVIEW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
