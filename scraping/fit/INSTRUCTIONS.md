# Sermon "fit" instructions (v2: two buckets)

You are judging, for one Bible book at a time, whether each sermon tagged to that book **helps a listener
study that book or passage**. The result powers a "Study this book" label on a men's group sermon library.
Precision matters more than coverage: labeling a sermon "study" sends someone who wants to learn Ephesians to a
talk about something else. When in doubt, the answer is `other`.

The sermons you see have already failed a simple rule (they are NOT part of a series that works through this
book), so most will be `other`. Look for the ones that still teach the passage in its context.

## Input
- A batch `.jsonl`: one sermon per line: `id, book, church, title, series, speaker, date, passage, refs,
  notes, series_ctx, bp_sections`.
  - `notes`: the episode/site description (may be empty or one line). Keller's are often the sermon's opening.
  - `series_ctx`: `{size, same_book, share, titles, nearby_same_book, nearby_titles}`: the sermon's series (by
    church + series name) and sermons from the same church on this book within 8 weeks.
  - `bp_sections`: ids of the BibleProject sections this sermon's passage overlaps.
- A context `.json`: per book, BibleProject's `big_idea`, `about`, and `sections` (`id, range, title, text`).
  This is the rubric for what each part of the book says and what setting it needs.

## Buckets
- **study**: teaches the passage in its context. The sermon's main point is the passage's main point, and it
  works with the text's own setting (author, audience, situation, people, structure, flow of argument, key
  terms). Examples: a one-off sermon that walks through a psalm's movement; a book-introduction sermon; a
  sermon in a multi-book series (e.g. "Real Jesus", "Daring to Draw Near") whose notes clearly expound this
  scene in its setting.
- **other**, with `why`:
  - `topical`: faithful to what the passage says, but organized around a topic, doctrine, season or occasion
    (Fruit of the Spirit, Ten Commandments, Christmas, a life-topic series). Helps with the passage, not the book.
  - `springboard`: the passage is a launch point; the sermon's point is one the passage isn't making, or it
    re-reads a phrase outside its context (vision Sundays, appeals, Phil 3:13 preached as freedom from trauma).
  - `secondary`: this book is a secondary text; the sermon is mainly on another book.
  - `unclear`: not enough evidence (title only, nothing telling). Do not guess `study` from a title alone
    unless the title plainly restates the passage's own content AND something else points to exposition.

## How to decide
1. **evidence** first (<= 30 words, quoted with source): `notes: 'Psalm 73 moves from envy to worship...'`.
2. **Point match**: compare the sermon's main point (title + notes) with the overlapping BibleProject section.
   `study` needs the same point AND use of the passage's setting or flow. Same point without context = `topical`.
3. **conf** 0-1: 0.9+ = explicit in the notes; 0.7-0.9 = clearly implied; < 0.7 = a lean.

Psalms: each psalm is its own unit; `study` = teaches the psalm itself (its movement, setting, superscription,
poetry). Gospels: one scene or parable expounded in its Gospel setting is `study`; the same parable used for a
topic is `topical`.

Optionally **ref_fix**: if the evidence shows the book/chapter tag is wrong or too coarse, say what it should be.

## Output
One JSON object keyed by sermon id:
```json
{"keller-123": {"bucket": "other", "why": "topical", "conf": 0.8,
                "evidence": "series: Fruit of the Spirit; notes: 'peace is...'", "ref_fix": null}}
```
`why` is null when bucket is `study`. Every input id must appear exactly once.
