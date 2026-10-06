"""Fetch BibleProject's book guides (one per book; Samuel, Kings, Chronicles, Ezra-Nehemiah, 1-3 John share a page)
and parse each into structured sections, as a rubric for judging whether a sermon teaches its passage.

Source URLs: the "bibleproject" field in data/books.json (60 unique pages for 66 books).
Raw pages are cached in scraping/bp_pages/ (gitignored); delete a file to re-fetch. --offline re-parses the cache.

Output scraping/bibleproject_guides.json, keyed by book id:
  {"url", "title", "about", "big_idea", "sections": [{"heading", "book", "range", "start": [ch, v], "end": [ch, v],
                                                      "title", "text"}]}
Pages shared by several books are stored under each of them with all sections; filter on section "book".

BibleProject content is copyrighted. This file is for local tagging only: it's gitignored so GitHub Pages
doesn't publish it. Don't copy its text into data/.

Usage:
    uv run scraping/bp_guides.py              # fetch (2s apart, ~2-3 min) + parse
    uv run scraping/bp_guides.py --offline    # parse the cache only
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from gil_scrape import fetch  # noqa: E402

CACHE = HERE / "bp_pages"
OUT = HERE / "bibleproject_guides.json"
DELAY = 2.0

RANGE = re.compile(r"^(?P<book>(?:[1-3]\s)?[A-Za-z][A-Za-z ]*?)\s+(?P<range>\d+[a-c]?(?::\d+)?(?:\s*[-–]\s*\d+[a-c]?(?::\d+)?)?)\s*[:–-]\s*(?P<title>.+)$")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _span(rng: str) -> tuple[list[int], list[int]]:
    """'1:27-2:18' -> [1,27],[2,18]; '3' -> [3,0],[3,0]; '1-4' -> [1,0],[4,0]."""
    # BibleProject marks part-chapters with a letter ("10b-19", "2c-3"); the letter is dropped here.
    a, _, b = re.sub(r"[\sa-c]", "", rng).replace("–", "-").partition("-")
    sc, _, sv = a.partition(":")
    start = [int(sc), int(sv or 0)]
    if not b:
        return start, list(start)
    if ":" in b:
        ec, ev = b.split(":")
        return start, [int(ec), int(ev)]
    return start, ([start[0], int(b)] if sv else [int(b), 0])  # '1:1-26' vs '1-4'


def parse_guide(page: str) -> dict:
    """One guide page -> structured dict. Pure function: no network."""
    body = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", "", page, flags=re.S)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    # Split on h2s; within each chunk keep paragraphs before any "Related Resources" h3.
    parts = re.split(r"(<h2[^>]*>.*?</h2>)", body, flags=re.S)
    out = {"title": _text(h1.group(1)) if h1 else "", "about": "", "big_idea": "", "sections": []}
    for head, chunk in zip(parts[1::2], parts[2::2]):
        heading = _text(head)
        if heading.lower().startswith("more resources"):
            break
        chunk = re.split(r"<h3[^>]*>\s*Related Resources", chunk, maxsplit=1)[0]
        if heading.lower() == "about":
            idea = re.split(r"<h3[^>]*>\s*The Big Idea\s*</h3>", chunk, maxsplit=1)
            out["about"] = "\n\n".join(_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", idea[0], re.S) if _text(p))
            if len(idea) > 1:
                out["big_idea"] = "\n\n".join(_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", idea[1], re.S) if _text(p))
            continue
        paras = [_text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", chunk, re.S)]
        sec = {"heading": heading, "text": "\n\n".join(p for p in paras if p)}
        m = RANGE.match(heading)
        if re.match(r"2 and 3 John\b", heading):  # 1-3 John share a page; this section covers both short letters
            sec.update(book="2-3 John", title=heading.split(":", 1)[-1].strip())
        elif m:
            start, end = _span(m["range"])
            sec.update(book=m["book"].strip(), range=m["range"].replace(" ", ""), start=start, end=end, title=m["title"].strip())
        out["sections"].append(sec)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    books = json.loads((ROOT / "data" / "books.json").read_text(encoding="utf-8"))["books"]
    CACHE.mkdir(exist_ok=True)
    parsed: dict[str, dict] = {}
    result, problems = {}, []
    for b in books:
        url = b.get("bibleproject")
        if not url:
            problems.append(f"{b['id']}: no guide url")
            continue
        if url not in parsed:
            f = CACHE / (url.rstrip("/").rsplit("/", 1)[-1] + ".html")
            if not f.exists():
                if args.offline:
                    problems.append(f"{b['id']}: not cached")
                    continue
                time.sleep(DELAY)
                print(f"fetch {url}", flush=True)
                f.write_text(fetch(url), encoding="utf-8")
            parsed[url] = parse_guide(f.read_text(encoding="utf-8"))
        g = parsed[url]
        if not any("range" in s for s in g["sections"]):
            problems.append(f"{b['id']}: no verse-range sections parsed")
        result[b["id"]] = {"url": url, **g}
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n_sec = sum(len(g["sections"]) for g in parsed.values())
    print(f"{len(result)} books from {len(parsed)} pages, {n_sec} sections -> {OUT.relative_to(ROOT)}")
    for p in problems:
        print("  !", p)


if __name__ == "__main__":
    main()
