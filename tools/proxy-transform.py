#!/usr/bin/env python3
"""Route Gemini through the Pages Function, keeping a pasted key as an override.

Run from the repository root:

    python3 tools/proxy-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

The key moves to an encrypted Pages environment variable and the browser talks
to /api/gemini instead of Google. A key pasted in Settings still overrides that
and goes direct: the app is tested at a driving range, and being able to get
working again there without a computer is worth one branch.

That override is also the trap. A key left in localStorage would silently take
precedence over the proxy and every symptom would be attributed to the wrong
half of the system, so the route in use is named in the log, on the boot line,
in the diagnostics header and in Settings.

Three call sites in the app become two helpers plus one shared body shape.
"No API key" stops meaning "no AI": the geometric fallback now belongs to a
failed or unconfigured proxy, which is what invariant 6's third outcome
describes from here on.
"""

import io
import sys

SRC = 'index.html'
src = io.open(SRC, encoding='utf-8').read()
n = 0


def sub(a, b, label):
    global src, n
    c = src.count(a)
    if c != 1:
        sys.stderr.write('ANCHOR FAIL (found %d): %s\n' % (c, label))
        sys.exit(1)
    src = src.replace(a, b)
    n += 1


# 1. one place that decides the route, so nothing can disagree about it
sub(r'''    async function callGemini(prompt, base64Data, timeoutMs, thinkingLevel) {
      if (!userApiKey) return null;
      const url = "https://generativelanguage.googleapis.com/v1beta/models/" +
                  geminiModel + ":generateContent";
''',
r'''    // The proxy keeps the key on the server; a key pasted in Settings overrides
    // it and goes direct. One place decides, so no two call sites can disagree
    // about which is in play -- and geminiRoute() is what the log reports.
    const GEMINI_PROXY_URL = "/api/gemini";
    function geminiRoute() { return userApiKey ? "direct (your key)" : "proxy"; }
    function geminiUrl() {
      return userApiKey
        ? "https://generativelanguage.googleapis.com/v1beta/models/" + geminiModel + ":generateContent"
        : GEMINI_PROXY_URL;
    }
    function geminiHeaders() {
      const h = { "Content-Type": "application/json" };
      // The proxy supplies the key itself; sending one would be pointless here
      // and would put it back on the wire this change exists to take it off.
      if (userApiKey) h["x-goog-api-key"] = userApiKey;
      return h;
    }
    // Direct calls take Google's payload as the whole body; the proxy needs the
    // model too, because it validates that against a list rather than trusting
    // a string that ends up in a URL path.
    function geminiBody(payload) {
      return JSON.stringify(userApiKey ? payload : { model: geminiModel, payload: payload });
    }

    async function callGemini(prompt, base64Data, timeoutMs, thinkingLevel) {
      const url = geminiUrl();
''', 'route helpers')

sub(r'''      logLine("info", "Gemini request", { model: geminiModel, thinking: thinkingLevel || "none", imageKB: Math.round((base64Data || "").length * 0.75 / 1024), timeoutMs: timeoutMs || 20000 });''',
r'''      logLine("info", "Gemini request", { route: geminiRoute(), model: geminiModel, thinking: thinkingLevel || "none", imageKB: Math.round((base64Data || "").length * 0.75 / 1024), timeoutMs: timeoutMs || 20000 });''', 'log route on request')

sub(r'''        const res = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-goog-api-key": userApiKey
          },
          body: JSON.stringify(payload),
          signal: controller.signal
        });''',
r'''        const res = await fetch(url, {
          method: "POST",
          headers: geminiHeaders(),
          body: geminiBody(payload),
          signal: controller.signal
        });''', 'scan call uses helpers')

# 2. the benchmark tests whichever route is live, which is the one worth testing
sub(r'''    async function testApiKey() {
      if (!userApiKey) {
        logLine("warn", "API test skipped: no key saved in Settings");
        renderLog();
        return;
      }
      const url = "https://generativelanguage.googleapis.com/v1beta/models/" + geminiModel + ":generateContent";''',
r'''    async function testApiKey() {
      const url = geminiUrl();''', 'benchmark drops the key guard')

sub(r'''      logLine("info", "Latency benchmark -> " + geminiModel + " from " + location.origin);''',
r'''      // Whichever route is live is the one worth measuring: via the proxy this
      // also proves the secret is set, which is otherwise invisible from a phone.
      logLine("info", "Latency benchmark -> " + geminiModel + " via " + geminiRoute() + " from " + location.origin);''', 'benchmark logs route')

sub(r'''          const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json", "x-goog-api-key": userApiKey },
            body: JSON.stringify(payload)
          });''',
r'''          const res = await fetch(url, {
            method: "POST",
            headers: geminiHeaders(),
            body: geminiBody(payload)
          });''', 'benchmark uses helpers')

# 3. "no key" no longer means "no AI"
sub(r'''      scanBurstProgress.textContent = userApiKey ? "Analyzing address stance" : "Using geometric fallback";''',
r'''      scanBurstProgress.textContent = "Analyzing address stance";''', 'scan overlay text')

sub(r'''      const aiOk = !!(ai && ai.detected);
      let failReason = "";
      if (userApiKey) {
        if (!ai) failReason = lastGeminiError || "No response";
        else if (!ai.detected) failReason = "No stance found in frame";
      }''',
r'''      const aiOk = !!(ai && ai.detected);
      // A scan is always attempted now, so a failure is always worth naming --
      // there is no longer a "no key, nothing was tried" case to stay quiet for.
      let failReason = "";
      if (!ai) failReason = lastGeminiError || "No response";
      else if (!ai.detected) failReason = "No stance found in frame";''', 'fail reason always reported')

sub(r'''          rating: userApiKey
            ? "Review unavailable" + (lastGeminiError ? " — " + lastGeminiError : "")
            : "Add an API key for AI review",''',
r'''          rating: "Review unavailable" + (lastGeminiError ? " — " + lastGeminiError : ""),''', 'coach fallback text')

# 4. the route is named everywhere the key used to be
sub(r'''        "model:  " + geminiModel + "  key=" + (userApiKey ? "set (" + userApiKey.length + " chars)" : "NONE"),''',
r'''        "gemini: " + geminiModel + "  route=" + geminiRoute() +
          (userApiKey ? "  key=set (" + userApiKey.length + " chars)" : "  key=server-side"),''', 'diagnostics header')

sub(r'''        key: userApiKey ? "set (" + userApiKey.length + " chars)" : "NONE"''',
r'''        route: geminiRoute(),
        key: userApiKey ? "set (" + userApiKey.length + " chars)" : "server-side"''', 'boot line')

sub(r'''      showToast(userApiKey ? "Saved. Using " + geminiModel : "Running without AI review");''',
r'''      showToast(userApiKey
        ? "Saved. Using your own key with " + geminiModel
        : "Cleared. Using the server key with " + geminiModel);''', 'settings toast')

sub(r'''    const BUILD = "2026-09-05-review2";''',
r'''    const BUILD = "2026-09-06-proxy";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
