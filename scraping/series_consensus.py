"""Share a book across a series when the series is clearly a study of one book.

Votes per cluster (from <church>_series.json), by each member's primary book:
  regex / manual refs ............ 1.0
  AI tag, confidence >= 0.9 ...... 1.0
  AI tag, 0.6 - 0.9 .............. 0.5
  AI tag, < 0.6 .................. 0.25
A cluster is a "book series" when weighted support >= MIN_SUPPORT, the top book has >= MIN_PURITY of the votes,
and at least one anchor vote (regex/manual or AI >= 0.9) is for that book - AI guesses alone can't confirm each other.
Unmapped members then get that book (keeping their own AI chapters if same book), unless the AI said
topical (>= 0.7) or picked a different book at >= 0.8 - those are listed for review instead.
Regex-mapped members whose book disagrees with a strong series are listed as possible mis-maps
(e.g. a Romans 13 sermon whose first cited verse was Matthew 22).

Usage: uv run scraping/series_consensus.py   -> scraping/<church>_series_tags.json, scraping/ai_tagging/series_review.csv
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHURCHES = ["bridgetown", "cotcny", "eleven22", "vintage-sm"]
MIN_SUPPORT, MIN_PURITY = 2.0, 0.8
BOOK_BY_NAME = {b["name"].lower(): b["id"] for b in json.loads((ROOT / "data/books.json").read_text())["books"]}
BOOK_BY_NAME["psalm"] = "psalms"


def passage_book(p: str) -> str | None:
    p = p.split(";")[0].strip().lower()
    return next((BOOK_BY_NAME[n] for n in sorted(BOOK_BY_NAME, key=len, reverse=True) if p.startswith(n)), None)


def ai_weight(c: float) -> float:
    return 1.0 if c >= 0.9 else 0.5 if c >= 0.6 else 0.25


def main() -> None:
    review_rows = []
    for church in CHURCHES:
        rows = {r["episode_id"]: r for r in csv.DictReader(open(ROOT / f"scraping/{church}_review.csv", encoding="utf-8"))}
        links = json.loads((ROOT / f"scraping/{church}_series.json").read_text())
        ai = json.loads((ROOT / f"scraping/{church}_ai_tags.json").read_text())
        clusters = defaultdict(list)
        for eid, v in links.items():
            if eid in rows and rows[eid]["status"] != "excluded":
                clusters[v["key"]].append(eid)
        tags, stats = {}, defaultdict(int)
        for key, members in clusters.items():
            votes, anchors = defaultdict(float), defaultdict(int)
            for eid in members:
                r, a = rows[eid], ai.get(eid, {})
                if r["ref_source"] in ("regex", "manual"):
                    b = passage_book(r["passage"]) or (r["ai_refs"].split()[0] if r["ai_refs"] else None)
                    if b:
                        votes[b] += 1.0
                        anchors[b] += 1
                elif a.get("kind") == "book" and a.get("refs"):
                    votes[a["refs"][0]["book"]] += ai_weight(a["confidence"])
                    anchors[a["refs"][0]["book"]] += a["confidence"] >= 0.9
            support = sum(votes.values())
            if not votes:
                stats["no_votes"] += 1
                continue
            book, top = max(votes.items(), key=lambda kv: kv[1])
            purity = top / support
            if support < MIN_SUPPORT or purity < MIN_PURITY or not anchors[book]:
                stats["mixed_or_thin"] += 1
                continue
            stats["book_series"] += 1
            conf = round(min(0.97, purity * (0.85 + 0.03 * min(support, 4))), 2)
            name = links[members[0]]["name"]
            for eid in members:
                r, a = rows[eid], ai.get(eid, {})
                base = {"church": church, "series": name, "cluster": key, "series_book": book,
                        "support": round(support, 2), "purity": round(purity, 2), "date": r["date"],
                        "title": r["spotify_title"], "current": r["passage"] or r["ai_refs"],
                        "ref_source": r["ref_source"], "ai_kind": a.get("kind", ""), "ai_conf": a.get("confidence", "")}
                if r["ref_source"] in ("regex", "manual"):
                    if passage_book(r["passage"]) not in (book, None):
                        review_rows.append({**base, "issue": "mapped book differs from series"})
                    continue
                if r["ref_source"] == "ai":  # already applied at >= threshold
                    if a["refs"][0]["book"] != book:
                        review_rows.append({**base, "issue": "AI-applied book differs from series"})
                    continue
                if a.get("kind") == "topical" and a.get("confidence", 0) >= 0.7:
                    review_rows.append({**base, "issue": "AI says topical inside a book series"}); continue
                if a.get("kind") == "book" and a["refs"][0]["book"] != book and a["confidence"] >= 0.8:
                    review_rows.append({**base, "issue": "AI picked another book"}); continue
                same = [x for x in a.get("refs", []) if x["book"] == book]
                tags[eid] = {"_episode": r["spotify_title"], "refs": same[:1] or [{"book": book}],
                             "confidence": conf, "basis": f'{name} ({key}): {book} {top:.1f}/{support:.1f} votes'}
        (ROOT / f"scraping/{church}_series_tags.json").write_text(json.dumps(dict(sorted(tags.items())), indent=1, ensure_ascii=False) + "\n")
        print(f"{church}: clusters {dict(stats)} -> {len(tags)} episodes tagged from series")
    out = ROOT / "scraping/ai_tagging/series_review.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["issue", "church", "series", "series_book", "support", "purity", "date", "title",
                                          "current", "ref_source", "ai_kind", "ai_conf", "cluster"])
        w.writeheader()
        w.writerows(sorted(review_rows, key=lambda r: (r["issue"], r["church"], r["date"])))
    print(f"{len(review_rows)} rows for review -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
