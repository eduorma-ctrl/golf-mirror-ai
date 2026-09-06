// Cloudflare Pages Function: proxies Gemini so the API key stays on the server.
//
// The key lives in the Pages project as an encrypted environment variable named
// GEMINI_API_KEY (Settings -> Environment variables -> Add -> Encrypt). It is
// never sent to the browser and never appears in the repository.
//
// What this buys, and what it costs. The key is no longer readable from a phone
// that has the app open. In exchange the endpoint is public: anyone who finds
// this URL can spend the quota. The origin check below raises the effort from
// "paste the URL into curl" to "set one header", which is worth having and is
// not security. Real protection is a rate limit backed by KV, deliberately not
// built here.
//
// The client sends { model, payload }. The model is validated against a list
// rather than interpolated, because it lands in a URL path and an unvalidated
// string there is a path-traversal hole.
//
// Google's response is returned verbatim, status and body. The app's diagnostics
// log surfaces Google's own error text -- a 403 is almost always a key
// restriction or a disabled API, and only the body says which -- and a proxy
// that replaced that with a tidy message of its own would cost exactly the
// debugging the log exists to provide.

// MUST stay in step with GEMINI_MODELS in index.html. A name in the picker but
// not here is a 400 the golfer cannot explain; a name here but not in the picker
// is merely dead weight. /api/models lists what the key can actually reach.
const ALLOWED_MODELS = new Set([
  "gemini-3.7-flash",
  "gemini-3.8-flash",
  "gemini-3.1-flash-lite"
]);

// Images arrive as base64 at roughly 60-95KB; the coach review is text-only.
// A megabyte is generous for both and stops a stranger posting something huge.
const MAX_BODY_BYTES = 1024 * 1024;

const json = (status, obj) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" }
  });

export async function onRequestPost(context) {
  const { request, env } = context;

  if (!env.GEMINI_API_KEY) {
    // Said plainly, because the alternative is a scan that fails at the range
    // with nothing explaining why. This is the message you get when the secret
    // has not been added to the Pages project yet.
    return json(503, {
      error: { message: "GEMINI_API_KEY is not set on this Pages project" }
    });
  }

  // Best-effort origin check. A same-origin fetch always carries Origin; a
  // request without one is not necessarily hostile (curl sends none), so an
  // absent header is allowed and only a mismatched one is refused.
  const origin = request.headers.get("Origin");
  if (origin) {
    try {
      if (new URL(origin).host !== new URL(request.url).host) {
        return json(403, { error: { message: "Cross-origin requests are not accepted" } });
      }
    } catch (e) {
      return json(403, { error: { message: "Malformed Origin header" } });
    }
  }

  const raw = await request.text();
  if (raw.length > MAX_BODY_BYTES) {
    return json(413, { error: { message: "Request body too large" } });
  }

  let body;
  try {
    body = JSON.parse(raw);
  } catch (e) {
    return json(400, { error: { message: "Body is not valid JSON" } });
  }

  const model = body && body.model;
  if (!ALLOWED_MODELS.has(model)) {
    return json(400, {
      error: { message: "Unknown model: " + String(model) }
    });
  }
  if (!body.payload || typeof body.payload !== "object") {
    return json(400, { error: { message: "Missing payload" } });
  }

  const upstream = await fetch(
    "https://generativelanguage.googleapis.com/v1beta/models/" +
      encodeURIComponent(model) + ":generateContent",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": env.GEMINI_API_KEY
      },
      body: JSON.stringify(body.payload)
    }
  );

  // Verbatim, including errors. See the note at the top of this file.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" }
  });
}

// Anything that is not a POST gets a clear answer rather than the SPA's
// index.html, which would otherwise reach the client as unparseable "JSON".
export async function onRequest(context) {
  if (context.request.method === "POST") return onRequestPost(context);
  return json(405, { error: { message: "Use POST" } });
}
