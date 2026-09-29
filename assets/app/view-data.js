/* ------------------------------------------------------------ data sheet */

/* The sheet is one surface with one state, and every table on it reads that
   state. A sector bar, a fund row and the search box all write to the same
   object, so a click in one section changes what the sections below it say -
   which is the difference between a dashboard and a stack of printouts.

   State is deliberately NOT persisted. Reopening the sheet on the next run
   should show the whole book, not last week's question still applied to this
   week's numbers with no sign that it is. */
const SS = {
  filter: null,      // {kind:'sector'|'country'|'industry'|'fund', key, label}
  q: '',
  units: 'pct',      // 'pct' | 'eur'
  sort: {},          // table name -> {k, dir}
  shut: {},          // section id -> true when collapsed
  at: null,          // section id last jumped to - the drawer's half of the route
};

// Reads 'growth.revenue_yoy_pct' as well as 'pct', so a sort key can point at
// a nested figure without the row being flattened first.
const dig = (o, path) => String(path).split('.')
  .reduce((v, k) => (v == null ? v : v[k]), o);

function sortRows(rows, table, fallback) {
  const s = SS.sort[table] || {k: fallback, dir: -1};
  return rows.slice().sort((a, b) => {
    const x = dig(a, s.k), y = dig(b, s.k);
    // A missing value sinks in BOTH directions. Sorting ascending by surprise
    // must not put the six names that never reported one above the worst miss
    // in the book - absent is not the smallest number, it is not a number.
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return (typeof x === 'number' && typeof y === 'number'
      ? (x - y) : String(x).localeCompare(String(y))) * s.dir;
  });
}

// Sortable columns whose cells are words rather than figures. Numbers are
// right-aligned so they stack on their last digit and can be compared down the
// column; words need a predictable left margin instead, and without this list
// every sector, verdict and account cell was right-ragged against a hard edge.
//
// Kept as an explicit list and NOT derived from d0, though it is tempting: d0
// is which way a FIRST CLICK sorts, which merely correlates with text. 'Days
// ago' sorts ascending and is a number; 'As of' sorts descending and is a
// date. Deriving one from the other is this repo's own recurring bug - a
// derived value quietly claiming to mean more than it does.
const TEXTCOL = new Set([
  'held.name', 'log.verdict', 'log.tier', 'log.last_eval', 'log.next_check',
  'cov.covered', 'cov.gap', 'cov.klass', 'cov.name', 'names.name',
  'funds.name', 'funds.symbol', 'latest.date', 'mult.live.asof',
  'ind.ind.rsi_state',
]);

// A sortable header. `d0` is the direction a first click gives: -1 (biggest
// first) for figures, 1 (A-Z, oldest-first) for names and dates.
const th = (table, key, label, d0) => {
  const s = SS.sort[table];
  const on = s && s.k === key;
  const t = TEXTCOL.has(`${table}.${key}`) ? ' t' : '';
  return `<th class="s${t}" data-t="${table}" data-k="${esc(key)}"
    data-d0="${d0 == null ? -1 : d0}"${on ? ` data-dir="${s.dir}"` : ''}
    >${esc(label)}</th>`;
};

/* Push each header's alignment down its own column.

   The alternative was to write class="t" on every matching <td> by hand, in
   nine tables, and keep those in step with the headers forever. They would not
   have stayed in step: the cells and the headers are written hundreds of lines
   apart, and the funds table had already drifted far enough to emit one fewer
   cell than its header without anyone noticing.

   So the header is the single declaration and the cells follow it. A row whose
   cell count disagrees with the header is left untouched rather than aligned
   against the wrong columns - if the two ever disagree again, the result is a
   visibly unaligned table, which is the failure that gets reported, instead of
   a neat one that is quietly describing the wrong numbers. */
function alignColumns(root) {
  for (const table of root.querySelectorAll('table')) {
    const heads = [...table.querySelectorAll('thead th')];
    if (!heads.length) continue;
    const isText = heads.map((h) => h.classList.contains('t'));
    for (const row of table.querySelectorAll('tbody tr')) {
      const cells = row.children;
      if (cells.length !== heads.length) continue;
      for (let i = 0; i < cells.length; i++)
        cells[i].classList.toggle('t', isText[i]);
    }
  }
}

function paintSheet() {
  // One search box over every table. Matching on symbol OR name means typing
  // "micro" and typing "MSFT" find the same rows, and the sheet stops being
  // somewhere you scroll to find a ticker.
  const q = (SS.q || '').trim().toLowerCase();
  const hits = (r) => !q || [r.symbol, r.sym, r.yahoo, r.ticker, r.name,
    r.company, r.label].some((v) => v && String(v).toLowerCase().includes(q));
  const some = (n, all, what) => n === all ? `${all} ${what}`
    : `${n} of ${all} ${what}`;

  const hr = sortRows([...held.values()].filter(hits), 'held', 'value_eur');
  const h = `<h2 data-sec="hold" data-label="Holdings">Holdings — ${some(hr.length, held.size,
      'companies')}, ${(D.sources||{}).lots} lots</h2>
    <div class="sec" data-sec="hold">
    <div class="scroll"><table><thead><tr>
    ${th('held','ticker','Ticker',1)}${th('held','name','Company',1)}
    <th class="t">Acct</th>${th('held','units','Units')}${th('held','price','Price')}
    ${th('held','day_pct','Day')}${th('held','value_eur','Value €')}
    ${th('held','cost_eur','Cost €')}${th('held','pl_eur','P/L €')}
    ${th('held','pl_pct','P/L %')}${th('held','weight','Weight')}
    ${th('held','off_high','Off high')}</tr></thead><tbody>${hr.map((p) => `<tr
      class="click" data-sym="${esc(p.sym)}">
      <td>${esc(p.ticker)}</td><td>${esc(p.name)}</td>
      <td class="t">${esc(p.accounts.join('/'))}</td><td>${qty(p.units)}</td>
      <td>${fresh(p.freshness)}${px(p.price)}</td>
      <td class="${cls(p.day_pct)}">${pct(p.day_pct,1)}</td>
      <td>${eur(p.value_eur)}</td><td>${eur(p.cost_eur)}</td>
      <td class="${cls(p.pl_eur)}">${eur(p.pl_eur)}</td>
      <td class="${cls(p.pl_pct)}">${pct(p.pl_pct,1)}</td>
      <td>${p.weight.toFixed(1)}%</td><td>${pct(p.off_high,1)}</td></tr>`).join('')}
    </tbody></table></div></div>`;

  const wr = sortRows((D.watchlist||[]).filter(hits), 'log', 'upside_now');
  const w = `<h2 data-sec="log" data-label="Equity Log">Equity Log — ${some(wr.length,
      (D.watchlist||[]).length, 'rows')}, ${(D.sources||{}).equity_log_mode}</h2>
    <div class="sec" data-sec="log">
    <div class="scroll"><table><thead><tr>
    ${th('log','ticker','Ticker',1)}${th('log','verdict','Verdict',1)}
    ${th('log','tier','Tier',1)}${th('log','price_now','Price')}
    ${th('log','target','Target')}${th('log','upside_now','Upside now')}
    ${th('log','upside_at_eval','At eval')}${th('log','upside_decay_pts','Decay pts')}
    <th class="t">Trigger</th>${th('log','trigger_gap_pct','Gap')}
    ${th('log','last_eval','Evaluated',1)}${th('log','next_check','Next',1)}
    </tr></thead><tbody>${wr.map((x)=>`<tr
      class="${ROWSYM.has(x.yahoo || x.ticker) ? 'click' : ''}"
      data-sym="${esc(x.yahoo || x.ticker)}">
      <td>${esc(x.ticker)}</td><td>${esc(x.verdict)}</td><td>${esc(x.tier)}</td>
      <td>${fresh(freshnessOf(x.price_now, x.stale_price,
        x.yahoo || x.ticker))}${px(x.price_now)}</td><td>${px(x.target)}</td>
      <td class="${cls(x.upside_now)}">${pct(x.upside_now,1)}</td>
      <td>${pct(x.upside_at_eval,1)}</td>
      <td>${x.upside_decay_pts == null ? '—' : x.upside_decay_pts.toFixed(1)}</td>
      <td class="t">${x.trigger_level ? esc(x.trigger_kind)+' '+px(x.trigger_level) : '—'}</td>
      <td>${pct(x.trigger_gap_pct,1)}</td><td>${esc(x.last_eval)}</td>
      <td>${esc(x.next_check)}</td></tr>`).join('')}</tbody></table></div></div>`;

  // Ordered by money at risk, not alphabetically: the question the table
  // answers is "how much of the book is nobody watching", and the answer is
  // read off the top rows.
  const cr = sortRows((COV.rows || []).filter(hits), 'cov', 'value_eur');
  const cov = !(COV.rows || []).length ? '' :
   `<h2 data-sec="cov" data-label="Monitoring">Coverage —
    ${(COV.rows||[]).length - (COV.n_uncovered||0)}/${(COV.rows||[]).length} monitored,
    ${eur(COV.value_uncovered_eur)} (${(COV.pct_uncovered||0).toFixed(0)}%) unwatched</h2>
    <div class="sec" data-sec="cov">
    <div class="scroll"><table><thead><tr>
    ${th('cov','ticker','Ticker',1)}${th('cov','covered','Monitored',1)}
    ${th('cov','gap','Gap',1)}${th('cov','value_eur','Value €')}
    ${th('cov','weight_pct','Weight')}${th('cov','klass','Class',1)}
    <th class="t">Judged by</th>${th('cov','target_weight_pct','Target wt')}
    ${th('cov','drift_pts','Drift pts')}<th class="t">Acct</th>
    ${th('cov','name','Name',1)}</tr></thead><tbody>${cr.map((c) => `<tr
      class="${ROWSYM.has(c.yahoo || c.ticker) ? 'click' : ''}"
      data-sym="${esc(c.yahoo || c.ticker)}">
      <td>${esc(c.ticker)}</td><td>${c.covered ? 'yes' : '<b>no</b>'}</td>
      <td>${esc(c.gap || '')}</td>
      <td>${eur(c.value_eur)}</td><td>${num(c.weight_pct,1)}%</td>
      <td>${esc(c.klass)}</td>
      <td class="t">${c.klass === 'stock' ? 'thesis' : 'allocation'}</td>
      <td>${c.target_weight_pct == null ? '—' : num(c.target_weight_pct,1) + '%'
        + (c.target_basis === 'placeholder' ? ' <span class="est"'
          + ' title="Placeholder, not a policy">P</span>' : '')}</td>
      <td>${c.drift_pts == null ? '—' : num(c.drift_pts,1)}</td>
      <td class="t">${esc(c.account)}</td><td>${esc(c.name)}</td>
      </tr>`).join('')}</tbody></table></div>
    ${cr.some((c) => c.target_basis === 'placeholder') ? `<div class="prose under"><span class="est">P</span> — placeholder. Filled in
      by a rule (equal weight inside a core/satellite frame) so the allocation
      columns have something to draw. It is not a policy: the holding still
      counts as uncovered and its drift is never alerted on.</div>` : ''}
    ${(COV.researched_not_held||[]).length ? `<div class="prose under">Researched but not owned — ${(COV.researched_not_held||[])
      .map(esc).join(', ')}.</div>` : ''}</div>`;

  // The book seen through its wrappers. Two rules hold across everything
  // below. Bars are drawn against a full 100% track, so a row's width is its
  // share of the whole book and not its share of the largest row. And every
  // breakdown draws the mass it could not place as its own bar, because
  // Yahoo discloses ten constituents per fund - most of a thematic, almost
  // none of a world tracker - so coverage varies six-fold inside one
  // portfolio and a chart that hid that would be the most misleading thing
  // on this page. See exposure.py's header.
  const X = D.exposure || {};
  const XT = X.total_eur || 0;
  const share = (v) => XT ? (v / XT) * 100 : 0;
  const w100 = (v) => Math.max(0, Math.min(100, v || 0)).toFixed(3);
  // % or € on the same bars. Not decoration: a 0.30% real-estate sliver and a
  // €120 real-estate sliver are answers to different questions, and which one
  // you want changes with what you are about to do.
  const amt = (p, v) => SS.units === 'eur' ? eur(v) : num(p, 2) + '%';

  const xbar = (o) => `<div class="xrow ${o.un ? 'un' : ''}"
    ${o.kind ? `data-fk="${esc(o.kind)}" data-fv="${esc(o.key)}"
      data-fl="${esc(o.label)}"` : ''}
    data-on="${SS.filter && SS.filter.kind === o.kind
      && SS.filter.key === o.key ? 1 : 0}">
    <div class="n" title="${esc(o.label)}">${esc(o.label)}</div>
    <div class="t">${o.direct == null
      ? `<i class="f" style="width:${w100(o.pct)}%"></i>`
      : `<i class="f" style="width:${w100(o.direct)}%"></i>` +
        `<i class="f2" style="width:${w100(o.indirect)}%"></i>`}</div>
    <div class="p">${amt(o.pct, o.value)}</div></div>`;

  // One breakdown - sector, geography or industry - as a ranked stack. Rows
  // are click targets: picking one filters every table below to the names it
  // contains, which is the whole point of having both on one surface. The
  // unresolved bar is appended whenever there is anything to append and is
  // deliberately NOT clickable - it is the answer to "and the rest", not a
  // bucket you can look inside.
  // `note` is escaped and `mark` is not, deliberately: the note can carry a
  // vendor-supplied string (geography's basis line comes from the data), while
  // mark is only ever this file's own atBuild() markup.
  const xstack = (t, title, kind, note, mark) => {
    if (!t || !(t.rows || []).length) return '';
    const un = share(t.unresolved_eur || 0);
    return `<div><div class="tlabel run">${esc(title)} —
      ${num(t.resolved_pct, 1)}% placed</div>
      ${t.rows.map((r) => xbar({label: r.label, key: r.key, kind: kind,
        pct: r.pct, value: r.value_eur,
        direct: r.direct_eur == null ? null : share(r.direct_eur),
        indirect: r.indirect_eur == null ? null : share(r.indirect_eur)})).join('')}
      ${un > 0.005 ? xbar({label: 'Not resolved', pct: un,
        value: t.unresolved_eur, un: true}) : ''}
      <div class="xkey">${esc(note)}${mark || ''}</div></div>`;
  };

  const XC = X.concentration || {}, XM = X.multiples || {},
        XF = X.fees || {}, XN = X.names || {}, XO = X.overlap || {};
  const xcard = (k, v, s) => `<div class="xcard"><div class="k">${esc(k)}</div>
    <div class="v">${v}</div><div class="s">${s}</div></div>`;

  // Both tables below read the one live filter and the one search box, so a
  // click on a sector bar and a typed ticker compose instead of competing.
  const F = SS.filter;
  const inFilter = (r) => {
    if (!F) return true;
    if (F.kind === 'fund') return (r.via || []).some((v) => v.fund === F.key);
    return r[F.kind] === F.key;
  };
  // How many rows the filter could not judge either way, kept separate from
  // how many it excluded. A name Yahoo gave only a ticker for has no sector,
  // and counting it as "not Technology" would be an answer the data cannot
  // support. It is reported as unclassified and left out.
  const blind = !F || F.kind === 'fund' ? 0
    : (XN.rows || []).filter((r) => r[F.kind] == null).length;

  const nameRows = sortRows((XN.rows || []).filter((r) => inFilter(r) && hits(r)),
                            'names', 'pct');
  const fundRows = sortRows((X.funds || []).filter((f) => hits(f)
    && (!F || F.kind !== 'fund' || f.symbol === F.key)), 'funds', 'value_eur');

  const exp = !XT ? '' :
   `<h2 data-sec="exp" data-label="Concentration">Exposure — ${eur(XT)} across
    ${X.n_positions} positions, looked through</h2>
    <div class="sec" data-sec="exp">
    <div class="xgrid">
      ${xcard('Effective positions', num(XC.effective_n, 1),
        `of ${XC.n} held · top 5 ${num(XC.top5_pct,1)}% ·
         top 10 ${num(XC.top10_pct,1)}% · HHI ${num(XC.hhi,4)}`)}
      ${xcard('Blended P/E', num(XM.pe, 1),
        `P/B ${num(XM.pb,1)} · P/S ${num(XM.ps,2)} ·
         ${num(XM.pe_resolved_pct,1)}% of the book priced · harmonic, not averaged`
        + atBuild('each multiple is the vendor’s own figure at the '
          + 'vendor’s own asof; one holding quotes in pence, so a naive '
          + 'price-over-earnings rescale would be out by a factor of a hundred'))}
      ${xcard('Fund fee drag', feeDrag(XF).v, !feeDrag(XF).known ? feeDrag(XF).s :
        `${num(XF.sleeve_ter_pct,3)}% of the fund sleeve ·
         ${num(XF.book_ter_pct,3)}% of the book ·
         ${num(XF.resolved_pct,0)}% of fund value has a published TER`)}
      ${xcard('Names reached', XN.n || 0,
        `${num(XN.resolved_pct,1)}% of the book named ·
         ${XN.n_both_ways || 0} held directly and inside a fund ·
         the rest is inside undisclosed fund tails`
        + lookMark())}
      ${xcard('Funds drawing on one pot',
        (XO.n_substantial || 0) + ' of ' + (XO.n_pairs || 0),
        ((XO.pairs || [])[0]
          ? 'pairs substantially the same holding · biggest by euro is ' +
            esc(XO.pairs[0].a) + ' × ' + esc(XO.pairs[0].b) + ' on ' +
            XO.pairs[0].n_shared + ' names, ' + num(XO.pairs[0].pct, 1) +
            '% of the book'
          : 'no two funds disclose a name in common') +
        ' · <a href="#/data/lap">see every pair</a>')}
    </div>
    <div class="xcols">
      ${xstack(X.sectors, 'Sector', 'sector',
        'Solid is held directly, pale is reached through a fund. Fund cash is ' +
        'left unresolved rather than scaled away. Click a row to filter below.',
        lookMark())}
      ${xstack(X.geography, 'Geography', 'country',
        (X.geography || {}).basis || '', lookMark())}
    </div>
    ${xstack(X.industries, 'Industry', 'industry',
      'Directly-held stocks only. A fund reports sectors and never industries, ' +
      'so the fund sleeve is unresolved here by construction, not by failure.',
      lookMark())}
    </div>
    <h2 data-sec="look" data-label="Inside the funds">Look-through — ${nameRows.length}${
      nameRows.length === (XN.rows || []).length ? '' :
      ' of ' + (XN.rows || []).length} companies the book touches</h2>
    <div class="sec" data-sec="look">
    ${!nameRows.length ? '<div class="empty">No company matches that filter.</div>'
    : `<div class="scroll"><table><thead><tr>
    ${th('names','symbol','Symbol',1)}${th('names','name','Company',1)}
    ${th('names','pct','Total')}${th('names','direct_pct','Direct')}
    ${th('names','indirect_pct','Via funds')}${th('names','value_eur','Value €')}
    <th class="t">Reached through</th></tr></thead><tbody>${nameRows.map((r) => `<tr
      class="${ROWSYM.has(r.symbol) ? 'click' : ''}" data-sym="${esc(r.symbol)}">
      <td>${esc(r.symbol)}</td><td>${esc(r.name)}</td>
      <td><b>${amt(r.pct, r.value_eur)}</b></td>
      <td>${r.direct_pct ? num(r.direct_pct,2)+'%' : '—'}</td>
      <td>${r.indirect_pct ? num(r.indirect_pct,2)+'%' : '—'}</td>
      <td>${eur(r.value_eur)}</td>
      <td class="t" style="color:var(--muted)">${r.held_both_ways
        ? 'held outright + ' : ''}${(r.via || []).map((v) =>
        esc(v.fund)+' '+num(v.pct,1)+'%').join(', ') || 'held outright'}</td>
      </tr>`).join('')}</tbody></table></div>`}
    <div class="prose under">A name absent from this table is
      not absent from the book — it is absent from a fund's disclosed top ten.
      The indirect column is a floor.${blind ? ` ${blind} of these companies
      have no ${esc(F.kind === 'country' ? 'domicile' : F.kind)} on record and
      are excluded from this filter rather than assumed out of it.` : ''}
      ${nameRows.some((r) => ROWSYM.has(r.symbol))
        ? ' Rows with a chart of their own open it.' : ''}</div>
    </div>
    <h2 data-sec="funds" data-label="Funds">Funds — what each one tells you</h2>
    <div class="sec" data-sec="funds">
    <div class="scroll"><table><thead><tr>
    ${th('funds','symbol','Symbol',1)}${th('funds','name','Name',1)}
    ${th('funds','weight_pct','Weight')}${th('funds','value_eur','Value €')}
    ${th('funds','ter_pct','TER')}<th>Cost €/yr</th>
    ${th('funds','disclosed_pct','Discloses')}${th('funds','n_disclosed','Rows')}
    <th class="t">Sectors</th></tr></thead><tbody>${
      fundRows.map((f) => { const fee = ((XF.rows || [])
        .find((r) => r.symbol === f.symbol) || {});
      return `<tr class="click" data-fund="${esc(f.symbol || '')}"
      data-on="${F && F.kind === 'fund' && F.key === f.symbol ? 1 : 0}">
      <td>${esc(f.symbol || '—')}</td><td class="t">${esc(f.name)}</td>
      <td>${num(f.weight_pct,2)}%</td><td>${eur(f.value_eur)}</td>
      <td>${f.ter_pct == null ? '<span style="color:var(--muted)">not published</span>'
        : num(f.ter_pct,2)+'%'}</td>
      <td>${fee.annual_eur == null ? '—' : eur(fee.annual_eur)}</td>
      <td>${num(f.disclosed_pct,1)}%</td><td>${f.n_disclosed}</td>
      <td class="t">${f.has_sectors ? 'yes' : '<b>no</b>'}</td></tr>`; }).join('')
    }</tbody></table></div>
    <div class="prose under">The spread down the Discloses
      column is why every figure above carries a coverage percentage. A fund
      with no published TER is not free — it is counted against coverage, so
      the fee figure reads as a floor. Click a fund to see only what it
      reaches.</div>
    </div>
    <h2 data-sec="lap" data-label="Fund overlap">Fund overlap — ${
      XO.n_substantial || 0} of ${XO.n_pairs || 0} pairs substantially
      the same holding</h2>
    <div class="sec" data-sec="lap">
    ${!(XO.pairs || []).length
      ? `<div class="empty">${XO.n_funds
          ? 'No two of the ' + XO.n_funds + ' funds disclose a name in common.'
          : 'No fund discloses its holdings, so no pair can be compared.'}</div>`
      : `<div class="scroll"><table><thead><tr>
    <th class="t">Pair</th><th>Shared</th><th>Of A</th><th>Of B</th>
    <th>Via both €</th><th>Of book</th>
    <th class="t">Names in common</th></tr></thead><tbody>${
      (XO.pairs || []).filter((p) => hits({symbol: p.a + ' ' + p.b,
        name: (p.shared || []).join(' ')})).map((p) => `<tr>
      <td class="t"><b>${esc(p.a)}</b> × <b>${esc(p.b)}</b></td>
      <td>${p.n_shared} of ${p.n_a}/${p.n_b}</td>
      <td>${num(p.a_disclosed_in_shared_pct,1)}%</td>
      <td>${num(p.b_disclosed_in_shared_pct,1)}%</td>
      <td>${eur(p.value_eur)}</td>
      <td><b>${num(p.pct,2)}%</b></td>
      <td class="t" style="color:var(--muted)">${
        (p.shared || []).map(esc).join(', ')}</td></tr>`).join('')
    }</tbody></table></div>`}
    <div class="prose under">Two funds holding the same company is not a
      mistake, but owning it twice at a weight you never chose is. Of A and Of B
      are how much of each fund's <i>disclosed</i> value sits in the shared
      names — a pair reading high on both is two routes to one bet. The euro
      figure is the money reaching those shared names through the two funds
      added together: each fund's own value times its disclosed weight in each
      shared name. It is counted once per fund, so it is what the bet is worth,
      not a double count — but do not add the pairs up, because a name held by
      three funds is in three of these rows. Every column is a floor: it can
      only see names both funds publish, and a fund publishes its top ten.${
      lookMark()}</div>
    </div>`;

  /* ----------------------------------------------------------- reporting */
  // What is coming and what landed. Grouped by month rather than by a
  // days-until bucket: a bucket boundary moves under you overnight, a month
  // does not, and the horizon is a quarter wide because a four-week one was
  // measured empty for six weeks of every quarter.
  const R = D.reporting || {}, RC = R.calendar || {};
  const months = [];
  for (const row of RC.rows || []) {
    const key = row.date.slice(0, 7);
    let bucket = months.find((m) => m.key === key);
    if (!bucket) months.push(bucket = {key, rows: []});
    bucket.rows.push(row);
  }
  const monthName = (key) => {
    const d = new Date(key + '-01T00:00:00');
    return isNaN(d) ? key : d.toLocaleDateString('en-GB',
      {month: 'short', year: 'numeric'});
  };
  const dayName = (iso) => {
    const d = new Date(iso + 'T00:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('en-GB',
      {day: 'numeric', month: 'short'});
  };
  const landed = sortRows((R.latest || []).filter(hits), 'latest', 'date');

  const rep = !(RC.rows || []).length && !(R.latest || []).length ? '' :
   `<h2 data-sec="rep" data-label="Earnings">Reporting — ${RC.n || 0} prints in the next
    ${RC.horizon_days} days, ${num(RC.pct_ahead,0)}% of the book</h2>
    <div class="sec" data-sec="rep">
    ${!months.length ? `<div class="empty">Nothing scheduled inside
      ${RC.horizon_days} days.</div>` : `<div class="cal">${months.map((m) => `
      <div class="calwk">${esc(monthName(m.key))}</div>
      <div class="calbox ${m.rows.some((r) => r.soon) ? 'soon' : ''}">
        ${m.rows.map((r) => `<div class="calrow" data-sym="${esc(r.symbol)}">
          <span class="d">${esc(dayName(r.date))}</span>
          <span class="sym">${esc(r.symbol)}</span>
          <span class="co">${esc(r.name)}${r.estimated
            ? ' <span class="est">est. date</span>' : ''}</span>
          <span class="wt">${r.eps_estimate == null ? ''
            : 'cons. ' + num(r.eps_estimate, 2) + ' · '}${num(r.weight_pct,1)}%
            of book</span></div>`).join('')}
      </div>`).join('')}</div>`}
    ${(RC.unknown || []).length ? `<div class="xkey under">
      No scheduled date from Yahoo for ${(RC.unknown || []).map((u) =>
      esc(u.symbol)).join(', ')} — ${(RC.unknown || []).some((u) => u.has_history)
      ? 'the reporting history is there, the next date is not.'
      : 'nothing on record at all.'} Absence of a date is not absence of a
      quarter.</div>` : ''}
    <div class="tlabel run">Last reported</div>
    <div class="scroll"><table><thead><tr>
    ${th('latest','symbol','Symbol',1)}${th('latest','date','Reported')}
    ${th('latest','days_ago','Days ago',1)}${th('latest','eps_estimate','Expected')}
    ${th('latest','eps_reported','Actual')}${th('latest','surprise_pct','Surprise')}
    ${th('latest','record.median_surprise_pct','Record')}
    ${th('latest','growth.revenue_yoy_pct','Revenue YoY')}
    <th class="t">Quarter</th>${th('latest','weight_pct','Weight')}
    </tr></thead><tbody>${landed.map((r) => { const g = r.growth || {},
      rec = r.record || {};
      return `<tr class="${ROWSYM.has(r.symbol) ? 'click' : ''}"
      data-sym="${esc(r.symbol)}">
      <td>${esc(r.symbol)}</td><td>${esc(r.date)}</td>
      <td>${r.days_ago == null ? '—' : r.days_ago}</td>
      <td>${num(r.eps_estimate,2)}</td><td>${num(r.eps_reported,2)}</td>
      <td class="${r.surprise_pct == null ? '' : r.beat ? 'beat'
        : r.surprise_pct < 0 ? 'miss' : ''}">${pct(r.surprise_pct,1)}</td>
      <td>${rec.n ? `${rec.beats}B / ${rec.misses}M of ${rec.n}` : '—'}</td>
      <td class="${cls(g.revenue_yoy_pct)}">${pct(g.revenue_yoy_pct,1)}</td>
      <td class="t">${esc(g.period || '—')}</td><td>${num(r.weight_pct,1)}%</td>
      </tr>`; }).join('')}</tbody></table></div>
    <div class="prose under">Surprise is against analyst
      consensus, not against the thesis — a beat is a fact about expectations.
      Revenue is compared with the same quarter a year earlier, never with last
      quarter. A quarter that has not been reported is absent from this table
      rather than present at zero.</div>
    </div>`;

  // The board's figures beside today's, for every name that has either. Two
  // columns per multiple rather than one reconciled number: the gap IS the
  // reading, and a merged figure would be the one thing this cannot show.
  const fa = (D.watchlist||[]).filter((x) => x.live || x.pe != null || x.fwd_pe != null);
  const fw = sortRows(fa.filter(hits), 'mult', 'live.pe');
  const mult = !fa.length ? '' :
   `<h2 data-sec="mult" data-label="Multiples">Multiples — board vs today,
    ${fa.filter((x) => x.live).length} live</h2>
    <div class="sec" data-sec="mult">
    <div class="scroll"><table><thead><tr>${th('mult','ticker','Ticker',1)}
    ${th('mult','pe','P/E board')}${th('mult','live.pe','P/E now')}
    ${th('mult','pe_drift_pct','Drift')}
    ${th('mult','fwd_pe','Fwd board')}${th('mult','live.fwd_pe','Fwd now')}
    ${th('mult','fwd_pe_drift_pct','Drift')}
    ${th('mult','live.pb','P/B')}${th('mult','live.net_debt_ebitda','ND/EBITDA')}
    ${th('mult','live.roe_pct','ROE')}${th('mult','live.margin_pct','Margin')}
    ${th('mult','live.beta','Beta')}${th('mult','live.market_cap','Mkt cap')}
    <th>Street tgt</th>${th('mult','street_upside_pct','Street')}
    ${th('mult','upside_now','Yours')}${th('mult','live.street_analysts','Analysts')}
    ${th('mult','live.asof','As of')}</tr></thead><tbody>${fw.map((x) => {
      const L = x.live || {};
      return `<tr class="${ROWSYM.has(x.yahoo || x.ticker) ? 'click' : ''}"
      data-sym="${esc(x.yahoo || x.ticker)}"><td>${esc(x.ticker)}</td>
      <td>${num(x.pe,1)}</td><td>${num(L.pe,1)}</td>
      <td>${pct(x.pe_drift_pct,0)}</td>
      <td>${num(x.fwd_pe,1)}</td><td>${num(L.fwd_pe,1)}</td>
      <td>${pct(x.fwd_pe_drift_pct,0)}</td>
      <td>${num(L.pb,1)}</td><td>${num(L.net_debt_ebitda,2)}</td>
      <td>${L.roe_pct == null ? '—' : num(L.roe_pct,1)+'%'}</td>
      <td>${L.margin_pct == null ? '—' : num(L.margin_pct,1)+'%'}</td>
      <td>${num(L.beta,2)}</td><td>${big(L.market_cap)}</td>
      <td>${px(L.street_target)}</td>
      <td class="${cls(x.street_upside_pct)}">${pct(x.street_upside_pct,1)}</td>
      <td class="${cls(x.upside_now)}">${pct(x.upside_now,1)}</td>
      <td>${L.street_analysts == null ? '—' : num(L.street_analysts,0)}</td>
      <td>${esc(L.asof || '—')}</td></tr>`; }).join('')}</tbody></table></div></div>`;

  const ia = ROWS.filter((x) => x.ind);
  const ir = sortRows(ia.filter(hits), 'ind', 'ind.rsi');
  const ind = !ia.length ? '' :
   `<h2 data-sec="ind" data-label="Technicals">The chart, in numbers —
    ${some(ir.length, ia.length, 'symbols')}</h2>
    <div class="sec" data-sec="ind">
    <div class="scroll"><table><thead><tr>${th('ind','label','Ticker',1)}
    ${th('ind','ind.close','Close')}${th('ind','ind.rsi','RSI')}
    ${th('ind','ind.rsi_state','State',1)}${th('ind','ind.bb_pct_b','%B')}
    ${th('ind','ind.bb_width','Band w')}${th('ind','ind.macd_hist','MACD h')}
    ${th('ind','ind.sma50','MA50')}${th('ind','ind.sma200','MA200')}
    ${th('ind','ind.ma_spread_pct','Spread')}
    ${th('ind','ind.above_sma200_pct','vs MA200')}
    ${th('ind','ind.atr_pct','ATR %')}${th('ind','ind.vol_30d','Vol 30d')}
    ${th('ind','ind.max_drawdown_pct','Max DD')}
    ${th('ind','ind.range.pct','In range')}
    ${th('ind','ind.volume.relative','Vol ×avg')}${th('ind','ind.bars','Bars')}
    <th class="t">As of</th></tr></thead><tbody>${ir.map((x) => { const i = x.ind;
      return `<tr class="click" data-sym="${esc(x.sym)}">
      <td>${esc(x.label)}</td><td>${px(i.close)}</td>
      <td>${num(i.rsi,1)}</td><td>${esc(i.rsi_state || '')}</td>
      <td>${i.bb_pct_b == null ? '—' : num(i.bb_pct_b,2)}</td>
      <td>${i.bb_width == null ? '—' : num(i.bb_width*100,1)+'%'}</td>
      <td class="${cls(i.macd_hist)}">${num(i.macd_hist,2)}</td>
      <td>${px(i.sma50)}</td><td>${px(i.sma200)}</td>
      <td class="${cls(i.ma_spread_pct)}">${pct(i.ma_spread_pct,1)}</td>
      <td class="${cls(i.above_sma200_pct)}">${pct(i.above_sma200_pct,1)}</td>
      <td>${num(i.atr_pct,2)}</td><td>${num(i.vol_30d,1)}</td>
      <td class="dn-t">${pct(i.max_drawdown_pct,1)}</td>
      <td>${i.range ? num(i.range.pct,0) : '—'}</td>
      <td>${i.volume ? num(i.volume.relative,2) : '—'}</td>
      <td>${i.bars}</td><td class="t">${esc(i.asof)}</td></tr>`; }).join('')}</tbody></table></div>
    <div class="prose under">Computed in Python off the cached daily bars, up
      to each row's own <i>As of</i>. The chart's last candle tracks the live
      price and these do not, so on a fast day the two will differ by one
      partial session — that is the gap between a recorded figure and a moving
      one, not an error in either. Descriptive only — no row here is a
      signal.</div>
    </div>`;

  const al = (D.alerts||[]).filter((x) => !q ||
    (x.title + ' ' + x.detail).toLowerCase().includes(q));
  // Sales. The Nordnet export lists holdings and never transactions, so every
  // row here is the difference between two exports and nothing else.
  //
  // This section renders even when it has no rows, and that is the point of
  // it. "Nothing was sold" and "the question could not be asked" are different
  // answers, only one of them is good news, and a section that vanished on the
  // second would be read as the first - which is precisely the derived status
  // claiming more than it means that this repo keeps finding. So the prose
  // below always says which of the two it is.
  //
  // The euro column is ACHROMATIC on purpose, same argument as the multiple
  // drift above: a sale is not a bad thing and a purchase is not a good one.
  // Colouring them would have the page take a view that belongs to the thesis.
  const AC = D.activity || {};
  const acr = AC.changes || [];
  const KIND = {exited: 'sold out', reduced: 'sold down', opened: 'opened',
                increased: 'added to', adjusted: 'adjusted (not a trade)'};
  const acWhy = AC.comparable
    ? `Compared the ${esc(AC.from_exported)} export against
       ${esc(AC.to_exported)}.`
    : acr.length
      ? `Carried from the last comparison that was possible
         (${esc(AC.from_exported)} → ${esc(AC.to_exported)}). This run could not
         look again: ${esc(AC.reason)}.`
      : `<b>No comparison was possible</b>, so this is not a report that nothing
         was sold — it is the absence of a report. ${esc(AC.reason)}.`;
  const act = `<h2 data-sec="act" data-label="Changes">Activity — ${acr.length
      ? `${acr.length} change${acr.length === 1 ? '' : 's'} since the
         ${esc(AC.from_exported)} export`
      : (AC.comparable ? 'no change since the last export'
                       : 'cannot tell')}</h2>
    <div class="sec" data-sec="act">
    ${!acr.length ? '' : `<div class="scroll"><table><thead><tr>
      <th class="t">Ticker</th><th class="t">What</th><th>Units before</th>
      <th>Units after</th><th>Cost €</th><th class="t">Lots closed outright</th>
      <th class="t">Acct</th><th class="t">Name</th>
      </tr></thead><tbody>${acr.map((c) => `<tr
        class="${ROWSYM.has(c.yahoo || c.ticker) ? 'click' : ''}"
        data-sym="${esc(c.yahoo || c.ticker)}">
        <td class="t">${esc(c.ticker)}</td>
        <td class="t">${esc(KIND[c.kind] || c.kind)}${c.why
          ? ` <span class="est" title="${esc(c.why)}">?</span>` : ''}</td>
        <td>${num(c.units_before, 4)}</td><td>${num(c.units_after, 4)}</td>
        <td>${eur(c.cost_delta)}</td>
        <td class="t">${(c.lots_closed || []).map((l) => esc(l.bought))
          .join(', ') || '—'}</td>
        <td class="t">${esc(c.account)}</td><td class="t">${esc(c.name)}</td>
        </tr>`).join('')}</tbody></table></div>`}
    <div class="prose under">${acWhy} The export is a list of
    what you hold, never a list of what you traded, so a sale exists here only
    as the difference between two of those lists — and until a newer export
    lands there is nothing further to see.</div></div>`;

  const a = `<h2 data-sec="flag" data-label="Needs a look">Flags — ${some(al.length,
      (D.alerts||[]).length, 'open')}</h2>
    <div class="sec" data-sec="flag">
    <div class="scroll"><table><thead><tr><th>Level</th><th class="t">What</th><th class="t">Why</th>
    </tr></thead><tbody>${al.map((x) => `<tr>
      <td>${esc(x.level)}</td><td class="t">${esc(x.title)}</td>
      <td class="wrap t">${esc(x.detail)}</td></tr>`).join('')}</tbody></table></div>
    </div>`;

  const s = D.sources || {};
  const src = `<h2 data-sec="prov" data-label="Sources">Provenance</h2>
    <div class="sec" data-sec="prov"><div class="scroll"><table><tbody>
    <tr><td>Generated</td><td>${esc(D.generated)}</td></tr>
    <tr><td>Run</td><td>${s.run_mode === 'refresh'
      ? `intraday refresh · prices and FX re-fetched, everything else served from
         the last full run at ${esc(s.last_full_run || 'unknown')}`
      : 'full · every source read'}</td></tr>
    <tr><td>Nordnet export</td><td>${esc(s.nordnet_export_date)} ·
      ${s.nordnet_export_age_days} days old · ${esc((s.nordnet_files||[]).join(', '))}</td></tr>
    <tr><td>Equity Log</td><td>${esc(s.equity_log_mode)} ·
      ${s.equity_log_age_days} days old</td></tr>
    <tr><td>Price history</td><td>${s.history_symbols} symbols cached ·
      ${s.history_problems} without a fresh series${LIVEBAR.size
        ? ` · the chart's last candle is carried forward to the live price on
            ${LIVEBAR.size} of them; the cached bars themselves are never
            written over`
        : ''}</td></tr>
    <tr><td>Fundamentals</td><td>${s.fundamentals_asked == null ? 'not fetched'
      : `${s.fundamentals_priced}/${s.fundamentals_asked} symbols carry multiples ·
         ${s.fundamentals_problems} problem${s.fundamentals_problems === 1 ? '' : 's'}`
      }</td></tr>
    <tr><td>Indicators</td><td>${Object.keys(D.indicators || {}).length} symbols ·
      derived from the cached bars, no separate fetch</td></tr>
    <tr><td>Fund composition</td><td>${s.composition_asked == null ? 'not fetched'
      : `${s.composition_resolved}/${s.composition_asked} funds broken out ·
         ${s.composition_problems} problem${s.composition_problems === 1 ? '' : 's'} ·
         ten constituents per fund is Yahoo's limit, not a setting`}</td></tr>
    <tr><td>Reporting</td><td>${s.earnings_asked == null ? 'not fetched'
      : `${s.earnings_resolved}/${s.earnings_asked} stocks carry a reporting
         record · ${s.earnings_problems}
         problem${s.earnings_problems === 1 ? '' : 's'} ·
         ${(R.calendar||{}).n_unknown || 0} with no scheduled next date ·
         funds are not asked, Yahoo answers them with a 404`}</td></tr>
    </tbody></table></div></div>`;

  // Order is the argument this page makes about what matters. It used to run
  // Holdings, Equity Log, Coverage, Activity, ... with Flags eleventh of twelve
  // and Provenance above it - so the one section that answers "what should I
  // look at today" sat below the list of where the data came from. It now runs
  // in the order the questions get asked: what needs a decision, what changed,
  // what I own, what is unwatched, how concentrated, what is coming, then the
  // reference tables, then the receipts. `exp` carries look and funds inside
  // it, so those three cannot be separated without splitting that string.
  $('#sheetbody').innerHTML = a + act + h + cov + exp + rep + mult + ind + w + src;
  alignColumns($('#sheetbody'));

  // Collapse state is re-applied after the repaint rather than survived
  // through it. Every table above is rebuilt from the payload on every
  // interaction, which is the point - none of it can be a stale render of an
  // older answer - so the only things that persist are in SS.
  for (const node of $('#sheetbody').querySelectorAll('[data-sec]'))
    node.setAttribute('data-shut', SS.shut[node.getAttribute('data-sec')] ? '1' : '0');

  // The nav is built from the sections that actually rendered, not from a list
  // kept alongside them. A hand-maintained list would keep offering a jump to
  // Reporting on a run where Yahoo returned nothing and the section is absent.
  // The label is authored on the heading, not scraped off it. It used to be
  // `textContent.split('—')[0]`, which made the nav a side effect of prose:
  // rewriting a heading silently renamed a button, and one heading that is a
  // full sentence - "The chart, in numbers" - produced a full-sentence button
  // sitting beside one-word ones. The fallback keeps a new section navigable
  // if someone adds an h2 and forgets the label.
  const heads = [...$('#sheetbody').querySelectorAll('h2[data-sec]')];
  $('#sheetnav').innerHTML = heads.map((n) => `<button class="navb"
      data-go="${esc(n.getAttribute('data-sec'))}"
      >${esc(n.getAttribute('data-label')
              || n.textContent.split('—')[0].trim())}</button>`).join('')
    + (SS.filter ? `<span class="xchip">${esc(SS.filter.kindLabel)}
        <b>${esc(SS.filter.label)}</b>
        <button id="xclear" title="Clear filter">×</button></span>` : '');
}

