// Cloudflare Pages Function: lists the Gemini models this key can actually use.
//
// The app's model selector was a hardcoded list, and hardcoded lists go stale
// silently: gemini-3-pro-preview sat in the picker long after Google retired it,
// and the only symptom was a 404 nobody had reason to trigger. This endpoint
// exists so the list can be checked against reality instead of memory.
//
// Read-only and costs no generation quota, so it is a far smaller thing to have
// public than the generate endpoint next door. The same origin check applies,
// with the same honest caveat: it raises effort, it is not security.

const json = (status, obj) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" }
  });

export async function onRequestGet(context) {
  const { request, env } = context;

  if (!env.GEMINI_API_KEY) {
    return json(503, {
      error: { message: "GEMINI_API_KEY is not set on this Pages project" }
    });
  }

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

  const upstream = await fetch(
    "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
    { headers: { "x-goog-api-key": env.GEMINI_API_KEY } }
  );

  if (!upstream.ok) {
    // Verbatim, for the same reason the generate endpoint passes errors through.
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" }
    });
  }

  const data = await upstream.json();
  // Trimmed to what a picker needs. The full response carries token limits and
  // descriptions for every model on the account, which is a lot of bytes to
  // send a phone for a three-item list.
  const models = (data.models || [])
    .filter((m) => (m.supportedGenerationMethods || []).indexOf("generateContent") >= 0)
    .map((m) => ({
      id: String(m.name || "").replace(/^models\//, ""),
      label: m.displayName || ""
    }));

  return json(200, { models });
}

export async function onRequest(context) {
  if (context.request.method === "GET") return onRequestGet(context);
  return json(405, { error: { message: "Use GET" } });
}
