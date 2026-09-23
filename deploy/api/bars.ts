// Intraday candles for the one symbol on screen, for the 1D and 5D chart ranges.
//
// The daily series the page is built with has one candle per session, so on a
// year-wide chart a live price moves one bar out of ~250 and the picture looks
// frozen. Real five- and fifteen-minute bars are what make the chart move with
// the price. Yahoo's v8 chart endpoint serves them keyless, like the spark
// endpoint behind /api/quotes.
//
//   POST /api/bars  {"symbol": "ASML.AS", "range": "1d" | "5d"}
//
// Same gate as /api/quotes: deploy/middleware.ts matches '/:path*', so an
// anonymous caller is refused before this runs. POST for the same reason too -
// a symbol in a query string lands in request logs, and which symbol gets
// looked at is a view onto the book.
//
// A bucket Yahoo reports with any null or non-positive OHLC value is DROPPED,
// never zero-filled. Yahoo writes nulls for a bucket in which nothing traded;
// a zero reaching `low` would draw a wick to the floor of the chart.

export const config = { runtime: 'edge' };

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36';
const UPSTREAM_TIMEOUT_MS = 8000;

// 5d at five minutes is ~500 bars for a European listing, which is more than a
// chart of that width can draw as candles. Fifteen minutes keeps them legible.
const INTERVAL: Record<string, string> = { '1d': '5m', '5d': '15m' };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'private, no-store, max-age=0',
      'X-Robots-Tag': 'noindex, nofollow',
    },
  });
}

function pos(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null;
}

export default async function handler(request: Request): Promise<Response> {
  if (request.method !== 'POST') {
    return json({ error: 'POST {"symbol": ..., "range": "1d" | "5d"}' }, 405);
  }
  let body: any;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'body must be JSON' }, 400);
  }
  const symbol = typeof body?.symbol === 'string' ? body.symbol.trim() : '';
  if (!symbol || symbol.length >= 32) return json({ error: 'no usable symbol' }, 400);
  const range = body?.range === '5d' ? '5d' : '1d';
  const interval = INTERVAL[range];

  const url =
    'https://query1.finance.yahoo.com/v8/finance/chart/' +
    encodeURIComponent(symbol) +
    `?range=${range}&interval=${interval}&includePrePost=false`;

  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), UPSTREAM_TIMEOUT_MS);
  let data: any = null;
  let error: string | null = null;
  try {
    const r = await fetch(url, {
      signal: ctl.signal,
      headers: { 'User-Agent': UA, Accept: 'application/json' },
    });
    if (!r.ok) {
      const t = await r.text().catch(() => '');
      error = `HTTP ${r.status} ${t.slice(0, 160)}`.trim();
    } else {
      data = await r.json();
    }
  } catch (e: any) {
    error = e?.name === 'AbortError' ? 'timeout' : String(e?.message || 'fetch failed');
  } finally {
    clearTimeout(timer);
  }

  const res = data?.chart?.result?.[0];
  if (!res) {
    // An empty answer is reported as one, with the reason, so the page can say
    // "no intraday data" rather than draw an empty chart as if nothing traded.
    const why = error || data?.chart?.error?.description || 'upstream returned no series';
    return json({ symbol, range, interval, bars: [], dropped: 0, error: why });
  }

  const ts: unknown[] = Array.isArray(res.timestamp) ? res.timestamp : [];
  const q = res.indicators?.quote?.[0] || {};
  const bars: number[][] = [];
  let dropped = 0;
  for (let i = 0; i < ts.length; i++) {
    const t = typeof ts[i] === 'number' ? (ts[i] as number) : null;
    const o = pos(q.open?.[i]);
    const h = pos(q.high?.[i]);
    const l = pos(q.low?.[i]);
    const c = pos(q.close?.[i]);
    if (t === null || o === null || h === null || l === null || c === null) {
      dropped++;
      continue;
    }
    bars.push([t, o, Math.max(h, o, c), Math.min(l, o, c), c]);
  }

  return json({
    symbol,
    range,
    interval,
    // Unix seconds, UTC, as Yahoo gave them. The page shifts them for display.
    bars,
    // Counted, so a series that came back thin is distinguishable from a
    // quiet one.
    dropped,
    currency: typeof res.meta?.currency === 'string' ? res.meta.currency : null,
    fetchedAt: Math.floor(Date.now() / 1000),
    error: bars.length ? null : error || 'no complete bars in the series',
  });
}
