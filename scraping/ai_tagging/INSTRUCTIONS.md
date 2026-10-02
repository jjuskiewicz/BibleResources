# Sermon -> Bible book classification

You are tagging church sermon podcast episodes with the book of the Bible they teach from.
Input: batches/batch_NN.json (array of episodes). Valid book ids + chapter counts: book_ids.txt.

Each episode has: title, episode_title (raw podcast title), series, speaker, date, description (may be empty),
`same_series_mapped` (other episodes in the same series whose passage is KNOWN) and
`nearby_mapped_by_date` (known passages of this church's episodes closest in date).
Some text contains `[BOOK]` / `[REF]` placeholders where a book name or chapter was removed; treat them as unknown.

## Decide, per episode
- `kind`:
  - "book": the sermon primarily teaches from an identifiable passage/book.
  - "topical": a topical talk, interview, panel, conference session, prayer night, vision talk, etc. with no single
    primary text evident. Do NOT force a book for these.
  - "unknown": probably expositional, but there is not enough information to tell which book.
- `refs`: for "book", 1 to 2 entries `{"book": "<id from book_ids.txt>", "start": int|null, "end": int|null}`.
  Give chapters ONLY when the text supports them (a named story counts: "woman at the well" -> john 4;
  "Nebuchadnezzar's pride" -> daniel 4). Otherwise start/end null (= whole book). Chapters must exist in that book.
  Empty list for topical/unknown.
- `confidence`: 0.0-1.0 = probability that refs[0].book is the right primary book. Be calibrated: we will measure
  your accuracy against hidden answers. Strong evidence: description names the passage or a distinctive story;
  a series that is clearly a book study where siblings are all the same book. Weak evidence: the nearby-by-date
  list alone (churches switch series), a title with a vague theme, holiday guesses (Advent/Easter -> a gospel).
  For topical/unknown, confidence is how sure you are that NO single book applies (topical) or just 0 (unknown).
- `rationale`: one short sentence citing the evidence.

## Output
Write results/batch_NN.json (same NN): a JSON array with one object per input episode, same order, keys exactly:
`id, kind, refs, confidence, rationale`. Every input id must appear once. Validate with:
`python3 check.py results/batch_NN.json`
Do not use web search; judge from the provided text and your own Bible knowledge.
