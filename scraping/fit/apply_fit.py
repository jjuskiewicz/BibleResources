"""Combine the series rule, AI judgments and hand overrides into the per-book "study" labels the site uses.

A sermon is a **study** of a book when it helps a listener study that book/passage in context:
  1. series rule (build_input.py): part of a series that works through this book -> study, no AI needed
  2. otherwise the AI judgment in fit_ai.json ("study" | "other" + why: topical/springboard/secondary/unclear)
  3. fit_overrides.json always wins: {"<sermon id>|<book>": true | false}
Rows with no rule hit and no AI label are "other" and listed as needing AI (new sermons since the last run).

Usage:
    uv run scraping/fit/build_input.py       # refresh fit_input.jsonl (needs bibleproject_guides.json, keller_details.json)
    uv run scraping/fit/apply_fit.py         # -> scraping/fit/fit_labels.json, read by tools/build_sermons.py
    uv run tools/build_sermons.py && uv run tools/validate_data.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    rows = [json.loads(line) for line in (HERE / "fit_input.jsonl").read_text().splitlines() if line]
    ai = json.loads((HERE / "fit_ai.json").read_text())
    ov_path = HERE / "fit_overrides.json"
    overrides = json.loads(ov_path.read_text()) if ov_path.exists() else {}
    labels, todo, src = {}, [], Counter()
    for r in rows:
        key = f"{r['id']}|{r['book']}"
        if key in overrides:
            study, how = bool(overrides[key]), "override"
        elif r["rule"]:
            study, how = True, "rule"
        elif key in ai:
            study, how = ai[key]["bucket"] == "study", "ai"
        else:
            study, how = False, "needs-ai"
            todo.append(key)
        labels[key] = {"study": study, "source": how}
        src[(how, study)] += 1
    (HERE / "fit_labels.json").write_text(json.dumps(dict(sorted(labels.items())), indent=0) + "\n")
    n = sum(v["study"] for v in labels.values())
    print(f"{len(labels)} sermon-book rows: {n} study ({n / len(labels):.0%})")
    for (how, study), c in sorted(src.items()):
        print(f"  {how:9} {'study' if study else 'other':5} {c}")
    if todo:
        print(f"{len(todo)} rows need an AI pass (no rule hit, no label): see INSTRUCTIONS.md; first: {todo[:5]}")


if __name__ == "__main__":
    main()
