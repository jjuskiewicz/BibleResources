# AI book tagging for unmapped episodes

The regex in `convert_spotify.py` left 1,071 episodes unmapped. Sonnet subagents tagged each one
with a book of the Bible (and chapters where the text supports them), a `kind`, and a confidence score.
Results live in `scraping/<church>_ai_tags.json`, keyed by Spotify episode id.

## Rebuild

`bash scraping/rebuild.sh` reruns converters -> series_links -> series_consensus -> converters -> build -> validate.

## Layers (first match wins)

1. regex refs in title/description, or hand overrides in `<church>_overrides.json` -> `refSource: "regex"` / `"manual"`
2. AI tag, `kind == "book"`, confidence >= `--ai-min-confidence` (0.85) -> `"ai"`
3. Series consensus (`series_consensus.py`), confidence >= `--series-min-confidence` (0.85) -> `"series"`
4. AI `kind == "non_sermon"` at >= `--non-sermon-min-confidence` (0.7) -> excluded (interviews, Q&A/Q&R, panels, heritage-month story episodes, Relate bonus episodes)

Every linked record also gets `seriesKey` (same key = same series run), and blank `series` is filled from
Bridgetown's 'From the series "X"' descriptions.

### Series linking (`series_links.py` -> `<church>_series.json`)
- explicit series from titles; Bridgetown description series; Eleven22 untitled "Wk N" runs (a run ends when the
  number resets or the gap is too long)
- reused names ("Advent") are split into separate runs when episodes are > 120 days apart

### Series consensus (`series_consensus.py` -> `<church>_series_tags.json`)
A run is a book study when weighted votes are >= 2, the top book has >= 80%, and at least one vote is an anchor
(a regex/manual ref or an AI tag >= 0.9). Remaining members inherit that book. Conflicts are written to
`ai_tagging/series_review.csv` instead, including regex-mapped sermons whose first cited verse disagrees with
their series (e.g. a Romans 13 week mapped to Matthew 22).

### Two AI passes
- **Pass 1:** each episode judged on its own, with nearby context.
- **Pass 2:** every episode pass 1 didn't settle at >= 0.9, judged with its whole series visible. Pass 2 also
  splits `topical` from `non_sermon`. Pass 2 replaces the pass 1 entry, and the old guess is kept in the `pass1` field.

## How it is applied (pass 1 notes)

`convert_spotify.py --ai-min-confidence 0.9` (the default) applies an AI tag only when:
- the regex found nothing, and no hand override in `<church>_overrides.json` supplies refs
- the episode is not excluded
- `kind == "book"` and `confidence >= threshold`

Applied records get `"refSource": "ai"` and `"aiConfidence"`. The other records get `"regex"` or `"manual"`.
To re-threshold, rerun the converters (see the main README) with a different `--ai-min-confidence`.
Pass `1.01` to turn AI tags off. The review CSVs now include `ref_source`, `ai_kind`, `ai_confidence`,
`ai_refs` and `ai_rationale`, so you can sort by confidence and spot-check.

## Kinds

- `book`: teaches from an identifiable book/passage
- `topical`: an interview, panel, conference session or theme talk with no primary text. Left unmapped on purpose.
- `unknown`: probably expositional, but the title and description don't say which book

## Calibration

120 already-mapped episodes (30 per church) were mixed into the batches. Their book names and chapter
numbers were redacted, and the regex answer was held back for scoring (`calibration_scored.json`).

| confidence | correct |
|---|---|
| >= 0.9 | 83 / 85 |
| 0.8 - 0.9 | 19 / 19 |
| 0.7 - 0.8 | 6 / 6 |
| < 0.7 | 3 / 6 |

Caveat: calibration rows are easier than the real unmapped ones. Their descriptions usually still quote
or paraphrase the passage. A manual spot-check of unmapped rows found:
- **>= 0.9:** 20 of 20 had the right book.
- **0.6 - 0.9:** about two-thirds were well supported (e.g. a fruit-of-the-Spirit series -> Galatians 5). The rest
  were themed guesses (e.g. "Wk 2: Grace" -> Ephesians 2). Treat that band as needing review before you publish it.

## Pass 1 yield on the 1,071 unmapped (before pass 2 and series consensus)

| threshold | sermons added |
|---|---|
| 0.9 (default) | 199 |
| 0.8 | 314 |
| 0.7 | 366 |

By kind: 563 book, 305 topical, 203 unknown.

## Reproduce

`build_batches.py` (writes 40-row batches + calibration answers), `INSTRUCTIONS.md` (the agent prompt),
`check.py` (schema validator), `score.py` (calibration report). Run them from a working copy that holds
`data/books.json` and the `scraping/*_review.csv` / `*_episodes.json` files.

## Current totals (after pass 2 + series consensus)

1,192 sermons: 840 regex + 287 AI + 65 series consensus. 41 non-sermons excluded.
Left unmapped and not on the site: 371 topical, 217 AI book guesses below 0.85, 83 unknown.
