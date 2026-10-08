"""Link episodes into series clusters so books can be shared across a series.

Sources, in order of trust:
  explicit  - series parsed from the title by convert_spotify.py (review CSV)
  desc      - 'From the series "X"' / 'From "X Conference"' in the description (Bridgetown)
  wk-run    - untitled "Wk N:" / "Week N" / "Part N" episodes in consecutive order (Eleven22)
Reused names ("Advent" every year) are split into separate clusters when episodes are > GAP_DAYS apart.

Usage: uv run scraping/series_links.py           -> scraping/<church>_series.json
Run after convert_spotify.py (it reads the review CSVs).
"""

from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHURCHES = {"bridgetown": "bridgetown", "cotcny": "cotcny", "eleven22": "eleven22", "vintage-sm": "vintage"}
GAP_DAYS = 120
RUN_GAP_DAYS = 35
DESC_SERIES = re.compile(r'From (?:the |our )*(?:[\w ]*?series )?["“](?P<s>[^"”]+)["”]', re.I)
WK = re.compile(r"\b(?:Wk\.?|Week|Part|Pt\.?)\s*(?P<n>\d{1,2})\b", re.I)


def ep_id(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", url.split("?")[0].rstrip("/").split("/")[-1])[:60]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("&", " and ")).strip()  # "Stand Firm & Act Like Men" = "... and ..."


def days(d: str) -> int:
    return date.fromisoformat(d).toordinal()


def link(church: str, src: str) -> dict:
    review = [r for r in csv.DictReader(open(ROOT / f"scraping/{church}_review.csv", encoding="utf-8"))]
    descs = {}
    for f in (f"scraping/{src}_spotify_episodes.json", f"scraping/{src}_rss_episodes.json"):
        p = ROOT / f
        if p.exists():
            for e in json.loads(p.read_text()):
                if (e.get("desc") or "").strip():
                    descs[ep_id(e["url"])] = e["desc"]
    review.sort(key=lambda r: r["date"])
    named: dict[str, tuple[str, str]] = {}  # episode -> (series name, basis)
    for r in review:
        if r["series"].strip():
            named[r["episode_id"]] = (r["series"].strip(), "explicit")
        elif m := DESC_SERIES.search(descs.get(r["episode_id"], "")):
            named[r["episode_id"]] = (m["s"].strip().rstrip("."), "desc")

    # Wk-N runs among unnamed episodes: next number must be prev+0..prev+3 within RUN_GAP_DAYS (a repeat, e.g.
    # "Wk 4: Unity (Thursday)" then "(Sunday)", stays in the run). Same-day episodes go in week order.
    def wk(r: dict) -> int | None:
        m = WK.search(r["spotify_title"])
        return int(m["n"]) if m else None

    runs: dict[str, str] = {}
    cur, last_n, last_d = None, None, None
    for r in sorted(review, key=lambda r: (r["date"], wk(r) or 0)):
        if r["episode_id"] in named or r["status"] == "excluded" or (n := wk(r)) is None:
            continue
        d = days(r["date"])
        if not (cur and last_n is not None and 0 <= n - last_n <= 3 and d - last_d <= RUN_GAP_DAYS * max(1, n - last_n)):
            cur = f"wk-run {r['date']}"
        runs[r["episode_id"]] = cur
        last_n, last_d = n, d

    # cluster named series by normalized name + date gaps
    out, clusters = {}, {}
    for r in review:
        eid = r["episode_id"]
        if eid in named:
            name, basis = named[eid]
            key0 = norm(name)
        elif eid in runs:
            name, basis, key0 = runs[eid], "wk-run", runs[eid]
        else:
            continue
        lst = clusters.setdefault(key0, [])
        if not lst or days(r["date"]) - days(lst[-1][-1]["date"]) > GAP_DAYS:
            lst.append([])
        lst[-1].append(r)
        out[eid] = {"name": name, "basis": basis, "_k": key0, "_i": len(lst) - 1}
    for eid, v in out.items():
        members = clusters[v["_k"]][v["_i"]]
        first = members[0]["date"]
        v["key"] = f"{v['_k']}|{first[:7]}"
        v["size"] = len(members)
        if v["basis"] == "wk-run":  # a lone "Wk 3" isn't a series on the site, so leave it unnamed
            v["name"], v["name_basis"] = run_name(members, descs) if len(members) > 1 else ("", "single")
        del v["_k"], v["_i"]
    return out


# A wk-run has no name in its titles ("Wk 5: Fear Not"), but the site only groups sermons that share a series name.
# Name it, most trusted first: the description ("our series through the book of Philippians", coe22.com/john), the
# book most of its sermons are on (same vote rules as series_consensus.py), else a dated placeholder.
BOOKS = json.loads((ROOT / "data/books.json").read_text())["books"]
BOOK_NAME = {b["id"]: b["name"] for b in BOOKS}
BOOK_BY_NAME = {b["name"].lower(): b["id"] for b in BOOKS} | {"psalm": "psalms"}
DESC_BOOK = re.compile(r"\bseries (?:through|exploring|on|in|from) (?:the book of |the gospel of )?(?P<b>(?:[123] )?[A-Z][a-z]+)")
DESC_SLUG = re.compile(r"coe22\.com/(?P<slug>[a-z0-9-]+)", re.I)
SLUG_NAMES = {"bestsermonever": "Best. Sermon. Ever."}  # coe22.com/sermons lists this series under that name
# Looser than series_consensus.py: this only picks a display name, it never changes a sermon's refs.
MIN_SUPPORT, MIN_PURITY, MIN_ANCHOR_AI = 1.5, 0.7, 0.8


def passage_book(p: str) -> str | None:
    p = p.split(";")[0].strip().lower()
    return next((BOOK_BY_NAME[n] for n in sorted(BOOK_BY_NAME, key=len, reverse=True) if p.startswith(n)), None)


def run_name(members: list[dict], descs: dict[str, str]) -> tuple[str, str]:
    hints = []
    for r in members:
        d = descs.get(r["episode_id"], "")
        if (m := DESC_BOOK.search(d)) and m["b"].lower() in BOOK_BY_NAME:
            hints.append(BOOK_NAME[BOOK_BY_NAME[m["b"].lower()]])
        for m in DESC_SLUG.finditer(d):
            slug = m["slug"].lower()
            if slug in SLUG_NAMES:
                hints.append(SLUG_NAMES[slug])
            elif slug.replace("-", " ") in BOOK_BY_NAME:
                hints.append(BOOK_NAME[BOOK_BY_NAME[slug.replace("-", " ")]])
    if hints:
        return max(set(hints), key=hints.count), "desc"
    votes: dict[str, float] = {}
    anchors: set[str] = set()
    for r in members:
        if r["ref_source"] in ("regex", "manual") and (b := passage_book(r["passage"])):
            votes[b] = votes.get(b, 0) + 1.0
            anchors.add(b)
        elif r["ai_kind"] == "book" and r["ai_refs"]:  # AI guess even if not applied; never 'series' (circular)
            b, c = r["ai_refs"].split()[0], float(r["ai_confidence"] or 0)
            votes[b] = votes.get(b, 0) + (1.0 if c >= 0.9 else 0.5 if c >= 0.6 else 0.25)
            if c >= MIN_ANCHOR_AI:
                anchors.add(b)
    if votes:
        book, top = max(votes.items(), key=lambda kv: kv[1])
        support = sum(votes.values())
        if support >= MIN_SUPPORT and top / support >= MIN_PURITY and book in anchors and book in BOOK_NAME:
            return BOOK_NAME[book], "book"
    return f"Untitled series ({date.fromisoformat(members[0]['date']).strftime('%b %Y')})", "placeholder"


def main() -> None:
    for church, src in CHURCHES.items():
        links = link(church, src)
        (ROOT / f"scraping/{church}_series.json").write_text(json.dumps(links, indent=1, ensure_ascii=False) + "\n")
        n_clusters = len({v["key"] for v in links.values()})
        by = {b: sum(v["basis"] == b for v in links.values()) for b in ("explicit", "desc", "wk-run")}
        runs = {v["key"]: v["name_basis"] for v in links.values() if v["basis"] == "wk-run" and v["size"] > 1}
        named = {b: list(runs.values()).count(b) for b in ("desc", "book", "placeholder")}
        print(f"{church}: {len(links)} episodes linked into {n_clusters} clusters {by}; wk-runs of 2+ named by {named}")


if __name__ == "__main__":
    main()
