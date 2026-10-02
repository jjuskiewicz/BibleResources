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
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


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

    # Wk-N runs among unnamed episodes: next number must be prev+1..prev+3 within RUN_GAP_DAYS.
    runs: dict[str, str] = {}
    cur, last_n, last_d = None, None, None
    for r in review:
        if r["episode_id"] in named or r["status"] == "excluded":
            continue
        m = WK.search(r["spotify_title"])
        if not m:
            continue
        n, d = int(m["n"]), days(r["date"])
        if cur and last_n is not None and 0 < n - last_n <= 3 and d - last_d <= RUN_GAP_DAYS * (n - last_n):
            pass
        else:
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
        first = clusters[v["_k"]][v["_i"]][0]["date"]
        v["key"] = f"{v['_k']}|{first[:7]}"
        v["size"] = len(clusters[v["_k"]][v["_i"]])
        del v["_k"], v["_i"]
    return out


def main() -> None:
    for church, src in CHURCHES.items():
        links = link(church, src)
        (ROOT / f"scraping/{church}_series.json").write_text(json.dumps(links, indent=1, ensure_ascii=False) + "\n")
        n_clusters = len({v["key"] for v in links.values()})
        by = {b: sum(v["basis"] == b for v in links.values()) for b in ("explicit", "desc", "wk-run")}
        print(f"{church}: {len(links)} episodes linked into {n_clusters} clusters {by}")


if __name__ == "__main__":
    main()
