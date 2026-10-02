import json, glob, re, collections, csv
books = json.load(open("data/books.json"))["books"]
name2id = {b["name"].lower(): b["id"] for b in books}
ans = json.load(open("calibration_answers.json"))
inp = {r["id"]: r for f in glob.glob("batches/*.json") for r in json.load(open(f))}
out = {o["id"]: o for f in glob.glob("results/*.json") for o in json.load(open(f))}
def book_of(passage):
    p = passage.split(";")[0].strip().lower()
    p = re.sub(r"^psalm\b(?!s)", "psalms", p)
    for n in sorted(name2id, key=len, reverse=True):
        if p.startswith(n): return name2id[n]
def norm(t): return re.sub(r"[^a-z]", "", t.lower())[:20]
rows = []
for eid, passage in ans.items():
    r, o = inp[eid], out[eid]
    truth = book_of(passage)
    # leak = a context entry with same date (nearby) whose answer is the truth -> likely duplicate episode
    leak = any(n.startswith(r["date"]) for n in r["nearby_mapped_by_date"])
    pred = o["refs"][0]["book"] if o["refs"] else None
    rows.append(dict(id=eid, truth=truth, pred=pred, kind=o["kind"], conf=o["confidence"], leak=leak, church=r["church"],
                     correct=(pred == truth), title=r["episode_title"], passage=passage, why=o["rationale"]))
print("calibration rows:", len(rows), " with same-date leak:", sum(r["leak"] for r in rows))
print("kinds:", collections.Counter(r["kind"] for r in rows))
bands = [(0.9, 1.01), (0.8, 0.9), (0.7, 0.8), (0.6, 0.7), (0.5, 0.6), (0, 0.5)]
for label, sub in [("ALL", rows), ("NO-LEAK", [r for r in rows if not r["leak"]])]:
    print(f"\n{label}: book-kind predictions, accuracy by confidence band (cumulative >= lower bound in brackets)")
    bk = [r for r in sub if r["kind"] == "book"]
    for lo, hi in bands:
        b = [r for r in bk if lo <= r["conf"] < hi]; c = [r for r in bk if r["conf"] >= lo]
        if b or c: print(f"  {lo:.1f}-{min(hi,1):.1f}: {sum(r['correct'] for r in b)}/{len(b)}   [>= {lo:.1f}: {sum(r['correct'] for r in c)}/{len(c)}]")
    print("  abstained (topical/unknown):", sum(r["kind"] != "book" for r in sub))
print("\nper church (no-leak, book kind, conf>=0.7):")
for ch in sorted({r["church"] for r in rows}):
    c = [r for r in rows if r["church"] == ch and not r["leak"] and r["kind"] == "book" and r["conf"] >= 0.7]
    print(f"  {ch}: {sum(r['correct'] for r in c)}/{len(c)}  (of {sum(1 for r in rows if r['church']==ch and not r['leak'])} rows)")
print("\nWRONG with conf>=0.7:")
for r in rows:
    if r["kind"] == "book" and r["conf"] >= 0.7 and not r["correct"]:
        print(f"  [{r['conf']}{' LEAK' if r['leak'] else ''}] key={r['passage']} pred={r['pred']} | {r['title'][:60]} | {r['why'][:110]}")
json.dump(rows, open("calibration_scored.json", "w"), indent=1)
