// Live prices for the deployed cockpit, with no API key and no cost.
//
// Why this can exist at all: deploy/middleware.ts matches '/:path*', which
// includes this route. An anonymous caller is denied before this function runs,
// so a keyless upstream proxy here does not become an open relay for strangers.
// The gate is the API key. Narrow that matcher and this becomes a free quote
// API for the internet, billed to Daniel's account.
//
//   POST /api/quotes  {"symbols": ["ASML.AS", ...]}   the real call
//   GET  /api/quotes                                  health probe, no book
//
// POST rather than GET for the real call on purpose: a symbol list in a query
// string lands in request logs, and the symbol list IS the book's shape. The
// page itself is behind the same gate, so this is not a new exposure class, but
// there is no reason to write the holdings into a log line every 60 seconds.
//
// Two upstreams, both keyless, verified answering on 2026-09-22:
//   Yahoo v8 spark  - every symbol in ONE request. v7/quote returns 401 now
//                     (wants a crumb); v8 does not. Gives price, previous
//                     close, change, change%, timestamp. No currency - that is
//                     a property of the listing and is already known at build
//                     time, so it is not needed here.
//   Frankfurter     - FX only. Yahoo can serve FX too, but FX multiplies every
//                     non-EUR holding, so it gets a second independent source.
//
// A symbol this function cannot price is OMITTED from `quotes`, never returned
// as zero or as its previous close. The caller must be able to tell "Yahoo did
// not answer for this" from "this did not move", because those look identical
// once a missing value becomes a number. That is the bug class this repo keeps
// producing (see CLAUDE.md rule 4, and the OCS silent-zero in GBP).

export const config = { runtime: 'edge' };

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36';

// Yahoo's own words, in the 400 body, at 21 symbols:
//   "Number of symbols needs to be less than or equal to 20"
// Measured 2026-09-22: 20 returns 200 with all 20, 21 returns 400 with none.
// This was 40, which meant the main batch ALWAYS failed and only the short
// remainder chunk ever came back. The symptom was mild precisely because the
// contract below holds - the 21 unpriced holdings kept their build-time prices
// and the tape said "21 unpriced" - so nothing on screen was ever wrong. It
// was just quietly not live.
const CHUNK = 20;
const UPSTREAM_TIMEOUT_MS = 8000;
const MAX_SYMBOLS = 400;

// What today's session looked like, aggregated from the five-minute series this
// request already fetches and used to throw away.
//
// Read the field names literally: these are derived from five-minute CLOSES, so
// `high` and `low` are FLOORS - the true intraday extremes happened inside a
// bucket and are not in this data - and `open` is the first five-minute close,
// not the opening auction print. That is why the page prefers Yahoo's own daily
// bar whenever it has one for the same date and falls back to this only for a
// session the daily series has not started yet.
type Session = {
  open: number;
  high: number;
  low: number;
  points: number;
};

type Quote = {
  price: number;
  prevClose: number | null;
  change: number | null;
  changePct: number | null;
  asOf: number | null; // unix seconds, from Yahoo, not from this server
  session: Session | null;
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      // The prices are fresh or they are not worth having. No shared cache
      // should ever hold a response that is keyed to Daniel's book.
      'Cache-Control': 'private, no-store, max-age=0',
      'X-Robots-Tag': 'noindex, nofollow',
    },
  });
}

// Returns the payload AND why it is missing when it is. A bare `null` here is
// what let a chunk size of 40 fail on every call for as long as it did: the
// symbols correctly showed as unpriced, but nothing anywhere said the upstream
// had been answering 400 the entire time.
type Fetched = { data: any | null; error: string | null };

async function fetchJson(url: string): Promise<Fetched> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    const r = await fetch(url, {
      signal: ctl.signal,
      headers: { 'User-Agent': UA, Accept: 'application/json' },
    });
    if (!r.ok) {
      const body = await r.text().catch(() => '');
      return { data: null, error: `HTTP ${r.status} ${body.slice(0, 160)}`.trim() };
    }
    return { data: await r.json(), error: null };
  } catch (e: any) {
    const kind = e?.name === 'AbortError' ? 'timeout' : (e?.message || 'fetch failed');
    return { data: null, error: String(kind) };
  } finally {
    clearTimeout(timer);
  }
}

/** Last non-null close in the series, or null. Not `close[0]`, not 0. */
function lastClose(series: unknown): number | null {
  if (!Array.isArray(series)) return null;
  for (let i = series.length - 1; i >= 0; i--) {
    const v = series[i];
    if (typeof v === 'number' && Number.isFinite(v)) return v;
  }
  return null;
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

type ChunkResult = { quotes: Record<string, Quote>; error: string | null };

async function sparkChunk(symbols: string[]): Promise<ChunkResult> {
  const url =
    'https://query1.finance.yahoo.com/v8/finance/spark?symbols=' +
    symbols.map(encodeURIComponent).join(',') +
    '&range=1d&interval=5m';
  const { data, error } = await fetchJson(url);
  const out: Record<string, Quote> = {};
  if (!data || typeof data !== 'object') {
    return { quotes: out, error: error || 'upstream returned no object' };
  }

  for (const sym of symbols) {
    const row = (data as any)[sym];
    if (!row || typeof row !== 'object') continue;

    // `fulldayPrice` is Yahoo's own latest; fall back to the series tail.
    const price = num(row.fulldayPrice) ?? lastClose(row.close);
    // `<= 0` and not `=== null`. `num()` accepts 0 because 0 is finite, and a
    // zero that reaches the client values that position at nothing - the exact
    // silent-zero this whole file is written against, arriving through the
    // door marked "valid number". No traded instrument is worth 0.00, so a
    // zero here is a vendor artefact and belongs in `missing`.
    if (price === null || price <= 0) continue;

    // `previousClose` comes back null here while `chartPreviousClose` carries
    // the value. Reading the obvious field name would silently yield null for
    // every symbol and make every day-move unavailable.
    const prevClose = num(row.chartPreviousClose) ?? num(row.previousClose);

    let change = num(row.fulldayChange);
    let changePct = num(row.fulldayChangePercent);
    if (change === null && prevClose !== null) change = price - prevClose;
    if (changePct === null && prevClose !== null && prevClose !== 0) {
      changePct = ((price - prevClose) / prevClose) * 100;
    }

    const ts = Array.isArray(row.timestamp) ? row.timestamp : [];

    // Nulls are dropped, not zero-filled. Yahoo writes null for a five-minute
    // bucket in which nothing traded, and a single zero reaching `low` would
    // draw a candle with a wick to the floor of the chart - the silent-zero
    // this file is written against, in its most visible possible form.
    const closes = (Array.isArray(row.close) ? row.close : []).filter(
      (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0
    );
    const session: Session | null = closes.length
      ? {
          open: closes[0],
          high: Math.max(...closes),
          low: Math.min(...closes),
          // Reported so the caller can tell a one-point session - which carries
          // no range at all - from a full day of them.
          points: closes.length,
        }
      : null;

    out[sym] = {
      price,
      prevClose,
      change,
      changePct,
      asOf: num(ts[ts.length - 1]),
      session,
    };
  }
  return { quotes: out, error: null };
}

type QuotesResult = { quotes: Record<string, Quote>; errors: string[] };

async function quotesFor(symbols: string[]): Promise<QuotesResult> {
  const chunks: string[][] = [];
  for (let i = 0; i < symbols.length; i += CHUNK) {
    chunks.push(symbols.slice(i, i + CHUNK));
  }
  const results = await Promise.all(chunks.map(sparkChunk));
  const quotes = Object.assign({}, ...results.map((r) => r.quotes));
  // One chunk failing must not look like the symbols in it simply not
  // existing. They are reported missing either way; this says which.
  const errors = results
    .map((r, i) =>
      r.error ? `chunk ${i + 1}/${chunks.length} (${chunks[i].length} symbols): ${r.error}` : null
    )
    .filter((x): x is string => x !== null);
  return { quotes, errors };
}

// FX, in the SAME direction the page already uses, which is the inverse of
// what both upstreams return.
//
// sources.fx_rates() is documented "Units of EUR per 1 unit of currency" and
// computes `1.0 / EURUSD=X`, because analyse.value_holdings() does
// `price * units * rate`. Frankfurter's `from=EUR&to=USD` and Yahoo's
// `EURUSD=X` both give EUR->USD (~1.15). Feeding that straight in would
// multiply every USD holding by 1.15 instead of 0.87 - a ~32% overstatement
// that looks entirely plausible on screen. The inversion happens here, once,
// so no caller has to know which way round either vendor answers.
//
// `GBp` is not a typo and not a currency: London quotes in pence, so it is
// GBP/100. The page's own FX table carries it, so this one must too.
async function fxToEur(
  currencies: string[]
): Promise<{ rates: Record<string, number>; source: string | null }> {
  const wanted = Array.from(
    new Set(
      currencies
        .filter((c) => c && c !== 'EUR')
        .map((c) => (c === 'GBp' ? 'GBP' : c))
    )
  );
  if (!wanted.length) return { rates: { EUR: 1.0 }, source: null };

  const invert = (perEur: Record<string, unknown>) => {
    const out: Record<string, number> = {};
    for (const [ccy, v] of Object.entries(perEur)) {
      const n = num(v);
      if (n !== null && n > 0) out[ccy] = 1.0 / n;
    }
    return out;
  };

  let rates: Record<string, number> = {};
  let source: string | null = null;

  const fr = await fetchJson(
    'https://api.frankfurter.app/latest?from=EUR&to=' + wanted.join(',')
  );
  if (fr.data && fr.data.rates && typeof fr.data.rates === 'object') {
    rates = invert(fr.data.rates);
    if (Object.keys(rates).length) source = 'frankfurter';
  }

  // Second source, not a formatting fallback: FX multiplies every non-EUR
  // holding, so it is worth a second keyless vendor when the first is silent.
  if (!source) {
    const q = (await quotesFor(wanted.map((c) => `EUR${c}=X`))).quotes;
    const perEur: Record<string, number> = {};
    for (const c of wanted) {
      const hit = q[`EUR${c}=X`];
      if (hit && hit.price > 0) perEur[c] = hit.price;
    }
    rates = invert(perEur);
    if (Object.keys(rates).length) source = 'yahoo';
  }

  rates.EUR = 1.0;
  if (rates.GBP) rates.GBp = rates.GBP / 100;
  return { rates, source };
}

export default async function handler(request: Request): Promise<Response> {
  // Health probe. Deliberately uses a symbol that is NOT in the book: its whole
  // job is to answer "does Yahoo talk to Vercel's edge IPs at all", and that
  // question should be answerable without naming a single holding.
  if (request.method === 'GET') {
    const probe = await quotesFor(['AAPL']);
    const ok = Boolean(probe.quotes['AAPL']);
    return json(
      {
        ok,
        upstream: ok ? 'reachable' : 'unreachable',
        errors: probe.errors,
        note: ok
          ? 'Yahoo v8 spark answers from this edge region.'
          : 'Yahoo did not answer. The page should fall back to build-time prices.',
      },
      ok ? 200 : 503
    );
  }

  if (request.method !== 'POST') {
    return json({ error: 'GET for health, POST for quotes' }, 405);
  }

  let body: any;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'body must be JSON' }, 400);
  }

  const raw = Array.isArray(body?.symbols) ? body.symbols : null;
  if (!raw) return json({ error: 'expected {"symbols": [...]}' }, 400);

  const symbols = Array.from(
    new Set(
      raw
        .filter((s: unknown): s is string => typeof s === 'string')
        .map((s: string) => s.trim())
        .filter((s: string) => s.length > 0 && s.length < 32)
    )
  ).slice(0, MAX_SYMBOLS) as string[];

  if (!symbols.length) return json({ error: 'no usable symbols' }, 400);

  // `GBp` is a legitimate code here and has a LOWERCASE p, so /^[A-Z]{3}$/
  // rejects it. It did, silently, and because `fxMissing` below was computed
  // from the post-filter list, the response then reported nothing missing
  // while having dropped a currency on the floor. A pence-quoted London
  // holding would have shown unpriced under a clean bill of health.
  const CCY_RE = /^[A-Z]{2}[A-Za-z]$/;
  const rawCcy: string[] = Array.isArray(body?.currencies)
    ? body.currencies.filter((c: unknown): c is string => typeof c === 'string')
    : [];
  const currencies = rawCcy.filter((c) => CCY_RE.test(c));
  // Anything the parser refuses is reported, not dropped. Silence about a
  // rejection is indistinguishable from there being nothing to reject.
  const rejected = rawCcy.filter((c) => !CCY_RE.test(c));

  const [q, fx] = await Promise.all([quotesFor(symbols), fxToEur(currencies)]);
  const quotes = q.quotes;

  const priced = Object.keys(quotes);
  const missing = symbols.filter((s) => !(s in quotes));

  return json({
    // `fetchedAt` is when THIS server answered. Each quote carries its own
    // `asOf` from Yahoo. They are different facts and a page that shows the
    // first while implying the second is the "Built <date>" trap from OCS.
    fetchedAt: Math.floor(Date.now() / 1000),
    quotes,
    // Named explicitly so the caller cannot mistake silence for no-change. A
    // consumer that ignores this and renders only `quotes` will still be right;
    // one that renders a dash for these will be honest.
    missing,
    counts: { asked: symbols.length, priced: priced.length, missing: missing.length },
    // Empty when every chunk answered. Non-empty means the symbols in
    // `missing` are missing because the upstream refused, not because they do
    // not exist - a distinction that is invisible from `missing` alone.
    upstreamErrors: q.errors,
    // Units of EUR per 1 unit of currency - the page's own convention. See
    // fxToEur() for why this is the inverse of what the vendors return.
    fx: fx.rates,
    fxSource: fx.source,
    // Computed from what was ASKED, including codes this endpoint refused to
    // parse, so a caller can never read an empty list as "all present".
    fxMissing: rawCcy.filter((c) => c !== 'EUR' && !(c in fx.rates)),
    fxRejected: rejected,
  });
}
