# Golf Mirror AI — working notes

Single-file web app: `index.html`, no build step, no dependencies beyond two CDNs.
Live at https://golf-mirror-ai.pages.dev — Cloudflare Pages, auto-deploys on push
to `main`, usually live within ~60s.

Down-the-line swing mirror for solo range practice: draggable shaft-plane, Hogan
corridor, head-stability ring and tush line over a live camera feed, with a
hands-free countdown, delayed replay, and Gemini vision for stance detection.

---

## Rolling back

| Ref | What it is |
| --- | --- |
| `v1.0-working` | Annotated tag on the last known-good build (`2026-09-05-tushbody`) |
| `stable` | Branch at the same commit. A tag cannot be deployed by Pages; a branch can. |
| Cloudflare dashboard | Deployments → *Rollback to this deployment*. Fastest, needs no git. |

Never commit to `stable`. Build on `main`. If `main` breaks, either reset it to
`stable` or point Pages at `stable`.

---

## Debug with the log, not with guesses

Tap the terminal icon in the header.

It records boot geometry (DPR, canvas backing vs CSS size), camera negotiation, the
snapshot crop rect, every Gemini request and response *including Google's own error
text*, the raw coordinates returned, and those same points after mapping. **Copy**
exports it with device context. API keys are redacted on the way in.

It also shows **the exact frame sent to Gemini, with the returned coordinates drawn
on it**. Look at that picture before theorising. It separates the two failure modes
that are otherwise indistinguishable:

- markers land correctly on the image → detection is fine, the bug is in the mapping
- markers land wrong on the image → the model genuinely misread the frame

Not doing this cost several rounds of blind prompt-tuning. The overlay-contamination
bug below was invisible in the numbers and obvious in the picture.

**Test API key** runs the same trivial prompt at default / minimal / low thinking and
logs each duration. No image and no golf stance needed, so it is runnable anywhere.

Every log line carries `build:`. Bump `BUILD` on any deploy worth identifying.

---

## Gemini config — verified against the live API

| Setting | Value |
| --- | --- |
| Default model | `gemini-3.7-flash` |
| Also selectable | `gemini-3-pro-preview`, `gemini-3-flash-preview` |
| Thinking | `generationConfig.thinkingConfig.thinkingLevel` — **nested** |
| Stance scan | thinking `low`, 40s timeout |
| Coach review | thinking `medium`, 60s timeout |
| Coordinates | Gemini's native **0–1000** integer scale, not 0.0–1.0 |
| Auth | `x-goog-api-key` header, not a URL query param |
| Image | 1024px max width, JPEG 0.88 (~60–95KB) |

Never add `temperature`, `top_p` or `top_k` — Gemini 3.x rejects them outright.

`thinking_level` as a **top-level** field is invalid and 400s with
`Unknown name "thinking_level" at 'generation_config'`. Every call failed this way
and fell back silently. It must stay nested under `thinkingConfig`.

Timeouts are deliberately generous. A trivial text-only call on this account
measured 7.0–9.8s, so 20s was never enough for an image request. This costs the
golfer nothing: the snapshot is captured *before* the request, so they are waiting
for guides to appear, not holding the stance.

---

## Invariants that are easy to break

1. **Never send the model a frame with the guides drawn on it.** `render()` paints
   the overlays onto the same canvas the snapshot is cropped from. Feeding those
   back asks the model to locate features while showing it our own previous answers
   for those exact features — it dutifully returns the overlay position at 90–96
   confidence. `snapshotFrame()` is a promise that `render()` resolves in the gap
   between `ctx.restore()` and `drawGuides()`. Keep it that way. The stalled-render
   fallback redraws from the camera for the same reason.

2. **Do not flip x for the mirror.** The mirror is already baked into the canvas
   pixels when the video is drawn, and `drawGuides()` runs after `ctx.restore()`, so
   the snapshot and the guides are in the same screen space. Flipping applies a
   second mirror and puts everything on the wrong side.

3. **Derive the backing-store scale from the canvas, never from
   `devicePixelRatio`.** `resizeCanvas()` caps DPR at 2, so on a DPR-3 phone the raw
   value cropped 1.5× too large and 1.5× too far right — half the crop fell outside
   the canvas and the golfer was partly cut out.

4. **Apply sanity clamps in video-frame space, before mapping to canvas space.**
   The ranges describe where a body part sits within the picture. Applied after
   mapping, letterboxing drags valid points off the body.

5. **Shrink the shaft extension proportionally.** Clamping x and y independently
   bends the line and corrupts the shaft-angle readout, which is the core metric.

6. **A failed scan must never render as a lock.** Three outcomes stay visibly
   distinct: real detection (locked + confidence), no API key (default + geometric
   guides), error or empty frame (No lock + the actual reason, existing guides left
   untouched). A confident-looking wrong answer is worse than a visible failure.

7. **The tush line must sit on the golfer.** The model will otherwise latch onto
   background objects — it once put it on a backpack on the floor. The prompt names
   furniture, bags, beds, walls and doors as *not the golfer*, and the model may set
   `tushDetected: false`, in which case the existing line is kept rather than moved
   to a guess.

---

## Fixed, do not reintroduce

| Bug | Fix |
| --- | --- |
| `thinking_level` top-level → every call 400s, silent fallback to canned coords | nested under `thinkingConfig` |
| Snapshot cropped at uncapped DPR against a DPR-2 canvas | scale derived from `canvas.width / clientWidth` |
| Coordinates requested as 0.0–1.0 | Gemini's native 0–1000, descaled on receipt |
| Coordinates mapped ignoring letterboxing | mapped through `capturedVideoRect` |
| Mirror undone a second time in code | removed; pixels already mirrored |
| Failure rendered as a confident lock | three distinct outcomes |
| 20s timeout vs ~9s baseline latency | 40s / 60s, smaller image |
| **Guide overlays baked into the frame sent to the model** | snapshot taken before `drawGuides()` |
| Model could not decline the tush line, so it always guessed | `tushDetected`, existing line kept |
| Tush line locking onto background objects | prompt states it must be on the body outline |
| Frame viewer canvas 688px tall in a 636px viewport, hiding Copy | fits width *and* 38vh |
| Scan before layout → 1×1 image through a zero-sized rect | readiness guard |
| `DOMContentLoaded` never fired (script at end of body) | `boot()` checks `readyState` |
| Camera auto-started on load; iOS blocks it | starts from a user gesture |
| Fixed `h-full` broke when the mobile URL bar collapsed | `100dvh` |
| Header buttons overflowed narrow screens | horizontal scroll, labels hidden below `sm` |
| Canvas ignored devicePixelRatio | DPR-aware, capped at 2 |
| Video stretched, breaking overlay geometry | `drawContain()` |
| Drag handles moved the wrong way when mirrored | pointer x inverted — **see open items** |
| Head reticle drew a diagonal | `lineTo(cx, cy + 10)` |
| Frame buffer leaked inside an async `.then()` | prunes every frame, records only in delay mode |
| Shaft angle computed in normalized units | `screenAngleDeg()` uses real screen pixels |

---

## Open

1. **API key is client-side.** A Cloudflare Pages Function proxying Gemini would
   hide it and likely cut latency. Same job as a Netlify Function, also free.
2. **Account latency.** 7.0–9.8s for a trivial text-only call. If that is the steady
   state rather than cold start, the proxy is worth doing for speed alone.
3. **`getCanvasCoords` inverts pointer x when mirrored.** By the same reasoning as
   invariant 2 this looks wrong — guides are in screen space, so a touch should map
   straight across. Untested. With mirror on, drag a handle: if it moves opposite
   your finger, delete the inversion.
4. **Gemini's `shaftAngleDegrees` disagrees with its own points** (41.5° reported vs
   57.5° implied by its clubHead→gripHands). The app ignores the reported angle and
   derives it geometrically. Worth investigating on a clean rear-camera DTL shot.
5. **Tailwind CDN** warns in production. Eventually swap for prebuilt CSS.
6. **Boot log reports `canvas 300x150`** because it logs before layout settles.
   Cosmetic; the `Scan start` line has the real numbers.
7. **A/B the models** on the range — 3.7 Flash vs 3 Pro Preview.
8. **Face-On is a thin mode.** It presets a vertical plane line and passes its label
   into the prompt, and that is all. The geometric fallback branches only on
   `isLefty`, so Face-On silently receives the Righty DTL coordinates, and the tush
   line and Hogan corridor are down-the-line concepts with no face-on meaning. Either
   make it a real mode or remove it.

---

## Working style

- Concise replies, bullet points, English.
- Step by step, one step at a time, wait for confirmation.
- Do not change things that were not asked about. If something already chosen looks
  wrong, check before overriding it — but do say so, with evidence.
- Verify before claiming. Deploys are checked by checksum against the built file,
  JavaScript is syntax-checked before pushing, and coordinate maths is replayed
  against real logged values.

---

## Why the video is letterboxed, and why not to "fix" it

The camera is 9:16 (aspect 0.563). The normal view's canvas is 0.646 — wider — so
the picture is pillarboxed with ~27px side bars. The obvious fix is to switch
`drawContain()` to a cover fit so it fills edge to edge. **Do not.**

Cover crops 13% of the camera height in the normal view, 6.5% off top and bottom.
Measured clubhead positions from real scans sit at y=0.94–0.985 of the frame, so
that crop removes the clubhead from the picture entirely and shaft detection stops
working. The bars are the cheaper problem.

The practice view already solves it without any cropping: hiding the chrome makes
the canvas 411x743, aspect 0.553, which nearly matches the camera. The picture
fills the width with 0px side bars and ~6px top and bottom. That was the chosen
answer, and it needs no code.

If a future setup genuinely needs cover, it is only safe when the aspect mismatch
is small enough that the crop cannot reach the clubhead, and the snapshot path has
to change with it: `videoRect` would extend beyond the canvas, so the frame sent to
Gemini must be the visible intersection, and the returned coordinates mapped back
through that crop into source-video space.

---

## Working in the cloud, with the laptop off

Nothing about this project lives on a local machine, by design. The repo is the
source of truth, Cloudflare Pages builds from it, and the app runs on the phone.
There is no working copy to lose and nothing to hand-transfer.

**Remote Control is not the same thing as a cloud session.** If the mobile app shows
the session as connected to a laptop, that is Remote Control: the session runs on the
laptop and the phone is only a viewer. Close the laptop and the session dies. Cloud
sessions instead run in an Anthropic-managed VM that clones the repo from GitHub, and
they survive the browser closing.

To start one: connect GitHub to the Claude account (authorize the Claude GitHub App at
claude.ai/code, or run `/web-setup` to sync a `gh` token), then start the task from
claude.ai/code rather than from a terminal. Session handoff is one-way from the CLI —
`--teleport` pulls cloud to local, but a terminal session cannot be pushed to the web.
The desktop app's **Continue in** menu is the exception.

Two things from the old setup do not carry over, and neither matters:

- **Composio MCP** was the only GitHub path from the desktop session, which is why
  history shows file writes through the GitHub contents API instead of commits. A
  cloud session clones the repo and uses real `git`, which is strictly better.
- **Cloudflare access** is not needed for deploys. Pages watches `main` and builds on
  push regardless of who pushed.

Cloud sessions have limited network egress by default. Gemini is called from the
golfer's phone, not from the session, so that does not affect debugging — the log is
still copied out of the app and pasted into the conversation.
