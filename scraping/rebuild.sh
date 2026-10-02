#!/usr/bin/env bash
# Rebuild everything from the scraped episode files (no network). Run from the repo root.
# Order matters: series_consensus reads the review CSVs, so the converters run twice.
set -euo pipefail
convert_all() {
  uv run --quiet scraping/convert_spotify.py scraping/cotcny_rss_episodes.json --church cotcny --source rss
  uv run --quiet scraping/convert_spotify.py scraping/vintage_rss_episodes.json --church vintage-sm --source rss --strip "Santa Monica"
  uv run --quiet scraping/convert_spotify.py scraping/bridgetown_rss_episodes.json --church bridgetown --source rss
  uv run --quiet scraping/convert_spotify.py scraping/eleven22_rss_episodes.json --church eleven22 --source rss --title-first --series-prefix Saturated
  if [ -f scraping/keller_episodes.json ]; then uv run --quiet scraping/convert_gil.py; fi
}
convert_all
uv run --quiet scraping/series_links.py
uv run --quiet scraping/series_consensus.py
convert_all
uv run --quiet tools/build_sermons.py
uv run --quiet tools/validate_data.py
