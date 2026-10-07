# LA Farmers Sermon Library

A static site for the LA Farmers men's group: browse the 66 books of the Bible, click one, and get links to sermons on it from the churches we attend. No build step, no backend. GitHub Pages serves the files as-is.

## Run locally

`fetch()` doesn't work from `file://`, so serve the folder:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Deploy (GitHub Pages)

1. Push this folder to a GitHub repo (root of the default branch).
2. Repo **Settings → Pages → Build and deployment → Deploy from a branch**, pick the branch and `/ (root)`.
3. Site appears at `https://<user>.github.io/<repo>/`. `.nojekyll` is included so GitHub serves files untouched.

## Layout

```
index.html            page shell
assets/styles.css     design tokens, light/dark, mobile bottom sheet
assets/app.js         rendering, search, routing  (CONFIG block at top)
data/books.json       66 books, sections, chapter counts, search aliases, BibleProject guide links  (don't need to touch)
data/churches.json    the churches we pull from
data/sermons.json     the sermons  <-- this is what you'll grow
data/notes.json       show notes per sermon id (generated; loaded only when a sermon page opens)
assets/spotify.svg, assets/apple-podcasts.svg   listen icons (used as CSS masks, so CSS sets their color)
tools/validate_data.py  checks the data before you push
```

## Data schema

### churches.json

```json
[
  { "id": "church-a", "name": "Sample Church A", "short": "Church A", "url": "https://example.com", "color": "#2f6b8a" }
]
```

`color` is optional (used for the dot next to the church name). `short` is optional; phones show it on cards and filter chips instead of the full name.

### sermons.json

```json
{
  "sermons": [
    {
      "title": "Grace Abounds",
      "church": "church-a",
      "speaker": "Lead Pastor",
      "date": "2026-08-23",
      "series": "Romans",
      "passage": "Romans 5:12-6:14",
      "refs": [{ "book": "romans", "start": 5, "end": 6 }],
      "url": "https://...",
      "tags": ["grace"]
    }
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `title` | yes | |
| `church` | yes | must match an `id` in churches.json |
| `url` | yes | link to the sermon page / video / podcast episode (a Spotify link gets the Spotify icon) |
| `appleUrl` | no | Apple Podcasts episode link (filled by `rss_to_episodes.py --apple`) |
| `audio` | no | direct audio file; offered as "Play the audio file" |
| `refs` | yes | one or more `{book, start, end}`. `book` is a books.json id (`genesis`, `1-samuel`, `song-of-songs`); names like `"1 Sam"` also resolve. Omit `start`/`end` for a whole-book overview. `end` defaults to `start`. |
| `passage` | no | display text; if omitted it's generated from `refs` |
| `speaker`, `date` (YYYY-MM-DD), `series`, `tags` | no | all searchable |

A sermon covering two books (e.g. "Genesis 15; Romans 4") lists both in `refs` and shows up under each book.

Validate before pushing:

```bash
uv run tools/validate_data.py
```

## Features

- Book grid grouped by section, colored OT warm / NT cool. Badge = sermon count, bottom bar = share of chapters covered. Empty books are muted.
- Search understands books (`1 cor`, `first samuel`, `ps`), references (`John 3`, `Rom 8:28` then Enter opens that chapter), and sermon text (title, speaker, series, tags, church).
- Testament toggle and multi-select church filter.
- Book drawer with a chapter picker (chapters with sermons are highlighted) and sermons grouped by chapter.
- Shareable deep links: `#/john` or `#/john/3`. The link button in the drawer copies it.
- Sermon cards: one-tap listen icons (Spotify / Apple, or site / audio when that's all there is); tapping the rest of the card opens the sermon page (`#/sermon/<id>`) in the same panel: big listen buttons (the service you used last goes first, remembered per browser), passage/speaker/series, show notes, and the whole series in order with this sermon marked. Back returns to the list where you left it; a shared sermon link's Back goes to that passage.
- Keyboard: `/` focuses search, `Esc` closes the drawer. Light/dark follow the OS. Drawer is a bottom sheet on phones.
- Book studies: the book drawer's "Book studies only" toggle shows sermons that teach the passage in context (`study` in sermons.json, from scraping/fit/); they sort first in each chapter and carry a "Study" mark.
- Phones: compact header, sticky search, 4-across book grid, 3-line sermon cards (passage + "Study" mark / date, title, church · speaker · length · series; topic tags live on the sermon page, not the card). The book sheet has a sticky, swipeable strip of only the chapters that have sermons; drag the sheet header down to close; the link button opens the native share sheet.
- Jump-to-section row under the search bar (Law, History, Wisdom...). Tapping one scrolls there; it highlights the section you're in as you scroll and hides while a search is active.

## Config

Top of `assets/app.js`:

- `suggestUrl`: set to a GitHub "new issue" URL (or a Google Form) to show "Suggest a sermon" links.
- `recentCount`: how many items in "Recently added".

## Data pipeline

```
scraping/<church>_spotify_episodes.json   raw scrape (js_scrape.txt, run in the browser console on the show page)
        │  uv run scraping/convert_spotify.py scraping/cotcny_spotify_episodes.json --church cotcny --scraped-on YYYY-MM-DD
        ├─> data/sources/cotcny.json        sermons with a scripture ref
        └─> scraping/cotcny_review.csv      every episode: mapped / unmapped / excluded + what was extracted
scraping/<church>_overrides.json           hand fixes, keyed by Spotify episode id (optional)
data/sources/manual.json                   hand-entered sermons from anywhere
        │  uv run tools/build_sermons.py && uv run tools/validate_data.py
        └─> data/sermons.json               what the site loads (generated - don't edit)
```

Per church:

Apple Podcasts links: `apple_episodes.py` pulls every episode of a show from Apple's catalog API (guid + episode link)
and `rss_to_episodes.py --apple` joins them to the feed on the RSS `<guid>`, so matching is exact. Needs
podcasts.apple.com and amp-api.podcasts.apple.com reachable; `--search "Show name"` finds a new church's Apple show id
(check the printed feed URL matches). `apple_scrape.txt` is the same thing as a browser-console script.

```bash
# Church of the City NY: RSS feed (Libsyn), linked to Spotify episodes
curl -L "https://rss.libsyn.com/shows/100249/destinations/527009.xml" -o scraping/cotcny_feed.xml
uv run scraping/apple_episodes.py 1245313998 -o scraping/cotcny_apple_episodes.json
uv run scraping/rss_to_episodes.py scraping/cotcny_feed.xml -o scraping/cotcny_rss_episodes.json --spotify scraping/cotcny_spotify_episodes.json --apple scraping/cotcny_apple_episodes.json
uv run scraping/convert_spotify.py scraping/cotcny_rss_episodes.json --church cotcny --source rss

# Vintage: RSS feed (preferred - exact dates, no browser scraping), borrowing Spotify links by title+date
curl -L "https://vintagetwopoint0.squarespace.com/vintage-church-la-sermons?format=rss" -o scraping/vintage_feed.xml
uv run scraping/apple_episodes.py 1205019953 -o scraping/vintage_apple_episodes.json
uv run scraping/rss_to_episodes.py scraping/vintage_feed.xml -o scraping/vintage_rss_episodes.json --spotify scraping/vintage_spotify_episodes.json --apple scraping/vintage_apple_episodes.json
uv run scraping/convert_spotify.py scraping/vintage_rss_episodes.json --church vintage-sm --source rss --strip "Santa Monica"

# Bridgetown Church (Portland): Podbean feed, linked to Spotify episodes
curl -L "https://feed.podbean.com/bridgetown/feed.xml" -o scraping/bridgetown_feed.xml
uv run scraping/apple_episodes.py 84246334 -o scraping/bridgetown_apple_episodes.json
uv run scraping/rss_to_episodes.py scraping/bridgetown_feed.xml -o scraping/bridgetown_rss_episodes.json --spotify scraping/bridgetown_spotify_episodes.json --apple scraping/bridgetown_apple_episodes.json
uv run scraping/convert_spotify.py scraping/bridgetown_rss_episodes.json --church bridgetown --source rss

# Church Eleven22: Podbean feed, linked to Spotify episodes ("Title - Series - Wk N" titles)
curl -L "https://feed.podbean.com/coe22/feed.xml" -o scraping/coe22_feed.xml
uv run scraping/apple_episodes.py 599849932 -o scraping/eleven22_apple_episodes.json
uv run scraping/rss_to_episodes.py scraping/coe22_feed.xml -o scraping/eleven22_rss_episodes.json --spotify scraping/eleven22_spotify_episodes.json --apple scraping/eleven22_apple_episodes.json
uv run scraping/convert_spotify.py scraping/eleven22_rss_episodes.json --church eleven22 --source rss --title-first --series-prefix Saturated

# Tim Keller (gospelinlife.com): server-rendered archive, 20/page; scripture + series come structured from the site
uv run scraping/gil_scrape.py --dates    # ~82 pages at 1 req/s, cached in scraping/gil_pages/; --dates fills exact preached dates from /wp-json (~17 requests)
uv run scraping/gil_details.py          # one request per sermon page (~35 min, resumable): overview -> notes, topics -> tags, duration
uv run scraping/convert_gil.py           # -> data/sources/keller.json + scraping/keller_review.csv

uv run tools/build_sermons.py && uv run tools/validate_data.py
```

BibleProject guides (input for judging whether a sermon teaches its passage; local only, gitignored):

```bash
uv run scraping/bp_guides.py             # 60 guide pages for 66 books -> scraping/bibleproject_guides.json (sections with verse ranges)
```

- `--title-first` / `--series-prefix`: per-church title shapes (Eleven22 puts the title before the series; "Saturated ..." segments are the series).
- `--strip` removes campus/location text from titles ("... - Ger Jones - Santa Monica, July 10th, 2022").
- Book-series titles with no chapter ("John Pt 5: ...", "Acts: Loving a Broken City", "Hebrews Pt. 3 - ...") are tagged to the whole book and show under "Whole book" in the drawer.
- Spotify's relative dates ("Wednesday", "Yesterday", "3 days ago") are resolved against `--scraped-on`.
- `--scraped-on` matters: Spotify omits the year for current-year episodes ("Sep 28"), so the converter infers it from this date.
- Episodes under 20 minutes (`--min-minutes`) and titles with "devotional"/"bonus episode"/"interview" are excluded.
- Only the first scripture ref in an episode becomes its passage; later mentions show in the review CSV's `other_refs_in_desc` column.
- Episodes with no explicit ref are **unmapped** and don't appear on the site until you tag them.

Override example (`scraping/cotcny_overrides.json`):

```json
{
  "2ea8GwCOmR4xUZzuuc2AR9": { "refs": [{ "book": "john", "start": 20, "end": 20 }], "passage": "John 20" },
  "4t3D72K7iKl2IQtaEFuro1": { "speaker": "Jon Tyson" },
  "1YGYwCGaqbnZQbVWkas4FF": { "exclude": true }
}
```
