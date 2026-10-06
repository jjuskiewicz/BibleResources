"""Pull every episode of an Apple Podcasts show (guid -> Apple link) from Apple's catalog API.

Usage:
    uv run scraping/apple_episodes.py 1245313998 -o scraping/cotcny_apple_episodes.json
    uv run scraping/apple_episodes.py --search "Bridgetown Audio Podcast"   # find a show id + its feed URL

Output rows: {guid, appleId, url, title, date}. rss_to_episodes.py joins these to the RSS feed on guid.
Auth: the anonymous developer token embedded in podcasts.apple.com's JS bundle (same one the web
player uses), so no Apple account. Needs podcasts.apple.com and amp-api.podcasts.apple.com reachable.
Python port of apple_scrape.txt (the browser-console version).
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

WEB = "https://podcasts.apple.com"
API = "https://amp-api.podcasts.apple.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36"


def get(url: str, token: str | None = None) -> str:
    headers = {"User-Agent": UA, "Origin": WEB}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return r.read().decode()


def find_token() -> str:
    page = get(f"{WEB}/us/browse")
    for js in re.findall(r'/assets/index~[^"]+\.js', page):
        if m := re.search(r"eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+", get(WEB + js)):
            return m.group(0)
    raise SystemExit("No developer token found in podcasts.apple.com JS bundle")


def search(term: str, token: str) -> None:
    q = urllib.parse.urlencode({"term": term, "types": "podcasts", "limit": 10, "extend": "feedUrl", "l": "en-US"})
    body = json.loads(get(f"{API}/v1/catalog/us/search?{q}", token))
    for p in body.get("results", {}).get("podcasts", {}).get("data", []):
        a = p["attributes"]
        print(f"{p['id']:>12}  {a.get('name')}  |  {a.get('feedUrl', '')}")


def episodes(show_id: str, token: str) -> list[dict]:
    out, offset, page = [], 0, 25
    while True:
        url = f"{API}/v1/catalog/us/podcasts/{show_id}/episodes?limit={page}&offset={offset}&l=en-US"
        body = json.loads(get(url, token))
        for e in body.get("data", []):
            a = e.get("attributes", {})
            out.append({
                "guid": a.get("guid", ""),
                "appleId": e["id"],
                "url": a.get("url") or f"{WEB}/us/podcast/id{show_id}?i={e['id']}",
                "title": a.get("name", ""),
                "date": a.get("releaseDateTime", "")[:10],
            })
        if not body.get("next"):
            return out
        offset += page
        time.sleep(0.3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("show_id", nargs="?")
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--search")
    args = ap.parse_args()
    token = find_token()
    if args.search:
        return search(args.search, token)
    if not (args.show_id and args.out):
        ap.error("show_id and -o are required unless --search")
    eps = episodes(args.show_id, token)
    args.out.write_text(json.dumps(eps, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(eps)} episodes ({sum(not e['guid'] for e in eps)} without guid) -> {args.out}")


if __name__ == "__main__":
    main()
