"""Build the input for the sermon-fit pilot: one line per (sermon, book) for the chosen books.

Usage: uv run scraping/fit/build_input.py                 # every book
       uv run scraping/fit/build_input.py ephesians mark    # just these
Each row carries "rule": true when the series rule settles it (part of a series that is a study of this book),
so only the rest go to the AI (see INSTRUCTIONS.md).
Writes scraping/fit/fit_input.jsonl and scraping/fit/fit_context.json (both gitignored: they carry
BibleProject text and the full Keller overviews).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
NOTES_MAX = 2500
SERIES_MIN, SHARE_MIN, NEARBY_MIN = 3, 0.7, 3
NEARBY_DAYS = 56  # same church + same book within 8 weeks: catches book series whose series name is blank


def _d(s: dict) -> date | None:
    try:
        return date.fromisoformat(s.get("date") or "")
    except ValueError:
        return None


def overlaps(ref: dict, sec: dict) -> bool:
    if "start" not in ref or not sec.get("start"):  # whole-book sermon, or a section without a range
        return False
    a, b = ref["start"], ref.get("end", ref["start"])
    return not (b < sec["start"][0] or a > sec["end"][0])


def series_rule(row: dict) -> bool:
    """Book-study series: >= 3 sermons with >= 70% on this book; or, with no series name, >= 3 sermons from the
    same church on this book within 8 weeks (series names are blank for some churches)."""
    c = row["series_ctx"]
    if row["series"]:
        return c["size"] >= SERIES_MIN and (c["share"] or 0) >= SHARE_MIN
    return c["nearby_same_book"] >= NEARBY_MIN


def main(books: list[str]) -> None:
    sermons = json.loads((ROOT / "data/sermons.json").read_text())["sermons"]
    notes = json.loads((ROOT / "data/notes.json").read_text())
    keller = json.loads((ROOT / "scraping/keller_details.json").read_text())
    guides = json.loads((ROOT / "scraping/bibleproject_guides.json").read_text())
    names = {b["id"]: b["name"] for b in json.loads((ROOT / "data/books.json").read_text())["books"]}

    series = defaultdict(list)
    for s in sermons:
        if s.get("series"):
            series[(s["church"], s["series"])].append(s)

    if not books:
        books = sorted({r["book"] for s in sermons for r in s["refs"]})
    context, rows = {}, []
    for book in books:
        g = guides[book]
        secs = []
        for i, sec in enumerate(g["sections"]):
            if sec.get("book") and sec["book"].lower().replace(" ", "-") != book and sec["book"] != names[book]:
                continue  # shared pages (1-2 Samuel): keep this book's sections plus the untitled ones
            secs.append({"id": f"{book}-{i}", **{k: sec.get(k) for k in ("range", "title", "start", "end")},
                         "heading": sec["heading"], "text": sec["text"]})
        context[book] = {"name": names[book], "big_idea": g["big_idea"], "about": g["about"], "sections": secs}

        on_book = [s for s in sermons if any(r["book"] == book for r in s["refs"])]
        for s in on_book:
            refs = [r for r in s["refs"] if r["book"] == book]
            d0 = _d(s)
            nearby = [m for m in on_book if m["id"] != s["id"] and m["church"] == s["church"] and d0 and _d(m)
                      and abs((_d(m) - d0).days) <= NEARBY_DAYS]
            n = notes.get(s["id"], "")
            if s["church"] == "keller":
                n = keller.get(s["id"].removeprefix("keller-"), {}).get("overview") or n
            members = series.get((s["church"], s.get("series")), []) if s.get("series") else []
            same = [m for m in members if any(r["book"] == book for r in m["refs"])]
            rows.append({
                "id": s["id"], "book": book, "church": s["church"], "title": s["title"],
                "series": s.get("series") or "", "speaker": s.get("speaker") or "", "date": s.get("date") or str(s.get("year") or ""),
                "passage": s.get("passage") or "", "refs": refs,
                "notes": n[:NOTES_MAX],
                "series_ctx": {"size": len(members), "same_book": len(same),
                               "share": round(len(same) / len(members), 2) if members else None,
                               "titles": [f"{m['title']} ({m.get('passage') or '-'})" for m in members if m["id"] != s["id"]][:12],
                               "nearby_same_book": len(nearby),
                               "nearby_titles": [f"{m['date']} {m['title']} ({m.get('passage') or '-'})" for m in sorted(nearby, key=lambda m: m["date"])][:10]},
                "bp_sections": sorted({sec["id"] for r in refs for sec in secs if overlaps(r, sec)}),
            })
            rows[-1]["rule"] = series_rule(rows[-1])
    (HERE / "fit_input.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (HERE / "fit_context.json").write_text(json.dumps(context, indent=1, ensure_ascii=False) + "\n")
    by = defaultdict(int)
    for r in rows:
        by[r["book"]] += 1
    print(f"{len(rows)} rows in {len(by)} books; series rule settles {sum(r['rule'] for r in rows)}; "
          f"with notes: {sum(1 for r in rows if len(r['notes']) > 150)}")


if __name__ == "__main__":
    main(sys.argv[1:])
