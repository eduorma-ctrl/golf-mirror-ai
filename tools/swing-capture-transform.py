#!/usr/bin/env python3
"""Catch the swing automatically, and show where it is in the clip.

Run from the repository root:

    python3 tools/swing-capture-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

The rolling buffer ends at "now", and "now" is when the golfer finally reaches
the phone -- five to fifteen seconds after the swing. By then the swing has
half rolled out of the window, so the clip is only reliable if you tap
immediately, which is exactly when you cannot. Two changes:

A. Auto-capture. A 64x64 frame difference, sampled at 10Hz, watches for a burst
   of motion followed by stillness -- a swing, then the golfer standing up. On
   that pattern the last few seconds are moved out of the live buffer into a
   held clip that nothing prunes, and a badge says so. Walk over whenever; the
   swing is waiting, and the buffer kept rolling behind it so a false trigger
   never costs the next one.

   The frames are MOVED, not copied. Two arrays sharing ImageBitmaps would need
   refcounting to know when close() is safe, and getting that wrong closes a
   bitmap another array is still drawing.

   Thresholds are guesses until they meet a real swing, so every capture logs
   its peak and every near-miss logs why it was not one. Tune from that, not
   from taste.

B. A motion trace under the scrubber, so the swing is visibly a spike rather
   than somewhere in ten seconds of scrubbing. Each frame carries the motion
   reading current when it was buffered.

Sampling is 10Hz, not per frame: getImageData is a GPU-to-CPU readback and is
the reason the existing stability check only runs during the countdown.
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


# ---------- state ----------
sub(r'''    const BUFFER_GAP_MS = 1000 / BUFFER_FPS - 4;''',
r'''    const BUFFER_GAP_MS = 1000 / BUFFER_FPS - 4;

    // The held swing. Frames are moved here out of frameBuffer, never copied:
    // two arrays sharing ImageBitmaps would need refcounting to know when
    // close() is safe, and closing one another array still draws is a crash.
    const swingClip = [];
    const SWING_CLIP_SECONDS = 4;

    // Motion, sampled at 10Hz rather than per frame -- getImageData is a
    // GPU-to-CPU readback, which is why the countdown's stability check has
    // always been the only thing doing it.
    const MOTION_SAMPLE_MS = 100;
    // Guesses until they meet a real swing. The countdown calls under 14 "still"
    // on the same scale, so a swing should clear SWING_ON comfortably. Every
    // capture and every near-miss logs its numbers; tune from those.
    const SWING_ON = 35;
    const SWING_OFF = 12;
    const SWING_MIN_MS = 150;
    const SWING_QUIET_MS = 1200;
    const SWING_COOLDOWN_MS = 3000;
    let motionValue = 0;
    let motionPrevPixels = null;
    let lastMotionSample = 0;
    let swingActive = false;
    let swingStartedAt = 0;
    let swingPeak = 0;
    let swingQuietSince = 0;
    let lastCaptureAt = 0;''', 'swing state')

sub(r'''    let replayScrubbing = false;''',
r'''    let replayScrubbing = false;
    // Which array replay is reading: the held swing when there is one, the live
    // buffer otherwise. Everything in replay goes through this, never through
    // frameBuffer directly.
    let replayFrames = null;''', 'replayFrames state')

# ---------- refs ----------
sub(r'''    const exportStatus = $("export-status");''',
r'''    const exportStatus = $("export-status");
    const swingBadge = $("swing-badge");
    const btnDiscardSwing = $("btn-discard-swing");
    const motionTrace = $("motion-trace");
    const motionCtx = motionTrace.getContext("2d");''', 'swing refs')

# ---------- markup ----------
sub(r'''        <button id="btn-mode-replay" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition">
          Replay
        </button>
      </div>''',
r'''        <button id="btn-mode-replay" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition">
          Replay
        </button>
        <span id="swing-badge" class="hidden items-center gap-1 px-2 py-1 rounded-lg bg-sky-500/20 border border-sky-500/50 text-sky-300 text-[10px] font-bold">
          <i data-lucide="check" class="w-3 h-3"></i> Swing
          <button id="btn-discard-swing" class="ml-0.5 text-sky-400/70 hover:text-white" title="Discard the captured swing">&times;</button>
        </span>
      </div>''', 'swing badge')

sub(r'''     <div class="flex items-center gap-1.5">
      <button id="btn-replay-play"''',
r'''     <canvas id="motion-trace" class="w-full h-4 rounded bg-slate-950/60"></canvas>
     <div class="flex items-center gap-1.5">
      <button id="btn-replay-play"''', 'motion trace canvas')

# ---------- motion sampling + swing detection ----------
sub(r'''    // ---------- Timer ----------''',
r'''    // ---------- Swing detection ----------
    // Its own canvas: the countdown's stability check runs concurrently on
    // stabCanvas and the two would overwrite each other's pixels.
    const motionCanvas = document.createElement("canvas");
    motionCanvas.width = 64; motionCanvas.height = 64;
    const motionSampleCtx = motionCanvas.getContext("2d", { willReadFrequently: true });

    // Sampled from the video element rather than the main canvas so that guides,
    // badges and the replay frame itself cannot register as movement.
    function sampleMotion(now) {
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
    }

    // A swing is a burst of motion followed by the golfer standing still. Both
    // halves are required: motion alone is someone walking past, and stillness
    // alone is the whole rest of the session.
    function detectSwing(now) {
      if (lastCaptureAt && now - lastCaptureAt < SWING_COOLDOWN_MS) return;

      if (!swingActive) {
        if (motionValue >= SWING_ON) {
          swingActive = true;
          swingStartedAt = now;
          swingPeak = motionValue;
          swingQuietSince = 0;
        }
        return;
      }

      if (motionValue > swingPeak) swingPeak = motionValue;

      if (motionValue < SWING_OFF) {
        if (!swingQuietSince) swingQuietSince = now;
        if (now - swingQuietSince >= SWING_QUIET_MS) {
          const activeMs = swingQuietSince - swingStartedAt;
          swingActive = false;
          if (activeMs >= SWING_MIN_MS) {
            captureSwing(now, activeMs);
          } else {
            // Logged rather than dropped: a threshold nobody can see is a
            // threshold nobody can tune.
            logLine("info", "Motion ignored - too brief for a swing", {
              activeMs: Math.round(activeMs), peak: +swingPeak.toFixed(1), minMs: SWING_MIN_MS
            });
          }
        }
      } else {
        swingQuietSince = 0;
      }
    }

    function captureSwing(now, activeMs) {
      // Moved, not copied. The live buffer keeps rolling from here, so a false
      // trigger costs a few seconds of scrollback and never the next swing.
      discardSwingClip();
      const cutoff = now - SWING_CLIP_SECONDS * 1000;
      let i = frameBuffer.length;
      while (i > 0 && frameBuffer[i - 1].timestamp >= cutoff) i--;
      const taken = frameBuffer.splice(i);
      for (let k = 0; k < taken.length; k++) swingClip.push(taken[k]);

      if (swingClip.length < 2) { discardSwingClip(); return; }

      lastCaptureAt = now;
      swingBadge.classList.remove("hidden");
      swingBadge.classList.add("flex");
      showToast("Swing captured - tap Replay", 3500);
      logLine("ok", "Swing captured", {
        frames: swingClip.length,
        seconds: +((swingClip[swingClip.length - 1].timestamp - swingClip[0].timestamp) / 1000).toFixed(1),
        peak: +swingPeak.toFixed(1),
        activeMs: Math.round(activeMs),
        thresholds: { on: SWING_ON, off: SWING_OFF, quietMs: SWING_QUIET_MS }
      });
    }

    function discardSwingClip() {
      while (swingClip.length) {
        const f = swingClip.pop();
        if (f && f.bitmap && f.bitmap.close) { try { f.bitmap.close(); } catch (e) {} }
      }
      swingBadge.classList.add("hidden");
      swingBadge.classList.remove("flex");
    }

    // ---------- Timer ----------''', 'motion + swing detection')

# ---------- render loop wiring ----------
sub(r'''      // Always recording, so Replay has something to show whichever mode the''',
r'''      // Not while replaying: the sample would read a paused frame, and a capture
      // would move frames out from under the playhead.
      if (liveReady && appMode !== "replay") {
        sampleMotion(now);
        detectSwing(now);
      }

      // Always recording, so Replay has something to show whichever mode the''', 'sample in render')

sub(r'''            frameBuffer.push({ timestamp: performance.now(), bitmap });''',
r'''            // motion rides along so the trace can be drawn later without a
            // second history to keep in step with the frames.
            frameBuffer.push({ timestamp: performance.now(), bitmap, motion: motionValue });''', 'frames carry motion')

# ---------- replay reads replayFrames ----------
sub(r'''    function measureBufferFps() {
      if (frameBuffer.length < 2) return BUFFER_FPS;
      const span = frameBuffer[frameBuffer.length - 1].timestamp - frameBuffer[0].timestamp;
      if (span <= 0) return BUFFER_FPS;
      return (frameBuffer.length - 1) / (span / 1000);
    }

    function replayFrameIndex() {
      return Math.max(0, Math.min(frameBuffer.length - 1, Math.floor(replayIndex)));
    }''',
r'''    // The held swing when there is one, the live buffer otherwise.
    function replaySourceFrames() {
      return replayFrames || (swingClip.length ? swingClip : frameBuffer);
    }

    function measureBufferFps(frames) {
      if (frames.length < 2) return BUFFER_FPS;
      const span = frames[frames.length - 1].timestamp - frames[0].timestamp;
      if (span <= 0) return BUFFER_FPS;
      return (frames.length - 1) / (span / 1000);
    }

    function replayFrameIndex() {
      const frames = replaySourceFrames();
      return Math.max(0, Math.min(frames.length - 1, Math.floor(replayIndex)));
    }

    // B. The swing is a spike, so it can be aimed at rather than hunted for.
    function drawMotionTrace() {
      const frames = replaySourceFrames();
      const cssW = motionTrace.clientWidth || 1;
      const cssH = motionTrace.clientHeight || 16;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (motionTrace.width !== Math.round(cssW * dpr)) {
        motionTrace.width = Math.round(cssW * dpr);
        motionTrace.height = Math.round(cssH * dpr);
      }
      const w = motionTrace.width, h = motionTrace.height;
      motionCtx.clearRect(0, 0, w, h);
      if (frames.length < 2) return;

      let peak = 1;
      for (let i = 0; i < frames.length; i++) peak = Math.max(peak, frames[i].motion || 0);

      motionCtx.beginPath();
      for (let i = 0; i < frames.length; i++) {
        const x = (i / (frames.length - 1)) * w;
        const y = h - ((frames[i].motion || 0) / peak) * (h - 2) - 1;
        if (i === 0) motionCtx.moveTo(x, y); else motionCtx.lineTo(x, y);
      }
      motionCtx.strokeStyle = "rgba(56, 189, 248, 0.85)";
      motionCtx.lineWidth = Math.max(1, dpr);
      motionCtx.stroke();

      const px = (replayFrameIndex() / Math.max(1, frames.length - 1)) * w;
      motionCtx.fillStyle = "#f8fafc";
      motionCtx.fillRect(px - dpr / 2, 0, Math.max(1, dpr), h);
    }''', 'replay source + motion trace')

sub(r'''        if (replayIndex >= frameBuffer.length) {
          replayIndex = 0;
          if (exportingClip) stopClipExport();
        }''',
r'''        if (replayIndex >= replaySourceFrames().length) {
          replayIndex = 0;
          if (exportingClip) stopClipExport();
        }''', 'wrap uses source')

sub(r'''    function syncReplayUi() {
      const total = frameBuffer.length;''',
r'''    function syncReplayUi() {
      const total = replaySourceFrames().length;''', 'sync uses source')

sub(r'''    function stepReplay(delta) {
      setReplayPlaying(false);
      replayIndex = replayFrameIndex() + delta;
      if (replayIndex < 0) replayIndex = frameBuffer.length - 1;
      if (replayIndex > frameBuffer.length - 1) replayIndex = 0;
      syncReplayUi();
    }''',
r'''    function stepReplay(delta) {
      const total = replaySourceFrames().length;
      setReplayPlaying(false);
      replayIndex = replayFrameIndex() + delta;
      if (replayIndex < 0) replayIndex = total - 1;
      if (replayIndex > total - 1) replayIndex = 0;
      syncReplayUi();
    }''', 'step uses source')

sub(r'''      } else if (appMode === "replay" && frameBuffer.length) {
        const rf = frameBuffer[replayFrameIndex()];''',
r'''      } else if (appMode === "replay" && replaySourceFrames().length) {
        const rf = replaySourceFrames()[replayFrameIndex()];''', 'draw uses source')

sub(r'''      } else if (frameBuffer.length) {
        advanceReplay(now);
      }''',
r'''      } else if (replaySourceFrames().length) {
        advanceReplay(now);
        drawMotionTrace();
      }''', 'advance + trace')

sub(r'''      if (exportingClip && (!frameBuffer.length || now - clipStartedAt > clipDeadlineMs)) {''',
r'''      if (exportingClip && (!replaySourceFrames().length || now - clipStartedAt > clipDeadlineMs)) {''', 'watchdog uses source')

# ---------- entering replay picks a source ----------
sub(r'''      if (mode === "replay" && !frameBuffer.length) {
        showToast("Nothing recorded yet - give it a few seconds", 3000);
        return;
      }''',
r'''      // The held swing is preferred: it is centred on what the golfer came to
      // look at, where the live buffer merely ends at whenever they arrived.
      const entering = swingClip.length ? swingClip : frameBuffer;
      if (mode === "replay" && !entering.length) {
        showToast("Nothing recorded yet - give it a few seconds", 3000);
        return;
      }''', 'pick source on entry')

sub(r'''      if (mode === "replay") {
        exportStatus.textContent = "";
        replayIndex = 0;
        replaySpeed = 1;
        btnReplaySpeed.textContent = "1x";
        replayFps = measureBufferFps();''',
r'''      if (mode === "replay") {
        replayFrames = entering;
        exportStatus.textContent = "";
        replayIndex = 0;
        replaySpeed = 1;
        btnReplaySpeed.textContent = "1x";
        replayFps = measureBufferFps(entering);''', 'set source on entry')

sub(r'''        logLine("info", "Replay", {
          frames: frameBuffer.length,
          seconds: +(frameBuffer.length / replayFps).toFixed(1),
          actualFps: +replayFps.toFixed(1),
          targetFps: BUFFER_FPS
        });
      } else {
        replayPlaying = false;
      }''',
r'''        logLine("info", "Replay", {
          source: entering === swingClip ? "captured swing" : "live buffer",
          frames: entering.length,
          seconds: +(entering.length / replayFps).toFixed(1),
          actualFps: +replayFps.toFixed(1),
          targetFps: BUFFER_FPS
        });
      } else {
        replayPlaying = false;
        replayFrames = null;
      }''', 'log source')

sub(r'''        seconds: +(frameBuffer.length / replayFps).toFixed(1),
        actualFps: +replayFps.toFixed(1)
      });''',
r'''        seconds: +(replaySourceFrames().length / replayFps).toFixed(1),
        actualFps: +replayFps.toFixed(1)
      });''', 'clip log uses source')

sub(r'''      clipDeadlineMs = (frameBuffer.length / replayFps) * 1000 + 4000;''',
r'''      clipDeadlineMs = (replaySourceFrames().length / replayFps) * 1000 + 4000;''', 'deadline uses source')

sub(r'''      if (!frameBuffer.length) { showToast("Nothing to save", 3000); return; }''',
r'''      if (!replaySourceFrames().length) { showToast("Nothing to save", 3000); return; }''', 'export guard uses source')

# ---------- discard ----------
sub(r'''    btnSaveFrame.addEventListener("click", saveFrame);''',
r'''    btnDiscardSwing.addEventListener("click", (e) => {
      e.stopPropagation();
      discardSwingClip();
      if (appMode === "replay") setAppMode("live");
      showToast("Swing discarded");
    });

    btnSaveFrame.addEventListener("click", saveFrame);''', 'discard wiring')

sub(r'''    const BUILD = "2026-09-05-hardened";''',
r'''    const BUILD = "2026-09-05-autoswing";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
