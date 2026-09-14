import { NextRequest } from 'next/server';

/**
 * Server-side proxy to the Cube REST API.
 *
 * Exists so CUBEJS_API_SECRET never reaches the browser. The dashboard calls
 * /api/cube/load; this route signs the request and forwards it to Cube, which
 * runs alongside in the same SPCS service (localhost:4000).
 *
 * Cube's /load endpoint returns HTTP 200 with {"error":"Continue wait"} while a
 * query is still running. That is a protocol-level poll, not a failure, so it is
 * retried here rather than surfaced to the tile — otherwise every cold query
 * would render as an error.
 */

const CUBE_API_URL = process.env.CUBE_API_URL ?? 'http://localhost:4000/cubejs-api/v1';
const CUBE_API_SECRET = process.env.CUBEJS_API_SECRET ?? '';

// The SPCS ingress proxy cuts a request off at 90s with a plain-text
// "upstream request timeout" body. Giving up just under that keeps the failure
// ours: a clean JSON error the tile can render, instead of an ingress response
// the client cannot parse.
const MAX_WAIT_MS = 75_000;

/** Minimal unsigned-payload HS256 JWT. Cube accepts it in dev mode; in prod the
 *  secret must match, which it does because both come from the same .env.cube. */
async function signToken(): Promise<string> {
  const enc = new TextEncoder();
  const header = { alg: 'HS256', typ: 'JWT' };
  const payload = { exp: Math.floor(Date.now() / 1000) + 3600 };
  const b64 = (o: unknown) =>
    Buffer.from(JSON.stringify(o))
      .toString('base64')
      .replace(/=/g, '')
      .replace(/\+/g, '-')
      .replace(/\//g, '_');
  const data = `${b64(header)}.${b64(payload)}`;
  const key = await crypto.subtle.importKey(
    'raw',
    enc.encode(CUBE_API_SECRET),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(data));
  const sigB64 = Buffer.from(sig)
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  return `${data}.${sigB64}`;
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const endpoint = path.join('/');
  const body = await req.text();
  const token = await signToken();

  const deadline = Date.now() + MAX_WAIT_MS;
  let last = '';

  while (Date.now() < deadline) {
    const res = await fetch(`${CUBE_API_URL}/${endpoint}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: token },
      body,
      cache: 'no-store',
    });
    last = await res.text();

    // Cube signals "still running" with a 200 and this exact error string.
    if (res.ok && last.includes('Continue wait')) {
      await new Promise((r) => setTimeout(r, 800));
      continue;
    }

    // Anything non-JSON here is an infrastructure response, not Cube's -- most
    // often the SPCS ingress timeout. Wrap it so the client always gets JSON.
    try {
      JSON.parse(last);
    } catch {
      return Response.json(
        { error: `Upstream returned non-JSON (${res.status}): ${last.slice(0, 200)}` },
        { status: 502 },
      );
    }

    return new Response(last, {
      status: res.status,
      headers: { 'content-type': 'application/json' },
    });
  }

  return Response.json(
    {
      error:
        `Query still running after ${MAX_WAIT_MS / 1000}s and was abandoned. ` +
        `On the Postgres source this is expected once the window gets large, and ` +
        `not for want of an index: the fact table is indexed on order_date, but ` +
        `each tile's COUNT(DISTINCT order_id) must sort every matching row, and ` +
        `once that sort no longer fits in memory it spills to disk and cost jumps ` +
        `by orders of magnitude. Short ranges return in about a second; long ones ` +
        `may not finish at all. Snowflake stays flat across every range because it ` +
        `prunes by the clustering key instead of scanning.\n\nIf a SHORT range ` +
        `fails too, it is contention rather than volume - every tile queries at ` +
        `once, and a previous long-range visit can still be occupying Postgres. ` +
        `Wait a minute and reload.`,
    },
    { status: 504 },
  );
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const token = await signToken();
  const res = await fetch(`${CUBE_API_URL}/${path.join('/')}`, {
    headers: { authorization: token },
    cache: 'no-store',
  });
  return new Response(await res.text(), {
    status: res.status,
    headers: { 'content-type': 'application/json' },
  });
}
