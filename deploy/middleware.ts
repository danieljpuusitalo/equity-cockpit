/* The only thing standing between the open internet and Daniel's whole book.
 *
 * The deployed page is `out/dashboard.html` verbatim: every ISIN, account
 * number, unit count and euro amount. The repo is public and stays publishable
 * because the book lives in gitignored files; the deployment has no such
 * structure to lean on, so it leans on this file instead.
 *
 * Three properties, in the order they matter:
 *
 *   1. It fails CLOSED. A missing or empty COCKPIT_PASSWORD denies every
 *      request rather than waving them through. The failure mode of an auth
 *      layer that fails open is that it looks exactly like a working one -
 *      the page loads, nobody is asked for anything, and there is no error to
 *      notice. This repo has met that bug class repeatedly under a different
 *      name: a derived status claiming more than it means.
 *   2. It matches EVERYTHING. `/:path*` covers the page, the favicon, the 404
 *      and any path a future version adds. An allowlist of paths would have to
 *      be maintained in step with the deployment, and would be wrong the first
 *      time it was not.
 *   3. It compares digests, not strings. Equal-length, constant-time, so a
 *      wrong guess takes as long as a right one whatever its length.
 */
import { next } from '@vercel/edge';

export const config = {
  // Everything. See property 2 above before narrowing this.
  matcher: '/:path*',
};

const REALM = 'Equity cockpit';

function challenge(reason: string): Response {
  // 401 with no body. The reason is a response header rather than prose in the
  // page, so the deployment can be diagnosed without any of it being readable
  // by whoever is knocking.
  return new Response(null, {
    status: 401,
    headers: {
      'WWW-Authenticate': `Basic realm="${REALM}", charset="UTF-8"`,
      'X-Cockpit-Denied': reason,
      'Cache-Control': 'no-store',
      'X-Robots-Tag': 'noindex, nofollow, noarchive',
    },
  });
}

async function digest(value: string): Promise<Uint8Array> {
  const bytes = new TextEncoder().encode(value);
  return new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
}

// Both arguments are 32-byte digests, so this never returns early on length
// and never short-circuits on the first differing byte.
function sameDigest(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export default async function middleware(request: Request): Promise<Response> {
  const expected = process.env.COCKPIT_PASSWORD;
  // Property 1. Not a misconfiguration to route around - a closed door.
  if (!expected) return challenge('unconfigured');

  const header = request.headers.get('authorization') || '';
  const [scheme, encoded] = header.split(' ');
  if (scheme !== 'Basic' || !encoded) return challenge('no-credentials');

  let supplied: string;
  try {
    // "user:password". The user half is ignored on purpose: there is one
    // reader, and a username is a second thing to remember that protects
    // nothing. Everything after the FIRST colon is the password, so a password
    // containing a colon still works.
    const decoded = atob(encoded);
    const colon = decoded.indexOf(':');
    supplied = colon === -1 ? '' : decoded.slice(colon + 1);
  } catch {
    return challenge('undecodable');
  }

  const [a, b] = await Promise.all([digest(supplied), digest(expected)]);
  if (!sameDigest(a, b)) return challenge('bad-credentials');

  // Past the door. The book is still not something a cache, a proxy or a
  // search engine should be holding on to.
  const response = next();
  response.headers.set('Cache-Control', 'private, no-store, max-age=0');
  response.headers.set('X-Robots-Tag', 'noindex, nofollow, noarchive');
  response.headers.set('Referrer-Policy', 'no-referrer');
  return response;
}
