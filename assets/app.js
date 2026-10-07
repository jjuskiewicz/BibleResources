'use strict';

/* ============================================================
   Config - edit these
   ============================================================ */
const CONFIG = {
  booksUrl: 'data/books.json',
  churchesUrl: 'data/churches.json',
  sermonsUrl: 'data/sermons.json',
  notesUrl: 'data/notes.json',     // show notes, fetched lazily (sermon page + search)
  // e.g. 'https://github.com/<you>/<repo>/issues/new?template=sermon.md'  (null hides the link)
  suggestUrl: null,
  recentCount: 6,   // "Latest sermons" (newest by preached date)
  maxResults: 24,   // search results shown at first; "Show more" adds this many again
  speakerPage: 30,  // speaker page in the panel: sermons shown at first, "Show more" adds this many
  inBooks: 12,      // search: how many books the "In" row lists
};

// Short labels for the jump-to-section row (full names stay in the tooltip / screen reader label)
const SECTION_SHORT = {
  law: 'Law', history: 'History', wisdom: 'Wisdom', major: 'Major Prophets', minor: 'Minor Prophets',
  gospels: 'Gospels', acts: 'Acts', pauline: 'Paul', general: 'General', prophecy: 'Revelation',
};

const FALLBACK_CHURCH_COLORS = ['#2f6b8a', '#b07a1f', '#8a4a8a', '#2d7d71', '#8a3b3b', '#5d4f97'];

/* ============================================================
   State
   ============================================================ */
const state = {
  sections: [],
  sectionById: new Map(),
  books: [],
  bookById: new Map(),
  churches: new Map(),
  sermons: [],
  sermonById: new Map(),
  testament: 'all',
  churchFilter: new Set(), // empty = all
  query: '',
  // The side panel (bottom sheet on phones). One of:
  //   { kind: 'book', bookId, chapter }   { kind: 'sermon', sermonId }
  //   { kind: 'series', id }              { kind: 'speaker', id }
  open: null,
  panelScroll: new Map(),  // panel view key -> scrollTop, so Back lands where you were
  lastSermonId: null,      // the sermon last opened in the panel (marked in its series list)
  bookQuery: null,         // { bookId, q }: a book opened from a search shows only that search's matches
  speakerShown: 0,
  series: new Map(),       // id -> { id, name, church, color, sermons }
  speakers: new Map(),     // id -> { id, name, color, sermons }
  lastFocus: null,
  notes: null,             // id -> show notes text, once data/notes.json has loaded
  shown: 0,                // how many search results are rendered
  shownFor: '',            // the query `shown` belongs to (a new query starts over)
  studyOnly: false,        // book panel: only sermons that study the book (s.study), remembered per browser
};

// Labels some feeds use for one-off messages; not worth grouping
const NOT_A_SERIES = /^(stand ?alone|testimony|lecture|introduction)$/i;

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const slug = (s) => norm(s).replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
const splitSpeakers = (s) => String(s ?? '').split(/\s+(?:and|&)\s+|\s*,\s*/).map((x) => x.trim()).filter(Boolean);
const plural = (n, word) => `${n.toLocaleString('en-US')} ${word}${n === 1 ? '' : /(ch|sh|s|x)$/.test(word) ? 'es' : 's'}`;

/* ============================================================
   Book name matching ("1 Sam", "first samuel", "1sam", "Ps", ...)
   ============================================================ */
function norm(s) {
  return String(s ?? '')
    .toLowerCase()
    .replace(/[.’']/g, '')
    .replace(/\b(first|1st)\b/g, '1')
    .replace(/\b(second|2nd)\b/g, '2')
    .replace(/\b(third|3rd)\b/g, '3')
    .replace(/^iii\s/, '3 ').replace(/^ii\s/, '2 ').replace(/^i\s/, '1 ')
    .replace(/^([123])\s*(?=[a-z])/, '$1 ')
    .replace(/\s+/g, ' ')
    .trim();
}

function bookKeys(b) {
  return [b.id.replace(/-/g, ' '), b.name, b.abbr, ...(b.aliases || [])].map(norm);
}

function matchBooks(q) {
  const n = norm(q);
  if (!n) return [];
  return state.books.filter((b) => b._keys.some((k) => k.startsWith(n)));
}

function resolveBook(q) {
  const n = norm(q);
  if (!n) return null;
  const exact = state.books.find((b) => b._keys.includes(n));
  if (exact) return exact;
  const prefix = matchBooks(q);
  return prefix.length === 1 ? prefix[0] : null;
}

/** "John 3", "1 cor 13:4", "Ps 23" -> { book, chapter } */
function parseRef(q) {
  const m = q.trim().match(/^(.+?)\s*(\d+)(?:\s*[:.]\s*\d+(?:\s*[-–]\s*\d+)?)?$/);
  if (!m) return null;
  const book = resolveBook(m[1]);
  const chapter = Number(m[2]);
  if (!book || chapter < 1 || chapter > book.chapters) return null;
  return { book, chapter };
}

/* ============================================================
   Data loading + normalization
   ============================================================ */
async function getJSON(url) {
  const res = await fetch(url, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

async function load() {
  const [bookData, churches, sermonData] = await Promise.all([
    getJSON(CONFIG.booksUrl),
    getJSON(CONFIG.churchesUrl),
    getJSON(CONFIG.sermonsUrl),
  ]);

  state.sections = bookData.sections;
  state.sectionById = new Map(state.sections.map((s) => [s.id, s]));
  state.books = bookData.books.map((b) => ({ ...b, _keys: bookKeys(b) }));
  state.bookById = new Map(state.books.map((b) => [b.id, b]));

  churches.forEach((c, i) => {
    state.churches.set(c.id, { ...c, color: c.color || FALLBACK_CHURCH_COLORS[i % FALLBACK_CHURCH_COLORS.length] });
  });

  const raw = Array.isArray(sermonData) ? sermonData : sermonData.sermons || [];
  state.sermons = raw.map(normalizeSermon).filter(Boolean);
  state.sermonById = new Map(state.sermons.map((s) => [s.id, s]));
  buildGroups();
}

/** Series and speaker groupings. Only groups with 2+ sermons become clickable. */
function buildGroups() {
  const series = new Map();
  const speakers = new Map();
  const add = (map, id, make, s) => {
    if (!map.has(id)) map.set(id, { ...make(), sermons: [] });
    map.get(id).sermons.push(s);
  };
  for (const s of state.sermons) {
    const name = (s.series || '').trim();
    if (name && !NOT_A_SERIES.test(name)) {
      // seriesKey (from series_links.py) already splits reused names like "Advent" by year
      const id = slug(`${s.church} ${s.seriesKey || name}`);
      add(series, id, () => ({ id, church: s.church, color: s.churchObj.color }), s);
      s._seriesId = id;
    }
    s._speakerIds = splitSpeakers(s.speaker).map((n) => {
      const id = slug(n);
      add(speakers, id, () => ({ id, name: n }), s);
      return id;
    });
  }
  const mostCommon = (arr) => {
    const c = new Map();
    arr.forEach((x) => c.set(x, (c.get(x) || 0) + 1));
    return [...c].sort((a, b) => b[1] - a[1])[0][0];
  };
  for (const [id, g] of series) {
    if (g.sermons.length < 2) { series.delete(id); g.sermons.forEach((s) => { s._seriesId = null; }); continue; }
    g.name = mostCommon(g.sermons.map((s) => s.series.trim()));
  }
  for (const [id, g] of speakers) {
    if (g.sermons.length < 2) { speakers.delete(id); continue; }
    g.color = state.churches.get(mostCommon(g.sermons.map((s) => s.church)))?.color || 'var(--muted)';
  }
  state.series = series;
  state.speakers = speakers;
}

const groupOf = (kind, id) => (kind === 'series' ? state.series : state.speakers).get(id) || null;

function normalizeSermon(s, i) {
  const refs = (s.refs || []).map((r) => {
    const book = state.bookById.get(r.book) || resolveBook(r.book);
    if (!book) {
      console.warn(`[sermons] #${i} "${s.title}": unknown book "${r.book}"`);
      return null;
    }
    const whole = r.start == null;
    const start = whole ? null : Math.min(Math.max(1, r.start), book.chapters);
    const end = whole ? null : Math.min(Math.max(start, r.end ?? start), book.chapters);
    return { book: book.id, start, end };
  }).filter(Boolean);

  if (!refs.length) {
    console.warn(`[sermons] #${i} "${s.title}": no valid refs, skipped`);
    return null;
  }
  const church = state.churches.get(s.church);
  if (!church) console.warn(`[sermons] #${i} "${s.title}": unknown church "${s.church}"`);

  const date = s.date ? new Date(`${s.date}T12:00:00`) : null;
  return {
    ...s,
    id: s.id || `s${i}`,
    refs,
    churchObj: church || { id: s.church, name: s.church || 'Unknown church', color: 'var(--faint)' },
    dateObj: date && !isNaN(date) ? date : null,
    // Searchable fields, weighted in searchSermons. Notes are added when notes.json arrives.
    _f: {
      title: norm(s.title),
      series: norm(s.series),
      speaker: norm(s.speaker),
      other: norm([s.passage, church?.name, church?.short, ...(s.tags || [])].join(' ')),
      notes: '',
    },
  };
}

/* ============================================================
   Derived data
   ============================================================ */
const testamentOf = (bookId) => state.sectionById.get(state.bookById.get(bookId).section).testament;

/** Church filter only. The panel uses this: an open book, series or speaker shows all of itself. */
function churchSermons() {
  if (!state.churchFilter.size) return state.sermons;
  return state.sermons.filter((s) => state.churchFilter.has(s.church));
}

/** Church + testament filters: what the main column (latest, search, book grid) works from. */
function visibleSermons() {
  const base = churchSermons();
  if (state.testament === 'all') return base;
  return base.filter((s) => s.refs.some((r) => testamentOf(r.book) === state.testament));
}

function bookStats(sermons) {
  const stats = new Map(state.books.map((b) => [b.id, { count: 0, chapters: new Set() }]));
  for (const s of sermons) {
    const seen = new Set();
    for (const r of s.refs) {
      const st = stats.get(r.book);
      if (!seen.has(r.book)) { st.count++; seen.add(r.book); }
      if (r.start != null) for (let c = r.start; c <= r.end; c++) st.chapters.add(c);
    }
  }
  return stats;
}

function refLabel(s) {
  if (s.passage) return s.passage;
  return s.refs.map((r) => {
    const b = state.bookById.get(r.book);
    if (r.start == null) return b.name;
    return r.start === r.end ? `${b.name} ${r.start}` : `${b.name} ${r.start}–${r.end}`;
  }).join('; ');
}

const byDateDesc = (a, b) => (b.dateObj?.getTime() || 0) - (a.dateObj?.getTime() || 0);
const fmtDate = (d) => d ? d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
/** Card date: always include the year ("Sep 28, 2026") so current-year sermons aren't ambiguous */
const fmtShort = fmtDate;
/** Full name on wide screens, short name on phones (CSS toggles .long/.short) */
const churchName = (c) => c.short && c.short !== c.name
  ? `<span class="long">${esc(c.name)}</span><span class="short">${esc(c.short)}</span>`
  : esc(c.name);
const isTouch = matchMedia('(hover: none) and (pointer: coarse)').matches;
/** Wide screens: the panel sits beside the page instead of covering it (keep in sync with styles.css). */
const wide = matchMedia('(min-width: 1100px)');
const isModal = () => !!state.open && !wide.matches;

/* ============================================================
   Search: what is being asked for, and what matches
   ============================================================ */
/**
 * The search box means one of:
 *   none     fewer than 2 characters
 *   ref      a chapter ("John 3", "Rom 8:28")
 *   book     a book's name or abbreviation exactly ("romans", "1 cor", "ps"): its sermons, same count as its page
 *   text     anything else: ranked title/series/speaker/topic/notes search
 */
function searchMode(raw = state.query) {
  const q = raw.trim();
  const n = norm(q);
  if (n.length < 2) return { kind: 'none', n };
  const ref = parseRef(q);
  if (ref) return { kind: 'ref', n, ...ref };
  const book = state.books.find((b) => b._keys.includes(n));
  if (book) return { kind: 'book', n, book };
  return { kind: 'text', n };
}

function findHits(sermons, mode) {
  if (mode.kind === 'ref') {
    const { book, chapter } = mode;
    return sermons
      .filter((s) => s.refs.some((r) => r.book === book.id && (r.start == null || (chapter >= r.start && chapter <= r.end))))
      // Sermons on that chapter first; whole-book ones ("John" with no chapter) after them
      .sort((a, b) => wholeBookOnly(a, book.id) - wholeBookOnly(b, book.id) || byDateDesc(a, b));
  }
  if (mode.kind === 'book') return sermons.filter((s) => s.refs.some((r) => r.book === mode.book.id)).sort(byDateDesc);
  if (mode.kind === 'text') return searchSermons(sermons, mode.n);
  return [];
}

/* Text ranking: every typed word has to start a word somewhere in the sermon.
   Each word scores by the best field it hits; a title containing the whole phrase gets a bonus.
   Ties go to the newer sermon. */
const FIELD_WEIGHT = { title: 10, series: 6, speaker: 6, other: 3, notes: 1 };
const reEsc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const wholeBookOnly = (s, bookId) => (s.refs.some((r) => r.book === bookId && r.start != null) ? 0 : 1);

function searchSermons(sermons, q) {
  const terms = q.split(' ').filter(Boolean);
  const res = terms.map((t) => new RegExp(`(?:^|[^a-z0-9])${reEsc(t)}`));
  const phrase = terms.length > 1 ? q : null;
  const out = [];
  for (const s of sermons) {
    let score = 0;
    let notesOnly = false;
    for (const re of res) {
      let best = 0;
      for (const f in FIELD_WEIGHT) if (FIELD_WEIGHT[f] > best && re.test(s._f[f])) best = FIELD_WEIGHT[f];
      if (!best) { score = 0; break; }
      if (best === FIELD_WEIGHT.notes) notesOnly = true;
      score += best;
    }
    if (!score) continue;
    if (phrase && s._f.title.includes(phrase)) score += 10;
    s._score = score;
    s._viaNotes = notesOnly;
    out.push(s);
  }
  return out.sort((a, b) => b._score - a._score || byDateDesc(a, b));
}

/** Series/speakers whose name has a word starting with every typed term. */
function groupSuggestions(n) {
  if (n.length < 3) return [];
  const terms = n.split(' ');
  const hit = (name) => {
    const words = norm(name).split(/[^a-z0-9]+/);
    return terms.every((t) => words.some((w) => w.startsWith(t)));
  };
  const out = [];
  for (const g of state.speakers.values()) if (hit(g.name)) out.push({ kind: 'speaker', ...g });
  for (const g of state.series.values()) if (hit(g.name)) out.push({ kind: 'series', ...g });
  return out.sort((a, b) => b.sermons.length - a.sermons.length).slice(0, 3);
}

/** The book a search points at, if any: a chapter, an exact name, or the only book the typing could be. */
function searchBook(mode) {
  if (mode.kind === 'ref' || mode.kind === 'book') return mode.book;
  const books = matchBooks(state.query);
  return books.length === 1 ? books[0] : null;
}

/** A short show-notes snippet around the first typed word, for results found only through the notes. */
function noteExcerpt(s, q) {
  const text = s._viaNotes && state.notes?.[s.id];
  if (!text) return '';
  const words = q.split(' ').filter((w) => w.length > 2 && !s._f.title.includes(w));
  for (const w of words) {
    const m = new RegExp(`(^|[^a-z0-9])(${reEsc(w)}[a-z]*)`, 'i').exec(text);
    if (!m) continue;
    const at = m.index + m[1].length;
    const from = Math.max(0, text.lastIndexOf(' ', Math.max(0, at - 60)) + 1);
    const to = Math.min(text.length, at + m[2].length + 70);
    const clip = (from > 0 ? '…' : '') + esc(text.slice(from, at)) + `<mark>${esc(m[2])}</mark>` + esc(text.slice(at + m[2].length, to)) + (to < text.length ? '…' : '');
    return `<span class="hit">${clip}</span>`;
  }
  return '';
}

/** notes.json landed: make the notes searchable, and refresh an open search. */
function attachNotes(notes) {
  if (state.notes || !notes || !Object.keys(notes).length) return;
  state.notes = notes;
  for (const s of state.sermons) s._f.notes = norm(notes[s.id] || '');
  if (searchMode().kind === 'text' || state.bookQuery) render();
}

/* ============================================================
   Rendering
   ============================================================ */
/* ---------- Listening links ---------- */
const ICON = {
  spotify: '<span class="brand-ico spotify" aria-hidden="true"></span>',
  apple: '<span class="brand-ico apple" aria-hidden="true"></span>',
  web: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/></svg>',
  audio: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="14" width="5" height="7" rx="1.5"/><rect x="16" y="14" width="5" height="7" rx="1.5"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7"/></svg>',
  x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17"/></svg>',
};
const hostOf = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
const SITE_NAMES = { 'gospelinlife.com': 'Gospel in Life' };

/** Last service the viewer listened on ("spotify" / "apple"), so the sermon page leads with it. */
const PREF_KEY = 'listenOn';
const getPref = () => { try { return localStorage.getItem(PREF_KEY); } catch { return null; } };
const setPref = (v) => { try { localStorage.setItem(PREF_KEY, v); } catch { /* private mode */ } };

/** Book panel "Book studies only" toggle, remembered per browser. */
const STUDY_KEY = 'studyOnly';
try { state.studyOnly = localStorage.getItem(STUDY_KEY) === '1'; } catch { /* private mode */ }
const setStudyOnly = (on) => {
  state.studyOnly = on;
  try { localStorage.setItem(STUDY_KEY, on ? '1' : '0'); } catch { /* private mode */ }
};
/** Does this sermon teach this book's passage in context (vs. a topical sermon citing it)? scraping/fit/ */
const isStudy = (s, bookId) => !!s.study?.includes(bookId);

/** One-time explainer for the "Study" mark, shown above lists that contain one until dismissed (per browser). */
const STUDY_NOTE_KEY = 'studyNoteSeen';
let studyNoteSeen = false;
try { studyNoteSeen = localStorage.getItem(STUDY_NOTE_KEY) === '1'; } catch { /* private mode */ }
function studyNote(sermons) {
  if (studyNoteSeen || !sermons.some((s) => s.study?.length && s.refs.length <= 2)) return '';
  return `<p class="study-note"><span class="study-mark">Study</span><span>Teaches the passage in context, not a topical sermon that cites it.</span>
    <button type="button" class="sn-close" data-dismiss-study aria-label="Got it, hide this note">Got it</button></p>`;
}

/**
 * Filters that are on, as removable chips next to the counts they affect.
 * opts.testament: false in the panel, which ignores the testament toggle.
 */
function filterChips({ testament = true } = {}) {
  const chips = [];
  if (testament && state.testament !== 'all') {
    chips.push(`<button type="button" class="fchip" data-clear-filter="testament" aria-label="Remove filter: ${state.testament === 'OT' ? 'Old' : 'New'} Testament">${state.testament === 'OT' ? 'Old Testament' : 'New Testament'}${ICON.x}</button>`);
  }
  for (const id of state.churchFilter) {
    const c = state.churches.get(id);
    if (!c) continue;
    chips.push(`<button type="button" class="fchip" data-clear-filter="church:${esc(id)}" aria-label="Remove filter: ${esc(c.name)}"><span class="dot" style="--cc:${esc(c.color)}"></span>${esc(c.short || c.name)}${ICON.x}</button>`);
  }
  return chips.length ? `<span class="fchips" role="group" aria-label="Filters on">${chips.join('')}</span>` : '';
}

/** Every place a sermon can be heard, in a fixed order: Spotify, Apple, church site, audio file. */
function listenLinks(s) {
  const out = [];
  const host = hostOf(s.url);
  if (host === 'open.spotify.com') out.push({ kind: 'spotify', url: s.url, name: 'Spotify' });
  if (s.appleUrl) out.push({ kind: 'apple', url: s.appleUrl, name: 'Apple Podcasts' });
  if (s.url && host !== 'open.spotify.com') out.push({ kind: 'web', url: s.url, name: SITE_NAMES[host] || host || 'Church site' });
  if (s.audio) out.push({ kind: 'audio', url: s.audio, name: 'Audio file' });
  return out;
}

const listenAttrs = (l) =>
  `href="${esc(l.url)}" target="_blank" rel="noopener noreferrer" data-listen="${l.kind}"`;

/** One pill per book reference; each opens that book (and chapter) page. */
function refPills(s) {
  const parts = s.passage ? s.passage.split(/\s*;\s*/) : [];
  return s.refs.map((r, i) => {
    const b = state.bookById.get(r.book);
    const generated = r.start == null ? b.name : r.start === r.end ? `${b.name} ${r.start}` : `${b.name} ${r.start}–${r.end}`;
    // Prefer the display passage ("Romans 5:12–6:14") when it lines up with the refs
    const part = parts.length === s.refs.length ? parts[i] : null;
    const label = part && b._keys.some((k) => norm(part).startsWith(k)) ? part : generated;
    const target = r.start == null ? b.id : `${b.id}/${r.start}`;
    const where = r.start == null ? b.name : `${b.name} ${r.start}`;
    return `<button type="button" class="pill" data-goto="${target}" style="--pc:var(--${b.section})" title="All sermons on ${esc(where)}">${esc(label)}</button>`;
  }).join('');
}

/** A series or speaker name that opens its page in the panel. */
const facet = (kind, id, label, extra = '') =>
  `<button type="button" class="facet${extra}" data-group="${kind}:${id}" title="All ${kind === 'series' ? 'messages in this series' : `sermons by ${esc(label)}`}">${esc(label)}</button>`;

/** opts.speakerId: on that speaker's own page, their name isn't a link. */
function speakerHtml(s, opts = {}) {
  if (!s.speaker) return '';
  const names = splitSpeakers(s.speaker);
  const parts = names.map((n, i) => {
    const id = s._speakerIds[i];
    return state.speakers.has(id) && id !== opts.speakerId ? facet('speaker', id, n) : esc(n);
  });
  return `<span class="speaker">${parts.join(names.length === 2 ? ' and ' : ', ')}</span>`;
}

/**
 * Sermon card: three lines, each answering one question.
 *   1. passage (+ "Study" when it teaches that passage in context) ........ date
 *   2. title
 *   3. church · speaker · length · series   (one line; series truncates)
 * Topic tags live on the sermon page (and in search), not on the card.
 * opts.bookId: in a book panel, "Study" means a study of that book; elsewhere, of any book it cites.
 * opts.hideStudy: the list is already filtered to studies, so the mark would be noise.
 * opts.seriesId / opts.speakerId: on that series/speaker page, don't repeat it on every card.
 * opts.here: the sermon you just came from (marked in its series list).
 */
function sermonCard(s, extra = '', opts = {}) {
  const firstBook = state.bookById.get(s.refs[0].book);
  const color = `var(--${firstBook.section})`;
  // A series named after the book ("John", "Acts") just repeats the passage line, so drop it.
  const bookNames = new Set(s.refs.map((r) => norm(state.bookById.get(r.book).name)));
  const series = s.series && !bookNames.has(norm(s.series)) ? s.series : '';
  const inSeries = opts.seriesId && s._seriesId === opts.seriesId;
  const seriesHtml = !series || inSeries ? ''
    : s._seriesId ? facet('series', s._seriesId, series, ' series') : `<span class="series">${esc(series)}</span>`;
  const meta = [
    `<span class="who"><span class="dot" style="--cc:${esc(s.churchObj.color)}"></span>${churchName(s.churchObj)}</span>`,
    speakerHtml(s, opts),
    s.durationMin && `<span class="dur">${Math.round(s.durationMin)} min</span>`,
    seriesHtml,
  ].filter(Boolean).join('');
  const when = s.dateObj ? `<time datetime="${esc(s.date)}" title="${fmtDate(s.dateObj)}">${fmtShort(s.dateObj)}</time>`
    : s.year ? `<time datetime="${esc(s.year)}" title="Exact date unknown">${esc(s.year)}</time>` : '';
  // Skipped on cards with 3+ passage pills: the line can't fit it without crushing the pills.
  const study = !opts.hideStudy && s.refs.length <= 2 && (opts.bookId ? isStudy(s, opts.bookId) : !!s.study?.length);
  const studyHtml = study ? `<span class="study-mark" title="Teaches this passage in context, not a topical sermon that cites it">Study</span>` : '';
  // One-tap listening: up to two services as icon buttons; the rest of the card opens the sermon page.
  // The audio file only gets an icon when there's no Spotify/Apple pair (e.g. Keller: site + audio).
  const all = listenLinks(s);
  const players = all.filter((l) => l.kind !== 'audio');
  const icons = (players.length >= 2 ? players : all).slice(0, 2).map((l) =>
    `<a class="ico ${l.kind}" ${listenAttrs(l)} aria-label="Listen on ${esc(l.name)}" title="Listen on ${esc(l.name)}">${ICON[l.kind]}</a>`).join('');
  const here = opts.here === s.id;
  return `
    <li>
      <article class="sermon${here ? ' is-here' : ''}" style="--c:${color}" data-card="${esc(s.id)}">
        <span class="ref"><span class="pass">${refPills(s)}</span>${studyHtml}${here ? '<span class="here-mark">Just viewed</span>' : ''}${when}</span>
        <a class="title" href="#/sermon/${esc(s.id)}" data-sermon="${esc(s.id)}"${here ? ' aria-current="page"' : ''}>${esc(s.title)}</a>
        <span class="meta">${meta}</span>
        ${extra}
        <span class="listen">${icons}</span>
      </article>
    </li>`;
}

function renderChurchChips() {
  const el = $('#churches');
  const all = `<button class="chip" data-church="" aria-pressed="${state.churchFilter.size === 0}">All churches</button>`;
  const chips = [...state.churches.values()].map((c) => `
    <button class="chip" data-church="${esc(c.id)}" aria-pressed="${state.churchFilter.has(c.id)}">
      <span class="dot" style="--cc:${esc(c.color)}"></span>${churchName(c)}
    </button>`).join('');
  el.innerHTML = all + chips;
}

/** One line under the filters that always describes what the page is showing. */
function renderStats(sermons, stats, mode, hits) {
  const inTestament = state.books.filter((b) => state.testament === 'all' || testamentOf(b.id) === state.testament).length;
  const covered = [...stats.values()].filter((s) => s.count).length;
  const el = $('#stats');
  if (mode.kind === 'text') {
    el.innerHTML = `<strong>${hits.length.toLocaleString('en-US')}</strong> of ${plural(sermons.length, 'sermon')} match` +
      ` · in <strong>${covered}</strong> of ${inTestament} books`;
    return;
  }
  const churches = new Set(sermons.map((s) => s.church)).size;
  el.innerHTML =
    `<strong>${plural(sermons.length, 'sermon')}</strong> from <strong>${plural(churches, 'church')}</strong>` +
    ` · <strong>${covered}</strong> of ${inTestament} books covered`;
}

/**
 * The book grid. Typing a book name narrows it to those books; a text search keeps every book but
 * recounts each tile to the matches (books with none go quiet), and a tile then opens that book
 * showing only the matches.
 */
function renderLibrary(stats, mode) {
  const q = state.query.trim();
  const named = q ? (mode.kind === 'ref' ? [mode.book] : matchBooks(q)) : [];
  const only = named.length ? new Set(named.map((b) => b.id)) : null;
  const searching = mode.kind === 'text' && !only;

  const html = state.sections
    .filter((sec) => state.testament === 'all' || sec.testament === state.testament)
    .map((sec) => {
      const books = state.books.filter((b) => b.section === sec.id && (!only || only.has(b.id)));
      if (!books.length) return '';
      const secCount = books.reduce((n, b) => n + stats.get(b.id).count, 0);
      const tiles = books.map((b) => {
        const st = stats.get(b.id);
        const pct = Math.round((st.chapters.size / b.chapters) * 100);
        const what = searching ? `${plural(st.count, 'match')} for “${q}”` : plural(st.count, 'sermon');
        const label = `${b.name}, ${plural(b.chapters, 'chapter')}, ${what}`;
        return `
          <button class="tile${st.count ? '' : ' empty'}" data-book="${b.id}" aria-label="${esc(label)}">
            <span class="abbr" aria-hidden="true">${esc(b.abbr)}</span>
            <span class="name" aria-hidden="true">${esc(b.name)}</span>
            <span class="meta" aria-hidden="true">${b.chapters} ch</span>
            <span class="count" aria-hidden="true">${st.count}</span>
            <span class="bar" aria-hidden="true" title="${pct}% of chapters have a ${searching ? 'match' : 'sermon'}"><i style="width:${pct}%"></i></span>
          </button>`;
      }).join('');
      return `
        <section class="section" data-sec="${sec.id}" style="--c:var(--${sec.id})" aria-labelledby="sec-${sec.id}">
          <div class="section-head">
            <h2 id="sec-${sec.id}">${esc(sec.name)}</h2>
            <span>${plural(books.length, 'book')} · ${searching ? `${plural(secCount, 'match')}` : plural(secCount, 'sermon')}</span>
          </div>
          <div class="grid">${tiles}</div>
        </section>`;
    }).join('');

  const lib = $('#library');
  lib.classList.toggle('searching', searching);
  lib.innerHTML = html || `<div class="empty-state"><strong>No books match.</strong>Try another name.</div>`;
  renderJump();
}

/* ============================================================
   Jump to section (sticky row under search, highlights where you are)
   ============================================================ */
function renderJump() {
  const nav = $('#jump');
  const ids = [...document.querySelectorAll('#library .section')].map((el) => el.dataset.sec);
  // Only useful when browsing the full list, not while a search is narrowing it
  if (state.query.trim() || ids.length < 3) { nav.hidden = true; nav.innerHTML = ''; return; }
  nav.hidden = false;
  nav.innerHTML = ids.map((id) => {
    const sec = state.sections.find((s) => s.id === id);
    const short = SECTION_SHORT[id] || sec.name;
    return `<button type="button" data-jump="${id}" style="--c:var(--${id})" aria-label="${esc(sec.name)}" title="${esc(sec.name)}"><span class="dot" style="--cc:var(--${id})"></span>${esc(short)}</button>`;
  }).join('');
  spy.pinned = null;
  spy.current = undefined;
  spy();
}

function jumpTo(id) {
  const el = document.getElementById(`sec-${id}`)?.closest('.section');
  if (!el) return;
  const smooth = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Keep the tapped section highlighted until the user scrolls by hand
  // (near the end of the page, short sections can't reach the top).
  spy.pinned = id;
  spy.current = id;
  setActiveJump(id);
  el.scrollIntoView({ block: 'start', behavior: smooth ? 'smooth' : 'auto' });
}

function setActiveJump(id) {
  const nav = $('#jump');
  let active = null;
  nav.querySelectorAll('button').forEach((b) => {
    const on = b.dataset.jump === id;
    if (on) { b.setAttribute('aria-current', 'true'); active = b; } else b.removeAttribute('aria-current');
  });
  // Keep the active chip visible by scrolling the row only (never the page)
  if (active && nav.scrollWidth > nav.clientWidth) {
    const left = active.offsetLeft - (nav.clientWidth - active.offsetWidth) / 2;
    nav.scrollTo({ left: Math.max(0, left), behavior: 'smooth' });
  }
}

/** Highlight the section currently under the sticky bar. */
function spy() {
  const nav = $('#jump');
  if (nav.hidden || spy.pinned) return;
  const barBottom = $('.toolbar').getBoundingClientRect().bottom;
  const sections = [...document.querySelectorAll('#library .section')];
  let current = null;
  for (const el of sections) {
    if (el.getBoundingClientRect().top <= barBottom + 24) current = el.dataset.sec;
  }
  const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
  if (atBottom && sections.length) current = sections[sections.length - 1].dataset.sec;
  if (current !== spy.current) { spy.current = current; setActiveJump(current); }
}

/** Keyboard hint under the search box (wide screens; phones get the same thing as the first result). */
function renderHint(mode) {
  const hint = $('#q-hint');
  const book = searchBook(mode);
  if (!book) { hint.innerHTML = ''; return; }
  const target = mode.kind === 'ref' ? `${book.id}/${mode.chapter}` : book.id;
  const label = mode.kind === 'ref' ? `${book.name} ${mode.chapter}` : book.name;
  hint.innerHTML = `Press Enter or <button type="button" data-goto="${target}">Open ${esc(label)} <span aria-hidden="true">→</span></button>`;
}

/** "Go to" rows above the results: the book or chapter the search names, and matching speakers/series. */
function gotoRows(mode, hits) {
  const rows = [];
  const book = searchBook(mode);
  if (book) {
    const sermons = churchSermons();
    if (mode.kind === 'ref') {
      rows.push({ attr: `data-goto="${book.id}/${mode.chapter}"`, kind: 'Chapter', name: `${book.name} ${mode.chapter}`,
        sub: plural(hits.length, 'sermon'), color: `var(--${book.section})` });
    } else {
      const n = sermons.filter((s) => s.refs.some((r) => r.book === book.id)).length;
      rows.push({ attr: `data-goto="${book.id}"`, kind: 'Book', name: book.name,
        sub: `${plural(n, 'sermon')} · ${plural(book.chapters, 'chapter')}`, color: `var(--${book.section})` });
    }
  }
  if (mode.kind !== 'ref') {
    for (const g of groupSuggestions(mode.n)) {
      const church = state.churches.get(g.church);
      rows.push({ attr: `data-group="${g.kind}:${g.id}"`, kind: g.kind === 'series' ? `Series${church ? ` · ${church.short || church.name}` : ''}` : 'Speaker',
        name: g.name, sub: plural(g.sermons.length, g.kind === 'series' ? 'message' : 'sermon'), color: g.color });
    }
  }
  if (!rows.length) return '';
  return `<ul class="goto">${rows.map((r) => `
    <li><button type="button" class="goto-row" ${r.attr} style="--gc:${esc(r.color)}">
      <span class="g-kind">${esc(r.kind)}</span><span class="g-name">${esc(r.name)}</span><span class="g-sub">${esc(r.sub)}</span>${ICON.arrow}
    </button></li>`).join('')}</ul>`;
}

/** Text search: which books the matches are in, most first. Tapping one opens that book showing just the matches. */
function inBooksRow(stats) {
  const books = state.books.map((b) => ({ b, n: stats.get(b.id).count })).filter((x) => x.n)
    .sort((a, b) => b.n - a.n).slice(0, CONFIG.inBooks);
  if (books.length < 2) return '';
  return `<div class="inbooks" role="group" aria-label="Matches by book"><span class="ib-label">In</span>${books.map(({ b, n }) =>
    `<button type="button" class="ib" data-book-q="${b.id}" style="--c:var(--${b.section})" title="${esc(b.name)}: just these matches">${esc(b.name)}<span class="n">${n}</span></button>`).join('')}</div>`;
}

function renderResults(mode, hits, stats) {
  const panel = $('#results');
  if (mode.kind === 'none') { panel.hidden = true; return; }
  if (state.shownFor !== mode.n) { state.shownFor = mode.n; state.shown = CONFIG.maxResults; }
  const q = state.query.trim();
  const heading = mode.kind === 'text' ? `Sermons matching “${esc(q)}”`
    : mode.kind === 'ref' ? `Sermons on ${esc(mode.book.name)} ${mode.chapter}`
    : `Sermons on ${esc(mode.book.name)}`;
  const goto = gotoRows(mode, hits);
  let body;
  if (!hits.length) {
    body = `<div class="empty-state"><strong>No sermons match “${esc(q)}”.</strong>${state.churchFilter.size || state.testament !== 'all'
      ? 'Try clearing the church or testament filter.' : 'Try a book name, a speaker, or a topic like “faith”.'}</div>`;
  } else {
    body = `
      ${mode.kind === 'text' ? inBooksRow(stats) : ''}
      <ul class="sermons cols">${hits.slice(0, state.shown).map((s) => sermonCard(s, mode.kind === 'text' ? noteExcerpt(s, mode.n) : '')).join('')}</ul>
      ${hits.length > state.shown ? `<button type="button" class="more-btn" data-more>Show ${Math.min(CONFIG.maxResults * 2, hits.length - state.shown)} more <span class="muted">· ${state.shown} of ${hits.length}</span></button>` : ''}`;
  }
  panel.hidden = false;
  panel.innerHTML = `
    ${goto}
    <div class="panel-head"><h2>${heading}</h2>${filterChips()}<span class="muted ph-count">${hits.length.toLocaleString('en-US')}</span></div>
    ${hits.length ? studyNote(hits.slice(0, state.shown)) : ''}
    ${body}`;
}

function renderRecent(sermons) {
  const panel = $('#recent');
  if (state.query.trim() || !sermons.length) { panel.hidden = true; return; }
  const recent = [...sermons].sort(byDateDesc).slice(0, CONFIG.recentCount);
  panel.hidden = false;
  panel.innerHTML = `
    <div class="panel-head"><h2>Latest sermons</h2>${filterChips()}</div>
    ${studyNote(recent)}
    <ul class="sermons cols scroller">${recent.map((s) => sermonCard(s)).join('')}</ul>`;
}

function render() {
  const sermons = visibleSermons();
  const mode = searchMode();
  const hits = mode.kind === 'none' ? [] : findHits(sermons, mode);
  const stats = bookStats(mode.kind === 'text' ? hits : sermons);
  document.body.classList.toggle('searching-text', mode.kind === 'text');
  renderStats(sermons, stats, mode, hits);
  renderResults(mode, hits, stats);
  renderRecent(sermons);
  renderLibrary(stats, mode);
  renderHint(mode);
  if (state.open) renderDrawer();
  markOpen();
}

/** Wide screens: highlight the card or book tile whose page is open beside the list. */
function markOpen() {
  document.querySelectorAll('main .is-open').forEach((el) => el.classList.remove('is-open'));
  const o = state.open;
  if (!o) return;
  if (o.kind === 'sermon') document.querySelectorAll(`main [data-card="${CSS.escape(o.sermonId)}"]`).forEach((el) => el.classList.add('is-open'));
  if (o.kind === 'book') document.querySelector(`main .tile[data-book="${o.bookId}"]`)?.classList.add('is-open');
}

/* ============================================================
   Panel: book, sermon, series and speaker pages.
   Rule: the main column is for finding; the panel is for going deeper.
   Nothing in the panel sends you back to the main column - links inside it
   open the next page in the panel, and Back walks back through them.
   ============================================================ */
function renderDrawer() {
  const drawer = $('#drawer');
  const { kind } = state.open;
  drawer.classList.toggle('is-sermon', kind !== 'book');
  $('#d-book').hidden = kind !== 'book';
  $('#d-sermon').hidden = kind !== 'sermon';
  $('#d-group').hidden = kind !== 'series' && kind !== 'speaker';
  $('#d-back').hidden = !backTarget();
  $('#d-share').hidden = kind !== 'book';
  $('#d-bp').hidden = true;
  $('#d-filters').innerHTML = '';
  if (kind === 'sermon') return renderSermon(state.sermonById.get(state.open.sermonId));
  if (kind === 'book') return renderBook();
  renderGroup(kind, state.open.id);
}

function renderBook() {
  const { bookId, chapter } = state.open;
  const book = state.bookById.get(bookId);
  const section = state.sectionById.get(book.section);
  const drawer = $('#drawer');
  drawer.style.setProperty('--c', `var(--${book.section})`);

  const onBook = churchSermons().filter((s) => s.refs.some((r) => r.book === bookId));
  // Opened from a text search: only that search's matches, until "Show all" clears it
  const bq = state.bookQuery?.bookId === bookId ? state.bookQuery.q : null;
  const all = bq ? searchSermons(onBook, norm(bq)) : onBook;
  const chaptersWith = new Set();
  all.forEach((s) => s.refs.forEach((r) => {
    if (r.book === bookId && r.start != null) for (let c = r.start; c <= r.end; c++) chaptersWith.add(c);
  }));

  $('#d-section').textContent = `${section.testament === 'OT' ? 'Old' : 'New'} Testament · ${section.name}`;
  $('#d-title').textContent = book.name;
  $('#d-meta').textContent = `${plural(book.chapters, 'chapter')} · ${plural(onBook.length, 'sermon')}`;
  $('#d-filters').innerHTML = filterChips({ testament: false });
  const bp = $('#d-bp');
  bp.hidden = !book.bibleproject;
  if (book.bibleproject) {
    bp.href = book.bibleproject;
    bp.setAttribute('aria-label', `BibleProject guide to ${book.name} (opens in a new tab)`);
  }

  const qbar = $('#d-qbar');
  qbar.hidden = !bq;
  if (bq) {
    qbar.innerHTML = `<span class="qb-text">Showing <strong>${all.length}</strong> of ${onBook.length} that match “${esc(bq)}”</span>
      <button type="button" class="chip" data-clear-bq>Show all ${onBook.length}</button>`;
  }

  let btns = `<button class="all" data-ch="" aria-pressed="${chapter == null}">All</button>`;
  for (let c = 1; c <= book.chapters; c++) {
    const has = chaptersWith.has(c);
    btns += `<button data-ch="${c}" class="${has ? 'has' : ''}" aria-pressed="${chapter === c}" ${has ? '' : 'disabled'}
      aria-label="Chapter ${c}${has ? '' : bq ? ', no matches' : ', no sermons'}">${c}</button>`;
  }
  $('#d-chapters').innerHTML = btns;
  const sel = $('#d-chapters [aria-pressed="true"]');
  if (sel && chapter != null) sel.scrollIntoView({ block: 'nearest', inline: 'center' });

  const inChapter = chapter == null
    ? all
    : all.filter((s) => s.refs.some((r) => r.book === bookId && r.start != null && chapter >= r.start && chapter <= r.end));

  // "Book studies only": hidden when nothing here is a study, so it never empties the list by itself.
  const studies = inChapter.filter((s) => isStudy(s, bookId)).length;
  const fit = $('#d-fit');
  fit.hidden = !studies || studies === inChapter.length;
  const filtering = state.studyOnly && !fit.hidden;
  $('#d-study').setAttribute('aria-pressed', String(filtering));
  $('#d-study .n').textContent = `${studies} of ${inChapter.length}`;
  const list = filtering ? inChapter.filter((s) => isStudy(s, bookId)) : inChapter;

  $('#d-list-label').textContent = chapter == null ? 'Sermons' : `Sermons on chapter ${chapter}`;

  if (!list.length) {
    const suggest = CONFIG.suggestUrl ? ` <a href="${esc(CONFIG.suggestUrl)}" target="_blank" rel="noopener">Suggest one</a>.` : '';
    const churchNote = state.churchFilter.size ? ' with the current church filter' : '';
    $('#d-list').innerHTML = bq
      ? `<li class="empty-state"><strong>Nothing in ${chapter ? `chapter ${chapter}` : esc(book.name)} matches “${esc(bq)}”.</strong></li>`
      : `<li class="empty-state"><strong>No sermons yet${churchNote}.</strong>Heard a good one on ${esc(book.name)}?${suggest}</li>`;
    return;
  }

  // Group: whole-book overviews first, then by starting chapter, newest first within a chapter.
  const startOf = (s) => {
    const r = s.refs.find((x) => x.book === bookId);
    return r.start ?? 0;
  };
  // Within a chapter, sermons that study the passage come first.
  const studyRank = (s) => (isStudy(s, bookId) ? 0 : 1);
  const sorted = [...list].sort((a, b) => startOf(a) - startOf(b) || studyRank(a) - studyRank(b) || byDateDesc(a, b));
  let html = '';
  let current = null;
  for (const s of sorted) {
    const st = startOf(s);
    if (chapter == null && st !== current) {
      current = st;
      html += `<li class="group-label">${st === 0 ? 'Whole book' : `Chapter ${st}`}</li>`;
    }
    html += sermonCard(s, bq ? noteExcerpt(s, norm(bq)) : '', { bookId, hideStudy: filtering });
  }
  $('#d-list').innerHTML = html;
}

/** Series page (in order, oldest first) or speaker page (newest first, paged). */
function renderGroup(kind, id) {
  const g = groupOf(kind, id);
  const isSeries = kind === 'series';
  $('#drawer').style.setProperty('--c', g.color);

  const dates = g.sermons.map((s) => s.dateObj).filter(Boolean).sort((a, b) => a - b);
  const month = (d) => d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  const span = dates.length ? (month(dates[0]) === month(dates.at(-1)) ? month(dates[0]) : `${month(dates[0])} – ${month(dates.at(-1))}`) : '';
  const churches = [...new Set(g.sermons.map((s) => s.church))].map((c) => state.churches.get(c)).filter(Boolean);
  $('#d-section').innerHTML = `<span class="dot" style="--cc:${esc(g.color)}"></span>${isSeries ? 'Series' : 'Speaker'} · ${churches.map((c) => esc(c.short || c.name)).join(', ')}`;
  $('#d-title').textContent = g.name;

  // A series is one church's, so it always shows whole; a speaker follows the church filter like a book does.
  const visible = new Set(churchSermons());
  const pool = isSeries ? g.sermons : g.sermons.filter((s) => visible.has(s));
  $('#d-meta').textContent = [plural(pool.length, isSeries ? 'message' : 'sermon'), span].filter(Boolean).join(' · ');
  $('#d-filters').innerHTML = isSeries ? '' : filterChips({ testament: false });

  const box = $('#d-group');
  if (!pool.length) {
    box.innerHTML = `<div class="empty-state"><strong>None with the current church filter.</strong>Tap “All churches” to see them.</div>`;
    return;
  }
  const sorted = [...pool].sort(isSeries ? seriesOrder : byDateDesc);
  const shown = isSeries ? sorted : sorted.slice(0, state.speakerShown || CONFIG.speakerPage);
  const opts = isSeries ? { seriesId: id, here: state.lastSermonId } : { speakerId: id };
  box.innerHTML = `
    <ol class="sermons${isSeries ? ' numbered' : ''}">${shown.map((s) => sermonCard(s, '', opts)).join('')}</ol>
    ${shown.length < sorted.length ? `<button type="button" class="more-btn" data-more-panel>Show ${Math.min(CONFIG.speakerPage, sorted.length - shown.length)} more <span class="muted">· ${shown.length} of ${sorted.length}</span></button>` : ''}`;
}

/* ============================================================
   Sermon page
   ============================================================ */
let notesPromise = null;
function loadNotes() {
  notesPromise ||= getJSON(CONFIG.notesUrl).catch((err) => { console.warn(err); notesPromise = null; return {}; });
  return notesPromise;
}

/** Series order: by date; year-only sermons (Keller) by year, then by the site's post number. */
function seriesOrder(a, b) {
  const t = (x) => x.dateObj?.getTime() ?? (x.year ? Date.UTC(x.year, 0, 1) : 0);
  const n = (x) => Number(String(x.id).match(/(\d+)$/)?.[1] ?? 0);
  return t(a) - t(b) || n(a) - n(b);
}

/** One compact row in the sermon page's series list; the open sermon is marked, not linked. */
function seriesRow(t, i, current) {
  const when = t.dateObj ? fmtDate(t.dateObj) : t.year || '';
  const sub = [refLabel(t), t.speaker !== current.speaker && t.speaker, when].filter(Boolean).map(esc).join(' · ');
  const inner = `<span class="n">${i + 1}</span><span class="t">${esc(t.title)}<small>${sub}</small></span>`;
  return t === current
    ? `<li><div class="s-row current" aria-current="page">${inner}<span class="here">Viewing</span></div></li>`
    : `<li><a class="s-row" href="#/sermon/${esc(t.id)}" data-sermon="${esc(t.id)}">${inner}</a></li>`;
}

function renderSermon(s) {
  const drawer = $('#drawer');
  drawer.style.setProperty('--c', s.churchObj.color);
  $('#d-section').innerHTML = `<span class="dot" style="--cc:${esc(s.churchObj.color)}"></span>${esc(s.churchObj.name)}`;
  $('#d-title').textContent = s.title;
  $('#d-meta').textContent = [
    s.dateObj ? fmtDate(s.dateObj) : s.year,
    s.durationMin && `${Math.round(s.durationMin)} min`,
  ].filter(Boolean).join(' · ');

  // Big buttons: the service this viewer last used goes first
  const pref = getPref();
  const links = listenLinks(s).sort((a, b) => (b.kind === pref) - (a.kind === pref));
  const buttons = links.map((l, i) => `
    <a class="listen-btn ${l.kind}${i === 0 ? ' primary' : ''}" ${listenAttrs(l)}>
      ${ICON[l.kind]}<span class="lb-text"><small>${l.kind === 'audio' ? 'Play the' : 'Listen on'}</small>${esc(l.name)}</span>
    </a>`).join('');

  const bookNames = new Set(s.refs.map((r) => norm(state.bookById.get(r.book).name)));
  const seriesName = s.series && !bookNames.has(norm(s.series)) ? s.series : '';
  const group = s._seriesId ? state.series.get(s._seriesId) : null;
  // The whole series is listed further down this page, so the name here is plain text, not a link.
  const facts = [
    ['Passage', `<span class="pass">${refPills(s)}${s.study?.length
      ? `<span class="study-mark" title="Teaches this passage in context, not a topical sermon that cites it">Study</span>` : ''}</span>`],
    s.speaker && ['Speaker', speakerHtml(s)],
    seriesName && ['Series', `<span class="series">${esc(group?.name || seriesName)}</span>`],
    s.tags?.length && ['Topics', `<span class="tags">${s.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</span>`],
  ].filter(Boolean).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('');

  let seriesHtml = '';
  if (group) {
    const inOrder = [...group.sermons].sort(seriesOrder);
    const i = inOrder.indexOf(s);
    seriesHtml = `
      <section class="s-block">
        <h3 class="label">This series</h3>
        <p class="s-sub"><span class="series">${esc(group.name)}</span> · message ${i + 1} of ${inOrder.length}</p>
        <ol class="series-list">${inOrder.map((t, j) => seriesRow(t, j, s)).join('')}</ol>
      </section>`;
  }

  $('#d-sermon').innerHTML = `
    <div class="listen-btns">${buttons}</div>
    <dl class="facts">${facts}</dl>
    <section id="d-notes" class="s-block notes" hidden></section>
    ${seriesHtml}`;

  loadNotes().then((notes) => {
    if (state.open?.sermonId !== s.id) return;
    const text = notes[s.id];
    const box = $('#d-notes');
    if (!box || !text) return;
    box.innerHTML = `<h3 class="label">About this sermon</h3><p>${esc(text)}</p>`;
    box.hidden = false;
  });
}

/* ---------- Opening, closing, Back ---------- */
const panelKey = (o) => (o.kind === 'book' ? `book:${o.bookId}/${o.chapter ?? ''}` : o.kind === 'sermon' ? `sermon:${o.sermonId}` : `${o.kind}:${o.id}`);

/** Show a page in the panel, keeping each page's scroll position for when Back returns to it. */
function showPanel(next) {
  const prev = state.open;
  const body = $('.drawer-body');
  if (prev) state.panelScroll.set(panelKey(prev), body.scrollTop);
  if (next.kind === 'sermon') state.lastSermonId = next.sermonId;
  if (next.kind === 'speaker' && (prev?.kind !== 'speaker' || prev.id !== next.id)) state.speakerShown = 0;
  state.open = next;
  renderDrawer();
  const sameBook = prev?.kind === 'book' && next.kind === 'book' && prev.bookId === next.bookId;
  const saved = state.panelScroll.get(panelKey(next));
  if (!sameBook) body.scrollTop = saved ?? 0;
  // A series page opened from one of its sermons starts with that sermon in view
  const here = next.kind === 'series' && saved == null && $('#d-group .is-here');
  if (here) body.scrollTop += here.getBoundingClientRect().top - body.getBoundingClientRect().top - body.clientHeight / 3;
  if (!prev) openPanel();
  markOpen();
}

function openPanel() {
  state.lastFocus = document.activeElement;
  $('#drawer').hidden = false;
  applyPanelMode();
  // Keyboard users land on Close; on phones, focus the sheet itself so no focus ring flashes.
  if (isTouch) $('#drawer').focus({ preventScroll: true });
  else $('#d-close').focus({ preventScroll: true });
}

/** Phones and narrow windows: a modal sheet over the page. Wide screens: a pane beside it. */
function applyPanelMode() {
  const open = !!state.open;
  const modal = isModal();
  document.body.classList.toggle('panel-open', open && !modal);
  document.body.classList.toggle('locked', modal);
  $('#scrim').hidden = !modal;
  $('#drawer').setAttribute('aria-modal', String(modal));
}

function closePanel(restoreFocus = true) {
  if (!state.open) return;
  const bookId = state.open.bookId;
  state.open = null;
  state.bookQuery = null;
  state.lastSermonId = null;
  state.panelScroll.clear();
  $('#drawer').hidden = true;
  applyPanelMode();
  markOpen();
  if (!restoreFocus) return;
  const tile = bookId && document.querySelector(`.tile[data-book="${bookId}"]`);
  (tile || state.lastFocus)?.focus?.({ preventScroll: true });
}

/* ============================================================
   Routing: #/john, #/john/3, #/sermon/<id>, #/series/<id>, #/speaker/<id>
   (shareable links for group texts)
   ============================================================ */
/** In-app navigation. history.state.app counts entries made inside the site; history.state.panel
 *  says the entry before this one was a panel page, so Back can step back to it. */
function nav(hash, { replace = false } = {}) {
  const url = hash || location.pathname + location.search;
  if (replace) history.replaceState(history.state, '', url);
  else if (location.hash !== hash) history.pushState({ app: (history.state?.app || 0) + 1, panel: !!state.open }, '', url);
  route();
}

function go(bookId, chapter, { keepQuery = false } = {}) {
  if (!keepQuery) state.bookQuery = null;
  nav(bookId ? `#/${bookId}${chapter ? `/${chapter}` : ''}` : '');
}

/** A book opened from a text search shows only that search's matches. */
function goBookFromSearch(bookId) {
  const mode = searchMode();
  state.bookQuery = mode.kind === 'text' ? { bookId, q: state.query.trim() } : null;
  go(bookId, null, { keepQuery: true });
}

const openGroup = (kind, id) => nav(`#/${kind}/${id}`);

/** Where the panel's Back button goes, or null to hide it. */
function backTarget() {
  if (history.state?.panel) return 'history';
  // Opened straight from a shared sermon link: Back goes to that passage
  if (state.open?.kind === 'sermon' && !history.state?.app) return 'passage';
  return null;
}

function back() {
  const t = backTarget();
  if (t === 'history') { history.back(); return; }
  const r = state.sermonById.get(state.open?.sermonId)?.refs[0];
  if (r) nav(`#/${r.book}${r.start ? `/${r.start}` : ''}`, { replace: true });
}

function parseHash() {
  const h = location.hash;
  let m = h.match(/^#\/sermon\/([A-Za-z0-9_-]+)$/);
  if (m && state.sermonById.has(m[1])) return { kind: 'sermon', sermonId: m[1] };
  m = h.match(/^#\/(series|speaker)\/([a-z0-9-]+)$/);
  if (m && groupOf(m[1], m[2])) return { kind: m[1], id: m[2] };
  m = h.match(/^#\/([a-z0-9-]+)(?:\/(\d+))?$/);
  if (m && state.bookById.has(m[1])) {
    const book = state.bookById.get(m[1]);
    return { kind: 'book', bookId: m[1], chapter: m[2] ? Math.min(Number(m[2]), book.chapters) : null };
  }
  return null;
}

function route() {
  const next = parseHash();
  if (next) showPanel(next);
  else closePanel();
}

/* ============================================================
   Events
   ============================================================ */
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 1800);
}

function bind() {
  const input = $('#q');
  let timer;
  const clearBtn = $('#q-clear');
  const syncClear = () => {
    clearBtn.hidden = !input.value;
    $('.search').classList.toggle('has-value', !!input.value);
  };
  const clearSearch = () => {
    clearTimeout(timer);
    input.value = ''; state.query = ''; syncClear(); render();
  };
  clearBtn.addEventListener('click', () => {
    clearSearch();
    input.focus(); // keep the keyboard up so you can type the next search
  });
  input.addEventListener('input', () => {
    syncClear();
    if (!state.notes) loadNotes().then(attachNotes);
    clearTimeout(timer);
    timer = setTimeout(() => { state.query = input.value; render(); revealResults(); }, 80);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      // Without this, the Enter that opens the panel also "clicks" its Close button once focus lands there
      e.preventDefault();
      clearTimeout(timer);
      state.query = input.value;
      const mode = searchMode();
      const book = searchBook(mode);
      const groups = mode.kind === 'text' ? groupSuggestions(mode.n) : [];
      if (mode.kind === 'ref') go(mode.book.id, mode.chapter);
      else if (book) go(book.id);
      else if (groups.length === 1) openGroup(groups[0].kind, groups[0].id);
      else { render(); input.blur(); } // dismiss the phone keyboard so results are visible
    } else if (e.key === 'Escape' && input.value) {
      e.preventDefault(); // handled: don't also close the panel
      clearSearch();
    }
  });

  // Delegated clicks anywhere on the page (cards live in the main column and the panel)
  document.addEventListener('click', (e) => {
    const l = e.target.closest('[data-listen]');
    if (l) { if (l.dataset.listen === 'spotify' || l.dataset.listen === 'apple') setPref(l.dataset.listen); return; }
    const sm = e.target.closest('a[data-sermon]');
    if (sm) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button) return; // new tab/window: let the link work
      e.preventDefault();
      nav(`#/sermon/${sm.dataset.sermon}`);
      return;
    }
    const g = e.target.closest('[data-goto]');
    if (g) {
      const [id, ch] = g.dataset.goto.split('/');
      go(id, ch ? Number(ch) : null);
      return;
    }
    const bq = e.target.closest('[data-book-q]');
    if (bq) { goBookFromSearch(bq.dataset.bookQ); return; }
    if (e.target.closest('[data-more]')) {
      state.shown += CONFIG.maxResults * 2;
      const mode = searchMode();
      const sermons = visibleSermons();
      const hits = findHits(sermons, mode);
      renderResults(mode, hits, bookStats(mode.kind === 'text' ? hits : sermons));
      markOpen();
      return;
    }
    if (e.target.closest('[data-more-panel]')) {
      state.speakerShown = (state.speakerShown || CONFIG.speakerPage) + CONFIG.speakerPage;
      renderDrawer();
      return;
    }
    const cf = e.target.closest('[data-clear-filter]');
    if (cf) {
      const [what, id] = cf.dataset.clearFilter.split(':');
      if (what === 'testament') {
        state.testament = 'all';
        document.querySelectorAll('.seg button').forEach((x) => x.setAttribute('aria-checked', String(x.dataset.t === 'all')));
      } else {
        state.churchFilter.delete(id);
        renderChurchChips();
      }
      render();
      return;
    }
    if (e.target.closest('[data-dismiss-study]')) {
      studyNoteSeen = true;
      try { localStorage.setItem(STUDY_NOTE_KEY, '1'); } catch { /* private mode */ }
      document.querySelectorAll('.study-note').forEach((el) => el.remove());
      return;
    }
    if (e.target.closest('[data-clear-bq]')) {
      state.bookQuery = null;
      renderBook();
      return;
    }
    const gr = e.target.closest('[data-group]');
    if (gr) {
      const [kind, id] = gr.dataset.group.split(':');
      openGroup(kind, id);
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented) return;
    if (e.key === '/' && document.activeElement !== input && !isModal()) {
      e.preventDefault(); input.focus();
    } else if (e.key === 'Escape' && state.open) {
      go(null);
    } else if (e.key === 'Tab' && isModal()) {
      // keep focus inside the sheet while it covers the page
      const focusables = [...$('#drawer').querySelectorAll('button:not([disabled]), a[href]')].filter((el) => el.offsetParent);
      const first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });

  $('#library').addEventListener('click', (e) => {
    const tile = e.target.closest('.tile');
    if (tile) goBookFromSearch(tile.dataset.book);
  });

  $('.seg').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-t]');
    if (!b) return;
    state.testament = b.dataset.t;
    document.querySelectorAll('.seg button').forEach((x) => x.setAttribute('aria-checked', String(x === b)));
    render();
  });

  $('#churches').addEventListener('click', (e) => {
    const b = e.target.closest('.chip');
    if (!b) return;
    const id = b.dataset.church;
    if (!id) state.churchFilter.clear();
    else if (state.churchFilter.has(id)) state.churchFilter.delete(id);
    else state.churchFilter.add(id);
    if (state.churchFilter.size === state.churches.size) state.churchFilter.clear();
    renderChurchChips();
    render();
  });

  $('#d-study').addEventListener('click', () => {
    setStudyOnly(!state.studyOnly);
    renderBook();
  });

  $('#d-chapters').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-ch]');
    if (!b || b.disabled) return;
    const ch = b.dataset.ch ? Number(b.dataset.ch) : null;
    const { bookId, chapter } = state.open;
    const next = ch === chapter ? null : ch;
    // Switching chapters swaps the list in place rather than stacking up Back steps
    nav(`#/${bookId}${next ? `/${next}` : ''}`, { replace: true });
  });

  $('#d-close').addEventListener('click', () => go(null));
  $('#d-back').addEventListener('click', back);
  $('#scrim').addEventListener('click', () => go(null));
  $('#d-share').addEventListener('click', async () => {
    // Phones: native share sheet (Messages, WhatsApp...). Desktop: copy to clipboard.
    if (isTouch && navigator.share) {
      const { bookId, chapter } = state.open;
      if (!bookId) return;
      const name = state.bookById.get(bookId).name + (chapter ? ` ${chapter}` : '');
      try { await navigator.share({ title: `${name} sermons`, url: location.href }); } catch { /* dismissed */ }
      return;
    }
    try {
      await navigator.clipboard.writeText(location.href);
      toast('Link copied');
    } catch {
      toast(location.href);
    }
  });

  bindSheetSwipe();

  $('#jump').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-jump]');
    if (b) jumpTo(b.dataset.jump);
  });
  let spyFrame = 0;
  window.addEventListener('scroll', () => {
    if (spyFrame) return;
    spyFrame = requestAnimationFrame(() => { spyFrame = 0; spy(); });
  }, { passive: true });
  const unpin = () => { if (spy.pinned) { spy.pinned = null; spy(); } };
  ['wheel', 'touchstart', 'keydown'].forEach((ev) => window.addEventListener(ev, (e) => {
    if (ev === 'touchstart' && e.target.closest('#jump')) return; // tapping another chip
    unpin();
  }, { passive: true }));
  // Sections land just below the sticky bar, whatever its current height
  new ResizeObserver(([entry]) => {
    document.documentElement.style.setProperty('--bar-h', `${Math.round(entry.target.getBoundingClientRect().height)}px`);
  }).observe($('.toolbar'));

  // Resizing across the wide breakpoint switches the open panel between sheet and side pane
  wide.addEventListener('change', applyPanelMode);
  window.addEventListener('hashchange', route);
}

/** If the user typed while scrolled down the book list, jump back up so results are visible. */
function revealResults() {
  const main = $('main');
  const bar = $('.toolbar').getBoundingClientRect().height;
  const top = main.getBoundingClientRect().top + window.scrollY - bar;
  if (window.scrollY > top + 4) window.scrollTo({ top, behavior: 'instant' });
}

/** Phones: drag the sheet's header down to dismiss it. */
function bindSheetSwipe() {
  const drawer = $('#drawer');
  const head = $('.drawer-head');
  let y0 = null, dy = 0;
  head.addEventListener('touchstart', (e) => {
    if (!matchMedia('(max-width: 720px)').matches || e.target.closest('button, a')) return;
    y0 = e.touches[0].clientY; dy = 0;
    drawer.style.transition = 'none';
  }, { passive: true });
  head.addEventListener('touchmove', (e) => {
    if (y0 == null) return;
    dy = Math.max(0, e.touches[0].clientY - y0);
    drawer.style.transform = `translateY(${dy}px)`;
  }, { passive: true });
  const end = () => {
    if (y0 == null) return;
    y0 = null;
    drawer.style.transition = 'transform .18s ease';
    if (dy > 90) {
      drawer.style.transform = 'translateY(100%)';
      setTimeout(() => { go(null); drawer.style.transform = ''; drawer.style.transition = ''; }, 170);
    } else {
      drawer.style.transform = '';
    }
  };
  head.addEventListener('touchend', end);
  head.addEventListener('touchcancel', end);
}

/* ============================================================
   Boot
   ============================================================ */
(async function init() {
  if (CONFIG.suggestUrl) {
    const a = $('#suggest');
    a.href = CONFIG.suggestUrl;
    a.hidden = false;
  }
  try {
    await load();
  } catch (err) {
    console.error(err);
    const e = $('#error');
    e.hidden = false;
    e.innerHTML = location.protocol === 'file:'
      ? 'The data files can’t load when the page is opened directly from disk. Run <code>python3 -m http.server</code> in this folder and open <code>http://localhost:8000</code>.'
      : `Couldn’t load sermon data (${esc(err.message)}).`;
    return;
  }
  renderChurchChips();
  bind();
  render();
  route();
  // Warm the show notes once the page is idle so the first sermon page opens with them
  (window.requestIdleCallback || ((f) => setTimeout(f, 2000)))(() => loadNotes().then(attachNotes));
})();
