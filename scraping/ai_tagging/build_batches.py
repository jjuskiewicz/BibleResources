"""Build classification batches: all unmapped episodes + redacted calibration rows from mapped ones."""
import csv, json, random, re
from pathlib import Path

random.seed(42)
ROOT = Path(".")
BOOKS = json.loads((ROOT / "data/books.json").read_text())["books"]
CHURCHES = {"bridgetown": ["bridgetown"], "cotcny": ["cotcny"], "eleven22": ["eleven22"], "vintage-sm": ["vintage"]}
CAL_PER_CHURCH = 30
BATCH_SIZE = 40

def ep_id(url):
    return re.sub(r"[^A-Za-z0-9_-]", "", url.split("?")[0].rstrip("/").split("/")[-1])[:60]

# Redaction: every book name/abbr/alias (+ "1st"/"First" ordinals handled by name variants) and chapter:verse numerics.
names = set()
for b in BOOKS:
    for n in [b["name"], b["abbr"], *b.get("aliases", [])]:
        names.add(n)
        m = re.match(r"^([123]) (.+)$", n)
        if m:
            ordw = {"1": ["First", "1st", "I"], "2": ["Second", "2nd", "II"], "3": ["Third", "3rd", "III"]}[m.group(1)]
            names.update(f"{o} {m.group(2)}" for o in ordw)
name_rx = re.compile(r"\b(?:" + "|".join(sorted((re.escape(n) for n in names if len(n) > 2), key=len, reverse=True)) + r")\b\.?", re.I)
num_rx = re.compile(r"\b\d{1,3}\s*(?:[:v.]\s*\d{1,3}(?:\s*[-–]\s*\d{1,3}(?:[:v.]\d{1,3})?)?)?\b|\b(?:chapters?|ch\.?|verses?|vv?\.)\s*\d+", re.I)
def redact(s):
    s = name_rx.sub("[BOOK]", s or "")
    s = re.sub(r"\[BOOK\]\s*" + num_rx.pattern, "[BOOK] [REF]", s, flags=re.I)
    s = re.sub(r"(?:chapters?|ch\.?|verses?)\s*\d+(?:\s*[-–:]\s*\d+)*", "[REF]", s, flags=re.I)
    return s

rows, answers = [], {}
for church, srcs in CHURCHES.items():
    review = list(csv.DictReader(open(f"scraping/{church}_review.csv", encoding="utf-8")))
    descs = {}
    for f in [f"scraping/{srcs[0]}_spotify_episodes.json", f"scraping/{srcs[0]}_rss_episodes.json"]:
        p = Path(f)
        if p.exists():
            for e in json.loads(p.read_text()):
                d = (e.get("desc") or "").strip()
                if d:
                    descs[ep_id(e["url"])] = d  # rss overwrites spotify when both present
    mapped = [r for r in review if r["status"] == "mapped"]
    by_date = sorted(mapped, key=lambda r: r["date"])
    cal = set(r["episode_id"] for r in random.sample(mapped, min(CAL_PER_CHURCH, len(mapped))))

    def context(r):
        sib = [f'{s["title"]} -> {s["passage"]}' for s in mapped
               if r["series"] and s["series"] == r["series"] and s["episode_id"] != r["episode_id"]][:8]
        near = sorted((s for s in by_date if s["episode_id"] != r["episode_id"]),
                      key=lambda s: abs((int(s["date"][:4]) * 400 + int(s["date"][5:7]) * 31 + int(s["date"][8:10]))
                                        - (int(r["date"][:4]) * 400 + int(r["date"][5:7]) * 31 + int(r["date"][8:10]))))[:6]
        return sib, [f'{s["date"]} {s["title"]} -> {s["passage"]}' for s in sorted(near, key=lambda s: s["date"])]

    for r in review:
        is_cal = r["episode_id"] in cal
        if r["status"] != "unmapped" and not is_cal:
            continue
        sib, near = context(r)
        title, series, desc, sp_title = r["title"], r["series"], descs.get(r["episode_id"], ""), r["spotify_title"]
        if is_cal:
            title, series, desc, sp_title = map(redact, (title, series, desc, sp_title))
            answers[r["episode_id"]] = r["passage"]
        rows.append({"id": r["episode_id"], "church": church, "date": r["date"], "series": series, "title": title,
                     "episode_title": sp_title, "speaker": r["speaker"], "minutes": r["minutes"],
                     "description": desc[:1200], "same_series_mapped": sib, "nearby_mapped_by_date": near,
                     "_cal": is_cal})

rows.sort(key=lambda r: (r["church"], r["series"], r["date"]))
for r in rows:
    r.pop("_cal")
batches = [rows[i:i + BATCH_SIZE] for i in range(0, len(rows), BATCH_SIZE)]
for i, b in enumerate(batches):
    Path(f"batches/batch_{i:02d}.json").write_text(json.dumps(b, indent=1, ensure_ascii=False))
Path("calibration_answers.json").write_text(json.dumps(answers, indent=1))
print(len(rows), "rows,", len(answers), "calibration,", len(batches), "batches")
