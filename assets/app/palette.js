/* ------------------------------------------------------------ jump palette
 *
 * Built from what is on the page at the moment it opens, not from a list kept
 * alongside it: the names from ROWS (which the live layer rebuilds), the
 * sections from the drawer's own headings. A section added later shows up here
 * without anyone remembering to register it.
 */
const PAL = {items: [], i: 0};

function palAll() {
  const out = [
    {kind: 'View', label: 'Home', sub: 'performance, what needs you, what is next',
      go: () => { sheetOpen(false); setView('home'); }},
    {kind: 'View', label: 'Allocation', sub: 'treemap, concentration, sector and geography',
      go: () => { sheetOpen(false); setView('overview'); }},
    {kind: 'View', label: 'Positions', sub: 'rail, chart and thesis', go: () => {
      sheetOpen(false); setView('positions'); }},
  ];
  for (const n of document.querySelectorAll('#sheetbody h2[data-sec]')) {
    const id = n.getAttribute('data-sec');
    out.push({kind: 'Data', label: n.getAttribute('data-label') || id,
      sub: (n.textContent || '').replace(/\s+/g, ' ').trim(),
      go: () => openSection(id)});
  }
  for (const r of ROWS) {
    out.push({kind: r.isHeld ? 'Holding' : 'Watchlist', label: r.label,
      sub: r.company !== r.label ? r.company : '', level: r.worst,
      hay: r.sym, go: () => jump(r.sym)});
  }
  return out;
}

// Ranked, not just filtered: a ticker that starts with what you typed beats a
// company name that merely contains it, so "ab" finds ABB before Alphabet.
function palFilter(q) {
  q = q.trim().toLowerCase();
  const all = palAll();
  if (!q) return all;
  const scored = [];
  for (const it of all) {
    const l = it.label.toLowerCase(), h = String(it.hay || '').toLowerCase();
    const s = (it.sub || '').toLowerCase();
    const score = l.startsWith(q) || h.startsWith(q) ? 0
      : l.includes(q) || h.includes(q) ? 1 : s.includes(q) ? 2 : -1;
    if (score >= 0) scored.push([score, it]);
  }
  return scored.sort((a, b) => a[0] - b[0]).map((x) => x[1]);
}

function palPaint() {
  const box = $('#pallist');
  if (!box) return;
  box.innerHTML = PAL.items.length
    ? PAL.items.slice(0, 60).map((it, i) => `<button class="palrow" role="option"
        data-i="${i}" aria-selected="${i === PAL.i}"><span class="k">${
        esc(it.kind)}</span>${it.level ? `<span class="dot" style="background:${
        LEVEL[it.level] || 'var(--muted)'}"></span>` : ''}<b>${esc(it.label)}</b>
        <span class="s">${esc(it.sub || '')}</span></button>`).join('')
    : '<div class="palempty">Nothing by that name.</div>';
  const cur = box.querySelector && box.querySelector('[aria-selected="true"]');
  if (cur && cur.scrollIntoView) cur.scrollIntoView({block: 'nearest'});
}

function palOpen(open) {
  const p = $('#pal');
  if (!p) return;
  p.hidden = !open;
  if (!open) return;
  const q = $('#palq');
  if (q) q.value = '';
  PAL.items = palFilter('');
  PAL.i = 0;
  palPaint();
  if (q && q.focus) q.focus();
}
const palIsOpen = () => { const p = $('#pal'); return !!p && !p.hidden; };

function palPick(i) {
  const it = PAL.items[i];
  palOpen(false);
  if (it) it.go();
}

on('#t-jump', 'click', () => palOpen(true));
on('#palq', 'input', (e) => {
  PAL.items = palFilter(e.target.value || '');
  PAL.i = 0;
  palPaint();
});
on('#palq', 'keydown', (e) => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const n = Math.min(PAL.items.length, 60);
    if (n) PAL.i = (PAL.i + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
    palPaint();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    palPick(PAL.i);
  }
});
on('#pallist', 'click', (e) => {
  const b = e.target && e.target.closest && e.target.closest('.palrow');
  if (b) palPick(Number(b.getAttribute('data-i')));
});
// A click on the dimmed backdrop, outside the box, closes it.
on('#pal', 'click', (e) => { if (e.target === e.currentTarget) palOpen(false); });

// The keyboard map. Single keys only act when nothing is being typed into, so
// searching the rail for "D" does not throw the drawer open.
try {
  window.addEventListener('keydown', (e) => {
    const tag = e.target && e.target.tagName;
    const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      palOpen(!palIsOpen());
      return;
    }
    if (e.key === 'Escape') {
      if (palIsOpen()) { e.preventDefault(); palOpen(false); return; }
      if (SHEET) {
        e.preventDefault();
        if (SHEETPUSHED && history.back) history.back(); else sheetOpen(false);
        return;
      }
      if (typing && e.target.blur) e.target.blur();
      return;
    }
    if (typing || e.ctrlKey || e.metaKey || e.altKey || palIsOpen()) return;
    if (e.key === '/') { e.preventDefault(); palOpen(true); return; }
    if (e.key === '1') { sheetOpen(false); setView('home'); return; }
    if (e.key === '2') { sheetOpen(false); setView('positions'); return; }
    if (e.key === '3') { sheetOpen(false); setView('overview'); return; }
    if (e.key === 'd' || e.key === 'D') { sheetOpen(!SHEET); return; }
  });
} catch (e) {}

// Arrow keys walk the rail. It is a terminal; hands should not have to leave
// the keyboard to step through twenty-three names.
try {
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    // Only on Positions: elsewhere the rail is hidden, and stepping it would
    // repaint a surface nobody is looking at.
    if (palIsOpen() || SHEET || state.view !== 'positions') return;
    const rows = visible();
    const i = rows.findIndex((r) => r.sym === state.sym);
    const next = rows[Math.min(rows.length - 1, Math.max(0, i + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (next) { e.preventDefault(); select(next.sym); }
  });
} catch (e) {}

