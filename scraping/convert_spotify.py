"""Convert a Spotify show scrape (from js_scrape.txt) into site sermon records.

Usage:
    uv run scraping/convert_spotify.py scraping/cotcny_spotify_episodes.json --church cotcny

Writes:
    data/sources/<church>.json      sermons with a scripture ref (these show on the site)
    scraping/<church>_review.csv    every episode + what was extracted, for manual tagging
Reads (optional):
    scraping/<church>_overrides.json   {"<episode id>": {"refs": [...], "speaker": "...", "exclude": true, ...}}

Then run tools/build_sermons.py to merge all sources into data/sermons.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS = json.loads((ROOT / "data" / "books.json").read_text())["books"]
BOOK_BY_ID = {b["id"]: b for b in BOOKS}

# ---------- scripture reference extraction ----------
ORD = {"1": r"(?:1|I|1st|First)", "2": r"(?:2|II|2nd|Second)", "3": r"(?:3|III|3rd|Third)"}


def _book_patterns() -> list[tuple[str, str]]:
    """(regex, book_id) for every spelling. Case-sensitive on purpose: 'Job', 'Mark', 'Acts' must be capitalized."""
    out = []
    for b in BOOKS:
        names = {b["name"], b["abbr"], *[a.title() for a in b["aliases"] if len(a.replace(" ", "")) >= 3]}
        if b["id"] == "psalms":
            names |= {"Psalm", "Ps"}
        if b["id"] == "song-of-songs":
            names |= {"Song of Solomon"}
        for n in names:
            m = re.match(r"^([123]) (.+)$", n)
            body = re.escape(m.group(2) if m else n).replace(r"\ ", r"\s+")
            rx = rf"{ORD[m.group(1)]}\s*{body}" if m else body
            out.append((rx + r"\.?", b["id"]))
    return sorted(out, key=lambda p: -len(p[0]))


_BOOK_ALT = "|".join(f"(?P<b{i}>{rx})" for i, (rx, _) in enumerate(_book_patterns()))
_BOOK_IDS = [bid for _, bid in _book_patterns()]
REF_RX = re.compile(
    rf"\b(?:{_BOOK_ALT})\s+(?P<ch>\d{{1,3}})"
    r"(?:"
    r"\s*(?::|v(?=\d))\s*(?P<v1>\d{1,3})(?:\s*[-–—]\s*(?P<x>\d{1,3})(?:\s*(?::|v(?=\d))\s*(?P<v2>\d{1,3}))?)?"  # 5:13-26 / 5:12-6:14 / 11v28-30
    r"|\s*[-–—]\s*(?P<ch2>\d{1,3})(?!\s*(?::|v)\s*\d)"  # 5-7
    r"|\s+v(?:v|erses?)?\.?\s*(?P<vv1>\d{1,3})(?:\s*[-–]\s*(?P<vv2>\d{1,3}))?"  # 4 v1-16
    r")?(?!\d)"
)


def find_refs(text: str) -> list[dict]:
    refs = []
    for m in REF_RX.finditer(text):
        idx = next(int(k[1:]) for k, v in m.groupdict().items() if k.startswith("b") and k[1:].isdigit() and v)
        book = BOOK_BY_ID[_BOOK_IDS[idx]]
        ch = int(m["ch"])
        if not 1 <= ch <= book["chapters"]:
            continue  # "Job 401" etc.
        end, verses = ch, ""
        if m["v1"]:
            if m["v2"]:
                end, verses = int(m["x"]), f":{m['v1']}-{m['x']}:{m['v2']}"
            else:
                verses = f":{m['v1']}" + (f"-{m['x']}" if m["x"] else "")
        elif m["ch2"]:
            end = int(m["ch2"])
        elif m["vv1"]:
            verses = f":{m['vv1']}" + (f"-{m['vv2']}" if m["vv2"] else "")
        if not ch <= end <= book["chapters"]:
            end = ch
        label = f"{'Psalm' if book['id'] == 'psalms' else book['name']} {ch}" + (f"-{end}" if end != ch and not verses else "") + verses
        refs.append({"book": book["id"], "start": ch, "end": end, "_label": label})
    return refs


WHOLE_BOOK_RX = re.compile(
    rf"(?:^|\s[-\u2013|]\s|:\s)(?:{_BOOK_ALT})"
    r"(?=\s*(?::|$|\s[-\u2013|]\s|\s*,|\s+(?:Pt\.?|Part|Series|Week|Wk)\b|\s+S\d+\s?E\d+))"
)


def find_whole_book_refs(title: str) -> list[dict]:
    """Book-series titles without a chapter: "John Pt 5: I AM the Way", "Acts: Loving a Broken City"."""
    refs = []
    for m in WHOLE_BOOK_RX.finditer(title):
        idx = next(int(k[1:]) for k, v in m.groupdict().items() if k[1:].isdigit() and v)
        b = BOOK_BY_ID[_BOOK_IDS[idx]]
        refs.append({"book": b["id"], "_label": b["name"]})
    return refs


def dedupe_refs(refs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in refs:
        key = (r["book"], r.get("start"), r.get("end"))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# ---------- title / speaker / date / duration ----------
NAME = r"(?:(?:Dr|Rev|Bishop)\.?\s+)?[A-Z][a-zA-Z]+(?:\s+(?:[A-Z]\.|[A-Z][a-zA-Z'\-]+)){1,3}"
# Common given names: lets a one-off guest ("Psalm 139 - Megan Fate Marshman") count as a speaker
# without also accepting title phrases ("Teach Us To Pray - Week 4 - Experience Glory").
FIRST_NAMES = set("""
aaron aj adam alex alan alicia allison amanda amy andrew andy angela ann anna anne ash ashley austin
barbara ben benjamin beth bethany bill billy bob brad brandon brenda brian brittany bruce bryan caleb carl carlos
carol caroline carrie catherine chad charles charlie chris christian christina christine christopher christy
cindy claire cody colin corey cory craig crystal dan daniel danielle dave david dean deborah debbie denise derek
derwin diana diane dimas dominic donald donna doug douglas drew dustin dylan ed eddie edward elizabeth emily emma
eric erica erin esau ethan eugene evan frank gabriel gary george ger gerald glen glenn grace greg gregory guy hannah
heather heidi henry holly ian isaac jack jackie jacob jake james jamie jan jane janet jared jarrett jason jay jeff
jeffrey jen jennifer jenny jeremy jerry jesse jessica jill jim jimmy jo joan joanna jodi joe joel john johnny jon
jonathan jonny jordan jose joseph josh joshua joy judy julia julie justin karen kate katherine kathy katie keith
keithen kelly ken kenneth kevin kim kimberly kristen kyle larry laura lauren lee leah linda lisa lizzie lori louis
lucas luke lynn madison marc marcus margaret maria mark mary matt matthew megan melissa michael michelle mike molly
nancy natalie nate nathan nicholas nick nicole noah olivia pam pat patrick paul pete peter phil philip rachel
raegan ralph randy ray rebecca rich richard rick rob robert robin ron ronald ruth ryan sam samuel sandra sara sarah
scott sean seth shane shannon sharon shawn stephanie stephen steve steven sue susan suzy tammy tara ted teresa terry
thomas tim timothy tina todd tom tommy tony tracy travis trevor tyler valerie vanessa victor vince wanda wayne
wendy will william zach zachary jennie lysa albert robbie levi louie priscilla max francis
jonathan crawford lecrae
""".split())
SPEAKER_SUFFIX = re.compile(rf"(?:\s+[-\u2013]\s+|\s+ft\.?\s+)(?P<sp>{NAME}(?:\s+(?:and|&)\s+{NAME})?)\s*$")
DESC_WITH = re.compile(rf"\bwith\s+(?P<sp>(?:(?:Sister|Brother|Fr)\.?\s+)?{NAME}(?:\s+(?:and|&)\s+{NAME})?)")
# Sentence words that a greedy name match can swallow: "with Tyler Staton What if..."
NAME_TAIL_STOP = {"What", "How", "When", "Why", "Who", "Where", "In", "This", "The", "A", "As", "Through", "Is",
                  "Are", "Do", "Does", "Have", "Our", "We", "If", "Jesus", "God", "From", "On", "At", "And"}


def clean_name(sp: str, max_words: int = 4) -> str:
    """max_words caps the name (honorific not counted); "with X" matches use 2 because the
    next word usually starts the description sentence ("with Tyler Staton Genesis 1 ...")."""
    words = sp.split()
    hon = 1 if words and re.match(r"^(?:Dr|Rev|Bishop|Sister|Brother|Fr)\.?$", words[0]) else 0
    words = words[: hon + max_words] if " and " not in sp and " & " not in sp else words
    while len(words) > 2 and words[-1] in NAME_TAIL_STOP:
        words.pop()
    out = " ".join(words)
    if " and " in out or " & " in out:  # trim each half of "X and Y What"
        out = re.sub(r"\s+(?:and|&)\s+", " and ", out)
        out = " and ".join(clean_name(h, max_words) for h in out.split(" and "))
    return out


DESC_SPEAKER = re.compile(rf"(?:[Pp]astor|[Tt]eaching pastor,?)\s+(?P<sp>{NAME})")
# Older descriptions: "Church of the City New York - COTCNYC - Jon Tyson Isaiah 61 - 2017-12-17"
DESC_DASH_SPEAKER = re.compile(r"\s[-\u2013]\s(?P<sp>[A-Z][a-z]+ [A-Z][a-z]+)\b")
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
TRAILING_DATE = re.compile(
    rf"\s*[-\u2013,]\s*(?:[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*)?{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\s*$"
)
NON_NAMES = {"Week", "Part", "Series", "Sunday", "Advent", "Easter", "Lent", "The", "A", "An", "Intro", "Jesus", "God", "Christ", "Holy", "Spirit", "Controversial", "Pt", "Part"}


STRIP_PHRASES: list[str] = []  # set from --strip, e.g. campus names


def norm_title(raw: str) -> str:
    t = re.sub(r"\s+", " ", raw).strip()
    return re.sub(r"\s*\u2014\s*", " - ", t)  # em dash "Title — Speaker" -> "Title - Speaker"


TITLE_FIRST = {"on": False}  # from --title-first: "Title - Series - Wk 3" (vs "Series - Title - Week 3")
SERIES_PREFIXES: list[str] = []  # from --series-prefix: a segment starting with these is the series
# Trailing episode marker: "Death to Life - Matthew S7E1", "God at Work - 1 Timothy - Wk 10"
TRAILER = re.compile(r"\s[-\u2013]\s(?:[^-\u2013]*?\s)?(?:S\d+\s?E\d+|Wk\.?\s*\d+|Week\s*\d+)\s*$", re.I)
# "Saturated Thursday: Jennie Allen", "Mary's Voice: Dr. Amy Orr-Ewing"
COLON_SPEAKER = re.compile(
    rf"(?:(?:(?:Sun|Mon|Tues|Wednes|Thurs|Fri|Satur)day|\d{{4}}):\s+(?:Pastor\s+)?(?P<sp>{NAME})"
    rf"|:\s+(?P<sp2>(?:Dr|Bishop)\.?\s+{NAME}))\s*$"
)


def parse_title(raw: str, allow_speaker: bool = True) -> tuple[str, str, str]:
    """-> (series, title, speaker)"""
    t = norm_title(raw)
    for _ in range(2):  # "- Campus, Date" or "- Date - Campus"
        t = TRAILING_DATE.sub("", t)
        for phrase in STRIP_PHRASES:  # campus names
            t = re.sub(rf"\s*[-\u2013,]?\s*\b{re.escape(phrase)}\b,?\s*$", "", t)
    t = re.sub(r"(\S)- ", r"\1 - ", t)          # "Ger Jones- Santa Monica"
    t = re.sub(r"[\s\-\u2013]+$", "", t)         # dangling " -"
    speaker = ""
    m = SPEAKER_SUFFIX.search(t) if allow_speaker else None
    if m and not (set(m["sp"].split()) & NON_NAMES):
        speaker, t = re.sub(r"^Pastor\s+", "", m["sp"]), t[: m.start()].strip()
    elif allow_speaker and (cm := COLON_SPEAKER.search(t)) and not (set((cm["sp"] or cm["sp2"]).split()) & NON_NAMES):
        speaker, t = cm["sp"] or cm["sp2"], t[: cm.start() + cm.group(0).index(":")].strip()
    series = ""
    title_first = False
    if (tm := TRAILER.search(t)) and tm.start() > 0:
        t, title_first = t[: tm.start()].strip(), TITLE_FIRST["on"]
    # Leading passage: "Matthew 2:1-12; The Journey to Jesus" -> title "The Journey to Jesus"
    lead = REF_RX.match(t)
    if lead and re.match(r"\s*[;:\-\u2013]\s+\S", t[lead.end():]):
        t = re.sub(r"^\s*[;:\-\u2013]\s+", "", t[lead.end():])
    # " | " wins; otherwise split on whichever of ": " / " - " comes first.
    seps = [(" | ", t.find(" | "))] if " | " in t else sorted(
        ((sep, t.find(sep)) for sep in (": ", " - ") if sep in t), key=lambda x: x[1])
    if seps:
        series, t = (x.strip() for x in t.split(seps[0][0], 1))
        if title_first or any(t.startswith(px) for px in SERIES_PREFIXES):
            series, t = t, series  # "Title - Series - Wk 3" / "Title - Saturated Thursday"
        series = re.sub(r"\s+(?:Series\s+)?(?:Pt\.?|Part)\s*(?:\d+|[IVX]+|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve)\b\.?$|\s+Series$", "", series, flags=re.I).rstrip(" ,;-")
        if re.fullmatch(r"(?:Part|Pt\.?|Episode|Session|Wk\.?|Week)\s*\w+|S\d+\s?E\d+", series, flags=re.I):
            series = ""
    return series, t or raw.strip(), speaker


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_date(s: str, scraped_on: date) -> str:
    s = s.strip()
    low = s.lower()
    if low in ("today",) or re.search(r"\b(hr|min)s?\b.*ago", low):
        return scraped_on.isoformat()
    if low == "yesterday":
        return (scraped_on - timedelta(days=1)).isoformat()
    if m := re.match(r"(\d+)\s+days?\s+ago", low):
        return (scraped_on - timedelta(days=int(m[1]))).isoformat()
    if low in WEEKDAYS:  # Spotify shows weekday names for the past week
        back = (scraped_on.weekday() - WEEKDAYS.index(low)) % 7 or 7
        return (scraped_on - timedelta(days=back)).isoformat()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    try:  # "Sep 28": Spotify drops the year for the current year
        d = datetime.strptime(f"{s} {scraped_on.year}", "%b %d %Y").date()
        return (d if d <= scraped_on else d.replace(year=d.year - 1)).isoformat()
    except ValueError:
        return ""


def minutes(s: str) -> float:
    h = re.search(r"(\d+)\s*hr", s)
    m = re.search(r"(\d+)\s*min", s)
    sec = re.search(r"(\d+)\s*sec", s)
    return (int(h[1]) * 60 if h else 0) + (int(m[1]) if m else 0) + (int(sec[1]) / 60 if sec else 0)


NOT_SERMON = re.compile(r"(\b(devotional|bonus episode|interview|podcast trailer|announcement|parents night)\b|\bQ&A\b)", re.I)


def title_for_books(raw: str) -> str:
    """Title with the speaker/date suffix removed, so "... - John Mark Comer" can't tag Mark/John."""
    t = TRAILING_DATE.sub("", norm_title(raw))
    m = SPEAKER_SUFFIX.search(t)
    return t[: m.start()] if m else t


# ---------- main ----------
def clean_notes(desc: str) -> str:
    """Episode description worth showing on the sermon page, or "" for empty/boilerplate ones."""
    d = re.sub(r"\s+", " ", desc or "").strip()
    d = re.sub(r'^From the series "[^"]*"\.?\s*', "", d)  # Bridgetown prefix; series is shown already
    if len(d) < 60 or re.match(r"^Church of the City New York - COTCNYC", d):
        return ""
    return d


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--church", required=True, help="church id from data/churches.json")
    ap.add_argument("--scraped-on", type=date.fromisoformat, help="YYYY-MM-DD; defaults to the input file's mtime")
    ap.add_argument("--source", default="spotify", help='recorded on each sermon, e.g. "rss"')
    ap.add_argument("--title-first", action="store_true",
                    help='titles are "Title - Series - Wk N" (Church Eleven22) rather than "Series - Title"')
    ap.add_argument("--series-prefix", action="append", default=[],
                    help='title segment starting with this is the series, e.g. "Saturated" (repeatable)')
    ap.add_argument("--strip", action="append", default=[], help='phrase to remove from titles, e.g. "Santa Monica" (repeatable)')
    ap.add_argument("--min-minutes", type=float, default=20, help="shorter episodes are treated as devotionals/clips")
    ap.add_argument("--ai-min-confidence", type=float, default=0.85,
                    help="apply scraping/<church>_ai_tags.json book tags at or above this confidence (1.01 disables)")
    ap.add_argument("--series-min-confidence", type=float, default=0.85,
                    help="apply scraping/<church>_series_tags.json (book shared across a series) at or above this")
    ap.add_argument("--non-sermon-min-confidence", type=float, default=0.7,
                    help="exclude episodes the AI labelled non_sermon (interviews, Q&A, prayer nights) at or above this")
    args = ap.parse_args()

    STRIP_PHRASES.extend(args.strip)
    SERIES_PREFIXES.extend(args.series_prefix)
    TITLE_FIRST["on"] = args.title_first
    scraped_on = args.scraped_on or date.fromtimestamp(args.input.stat().st_mtime)
    episodes = json.loads(args.input.read_text())
    ov_path = ROOT / "scraping" / f"{args.church}_overrides.json"
    overrides = json.loads(ov_path.read_text()) if ov_path.exists() else {}
    ai_path = ROOT / "scraping" / f"{args.church}_ai_tags.json"
    ai_tags = json.loads(ai_path.read_text()) if ai_path.exists() else {}
    st_path = ROOT / "scraping" / f"{args.church}_series_tags.json"
    series_tags = json.loads(st_path.read_text()) if st_path.exists() else {}
    sl_path = ROOT / "scraping" / f"{args.church}_series.json"
    series_links = json.loads(sl_path.read_text()) if sl_path.exists() else {}

    # A " - Some Words" title suffix is only trusted as a speaker if it recurs across episodes,
    # appears in the description, or starts with "Dr." (filters out "Series - Missional Prayer").
    suffix_counts: dict[str, int] = {}
    for ep in episodes:
        sp = parse_title(ep["title"])[2]
        if sp:
            suffix_counts[sp] = suffix_counts.get(sp, 0) + 1

    sermons, review = [], []
    for ep in episodes:
        ep_id = re.sub(r"[^A-Za-z0-9_-]", "", ep["url"].split("?")[0].rstrip("/").split("/")[-1])[:60]
        series, title, speaker = parse_title(ep["title"])
        dated = bool(TRAILING_DATE.search(ep["title"])) or any(ph in ep["title"] for ph in STRIP_PHRASES)
        first = re.sub(r"^(?:Dr|Rev|Bishop)\.?\s+", "", speaker).split()[0].lower() if speaker else ""
        raw_t = TRAILING_DATE.sub("", norm_title(ep["title"]))
        after_week = bool(speaker) and bool(
            re.search(rf"Week\s*\d+\s*[-\u2013]\s*{re.escape(speaker)}\s*$", raw_t))
        trusted = speaker and (
            suffix_counts[speaker] > 1 or speaker.startswith("Dr") or dated or first in FIRST_NAMES
            or speaker.split(" and ")[0].split()[-1] in ep["desc"])
        if speaker and (after_week or not trusted):
            series, title, _ = parse_title(ep["title"], allow_speaker=False)
            speaker = ""
        if not speaker:
            # "Rule of Life: Episode 3 with Gemma Ryan" - only for known given names, so
            # "Eat with Tax Collectors" / "Small Things with Great Love" are left alone. Title is kept.
            tw = DESC_WITH.search(title) or DESC_WITH.search(series)  # "Saturated with Lysa TerKeurst"
            if tw:
                cand = clean_name(tw["sp"], 3)
                given = re.sub(r"^(?:Dr|Rev|Bishop|Sister|Brother|Fr)\.?\s+", "", cand).split()[0].lower()
                honor = cand != re.sub(r"^(?:Dr|Rev|Bishop|Sister|Brother|Fr)\.?\s+", "", cand)
                if (given in FIRST_NAMES or honor) and not (set(cand.split()) & NON_NAMES):
                    speaker = cand
                    if tw.string is series:
                        series = series[: tw.start()].strip()
        if not speaker:
            m = DESC_SPEAKER.search(ep["desc"])
            cap = 4
            if not m and (m := DESC_WITH.search(ep["desc"])):
                cap = 2
            m = m or DESC_DASH_SPEAKER.search(ep["desc"])
            cand = clean_name(m["sp"], cap) if m else ""
            speaker = cand if cand and not (set(cand.split()) & NON_NAMES) else ""
        title_refs, desc_refs = find_refs(ep["title"]), find_refs(ep["desc"])
        all_refs = dedupe_refs(title_refs + desc_refs)
        # Primary passage = first ref (usually "teaching from X"); later mentions are kept for review only.
        whole = [] if title_refs else find_whole_book_refs(title_for_books(ep["title"]))
        if title_refs:
            refs = dedupe_refs(title_refs)
        elif whole:
            # a desc ref in the same book is more specific than the whole-book tag; a different book is added
            same = [r for r in desc_refs if r["book"] in {w["book"] for w in whole}]
            refs = dedupe_refs(same[:1] or whole + desc_refs[:1])
        else:
            refs = desc_refs[:1]
        all_refs = dedupe_refs(refs + all_refs)
        mins = minutes(ep["duration"])

        status = "mapped" if refs else "unmapped"
        if mins and mins < args.min_minutes or NOT_SERMON.search(ep["title"]):
            status = "excluded"

        rec = {
            "id": f"{args.church}-{ep_id}",
            "title": title,
            "church": args.church,
            "speaker": speaker,
            "date": parse_date(ep["date"], scraped_on),
            "series": series,
            "passage": "; ".join(r["_label"] for r in refs),
            "refs": [{k: v for k, v in r.items() if not k.startswith("_")} for r in refs],
            "url": ep["url"],
            **({"appleUrl": ep["appleUrl"]} if ep.get("appleUrl") else {}),
            # Show notes for the sermon page; build_sermons.py moves these into data/notes.json
            **({"notes": notes} if (notes := clean_notes(ep.get("desc", ""))) else {}),
            "tags": [],
            "source": args.source,
            "durationMin": round(mins),
            "refSource": "regex" if refs else "",
        }
        ov = overrides.get(ep_id, {})
        if ov:
            rec.update({k: v for k, v in ov.items() if k != "exclude" and not k.startswith("_")})  # "_episode" = human note
            status = "excluded" if ov.get("exclude") else ("mapped" if rec["refs"] else "unmapped")
            if "refs" in ov and "passage" not in ov:
                rec["passage"] = ""  # site will generate from refs
            if "refs" in ov:
                rec["refSource"] = "manual"
        # AI tags fill only what regex and hand overrides left unmapped; never touch excluded episodes.
        ai = ai_tags.get(ep_id, {})
        if status == "unmapped" and ai.get("kind") == "book" and ai.get("refs") \
                and ai.get("confidence", 0) >= args.ai_min_confidence:
            rec.update(refs=ai["refs"], passage="", refSource="ai", aiConfidence=ai["confidence"])
            status = "mapped"
        stag = series_tags.get(ep_id, {})
        if status == "unmapped" and stag.get("confidence", 0) >= args.series_min_confidence:
            rec.update(refs=stag["refs"], passage="", refSource="series", aiConfidence=stag["confidence"])
            status = "mapped"
        if status == "unmapped" and ai.get("kind") == "non_sermon" \
                and ai.get("confidence", 0) >= args.non_sermon_min_confidence and not ov:
            status = "excluded"
        link = series_links.get(ep_id)
        if link:
            rec["seriesKey"] = link["key"]
            # 'From the series "X"' gives a real name (a wk-run name is just a placeholder). Once written to the
            # review CSV that name comes back as basis "explicit" on the next series_links.py run, so accept both
            # or the name flips on/off every rebuild.
            if not rec["series"] and link["basis"] != "wk-run":
                rec["series"] = link["name"]
        if not rec["refs"]:
            rec.pop("refSource", None)

        review.append({
            "episode_id": ep_id, "status": status, "date": rec["date"], "series": rec["series"],
            "title": rec["title"], "speaker": rec["speaker"], "minutes": rec["durationMin"],
            "passage": rec["passage"], "other_refs_in_desc": "; ".join(r["_label"] for r in all_refs[len(refs):]),
            "overridden": "yes" if ov else "", "spotify_title": ep["title"],
            "ref_source": rec.get("refSource", ""), "ai_kind": ai.get("kind", ""),
            "ai_confidence": ai.get("confidence", ""),
            "ai_refs": "; ".join(f'{r["book"]} {r.get("start", "")}'.strip() for r in ai.get("refs", [])),
            "ai_rationale": ai.get("rationale", ""), "ai_pass": ai.get("pass", ""),
            "series_key": link["key"] if link else "", "series_tag": stag.get("basis", ""),
        })
        if status == "mapped":
            sermons.append(rec)

    honorific = re.compile(r"^(?:Dr\.?|Bishop|Rev\.?|Pastor)\s+")
    canon = {}
    for r in review:
        if r["speaker"] and honorific.match(r["speaker"]):
            canon[honorific.sub("", r["speaker"])] = r["speaker"]
    for r in review:
        r["speaker"] = canon.get(r["speaker"], r["speaker"])
    for rec in sermons:
        rec["speaker"] = canon.get(rec["speaker"], rec["speaker"])

    out = ROOT / "data" / "sources" / f"{args.church}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sermons, indent=2, ensure_ascii=False) + "\n")

    rv = ROOT / "scraping" / f"{args.church}_review.csv"
    with rv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(review[0]))
        w.writeheader()
        w.writerows(review)

    counts = {s: sum(r["status"] == s for r in review) for s in ("mapped", "unmapped", "excluded")}
    print(f"{len(episodes)} episodes (scraped {scraped_on}): {counts}")
    print(f"wrote {out.relative_to(ROOT)} and {rv.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
