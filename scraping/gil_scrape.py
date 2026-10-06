"""Scrape Tim Keller sermons from gospelinlife.com's sermon archive into a raw episode JSON.

The archive is server-rendered WordPress (ElasticPress facets), 20 sermons per page. Each card carries a
data-sermon JSON blob (WP post id, title, permalink, audio/video) plus series, "Tim Keller (YEAR)" and scripture.
The list only shows the YEAR; --dates fills exact dates from the WP REST API (/wp-json/wp/v2/sermon). Checked
Oct 2026: those are the preached dates (91% Sundays, all agree with the listed year), so always pass --dates.

Usage (run on a machine that can reach gospelinlife.com):
    uv run scraping/gil_scrape.py                  # fetch all pages (cached), write scraping/keller_episodes.json
    uv run scraping/gil_scrape.py --dates          # also try to fill exact dates from /wp-json
    uv run scraping/gil_scrape.py --offline        # re-parse the cached pages only (no network)
    uv run scraping/gil_scrape.py --parse-file scraping/gil_page5.html   # test the parser on one saved page

Raw pages are cached in scraping/gil_pages/ (gitignored); delete a page file to re-fetch it.
Then: uv run scraping/convert_gil.py
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "gil_pages"
OUT = HERE / "keller_episodes.json"
BASE = "https://gospelinlife.com"
LIST_URL = BASE + "/sermons/page/{page}/?ep_filter_speaker=tim-keller&ep_post_type_filter=sermon"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
DELAY = 1.0  # seconds between live requests


def fetch(url: str, retries: int = 3) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise
            err = e
        except urllib.error.URLError as e:
            err = e
        wait = 5 * attempt
        print(f"  {url}: {err} - retry in {wait}s", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


# ---------- parsing ----------

def _text(fragment: str | None) -> str:
    if fragment is None:
        return ""
    fragment = re.sub(r'<span class="item-tag">.*?</span>', "", fragment, flags=re.S)  # "Series:" / "Scripture:"
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _div(card: str, cls: str) -> str | None:
    m = re.search(rf'<div class="{cls}">(.*?)</div>', card, re.S)
    return m.group(1) if m else None


def parse_page(page_html: str) -> list[dict]:
    """One archive page -> list of raw sermon dicts. Pure function: no network."""
    cards = re.split(r'<div class="gil-list-item gil-list-item--sermon\b', page_html)[1:]
    out = []
    for card in cards:
        blob = re.search(r'data-sermon="([^"]*)"', card)
        data = json.loads(html.unescape(blob.group(1))) if blob else {}
        title_m = re.search(r'<h3 class="item-title">(.*?)</h3>', card, re.S)
        speaker_raw = _text(_div(card, "sermon-speaker"))  # "Tim Keller (2014)"
        year_m = re.search(r"\((\d{4})\)\s*$", speaker_raw)
        video = data.get("video") or {}
        out.append({
            "wp_id": data.get("id"),
            "title": _text(title_m.group(1)) if title_m else html.unescape(data.get("title", "")),
            "url": data.get("permalink") or "",
            "speaker": re.sub(r"\s*\(\d{4}\)\s*$", "", speaker_raw),
            "year": int(year_m.group(1)) if year_m else None,
            "series": _text(_div(card, "sermon-series")),
            "scripture": _text(_div(card, "sermon-scripture")),
            "audio": data.get("audio") or "",
            "video": (str(video.get("value") or "").split() or [""])[0] if isinstance(video, dict) else "",  # some have notes appended
            "thumb": data.get("thumb") or "",
            "date": None,  # filled by --dates when the REST API cooperates
        })
    return out


def total_results(page_html: str) -> int | None:
    m = re.search(r'gil-archive--results-count">\s*([\d,]+)\s+Results', page_html)
    return int(m.group(1).replace(",", "")) if m else None


def last_page(page_html: str) -> int:
    nums = [int(n) for n in re.findall(r'class="page-numbers"[^>]*>\s*(\d+)\s*<', page_html)]
    nums += [int(n) for n in re.findall(r"/sermons/page/(\d+)/", page_html)]
    return max(nums) if nums else 1


# ---------- fetching ----------

def get_page(n: int, offline: bool) -> str | None:
    f = CACHE / f"page_{n:03d}.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    if offline:
        return None
    time.sleep(DELAY)
    print(f"fetch page {n}")
    text = fetch(LIST_URL.format(page=n))
    f.write_text(text, encoding="utf-8")
    return text


def fill_dates(rows: list[dict]) -> None:
    """Exact post dates via the WP REST API, if the 'sermon' post type is exposed there. Best effort."""
    try:
        types = json.loads(fetch(BASE + "/wp-json/wp/v2/types", retries=1))
    except Exception as e:  # noqa: BLE001
        print(f"--dates: REST API not reachable ({e}); keeping year-only dates", file=sys.stderr)
        return
    t = types.get("sermon") if isinstance(types, dict) else None
    if not t or not t.get("rest_base"):
        print("--dates: 'sermon' post type isn't exposed in /wp-json; keeping year-only dates", file=sys.stderr)
        return
    endpoint = f"{BASE}/wp-json/{t.get('rest_namespace', 'wp/v2')}/{t['rest_base']}"
    by_id = {r["wp_id"]: r for r in rows if r["wp_id"]}
    ids = list(by_id)
    got = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        url = f"{endpoint}?include={','.join(map(str, chunk))}&per_page=100&_fields=id,date"
        time.sleep(DELAY)
        try:
            items = json.loads(fetch(url, retries=2))
        except Exception as e:  # noqa: BLE001
            print(f"--dates: {e}; stopping", file=sys.stderr)
            break
        for it in items:
            r = by_id.get(it.get("id"))
            if r and it.get("date"):
                r["post_date"] = it["date"][:10]
                got += 1
    print(f"--dates: {got}/{len(ids)} post dates from {endpoint}")
    # Sanity: a WP post date is only the sermon date if it agrees with the year shown on the site.
    agree = sum(1 for r in rows if r.get("post_date") and r["year"] and r["post_date"][:4] == str(r["year"]))
    have = sum(1 for r in rows if r.get("post_date"))
    print(f"--dates: post date year matches listed year for {agree}/{have}")
    for r in rows:
        if r.get("post_date") and r["year"] and r["post_date"][:4] == str(r["year"]):
            r["date"] = r["post_date"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", action="store_true", help="try /wp-json for exact dates")
    ap.add_argument("--offline", action="store_true", help="parse cached pages only")
    ap.add_argument("--parse-file", type=Path, help="parse one saved page and print the result")
    args = ap.parse_args()

    if args.parse_file:
        page = args.parse_file.read_text(encoding="utf-8")
        rows = parse_page(page)
        print(json.dumps(rows[:3], indent=1, ensure_ascii=False))
        print(f"{len(rows)} cards; total={total_results(page)}; last page={last_page(page)}")
        return

    CACHE.mkdir(exist_ok=True)
    first = get_page(1, args.offline)
    if first is None:
        sys.exit("no cached page 1; run without --offline")
    total, pages = total_results(first), last_page(first)
    print(f"site reports {total} results across {pages} pages")

    rows, seen = [], set()
    for n in range(1, pages + 1):
        page = first if n == 1 else get_page(n, args.offline)
        if page is None:
            print(f"page {n}: not cached, skipped")
            continue
        parsed = parse_page(page)
        if not parsed:
            print(f"page {n}: 0 cards parsed - layout change? check {CACHE / f'page_{n:03d}.html'}")
        for r in parsed:
            key = r["wp_id"] or r["url"]
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)

    if args.dates:
        fill_dates(rows)

    OUT.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"-> {OUT.relative_to(HERE.parent)}: {len(rows)} unique sermons")
    if total and len(rows) != total:
        print(f"WARNING: expected {total}, got {len(rows)}. If short, the archive order shifted between pages:"
              f" delete scraping/gil_pages/ and re-run.")
    missing = [k for k in ("scripture", "year", "series") if sum(1 for r in rows if not r[k])]
    for k in missing:
        print(f"  {sum(1 for r in rows if not r[k])} sermons with no {k}")


if __name__ == "__main__":
    main()
