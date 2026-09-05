#!/usr/bin/env python3
"""Second review pass: eight defects in auto-capture, export orientation and replay.

Run from the repository root:

    python3 tools/review2-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

1. Auto-capture overwrote the real swing with the walk to the phone. The
   trigger is "burst then stillness", which is also exactly what walking over
   and stopping looks like, and captureSwing discarded the held clip first.
   Two guards: a burst longer than a swing could be is abandoned (a swing is
   ~1.5s, a walk is 3-8s -- a cleaner discriminator than any threshold), and
   a clip the golfer has not yet opened in Replay is never replaced.

2. Delay mode read frameBuffer directly, and the capture splices the newest
   seconds out of it, so the delayed picture jumped back, froze, and resumed
   after the swing. Delay now looks up its frame across both arrays. No
   deferral, no refcounting: the frames still exist, just elsewhere.

3. The un-mirrored export flipped guide positions but not chirality. The
   corridor's perpendicular was a fixed "minus ninety", and the tush wall's
   side came from the unflipped x, so both drew on the wrong side of the
   golfer in the saved file.

4. Tapping Replay during an export fell through the guard and restarted the
   playhead under a running recorder.

5. The mirror toggle stayed live during an export. Scan and drag were guarded;
   this was not.

6. Replay forced a synchronous layout every frame: syncReplayUi wrote the DOM,
   then drawMotionTrace read clientWidth. The trace's CSS size is now cached
   on entry and on resize, the scrubber's max is set once, and the transport
   is written only when the frame index actually changes.

7. The held clip was not counted against MAX_BUFFER_FRAMES, breaking the
   constant-memory promise HANDOFF makes for that cap.

8. The countdown's frame-difference loop and the swing detector's were two
   copies of one computation, which is the only reason their thresholds were
   on the same scale. One helper now, and one close-all helper for the two
   bitmap arrays.
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


# ---------- 8. shared helpers ----------
sub(r'''    let lastFramePixels = null;''',
r'''    // Previous-frame pixels for the two frame-difference consumers. Objects so
    // a reset is one assignment and the shared helper can update them in place.
    const stabPrev = { pixels: null };
    const motionPrev = { pixels: null };''', 'prev-pixel holders')

sub(r'''    function clearFrameBuffer() {
      while (frameBuffer.length) {
        const f = frameBuffer.shift();
        if (f && f.bitmap && f.bitmap.close) { try { f.bitmap.close(); } catch (e) {} }
      }
    }''',
r'''    function closeFrames(frames) {
      while (frames.length) {
        const f = frames.pop();
        if (f && f.bitmap && f.bitmap.close) { try { f.bitmap.close(); } catch (e) {} }
      }
    }

    function clearFrameBuffer() { closeFrames(frameBuffer); }''', 'closeFrames helper')

sub(r'''    function checkAddressStability() {
      try {
        stabCtx.drawImage(canvas, 0, 0, 64, 64);
        const data = stabCtx.getImageData(0, 0, 64, 64).data;
        if (!lastFramePixels) { lastFramePixels = new Uint8ClampedArray(data); return false; }
        let diff = 0;
        for (let i = 0; i < data.length; i += 16) diff += Math.abs(data[i] - lastFramePixels[i]);
        lastFramePixels = new Uint8ClampedArray(data);
        return (diff / (64 * 64 / 4)) < 14;
      } catch (e) { return true; }
    }''',
r'''    // Mean absolute red-channel difference between this frame and the last one
    // seen through the same scratch canvas. One implementation, so the
    // countdown's "still" threshold and the swing detector's thresholds are on
    // the same scale by construction rather than by two loops staying identical.
    // Returns null on the first call, when there is nothing to compare against.
    function frameDiff(sctx, source, prev) {
      sctx.drawImage(source, 0, 0, 64, 64);
      const data = sctx.getImageData(0, 0, 64, 64).data;
      if (!prev.pixels) { prev.pixels = new Uint8ClampedArray(data); return null; }
      let diff = 0;
      for (let i = 0; i < data.length; i += 16) diff += Math.abs(data[i] - prev.pixels[i]);
      prev.pixels = new Uint8ClampedArray(data);
      return diff / (64 * 64 / 4);
    }

    function checkAddressStability() {
      try {
        const d = frameDiff(stabCtx, canvas, stabPrev);
        return d !== null && d < 14;
      } catch (e) { return true; }
    }''', 'checkAddressStability via helper')

sub(r'''      lastFramePixels = null;''',
r'''      stabPrev.pixels = null;''', 'countdown resets stabPrev')

sub(r'''    function sampleMotion(now) {
      if (now - lastMotionSample < MOTION_SAMPLE_MS) return;
      lastMotionSample = now;
      try {
        motionSampleCtx.drawImage(video, 0, 0, 64, 64);
        const data = motionSampleCtx.getImageData(0, 0, 64, 64).data;
        if (!motionPrevPixels) { motionPrevPixels = new Uint8ClampedArray(data); return; }
        let diff = 0;
        for (let i = 0; i < data.length; i += 16) diff += Math.abs(data[i] - motionPrevPixels[i]);
        motionPrevPixels = new Uint8ClampedArray(data);
        motionValue = diff / (64 * 64 / 4);
      } catch (e) { /* readback can fail mid-resize; the next sample retries */ }
    }''',
r'''    function sampleMotion(now) {
      if (now - lastMotionSample < MOTION_SAMPLE_MS) return;
      lastMotionSample = now;
      try {
        const d = frameDiff(motionSampleCtx, video, motionPrev);
        if (d !== null) motionValue = d;
      } catch (e) { /* readback can fail mid-resize; the next sample retries */ }
    }''', 'sampleMotion via helper')

sub(r'''    let motionValue = 0;
    let motionPrevPixels = null;''',
r'''    let motionValue = 0;''', 'drop old motionPrevPixels')

# ---------- 1. burst length cap + never replace an unviewed clip ----------
sub(r'''    const SWING_QUIET_MS = 1200;
    const SWING_COOLDOWN_MS = 3000;''',
r'''    const SWING_QUIET_MS = 1200;
    // A swing is over in about a second and a half. Walking to the phone and
    // stopping is the same "burst then stillness" shape but lasts far longer,
    // and duration separates the two more cleanly than any motion threshold.
    const SWING_MAX_MS = 2500;
    const SWING_COOLDOWN_MS = 3000;
    // A held clip the golfer has not opened yet is the swing they came for. It
    // is never replaced -- the walk over would otherwise be what replaces it.
    let swingClipViewed = false;''', 'swing max + viewed flag')

sub(r'''      if (motionValue > swingPeak) swingPeak = motionValue;

      if (motionValue < SWING_OFF) {''',
r'''      if (motionValue > swingPeak) swingPeak = motionValue;

      // Still moving past the longest a swing could take: this is a walk, a
      // practice waggle, or someone crossing the frame. Abandon it -- letting
      // it run would capture a window that no longer contains anything.
      if (now - swingStartedAt > SWING_MAX_MS) {
        logLine("info", "Motion ignored - too long for a swing", {
          activeMs: Math.round(now - swingStartedAt), peak: +swingPeak.toFixed(1), maxMs: SWING_MAX_MS
        });
        swingActive = false;
        lastCaptureAt = now;
        return;
      }

      if (motionValue < SWING_OFF) {''', 'abandon long bursts')

sub(r'''    function captureSwing(now, activeMs) {
      // Moved, not copied. The live buffer keeps rolling from here, so a false
      // trigger costs a few seconds of scrollback and never the next swing.
      discardSwingClip();''',
r'''    function captureSwing(now, activeMs) {
      if (swingClip.length && !swingClipViewed) {
        // The first capture after a swing is the swing. Anything that fires
        // before the golfer has looked at it is the walk over, and must lose.
        lastCaptureAt = now;
        logLine("info", "Motion ignored - a swing is already held and unviewed", {
          activeMs: Math.round(activeMs), peak: +swingPeak.toFixed(1)
        });
        return;
      }
      // Moved, not copied. The live buffer keeps rolling from here, so a false
      // trigger costs a few seconds of scrollback and never the next swing.
      discardSwingClip();''', 'never replace unviewed clip')

sub(r'''      lastCaptureAt = now;
      swingBadge.classList.remove("hidden");
      swingBadge.classList.add("flex");''',
r'''      lastCaptureAt = now;
      swingClipViewed = false;
      swingBadge.classList.remove("hidden");
      swingBadge.classList.add("flex");''', 'new clip is unviewed')

sub(r'''    function discardSwingClip() {
      while (swingClip.length) {
        const f = swingClip.pop();
        if (f && f.bitmap && f.bitmap.close) { try { f.bitmap.close(); } catch (e) {} }
      }
      swingBadge.classList.add("hidden");''',
r'''    function discardSwingClip() {
      closeFrames(swingClip);
      swingClipViewed = false;
      swingBadge.classList.add("hidden");''', 'discard via helper')

# ---------- 2. delay mode reads across both arrays ----------
sub(r'''        const targetTime = now - delaySeconds * 1000;
        let frame = frameBuffer[0];
        for (let i = frameBuffer.length - 1; i >= 0; i--) {
          if (frameBuffer[i].timestamp <= targetTime) { frame = frameBuffer[i]; break; }
        }''',
r'''        const targetTime = now - delaySeconds * 1000;
        // Auto-capture moves the newest seconds out of frameBuffer into the
        // held clip. Those frames still exist, so the delayed view looks in
        // both rather than falling into the hole the move leaves behind.
        const frame = newestFrameAtOrBefore(targetTime);''', 'delay reads both')

sub(r'''    function closeFrames(frames) {''',
r'''    // Newest frame at or before a time, across the live buffer and the held
    // clip. The two never overlap in time, so whichever contains the target
    // wins; otherwise the newest frame older than the target, from either.
    function newestFrameAtOrBefore(t) {
      let best = null;
      const consider = (arr) => {
        for (let i = arr.length - 1; i >= 0; i--) {
          if (arr[i].timestamp <= t) {
            if (!best || arr[i].timestamp > best.timestamp) best = arr[i];
            return;
          }
        }
      };
      consider(frameBuffer);
      consider(swingClip);
      return best || frameBuffer[0] || swingClip[0] || null;
    }

    function closeFrames(frames) {''', 'newestFrameAtOrBefore')

# ---------- 3. chirality under the export flip ----------
sub(r'''          const angle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
          const perp = angle - Math.PI / 2;''',
r'''          const angle = Math.atan2(p2.y - p1.y, p2.x - p1.x);
          // A mirror flips chirality. vidToPxX has already flipped the line's
          // endpoints for an export; a fixed "minus ninety" would then put the
          // corridor on the far side of the shaft, so the sign flips with it.
          const perp = angle + (exportFlipX() ? 1 : -1) * Math.PI / 2;''', 'corridor chirality')

sub(r'''        const wallRight = guides.hipLine.x > 0.5;''',
r'''        // Which side the wall shades must follow the drawn position, which for
        // an export is the flipped one -- otherwise the gradient and the label
        // extend back toward the golfer in the saved file.
        const hipDrawnX = exportFlipX() ? 1 - guides.hipLine.x : guides.hipLine.x;
        const wallRight = hipDrawnX > 0.5;''', 'wall side follows flip')

# ---------- 4 + 5. replay tap and mirror toggle during an export ----------
sub(r'''      // Walking out mid-record would otherwise keep capturing the live feed
      // into a file the golfer asked to be of their replay.
      if (exportingClip && mode !== "replay") stopClipExport();''',
r'''      if (exportingClip) {
        // Re-entering replay would rewind the playhead under a running
        // recorder; walking out would keep capturing the live feed into a
        // file the golfer asked to be of their replay.
        if (mode === "replay") return;
        stopClipExport();
      }''', 'replay tap during export')

sub(r'''    btnToggleMirror.addEventListener("click", () => {
      unlockMobileAudio();
      isMirrored = !isMirrored;''',
r'''    btnToggleMirror.addEventListener("click", () => {
      unlockMobileAudio();
      // Flipping mid-export changes the orientation of the video, the guides,
      // or both, half way through the saved file.
      if (exportingClip) { showToast("Finish saving the clip first", 3000); return; }
      isMirrored = !isMirrored;''', 'mirror toggle during export')

# ---------- 6. no forced layout per frame ----------
sub(r'''    function syncReplayUi() {
      const total = replaySourceFrames().length;
      replayScrub.max = String(Math.max(1, total - 1));
      if (!replayScrubbing) replayScrub.value = String(replayFrameIndex());
      replayTime.textContent = (replayFrameIndex() / replayFps).toFixed(1) + "/" +
        (total / replayFps).toFixed(1) + "s";
    }''',
r'''    // Called every frame of replay, so it writes the DOM only when the frame
    // index has actually moved. The scrubber's range is fixed for the length
    // of a replay and is set once on entry.
    let lastSyncedIndex = -1;
    function syncReplayUi(force) {
      const idx = replayFrameIndex();
      if (!force && idx === lastSyncedIndex) return;
      lastSyncedIndex = idx;
      const total = replaySourceFrames().length;
      if (!replayScrubbing) replayScrub.value = String(idx);
      replayTime.textContent = (idx / replayFps).toFixed(1) + "/" +
        (total / replayFps).toFixed(1) + "s";
    }''', 'syncReplayUi only on change')

sub(r'''    function drawMotionTrace() {
      const frames = replaySourceFrames();
      const cssW = motionTrace.clientWidth || 1;
      const cssH = motionTrace.clientHeight || 16;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (motionTrace.width !== Math.round(cssW * dpr)) {
        motionTrace.width = Math.round(cssW * dpr);
        motionTrace.height = Math.round(cssH * dpr);
      }
      const w = motionTrace.width, h = motionTrace.height;''',
r'''    // Reading clientWidth right after syncReplayUi has written the DOM forces a
    // synchronous layout every frame of replay -- and of the real-time export
    // on the same loop. The CSS size is read here instead, on entry and on
    // resize, and drawMotionTrace works from the cached backing size.
    function sizeMotionTrace() {
      const cssW = motionTrace.clientWidth || 1;
      const cssH = motionTrace.clientHeight || 16;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const bw = Math.round(cssW * dpr), bh = Math.round(cssH * dpr);
      if (motionTrace.width !== bw || motionTrace.height !== bh) {
        motionTrace.width = bw;
        motionTrace.height = bh;
      }
    }

    function drawMotionTrace() {
      const frames = replaySourceFrames();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = motionTrace.width, h = motionTrace.height;''', 'trace size cached')

sub(r'''        replayFrames = entering;
        exportStatus.textContent = "";
        replayIndex = 0;
        replaySpeed = 1;
        btnReplaySpeed.textContent = "1x";
        replayFps = measureBufferFps(entering);
        setReplayPlaying(true);
        syncReplayUi();''',
r'''        replayFrames = entering;
        if (entering === swingClip) swingClipViewed = true;
        exportStatus.textContent = "";
        replayIndex = 0;
        replaySpeed = 1;
        btnReplaySpeed.textContent = "1x";
        replayFps = measureBufferFps(entering);
        replayScrub.max = String(Math.max(1, entering.length - 1));
        // The bar has just been unhidden; size the trace now, once, rather
        // than reading layout from inside the render loop.
        replayBar.classList.remove("hidden");
        sizeMotionTrace();
        setReplayPlaying(true);
        syncReplayUi(true);''', 'entry sets max, sizes trace, marks viewed')

sub(r'''    function resizeCanvas() {''',
r'''    function resizeCanvas() {
      if (appMode === "replay") sizeMotionTrace();''', 'resize keeps trace sized')

# ---------- 7. the held clip counts against the frame cap ----------
sub(r'''                frameBuffer.length > MAX_BUFFER_FRAMES)) {''',
r'''                frameBuffer.length + swingClip.length > MAX_BUFFER_FRAMES)) {''', 'cap counts held clip')

sub(r'''    const BUILD = "2026-09-05-trueorient";''',
r'''    const BUILD = "2026-09-05-review2";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
