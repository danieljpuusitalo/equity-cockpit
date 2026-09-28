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
  // Coverage sits on the tape rather than three clicks away because it is the
  // one number that says how much of this page is decoration. A position with
  // no thesis and no target weight cannot be judged by anything here.
  const nCov = (COV.rows || []).length;
  const nMon = nCov - (COV.n_uncovered || 0);
  const covChip = nCov
    ? `<span title="${eur(COV.value_uncovered_eur)} of ${eur(COV.value_total_eur)} sits in
        ${COV.n_uncovered} positions with no thesis (stocks) or no target weight (funds)."
        ><b>${nMon}</b>/${nCov} monitored<span style="color:var(--muted)"> · </span><b
        class="${COV.pct_uncovered > 0 ? 'dn-t' : ''}">${(COV.pct_uncovered || 0).toFixed(0)}%</b>
        of value unwatched</span>`
    : '';
  $('#t-meta').innerHTML = [
    `<b>${held.size}</b> held`,
    `<b>${watch.size}</b> watched`,
    `<b class="${flags ? 'dn-t' : ''}">${flags}</b> flag${flags === 1 ? '' : 's'}`,
    covChip,
    // The clock the prices were taken at. Without it an afternoon page and a
    // breakfast page are indistinguishable, which is the whole reason the
    // intraday refresh exists - and a page that refreshed but does not say so
    // is no more trustworthy than one that did not.
    `Priced <b title="${esc(D.generated || '')}${s.run_mode === 'refresh'
        ? ` · intraday refresh; board last read ${esc(s.last_full_run || '')}`
        : ' · full run'}">${esc((D.generated || '').slice(11, 16))}</b>`,
    // The live chip sits BESIDE the render clock and never replaces it. The
    // render clock is the recorded figure - the evidence of when this file was
    // built - and overwriting it with a live time would destroy the only
    // signal that the underlying book is old (CLAUDE.md rule 3). A page whose
    // prices are two seconds old and whose positions are four days old should
    // say both, not average them into one reassuring number.
    liveChip(),
    `CSV <b class="${stale ? 'dn-t' : ''}">${s.nordnet_export_age_days}d</b>`,
    `Notion <b>${live ? 'live' : 'cached'}</b>`,
  ].filter(Boolean).map((f) => `<span class="f">${f}</span>`)
   .join('<span style="color:var(--axis);margin:0 8px">·</span>');

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
  if (problems.length) {
    const worst = problems.some((p) => p.level === 'critical') ? 'critical' : 'warning';
    $('#t-banner').innerHTML =
      `<div class="banner"><span class="dot" style="background:${LEVEL[worst]}"></span>` +
      `<span><b>${esc(hs.headline || '')}</b> ` +
      `<span class="why">${problems.map((p) => esc(p.title)).join(' · ')}</span></span></div>`;
  }
}

