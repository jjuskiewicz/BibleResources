import json, sys
from pathlib import Path
books = {l.split("\t")[0]: int(l.split("\t")[2].split()[0]) for l in Path("book_ids.txt").read_text().splitlines()}
for f in sys.argv[1:]:
    out = json.loads(Path(f).read_text()); inp = json.loads(Path(f.replace("results", "batches")).read_text())
    errs = []
    if [o.get("id") for o in out] != [i["id"] for i in inp]: errs.append("ids/order mismatch with input")
    for o in out:
        if set(o) != {"id", "kind", "refs", "confidence", "rationale"}: errs.append(f'{o.get("id")}: bad keys {sorted(o)}')
        if o.get("kind") not in ("book", "topical", "unknown"): errs.append(f'{o.get("id")}: bad kind')
        if not isinstance(o.get("confidence"), (int, float)) or not 0 <= o["confidence"] <= 1: errs.append(f'{o.get("id")}: bad confidence')
        if o.get("kind") == "book" and not o.get("refs"): errs.append(f'{o.get("id")}: book kind needs refs')
        for r in o.get("refs") or []:
            if r.get("book") not in books: errs.append(f'{o["id"]}: unknown book {r.get("book")}'); continue
            for k in ("start", "end"):
                v = r.get(k)
                if v is not None and not (isinstance(v, int) and 1 <= v <= books[r["book"]]): errs.append(f'{o["id"]}: bad {k} {v}')
    print(f, "OK" if not errs else "ERRORS:\n  " + "\n  ".join(errs[:20]))
