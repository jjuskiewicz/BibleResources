"""Fetch each Keller sermon page on gospelinlife.com and pull the per-sermon details the archive list doesn't show.

The list pages (gil_scrape.py) carry title/series/scripture only. Each sermon page adds:
  overview   the "Overview" block - the sermon's opening (~5k chars), usually incl. where he turns to the text
  topics     the site's topic taxonomy ("Anxiety", "Prayer & Meditation")
  duration   "41:23"
The WP REST API doesn't expose these (checked Oct 2026: content/excerpt aren't in /wp-json/wp/v2/sermon), so it's one
page per sermon at DELAY seconds apart (~1,400 sermons -> ~30 min). Resumable: results are saved every 25 pages to
scraping/keller_details.json and sermons already there are skipped. Raw HTML isn't kept.

Usage (on a machine that can reach gospelinlife.com):
    uv run scraping/gil_details.py               # sermons on the site (data/sources/keller.json)
    uv run scraping/gil_details.py --all         # every row in keller_episodes.json (incl. unmapped/excluded)
    uv run scraping/gil_details.py --limit 5     # quick test
    uv run scraping/gil_details.py --retry-empty # re-fetch ones that came back with no overview
    uv run scraping/gil_details.py --max-seconds 160   # stop cleanly after N seconds; rerun to continue
Then: uv run scraping/convert_gil.py && uv run tools/build_sermons.py
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from gil_scrape import DELAY, fetch  # noqa: E402

OUT = HERE / "keller_details.json"


def _clean(fragment: str) -> str:
    fragment = re.sub(r"</p>\s*", "\n\n", fragment)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", "", fragment))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _meta(page: str, label: str) -> str | None:
    m = re.search(rf'<div class="gil-sermon-meta">{label}:.*?</div>', page, re.S)
    return m.group(0) if m else None


def parse_sermon_page(page: str) -> dict:
    """One sermon page -> details. Pure function: no network."""
    ov = re.search(r"<h2>\s*Overview\s*</h2>(.*?)</div>\s*</div>", page, re.S)
    topics_html = _meta(page, "Topics") or ""
    dur_html = _meta(page, "Duration") or ""
    dur = re.search(r"(\d+):(\d{2})(?::(\d{2}))?", _clean(dur_html))
    minutes = None
    if dur:
        a, b, c = dur.groups()
        minutes = round(int(a) * 60 + int(b) + int(c) / 60) if c else round(int(a) + int(b) / 60)
    return {
        "overview": _clean(ov.group(1)) if ov else "",
        "topics": [html.unescape(t).strip() for t in re.findall(r"<li[^>]*>(.*?)</li>", topics_html, re.S)],
        "durationMin": minutes,
    }


def targets(use_all: bool) -> list[tuple[str, str]]:
    if use_all:
        rows = json.loads((HERE / "keller_episodes.json").read_text(encoding="utf-8"))
        return [(str(r["wp_id"]), r["url"]) for r in rows if r.get("wp_id") and r.get("url")]
    rows = json.loads((ROOT / "data" / "sources" / "keller.json").read_text(encoding="utf-8"))
    return [(r["id"].removeprefix("keller-"), r["url"]) for r in rows if r.get("url")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every scraped row, not just sermons on the site")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--retry-empty", action="store_true")
    ap.add_argument("--delay", type=float, default=DELAY)
    ap.add_argument("--max-seconds", type=float, default=0, help="stop cleanly after this long (rerun to continue)")
    args = ap.parse_args()

    done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [(k, u) for k, u in targets(args.all)
            if k not in done or (args.retry_empty and not done[k].get("overview"))]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(done)} already fetched, {len(todo)} to go (~{len(todo) * (args.delay + 0.5) / 60:.0f} min)", flush=True)

    def save() -> None:
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(done, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(OUT)

    misses = 0
    t0 = time.monotonic()
    for i, (key, url) in enumerate(todo, 1):
        if args.max_seconds and time.monotonic() - t0 > args.max_seconds:
            print(f"time budget reached after {i - 1}; rerun to continue", flush=True)
            break
        time.sleep(args.delay)
        try:
            d = parse_sermon_page(fetch(url))
        except Exception as e:  # noqa: BLE001 - log and move on; --retry-empty / rerun picks it up
            print(f"  {key} {url}: {e}", file=sys.stderr, flush=True)
            continue
        if not d["overview"]:
            misses += 1
        done[key] = {"url": url, **d, "fetched": date.today().isoformat()}
        if i % 25 == 0 or i == len(todo):
            save()
            print(f"{i}/{len(todo)}  (no overview so far: {misses})", flush=True)
    save()
    have = sum(1 for v in done.values() if v.get("overview"))
    print(f"done: {len(done)} sermons, {have} with an overview -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
