# Golf Mirror AI — working notes

Single-file web app: `index.html`, no build step, no dependencies beyond two CDNs.
Live at https://golf-mirror-ai.pages.dev — Cloudflare Pages, auto-deploys on push
to `main`, usually live within ~60s.

Swing mirror for solo range practice, down-the-line or face-on: draggable
shaft-plane, Hogan corridor, head-stability ring and tush/sway line over a live
camera feed, with a hands-free countdown, delayed replay, a scrubbable replay
that catches the swing automatically and can be saved as a still or a clip, and
Gemini vision for stance detection.

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
| Key location | encrypted Pages env var `GEMINI_API_KEY`, proxied by `functions/api/gemini.js` |
| Image | 1024px max width, JPEG 0.88 (~60–95KB) |

The browser calls `/api/gemini`, never Google, unless a key is pasted in
Settings — that overrides the proxy and goes direct, which exists so a proxy
problem at the range can be worked around without a computer. It is also the
trap: a key left in localStorage silently outranks the server, so `geminiRoute()`
names the live route on the boot line, on every Gemini request, in the
diagnostics header and in the latency benchmark. Check it before blaming either
half.

The Function validates the model against a list rather than interpolating it —
the string lands in a URL path — and returns Google's status and body verbatim,
because the log's whole value is Google's own error text. Its origin check
raises the effort from "paste the URL into curl" to "set one header": worth
having, not security. The endpoint is public, so anyone who finds it can spend
the quota; a KV-backed rate limit is the real answer and is deliberately not
built. Setting the secret: Cloudflare → Pages → the project → Settings →
Environment variables → Add → **Encrypt**, named `GEMINI_API_KEY`, then redeploy.

Never add `temperature`, `top_p` or `top_k` — Gemini 3.x rejects them outright.

`thinking_level` as a **top-level** field is invalid and 400s with
`Unknown name "thinking_level" at 'generation_config'`. Every call failed this way
and fell back silently. It must stay nested under `thinkingConfig`.

Timeouts are deliberately generous. A trivial text-only call on this account
measured 7.0–9.8s, so 20s was never enough for an image request. This costs the
golfer nothing: the snapshot is captured *before* the request, so they are waiting
for guides to appear, not holding the stance.

---

## The frame buffer, and its three readers

`frameBuffer` holds the last `MAX_BUFFER_SECONDS` as `ImageBitmap`s. It is the
recording, and it always was — delay mode never did anything but read it at a
fixed offset from now. Replay was mostly a matter of freezing it and pointing a
playhead at it rather than a capture pipeline.

| Reader | How it reads |
| --- | --- |
| Live | not at all; draws the video element |
| Delay | the frame nearest `now - delaySeconds`, from **either** array below |
| Replay | `replaySourceFrames()[replayIndex]`, playhead driven by the transport |

There is a second array, `swingClip`: the held swing. Auto-capture (`detectSwing`)
watches a 10Hz 64×64 frame difference for a burst followed by stillness and, on
that pattern, **moves** the last `SWING_CLIP_SECONDS` out of `frameBuffer` into
it. Replay prefers it when it exists, because it is centred on what the golfer
came to look at where the live buffer merely ends at whenever they arrived.

Four things are load-bearing:

- **It fills in every mode except replay.** It used to fill only in delay, and be
  released on the way out, so a swing hit in Live was gone before you could ask
  to see it. The cost is that the ceiling is now occupied permanently.
- **Nothing may mutate it during replay** — not the pruner, not a late
  `createImageBitmap`, not the backgrounding handler. The clip is measured on
  entry (`measureBufferFps`) and the playhead indexes into it; change the array
  underneath and the clip erodes while it plays, which reads as a rendering bug.
- **Memory is capped by frames as well as by age, and the held clip counts.**
  Pruning by age alone let the frame rate set the memory bill. With both caps
  the rate/duration trade is automatic: ask for more fps and you keep fewer
  seconds, at constant memory. `frameBuffer.length + swingClip.length` is what
  the cap tests — counting only the live buffer quietly added 40% on top.
- **The held clip is moved, never copied, and never replaced unviewed.** Two
  arrays sharing `ImageBitmap`s would need refcounting to know when `close()` is
  safe, and closing one the other still draws is a crash. Moving means the
  frames still exist, so delay mode looks them up across both arrays rather
  than falling into the hole the move leaves. And a clip the golfer has not yet
  opened in Replay is the swing they came for: the walk to the phone has the
  same "burst then stillness" shape and would otherwise replace it.

The camera negotiates at 30fps and will not do 60 — asked for 60 with `ideal`,
it granted 30, and `actualFps` in the Replay log confirms the pipeline keeps
up with it. The frame cap means 60 would halve the clip rather than double
the memory, but the question is moot on this hardware.

Export reads the main canvas, which already has the frame and the guides
composited on it — a still via `toBlob`, a clip via `captureStream` +
`MediaRecorder` recording one pass in real time. Real time is the price of
reusing the on-screen render, and it buys a file that cannot disagree with what
the golfer was looking at. Both come out in **true orientation**: a mirror is
right to practise against and wrong to keep. For the length of an export
`unmirrorForExport` drops the mirror from the video draw and flips guide x in
`vidToPxX`, the single point every guide and hit test goes through, so the
guides move with the golfer. Scan, drag, the mirror toggle and re-entering
Replay are all refused while it runs.

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
   distinct: real detection (locked + confidence), no cloud answer (default +
   geometric guides), error or empty frame (No lock + the actual reason, existing
   guides left untouched). A confident-looking wrong answer is worse than a
   visible failure. The middle outcome used to mean "no API key saved"; with the
   proxy a scan is always attempted, so it now means the proxy is unreachable or
   its secret is unset — and that reason is named rather than swallowed.

7. **Playback timing must come from the buffer, never from `BUFFER_FPS`.** The
   buffer rarely fills at exactly the target: `createImageBitmap` has to keep up,
   `bufferBusy` silently drops any frame where it does not, and the camera may
   deliver less than asked. Driving replay from the constant made it run fast and
   the clock lie, and the gap widens every time the target goes up.
   `measureBufferFps()` reads the real rate off the frame timestamps; use
   `replayFps` for speed and for every readout. Its appearance in the log as
   `actualFps` against `targetFps` is also the only honest answer to "should we
   ask for 60".

8. **The frame gate needs slack.** `now - last > 1000 / BUFFER_FPS` is
   `> 33.333...` at 30fps, and two rAF intervals on a 60Hz screen land at 33.33 —
   not greater. Capture waited a third interval and quietly ran at 20fps. Compare
   against `BUFFER_GAP_MS`, which carries a few ms of tolerance, and never
   against the bare period.

9. **A recording must be able to end without the render loop.** `advanceReplay()`
   notices the loop wrapping and stops `MediaRecorder`, and it only runs while
   the buffer has frames — so emptying the buffer mid-record (flip the camera)
   or stopping rAF (background the page) left the recorder running until reload.
   The watchdog in `render()` and the `visibilitychange` handler both exist for
   that; keep them outside any buffer-length gate.

10. **The tush line must sit on the golfer.** The model will otherwise latch onto
   background objects — it once put it on a backpack on the floor. The prompt names
   furniture, bags, beds, walls and doors as *not the golfer*, and the model may set
   `tushDetected: false`, in which case the existing line is kept rather than moved
   to a guess.

11. **A mirror flips chirality, not just positions.** Under `exportFlipX()` the
   guide endpoints are already mirrored by `vidToPxX`; anything that then picks
   a side with a fixed sign draws on the wrong side of the golfer. The corridor's
   perpendicular flips its sign with the export, and the tush wall's side reads
   the *drawn* x, not the stored one. Any new side-dependent guide must do the
   same.

12. **Auto-capture must lose to an unviewed clip, and give up on long bursts.**
   The trigger — motion, then stillness — is also exactly what walking to the
   phone and stopping looks like. `captureSwing` refuses while `swingClip` holds
   frames the golfer has not opened, and `detectSwing` abandons any burst past
   `SWING_MAX_MS`: a swing is over in ~1.5s, a walk takes 3–8s, and duration
   separates them more cleanly than any motion threshold. Opening the clip in
   Replay is what frees the slot.

13. **Read layout before writing DOM in the replay loop.** `syncReplayUi` writes
   the transport and `drawMotionTrace` draws the trace on the same frame; a
   `clientWidth` read between them forces a synchronous layout 60×/s for the
   whole replay and the whole real-time export. The trace's backing size is set
   on entry and on a real canvas resize, and the transport is written only when
   the frame index moves.

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
| Frame buffer leaked inside an async `.then()` | prunes every frame |
| Buffer filled only in delay mode, so a swing hit in Live was unreplayable | fills in every mode except replay |
| Pruner, late bitmaps and backgrounding all mutated the buffer mid-replay | each guarded; late bitmaps discarded and closed |
| Frame gate `> 1000/fps` fell on the wrong side of two 60Hz rAF intervals, capping capture at 20fps | `BUFFER_GAP_MS` tolerance |
| Memory scaled with frame rate, uncapped | `MAX_BUFFER_FRAMES` beside the age cap |
| Clip export could never stop if the buffer emptied or the page was hidden | watchdog outside the buffer gate, plus stop-on-hidden |
| `MediaRecorder.start()` outside the try/catch guarding the constructor | inside it, unwinds the disabled transport |
| `captureStream` tracks never stopped, leaving a live 30fps capture per export | `releaseClipStream()` |
| Scrub `input` paused playback every pointer tick, running a document-wide `lucide.createIcons()` | pauses once, on the tick that pauses |
| Saved clips and stills came out mirrored | `unmirrorForExport`, read by the video draw and `vidToPxX` only |
| Auto-capture replaced the real swing with the walk to the phone | never replace an unviewed clip; abandon bursts past `SWING_MAX_MS` |
| Capture spliced the swing out from under delay mode | delay looks up its frame across both arrays |
| Corridor and tush wall on the wrong side of the golfer in the un-mirrored export | perpendicular sign and wall side follow the flip |
| Replay tap and mirror toggle live during an export | both refused, alongside scan and drag |
| Forced synchronous layout every replay frame | trace sized on entry/resize; DOM written only on index change |
| Held clip not counted against `MAX_BUFFER_FRAMES` | `frameBuffer.length + swingClip.length` |
| Two copies of the 64×64 frame-difference loop | one `frameDiff`; one `closeFrames` for both bitmap arrays |
| Shaft angle computed in normalized units | `screenAngleDeg()` uses real screen pixels |

---

## Open

1. **Rate limiting the proxy.** `/api/gemini` is public: the origin check stops
   casual use and nothing else, so anyone who finds the URL can spend the quota.
   KV-backed per-IP limiting is the real fix. Watch the Google Cloud console for
   unexplained usage in the meantime.
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
8. **The swing thresholds are untuned.** `SWING_ON`, `SWING_OFF`, `SWING_MIN_MS`,
   `SWING_MAX_MS` and `SWING_QUIET_MS` are guesses that have not yet met a real
   swing. Every capture logs `peak` and `activeMs`, and every rejection logs why
   — too brief, too long, or a clip already held. Tune from those lines, not
   from taste. Related design choice, not a bug: two swings without opening
   Replay in between drops the second. If that turns out wrong on the range,
   the alternative is keeping the newest N clips.
9. **Clip export is confirmed on Android Chrome only** (VP9 webm, 10s in 10.05s,
   1.9MB). iOS Safari is the expected casualty: the code reports missing
   `MediaRecorder`, missing `captureStream` or an unsupported container rather
   than failing quietly, and Save frame works regardless, but nobody has watched
   it happen.
10. **The no-key fallback assumes an unmirrored right-hander in face-on.** It
   hardcodes the trail hip to camera-left. With mirror on it is on the wrong
   side. Only affects no-key mode — a scan reads the hip off the body and is
   unaffected — so it has been left alone.

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
