"""Find a podcast's public RSS feed via Apple's iTunes Search API (no key needed).

Usage:  uv run scraping/find_feed.py "vintage church"
Prints show name, publisher, episode count, and feedUrl for the top matches.
Spotify-exclusive shows have no public feed and won't appear.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request


def main() -> None:
    term = " ".join(sys.argv[1:]) or sys.exit(__doc__)
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"media": "podcast", "limit": 8, "term": term})
    with urllib.request.urlopen(url, timeout=20) as r:
        results = json.load(r)["results"]
    if not results:
        print("No matches. Try the church's exact podcast name as shown on Apple/Spotify.")
    for x in results:
        print(f"{x['collectionName']}  ({x.get('artistName', '')}, {x.get('trackCount', '?')} episodes)")
        print(f"    {x.get('feedUrl', '(no feedUrl)')}\n")


if __name__ == "__main__":
    main()
