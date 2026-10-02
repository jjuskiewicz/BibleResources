'use strict';

/* ============================================================
   Config - edit these
   ============================================================ */
const CONFIG = {
  booksUrl: 'data/books.json',
  churchesUrl: 'data/churches.json',
  sermonsUrl: 'data/sermons.json',
  // e.g. 'https://github.com/<you>/<repo>/issues/new?template=sermon.md'  (null hides the link)
  suggestUrl: null,
  recentCount: 6,
  maxResults: 24,
};

// Short labels for the jump-to-section row on phones (full names show on wider screens)
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
  books: [],
  bookById: new Map(),
  churches: new Map(),
  sermons: [],
  testament: 'all',
  churchFilter: new Set(), // empty = all
  query: '',
  open: null,              // { bookId, chapter }
  lastFocus: null,
};

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : /(ch|sh|s|x)$/.test(word) ? 'es' : 's'}`;

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
  state.books = bookData.books.map((b) => ({ ...b, _keys: bookKeys(b) }));
  state.bookById = new Map(state.books.map((b) => [b.id, b]));

  churches.forEach((c, i) => {
    state.churches.set(c.id, { ...c, color: c.color || FALLBACK_CHURCH_COLORS[i % FALLBACK_CHURCH_COLORS.length] });
  });

  const raw = Array.isArray(sermonData) ? sermonData : sermonData.sermons || [];
  state.sermons = raw.map(normalizeSermon).filter(Boolean);
}

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
    _hay: norm([s.title, s.speaker, s.series, s.passage, church?.name, ...(s.tags || [])].join(' ')),
  };
}

/* ============================================================
   Derived data
   ============================================================ */
function visibleSermons() {
  if (!state.churchFilter.size) return state.sermons;
  return state.sermons.filter((s) => state.churchFilter.has(s.church));
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
const THIS_YEAR = new Date().getFullYear();
/** Compact date for cards: "Sep 30" this year, "Mar 2, 2025" otherwise */
const fmtShort = (d) => d ? d.toLocaleDateString('en-US', d.getFullYear() === THIS_YEAR
  ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' }) : '';
/** Full name on wide screens, short name on phones (CSS toggles .long/.short) */
const churchName = (c) => c.short && c.short !== c.name
  ? `<span class="long">${esc(c.name)}</span><span class="short">${esc(c.short)}</span>`
  : esc(c.name);
const isTouch = matchMedia('(hover: none) and (pointer: coarse)').matches;

/* ============================================================
   Rendering
   ============================================================ */
const EXT_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>';

function sermonCard(s) {
  const firstBook = state.bookById.get(s.refs[0].book);
  const color = `var(--${firstBook.section})`;
  // A series named after the book ("John", "Acts") just repeats the passage line, so drop it.
  const bookNames = new Set(s.refs.map((r) => norm(state.bookById.get(r.book).name)));
  const series = s.series && !bookNames.has(norm(s.series)) ? s.series : '';
  const meta = [
    `<span class="who"><span class="dot" style="--cc:${esc(s.churchObj.color)}"></span>${churchName(s.churchObj)}</span>`,
    s.speaker && `<span>${esc(s.speaker)}</span>`,
    s.durationMin && `<span class="dur">${Math.round(s.durationMin)} min</span>`,
    series && `<span class="series">${esc(series)}</span>`,
  ].filter(Boolean).join('');
  const when = s.dateObj ? `<time datetime="${esc(s.date)}" title="${fmtDate(s.dateObj)}">${fmtShort(s.dateObj)}</time>` : '';
  const tags = (s.tags || []).map((t) => `<span class="tag">#${esc(t)}</span>`).join('');
  return `
    <li>
      <a class="sermon" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer" style="--c:${color}" title="Opens ${esc(s.churchObj.name)} in a new tab">
        <span class="ref"><span class="pass">${esc(refLabel(s))}</span>${when}</span>
        <span class="title">${esc(s.title)}</span>
        <span class="meta">${meta}</span>
        ${tags ? `<span class="tags">${tags}</span>` : ''}
        ${EXT_ICON}
      </a>
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

function renderStats(sermons, stats) {
  const covered = [...stats.values()].filter((s) => s.count).length;
  const churches = new Set(sermons.map((s) => s.church)).size;
  $('#stats').innerHTML =
    `<strong>${plural(sermons.length, 'sermon')}</strong> from <strong>${plural(churches, 'church')}</strong>` +
    ` · <strong>${covered}</strong> of 66 books covered`;
}

function renderLibrary(stats) {
  const q = state.query.trim();
  const ref = q ? parseRef(q) : null;
  const matches = q ? new Set((ref ? [ref.book] : matchBooks(q)).map((b) => b.id)) : null;
  const filterBooks = matches && matches.size > 0;

  const html = state.sections
    .filter((sec) => state.testament === 'all' || sec.testament === state.testament)
    .map((sec) => {
      const books = state.books.filter((b) => b.section === sec.id && (!filterBooks || matches.has(b.id)));
      if (!books.length) return '';
      const secCount = books.reduce((n, b) => n + stats.get(b.id).count, 0);
      const tiles = books.map((b) => {
        const st = stats.get(b.id);
        const pct = Math.round((st.chapters.size / b.chapters) * 100);
        const label = `${b.name}, ${plural(b.chapters, 'chapter')}, ${plural(st.count, 'sermon')}`;
        return `
          <button class="tile${st.count ? '' : ' empty'}" data-book="${b.id}" aria-label="${esc(label)}">
            <span class="abbr" aria-hidden="true">${esc(b.abbr)}</span>
            <span class="name" aria-hidden="true">${esc(b.name)}</span>
            <span class="meta" aria-hidden="true">${b.chapters} ch</span>
            <span class="count" aria-hidden="true">${st.count}</span>
            <span class="bar" aria-hidden="true" title="${pct}% of chapters have a sermon"><i style="width:${pct}%"></i></span>
          </button>`;
      }).join('');
      return `
        <section class="section" data-sec="${sec.id}" style="--c:var(--${sec.id})" aria-labelledby="sec-${sec.id}">
          <div class="section-head">
            <h2 id="sec-${sec.id}">${esc(sec.name)}</h2>
            <span>${plural(books.length, 'book')} · ${plural(secCount, 'sermon')}</span>
          </div>
          <div class="grid">${tiles}</div>
        </section>`;
    }).join('');

  $('#library').innerHTML = html || `<div class="empty-state"><strong>No books match.</strong>Try another name.</div>`;
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
    const label = short === sec.name ? esc(sec.name)
      : `<span class="long">${esc(sec.name)}</span><span class="short">${esc(short)}</span>`;
    return `<button type="button" data-jump="${id}" style="--c:var(--${id})" aria-label="${esc(sec.name)}"><span class="dot" style="--cc:var(--${id})"></span>${label}</button>`;
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
  if (active) {
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

const hintBtn = (target, label) =>
  `<span class="long">Press Enter or </span><button type="button" data-open="${target}">Open ${esc(label)} <span aria-hidden="true">→</span></button>`;

function renderHint() {
  const q = state.query.trim();
  const hint = $('#q-hint');
  const ref = q ? parseRef(q) : null;
  if (ref) {
    hint.innerHTML = hintBtn(`${ref.book.id}/${ref.chapter}`, `${ref.book.name} ${ref.chapter}`);
    return;
  }
  const books = q ? matchBooks(q) : [];
  if (books.length === 1) {
    hint.innerHTML = hintBtn(books[0].id, books[0].name);
  } else {
    hint.textContent = '';
  }
}

function renderResults(sermons) {
  const panel = $('#results');
  const q = norm(state.query);
  if (q.length < 2) { panel.hidden = true; return; }

  const ref = parseRef(state.query);
  let hits;
  if (ref) {
    hits = sermons.filter((s) => s.refs.some((r) => r.book === ref.book.id && (r.start == null || (ref.chapter >= r.start && ref.chapter <= r.end))));
  } else {
    const terms = q.split(' ');
    hits = sermons.filter((s) => terms.every((t) => s._hay.includes(t)));
  }
  hits = hits.sort(byDateDesc);

  if (!hits.length) {
    panel.hidden = matchBooks(state.query).length > 0; // book matches are shown in the grid
    panel.innerHTML = `<div class="empty-state"><strong>No sermons match “${esc(state.query)}”.</strong>Try a book name, a speaker, or a topic like “faith”.</div>`;
    return;
  }
  panel.hidden = false;
  panel.innerHTML = `
    <div class="panel-head"><h2>Sermons matching “${esc(state.query)}”</h2><span class="muted">${hits.length}</span></div>
    <ul class="sermons cols">${hits.slice(0, CONFIG.maxResults).map((s) => sermonCard(s)).join('')}</ul>`;
}

function renderRecent(sermons) {
  const panel = $('#recent');
  if (state.query.trim() || !sermons.length) { panel.hidden = true; return; }
  const recent = [...sermons].sort(byDateDesc).slice(0, CONFIG.recentCount);
  panel.hidden = false;
  panel.innerHTML = `
    <div class="panel-head"><h2>Recently added</h2></div>
    <ul class="sermons cols scroller">${recent.map((s) => sermonCard(s)).join('')}</ul>`;
}

function render() {
  const sermons = visibleSermons();
  const stats = bookStats(sermons);
  renderStats(sermons, stats);
  renderResults(sermons);
  renderRecent(sermons);
  renderLibrary(stats);
  renderHint();
  if (state.open) renderDrawer();
}

/* ============================================================
   Drawer (book detail)
   ============================================================ */
function renderDrawer() {
  const { bookId, chapter } = state.open;
  const book = state.bookById.get(bookId);
  const section = state.sections.find((s) => s.id === book.section);
  const drawer = $('#drawer');
  drawer.style.setProperty('--c', `var(--${book.section})`);

  const all = visibleSermons().filter((s) => s.refs.some((r) => r.book === bookId));
  const chaptersWith = new Set();
  all.forEach((s) => s.refs.forEach((r) => {
    if (r.book === bookId && r.start != null) for (let c = r.start; c <= r.end; c++) chaptersWith.add(c);
  }));

  $('#d-section').textContent = `${section.testament === 'OT' ? 'Old' : 'New'} Testament · ${section.name}`;
  $('#d-title').textContent = book.name;
  $('#d-meta').textContent = `${plural(book.chapters, 'chapter')} · ${plural(all.length, 'sermon')}`;

  let btns = `<button class="all" data-ch="" aria-pressed="${chapter == null}">All</button>`;
  for (let c = 1; c <= book.chapters; c++) {
    const has = chaptersWith.has(c);
    btns += `<button data-ch="${c}" class="${has ? 'has' : ''}" aria-pressed="${chapter === c}" ${has ? '' : 'disabled'}
      aria-label="Chapter ${c}${has ? '' : ', no sermons'}">${c}</button>`;
  }
  $('#d-chapters').innerHTML = btns;
  const sel = $('#d-chapters [aria-pressed="true"]');
  if (sel && chapter != null) sel.scrollIntoView({ block: 'nearest', inline: 'center' });

  const list = chapter == null
    ? all
    : all.filter((s) => s.refs.some((r) => r.book === bookId && r.start != null && chapter >= r.start && chapter <= r.end));

  $('#d-list-label').textContent = chapter == null ? 'Sermons' : `Sermons on chapter ${chapter}`;

  if (!list.length) {
    const suggest = CONFIG.suggestUrl ? ` <a href="${esc(CONFIG.suggestUrl)}" target="_blank" rel="noopener">Suggest one</a>.` : '';
    const churchNote = state.churchFilter.size ? ' with the current church filter' : '';
    $('#d-list').innerHTML = `<li class="empty-state"><strong>No sermons yet${churchNote}.</strong>Heard a good one on ${esc(book.name)}?${suggest}</li>`;
    return;
  }

  // Group: whole-book overviews first, then by starting chapter, newest first within a chapter.
  const startOf = (s) => {
    const r = s.refs.find((x) => x.book === bookId);
    return r.start ?? 0;
  };
  const sorted = [...list].sort((a, b) => startOf(a) - startOf(b) || byDateDesc(a, b));
  let html = '';
  let current = null;
  for (const s of sorted) {
    const st = startOf(s);
    if (chapter == null && st !== current) {
      current = st;
      html += `<li class="group-label">${st === 0 ? 'Whole book' : `Chapter ${st}`}</li>`;
    }
    html += sermonCard(s);
  }
  $('#d-list').innerHTML = html;
}

function openDrawer(bookId, chapter) {
  const wasOpen = !!state.open;
  state.open = { bookId, chapter: chapter ?? null };
  renderDrawer();
  if (!wasOpen) {
    state.lastFocus = document.activeElement;
    $('#drawer').hidden = false;
    $('#scrim').hidden = false;
    document.body.classList.add('locked');
    // Keyboard users land on Close; on phones, focus the sheet itself so no focus ring flashes.
    if (isTouch) $('#drawer').focus({ preventScroll: true });
    else $('#d-close').focus();
    $('.drawer-body').scrollTop = 0;
  }
}

function closeDrawer() {
  if (!state.open) return;
  const bookId = state.open.bookId;
  state.open = null;
  $('#drawer').hidden = true;
  $('#scrim').hidden = true;
  document.body.classList.remove('locked');
  const tile = document.querySelector(`.tile[data-book="${bookId}"]`);
  (tile || state.lastFocus)?.focus?.();
}

/* ============================================================
   Routing: #/john  or  #/john/3   (shareable links for group texts)
   ============================================================ */
function go(bookId, chapter) {
  const hash = bookId ? `#/${bookId}${chapter ? `/${chapter}` : ''}` : '';
  if (location.hash !== hash) {
    if (hash) location.hash = hash;
    else { history.pushState(null, '', location.pathname + location.search); route(); }
  } else {
    route();
  }
}

function route() {
  const m = location.hash.match(/^#\/([a-z0-9-]+)(?:\/(\d+))?$/);
  if (m && state.bookById.has(m[1])) {
    const book = state.bookById.get(m[1]);
    const ch = m[2] ? Math.min(Number(m[2]), book.chapters) : null;
    openDrawer(m[1], ch);
  } else {
    closeDrawer();
  }
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
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.query = input.value; render(); revealResults(); }, 80);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      state.query = input.value;
      const ref = parseRef(state.query);
      const books = matchBooks(state.query);
      if (ref) go(ref.book.id, ref.chapter);
      else if (books.length === 1) go(books[0].id);
      else input.blur(); // dismiss the phone keyboard so results are visible
    } else if (e.key === 'Escape' && input.value) {
      input.value = ''; state.query = ''; render();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== input && !state.open) {
      e.preventDefault(); input.focus();
    } else if (e.key === 'Escape' && state.open) {
      go(null);
    } else if (e.key === 'Tab' && state.open) {
      // keep focus inside the dialog
      const focusables = [...$('#drawer').querySelectorAll('button:not([disabled]), a[href]')];
      const first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });

  $('#library').addEventListener('click', (e) => {
    const tile = e.target.closest('.tile');
    if (tile) go(tile.dataset.book);
  });

  $('#q-hint').addEventListener('click', (e) => {
    const b = e.target.closest('[data-open]');
    if (!b) return;
    const [id, ch] = b.dataset.open.split('/');
    go(id, ch ? Number(ch) : null);
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

  $('#d-chapters').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-ch]');
    if (!b || b.disabled) return;
    const ch = b.dataset.ch ? Number(b.dataset.ch) : null;
    go(state.open.bookId, ch === state.open.chapter ? null : ch);
  });

  $('#d-close').addEventListener('click', () => go(null));
  $('#scrim').addEventListener('click', () => go(null));
  $('#d-share').addEventListener('click', async () => {
    // Phones: native share sheet (Messages, WhatsApp...). Desktop: copy to clipboard.
    if (isTouch && navigator.share) {
      const { bookId, chapter } = state.open;
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
    if (!matchMedia('(max-width: 720px)').matches || e.target.closest('button')) return;
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
})();
