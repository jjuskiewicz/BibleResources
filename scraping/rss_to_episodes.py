"""Turn a podcast RSS feed (saved .xml) into the same episode JSON shape js_scrape.txt produces,
so convert_spotify.py can process it unchanged.

Usage:
    uv run scraping/rss_to_episodes.py scraping/vintage_feed.xml -o scraping/vintage_rss_episodes.json \
        [--spotify scraping/vintage_spotify_episodes.json] [--apple scraping/vintage_apple_episodes.json]

--spotify: when an RSS item's title matches a Spotify episode, use the Spotify link (nicer for listening);
           otherwise the item's <link> (church site) or the audio enclosure is used.
--apple:   output of apple_episodes.py; joined on the RSS <guid> (exact), adds "appleUrl".
Feeds carry full dates and full show notes, so no year inference and more passages found.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


def text(el: ET.Element, tag: str) -> str:
    x = el.find(tag)
    return (x.text or "").strip() if x is not None else ""


def strip_html(s: str) -> str:
    s = re.sub(r"<(br|p|/p|li|/li)[^>]*>", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def duration(s: str) -> str:
    """itunes:duration is seconds or H:MM:SS -> '1 hr 2 min' / '43 min 41 sec'."""
    s = (s or "").translate(str.maketrans("oOlI!", "00111"))  # hand-typed typos: "oo:48:00", "00:26:!5"
    if not s or not re.fullmatch(r"\d+(?::\d+){0,2}(?:\.\d+)?", s.strip()):
        return ""  # missing or junk (some feeds have values like "oo:47:38")
    s = s.strip()
    parts = [int(p) for p in s.split(":")] if ":" in s else [0, 0, int(float(s))]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    total = h * 3600 + m * 60 + sec
    h, m, sec = total // 3600, total % 3600 // 60, total % 60
    return f"{h} hr {m} min" if h else f"{m} min {sec} sec"


def key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def pick(candidates: list[dict], dt) -> str:
    """Spotify URL for the candidate whose date is within 10 days of the RSS pubDate."""
    if len(candidates) == 1:  # unique title: trust it (Spotify dates like "Wednesday" don't parse)
        return candidates[0]["url"]
    best = None
    for c in candidates:
        try:
            cd = datetime.strptime(c["date"], "%b %d, %Y")
        except ValueError:  # Spotify omits the current year
            try:
                cd = datetime.strptime(f"{c['date']} {dt.year}", "%b %d %Y")
            except (ValueError, AttributeError):
                continue
        gap = abs((cd.date() - dt.date()).days) if dt else 0
        if gap <= 10 and (best is None or gap < best[0]):
            best = (gap, c["url"])
    return best[1] if best else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("feed", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--spotify", type=Path, help="Spotify scrape to borrow episode links from")
    ap.add_argument("--apple", type=Path, help="apple_episodes.py output; adds appleUrl by guid")
    args = ap.parse_args()

    spotify = {}
    if args.spotify and args.spotify.exists():
        for e in json.loads(args.spotify.read_text()):  # same title can repeat ("Easter - Ger Jones")
            spotify.setdefault(key(e["title"]), []).append(e)

    apple = {}
    if args.apple and args.apple.exists():
        apple = {e["guid"]: e["url"] for e in json.loads(args.apple.read_text()) if e.get("guid")}

    items = ET.parse(args.feed).getroot().iter("item")
    episodes, matched, apple_matched = [], 0, 0
    for it in items:
        title = html.unescape(text(it, "title"))
        enc = it.find("enclosure")
        link = text(it, "link") or (enc.get("url") if enc is not None else "")
        pub = text(it, "pubDate")
        dt = parsedate_to_datetime(pub) if pub else None
        date = dt.strftime("%b %-d, %Y") if dt else ""
        if (sp := pick(spotify.get(key(title), []), dt)):
            link, matched = sp, matched + 1
        desc = strip_html(text(it, f"{CONTENT}encoded") or text(it, "description") or text(it, f"{ITUNES}summary"))
        author = text(it, f"{ITUNES}author")
        guid = text(it, "guid")
        apple_url = apple.get(guid, "")
        apple_matched += bool(apple_url)
        episodes.append({
            "title": title, "url": link, "date": date,
            "duration": duration(text(it, f"{ITUNES}duration")),
            "desc": desc,
            "author": author,  # often just the church name in church feeds, so not used for speaker
            "imageUrl": "", "audioUrl": enc.get("url") if enc is not None else "",
            "guid": guid, "appleUrl": apple_url,
        })

    args.out.write_text(json.dumps(episodes, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(episodes)} items -> {args.out}  ({matched} linked to Spotify, {apple_matched} to Apple)")


if __name__ == "__main__":
    main()
