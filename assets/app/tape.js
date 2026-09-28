/* ----------------------------------------------------------------- tape */

function paintTape() {
  const t = D.totals || {}, s = D.sources || {}, hs = D.health || {};
  // The tape is the ticker: it follows you to Positions, so it carries the two
  // numbers that must be true everywhere and nothing else. It used to carry
  // four - value, P/L in percent, P/L in euros and the IRR - and the Overview's
  // headline band repeated three of them verbatim forty pixels below, at a
  // larger size and with a subtitle. Each figure has one home now: the euro P/L
  // and the annualised return live in the band, where there is room to say what
  // they are measured against.
  $('#t-value').textContent = eur(t.value_eur);
  $('#t-pl').innerHTML = `<b class="${cls(t.pl_pct)}"
    title="Since purchase, against ${eur(t.cost_eur)} of cost">${pct(t.pl_pct)}</b>`;

  const live = s.equity_log_mode === 'live';
  const flags = (D.alerts || []).filter((a) => !a.health).length;
  const stale = s.nordnet_export_age_days > (D.thresholds || {}).csv_stale_days;
  const nCov = (COV.rows || []).length;
  const nMon = nCov - (COV.n_uncovered || 0);
  // Two lines of status, not eight. The header used to carry every fact about
  // the book and wrapped onto a second row whenever the facts grew. What stays
  // visible is what changes how the rest of the page should be read: the price
  // clock, the live state, and - only when it is true - a stale export. The
  // rest is one hover away on the dot. Coverage also stays a visible line: it
  // is raised as a flag, so it is listed under Needs you whenever it is short.
  const facts = [
    `${held.size} held · ${watch.size} watched`,
    `${flags} flag${flags === 1 ? '' : 's'}`,
    nCov ? `${nMon}/${nCov} monitored, ${(COV.pct_uncovered || 0).toFixed(0)}% of value unwatched` : '',
    `CSV ${s.nordnet_export_age_days}d old`,
    `Notion ${live ? 'live' : 'cached'}`,
    s.run_mode === 'refresh' ? `intraday refresh; board last read ${s.last_full_run || ''}` : 'full run',
  ].filter(Boolean);
  $('#t-meta').innerHTML = [
    // The clock the prices were taken at. Without it an afternoon page and a
    // breakfast page are indistinguishable, which is the whole reason the
    // intraday refresh exists.
    `As of <b title="${esc(D.generated || '')}">${esc((D.generated || '').slice(11, 16))}</b>`,
    // The live chip sits BESIDE the render clock and never replaces it. The
    // render clock is the recorded figure - the evidence of when this file was
    // built - and overwriting it with a live time would destroy the only
    // signal that the underlying book is old (CLAUDE.md rule 3).
    liveChip(),
    stale ? `CSV <b class="dn-t">${s.nordnet_export_age_days}d old</b>` : '',
  ].filter(Boolean).map((f) => `<span class="f">${f}</span>`)
   .join('<span class="msep">·</span>');

  // A failed parity check is a health problem, not a console warning. If the
  // JS recompute disagrees with the Python that produced this file, every
  // figure the live layer touches is suspect - and the reader is the one
  // person who needs to know that before acting on one. Nobody has the console
  // open, so a defect that only logs there is a defect nobody ever learns
  // about.
  const problems = (hs.problems || []).slice();
  if (typeof PARITY !== 'undefined' && !PARITY.ok) {
    problems.unshift({level: 'critical', title:
      `recompute disagrees with the build in ${PARITY.n_mismatches} of `
      + `${PARITY.checked} fields (first: ${PARITY.mismatches[0].path})`});
  }
  const st = (typeof DERIVE !== 'undefined') ? DERIVE.stats() : null;
  if (st && (st.coverage_unmatched || st.reporting_unmatched)) {
    // A join that matches nothing leaves the build-time numbers in place and
    // looks identical to one that worked. It said so once by accident; now it
    // says so on purpose.
    problems.unshift({level: 'warning', title:
      `${st.coverage_unmatched + st.reporting_unmatched} rows could not be `
      + `rejoined to a holding and still show build-time figures`});
  }
  // The dot is the worst thing true right now, and its title is everything.
  const dotLevel = problems.some((p) => p.level === 'critical') ? 'critical'
    : (problems.length || stale || (LIVE && LIVE.error && !LIVE.carried)) ? 'warning' : 'good';
  const dot = $('#t-dot');
  if (dot) {
    dot.style.background = LEVEL[dotLevel];
    dot.setAttribute('title', facts.concat(problems.map((p) => p.title)).join('\n'));
  }
  if (problems.length) {
    const worst = problems.some((p) => p.level === 'critical') ? 'critical' : 'warning';
    $('#t-banner').innerHTML =
      `<div class="banner"><span class="dot" style="background:${LEVEL[worst]}"></span>` +
      `<span><b>${esc(hs.headline || '')}</b> ` +
      `<span class="why">${problems.map((p) => esc(p.title)).join(' · ')}</span></span></div>`;
  }
}

