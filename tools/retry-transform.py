#!/usr/bin/env python3
"""Retry a busy model, then fall back a generation, inside the same time budget.

Run from the repository root:

    python3 tools/retry-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

The newest model answers "busy" intermittently -- observed live: one 503, then
three successes seconds later. Switching models by hand is a workaround for
something that resolves itself in about a second, and it has to be done standing
at the mat.

So: the picked model gets one retry, then each remaining model in the list gets
one attempt. Only transient failures qualify -- 429 and 5xx and network errors.
A 400 or 403 fails identically everywhere, so trying two more models would waste
the golfer's time to learn nothing.

The timeout becomes a budget for the whole sequence rather than for one attempt.
Retrying inside the old per-call timeout would have let a 40s scan become two
minutes, which is worse than the failure it fixes. This works because the two
failure modes spend the budget differently: a 503 comes back in about two
seconds and leaves room for several more attempts, while a timeout consumes the
budget and correctly leaves none.

A fallback answer is announced. The result then came from a model the picker is
not showing, and silently attributing it to the selected one would make the A/B
comparison the whole picker exists for meaningless.
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


# 1. the route helpers take a model, since an attempt may not use the picked one
sub(r'''    function geminiUrl() {
      return userApiKey
        ? "https://generativelanguage.googleapis.com/v1beta/models/" + geminiModel + ":generateContent"
        : GEMINI_PROXY_URL;
    }''',
r'''    function geminiUrl(model) {
      return userApiKey
        ? "https://generativelanguage.googleapis.com/v1beta/models/" + (model || geminiModel) + ":generateContent"
        : GEMINI_PROXY_URL;
    }''', 'geminiUrl takes model')

sub(r'''    function geminiBody(payload) {
      return JSON.stringify(userApiKey ? payload : { model: geminiModel, payload: payload });
    }''',
r'''    function geminiBody(payload, model) {
      return JSON.stringify(userApiKey ? payload : { model: model || geminiModel, payload: payload });
    }''', 'geminiBody takes model')

# 2. one attempt, and the sequence that drives it
sub(r'''    async function callGemini(prompt, base64Data, timeoutMs, thinkingLevel) {
      const url = geminiUrl();

      const generationConfig''',
r'''    // Worth another go: the request never reached a verdict. A 400 or 403 is a
    // verdict -- the same one every model would give -- so it stops the sequence.
    const TRANSIENT_STATUSES = new Set([429, 500, 502, 503, 504]);
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    // The picked model first, then the rest in list order.
    function modelPlan(primary) {
      const rest = GEMINI_MODELS.map((m) => m.id).filter((id) => id !== primary);
      return [primary].concat(rest);
    }

    async function geminiAttempt(model, payload, budgetMs) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), budgetMs);
      try {
        const res = await fetch(geminiUrl(model), {
          method: "POST",
          headers: geminiHeaders(),
          body: geminiBody(payload, model),
          signal: controller.signal
        });
        clearTimeout(timeoutId);
        if (!res.ok) {
          // Surface Google's own explanation, not just the status code. A 403 is
          // almost always a key restriction or a disabled API, and only the body
          // says which -- and you cannot open devtools on a phone at the range.
          let detail = "";
          try {
            const body = await res.text();
            try {
              const j = JSON.parse(body);
              detail = (j && j.error && (j.error.message || j.error.status)) || "";
            } catch (eParse) { detail = body; }
          } catch (eRead) {}
          detail = String(detail).replace(/\s+/g, " ").trim().slice(0, 160);
          return {
            ok: false,
            status: res.status,
            detail: detail || "(no body)",
            transient: TRANSIENT_STATUSES.has(res.status)
          };
        }
        const json = await res.json();
        const raw = json && json.candidates && json.candidates[0] &&
                    json.candidates[0].content && json.candidates[0].content.parts &&
                    json.candidates[0].content.parts[0] && json.candidates[0].content.parts[0].text;
        if (!raw) return { ok: false, status: 200, detail: "Empty response", transient: false };
        try {
          return { ok: true, parsed: JSON.parse(raw.replace(/```json/g, "").replace(/```/g, "").trim()) };
        } catch (eJson) {
          // Not retried: a model that formats badly tends to keep doing it, and
          // spending the budget to confirm that costs the golfer their answer.
          return { ok: false, status: 200, detail: "Unparseable JSON from model", transient: false };
        }
      } catch (e) {
        clearTimeout(timeoutId);
        const aborted = e && e.name === "AbortError";
        return {
          ok: false,
          status: 0,
          detail: aborted ? "Timed out" : "Request failed",
          transient: !aborted,
          aborted: aborted
        };
      }
    }

    async function callGemini(prompt, base64Data, timeoutMs, thinkingLevel) {
      const generationConfig''', 'attempt helper')

sub(r'''      logLine("info", "Gemini request", { route: geminiRoute(), model: geminiModel, thinking: thinkingLevel || "none", imageKB: Math.round((base64Data || "").length * 0.75 / 1024), timeoutMs: timeoutMs || 20000 });

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs || 20000);
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: geminiHeaders(),
          body: geminiBody(payload),
          signal: controller.signal
        });
        clearTimeout(timeoutId);
        if (!res.ok) {
          // Surface Google's own explanation, not just the status code. A 403 is
          // almost always a key restriction or a disabled API, and only the body
          // says which -- and you cannot open devtools on a phone at the range.
          let detail = "";
          try {
            const body = await res.text();
            try {
              const j = JSON.parse(body);
              detail = (j && j.error && (j.error.message || j.error.status)) || "";
            } catch (eParse) { detail = body; }
          } catch (eRead) {}
          detail = String(detail).replace(/\s+/g, " ").trim().slice(0, 160);
          console.warn("Gemini HTTP " + res.status, detail);
          logLine("error", "Gemini HTTP " + res.status, detail || "(no body)");
          lastGeminiError = "HTTP " + res.status + (detail ? ": " + detail : " on " + geminiModel);
          return null;
        }
        logLine("ok", "Gemini HTTP " + res.status);
        const json = await res.json();
        const raw = json && json.candidates && json.candidates[0] &&
                    json.candidates[0].content && json.candidates[0].content.parts &&
                    json.candidates[0].content.parts[0] && json.candidates[0].content.parts[0].text;
        if (!raw) { lastGeminiError = "Empty response"; return null; }
        lastGeminiError = "";
        return JSON.parse(raw.replace(/```json/g, "").replace(/```/g, "").trim());
      } catch (e) {
        clearTimeout(timeoutId);
        const name = e && e.name;
        lastGeminiError = name === "AbortError" ? "Timed out" : "Request failed";
        logLine("error", "Gemini call threw", name + ": " + (e && e.message));
        console.warn("Gemini call failed:", name);
        return null;
      }
    }''',
r'''      // A budget for the whole sequence, not for one attempt. Retrying inside the
      // old per-call timeout would have let a 40s scan run to two minutes, which
      // is worse than the failure it fixes.
      const totalBudget = timeoutMs || 20000;
      const deadline = performance.now() + totalBudget;
      const plan = modelPlan(geminiModel);
      const picked = geminiModel;

      logLine("info", "Gemini request", {
        route: geminiRoute(), model: picked, thinking: thinkingLevel || "none",
        imageKB: Math.round((base64Data || "").length * 0.75 / 1024),
        budgetMs: totalBudget, plan: plan.join(" -> ")
      });

      let attemptNo = 0;
      let last = null;

      for (let i = 0; i < plan.length; i++) {
        const model = plan[i];
        // The picked model earns a second go because a 503 on it is usually gone
        // a second later. A fallback that is also busy is a queue, not a blip.
        const tries = i === 0 ? 2 : 1;

        for (let t = 0; t < tries; t++) {
          const remaining = deadline - performance.now();
          // Below this an attempt cannot finish, and starting one only converts a
          // useful error message into "Timed out".
          if (remaining < 3000) {
            logLine("warn", "Gemini budget spent", { attempts: attemptNo, ofMs: totalBudget });
            i = plan.length;
            break;
          }

          attemptNo++;
          const r = await geminiAttempt(model, payload, remaining);
          last = r;

          if (r.ok) {
            if (model !== picked) {
              // The answer came from a model the picker is not showing. Saying so
              // keeps the comparison the picker exists for honest.
              logLine("warn", "Answered by fallback model", { picked: picked, used: model, attempts: attemptNo });
              showToast(picked.replace("gemini-", "") + " busy - used " + model.replace("gemini-", ""), 4000);
            } else if (attemptNo > 1) {
              logLine("ok", "Recovered on retry", { model: model, attempts: attemptNo });
            }
            lastGeminiError = "";
            return r.parsed;
          }

          logLine(r.transient ? "warn" : "error",
            "Gemini attempt " + attemptNo + " (" + model + ") " + (r.status || "network"),
            r.detail);

          if (!r.transient) { i = plan.length; break; }
          if (r.aborted) { i = plan.length; break; }
          // Brief, and deliberately shorter than the budget check above: the point
          // is to let a blip pass, not to wait out an outage.
          if (t + 1 < tries) await sleep(600);
        }
      }

      lastGeminiError = last
        ? (last.status ? "HTTP " + last.status + ": " + last.detail : last.detail)
        : "No response";
      logLine("error", "Gemini failed after " + attemptNo + " attempt(s)", lastGeminiError);
      return null;
    }''', 'retry sequence')

sub(r'''    const BUILD = "2026-09-06-flash3";''',
r'''    const BUILD = "2026-09-06-retry";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
