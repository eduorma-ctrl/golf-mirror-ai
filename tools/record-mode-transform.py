#!/usr/bin/env python3
"""Replace motion-triggered capture with a deliberate Record mode.

Run from the repository root:

    python3 tools/record-mode-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

Auto-capture is deleted. It could not have worked: the detector downscaled to
64x64 and took a mean pixel difference, at which size a club is thinner than one
pixel and a walking body fills the frame -- so walking in scored HIGHER than
swinging. The ordering was inverted, and no threshold can separate two things it
ranks the wrong way round. Tuning SWING_ON and SWING_MAX_MS was effort spent on a
signal that had nothing to say.

What replaces it is a trigger the golfer pulls: countdown, then record for a set
number of seconds, then review. A deliberate trigger cannot false-fire, which is
the entire complaint.

Modes become Live / Delay / Record.

- Live no longer buffers at all. It was always-recording to feed auto-capture,
  and with that gone the cost has no purchaser.
- Delay buffers only what the slider can reach, rather than the full ceiling.
- Record buffers only during its own countdown-started window, then freezes and
  shows the transport. Review is a phase of Record, not a fourth button.

Motion sampling stays, stripped of every decision it used to make. Each frame
still carries its reading so the trace can show where the action is inside a
clip -- navigation, never a trigger. Being wrong now costs a scrub.
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


def cut(a, label):
    sub(a, '', label)


# ---------- state ----------
sub(r'''    // The held swing. Frames are moved here out of frameBuffer, never copied:
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
    // A swing is over in about a second and a half. Walking to the phone and
    // stopping is the same "burst then stillness" shape but lasts far longer,
    // and duration separates the two more cleanly than any motion threshold.
    const SWING_MAX_MS = 2500;
    const SWING_COOLDOWN_MS = 3000;
    // A held clip the golfer has not opened yet is the swing they came for. It
    // is never replaced -- the walk over would otherwise be what replaces it.
    let swingClipViewed = false;
    let motionValue = 0;
    let lastMotionSample = 0;
    let swingActive = false;
    let swingStartedAt = 0;
    let swingPeak = 0;
    let swingQuietSince = 0;
    let lastCaptureAt = 0;''',
r'''    // Motion, sampled at 10Hz rather than per frame -- getImageData is a
    // GPU-to-CPU readback, which is why the countdown's stability check has
    // always been the only thing doing it. It decides nothing now: each frame
    // carries its reading so the trace can show where the action is inside a
    // recorded clip. Navigation, never a trigger.
    const MOTION_SAMPLE_MS = 100;
    let motionValue = 0;
    let lastMotionSample = 0;

    // Record is a mode with two phases. "armed" is the countdown, "recording"
    // is the window, "review" is the transport over what was caught. Review
    // being a phase rather than a fourth button keeps the footer usable on a
    // phone, which is where this app is used.
    const RECORD_LENGTHS = [5, 10, 15];
    let recordLengthIndex = 1;
    let recordState = "idle";
    let recordStartedAt = 0;
    let aiSwingAnalysis = false;
    try { aiSwingAnalysis = localStorage.getItem("golf_ai_swing") === "1"; } catch (e) {}''', 'swing state -> record state')

sub(r'''    // Raw bitmaps, so this is the wrong lever to keep pulling. Much past ten
    // seconds and a phone will feel it; longer clips want MediaRecorder.
    const MAX_BUFFER_SECONDS = 10;''',
r'''    // Raw bitmaps, so this is the wrong lever to keep pulling. The ceiling now
    // has to cover the longest recording rather than a rolling window, but it is
    // occupied far less of the time: Live never buffers, Delay keeps only what
    // its slider can reach, and Record holds frames only inside its own window.
    const MAX_BUFFER_SECONDS = 15;''', 'buffer seconds')

# ---------- refs ----------
sub(r'''    const swingBadge = $("swing-badge");
    const btnDiscardSwing = $("btn-discard-swing");''',
r'''    const recordControls = $("record-controls");
    const btnRecordLength = $("btn-record-length");
    const btnRecordAi = $("btn-record-ai");
    const recIndicator = $("rec-indicator");
    const recIndicatorText = $("rec-indicator-text");''', 'record refs')

sub(r'''    const btnModeReplay = $("btn-mode-replay");''',
r'''    const btnModeRecord = $("btn-mode-record");''', 'record button ref')

# ---------- markup ----------
sub(r'''        <button id="btn-mode-replay" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition">
          Replay
        </button>
        <span id="swing-badge" class="hidden items-center gap-1 px-2 py-1 rounded-lg bg-sky-500/20 border border-sky-500/50 text-sky-300 text-[10px] font-bold">
          <i data-lucide="check" class="w-3 h-3"></i> Swing
          <button id="btn-discard-swing" class="ml-0.5 text-sky-400/70 hover:text-white" title="Discard the captured swing">&times;</button>
        </span>
      </div>''',
r'''        <button id="btn-mode-record" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition">
          Record
        </button>
      </div>''', 'record mode button')

sub(r'''      <div id="delay-controls" class="flex-1 flex items-center justify-end gap-2 opacity-50 pointer-events-none transition-opacity min-w-0">''',
r'''      <div id="record-controls" class="hidden flex-1 items-center justify-end gap-1.5 min-w-0">
        <button id="btn-record-length" class="shrink-0 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-rose-300 text-[11px] font-bold active:scale-95 transition" title="Recording length">10s</button>
        <button id="btn-record-ai" class="shrink-0 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-400 text-[11px] font-bold active:scale-95 transition" title="Analyse the swing with AI after recording">AI off</button>
      </div>

      <div id="delay-controls" class="flex-1 flex items-center justify-end gap-2 opacity-50 pointer-events-none transition-opacity min-w-0">''', 'record controls')

sub(r'''    <div id="lock-flash-overlay"''',
r'''    <div id="rec-indicator" class="hidden absolute top-4 left-4 bg-rose-600 text-white font-bold text-xs px-3 py-1 rounded-full backdrop-blur shadow-xl flex items-center gap-1.5 z-20">
      <span class="w-2 h-2 rounded-full bg-white animate-pulse"></span>
      <span id="rec-indicator-text">REC 10.0s</span>
    </div>

    <div id="lock-flash-overlay"''', 'rec indicator')

# ---------- delete the detector ----------
sub(r'''    // Sampled from the video element rather than the main canvas so that guides,
    // badges and the replay frame itself cannot register as movement.
    function sampleMotion(now) {''',
r'''    // Sampled from the video element rather than the main canvas so that guides
    // and the replayed frame itself cannot register as movement.
    function sampleMotion(now) {''', 'sampleMotion comment')

sub(r'''    // A swing is a burst of motion followed by the golfer standing still. Both
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
      discardSwingClip();
      const cutoff = now - SWING_CLIP_SECONDS * 1000;
      let i = frameBuffer.length;
      while (i > 0 && frameBuffer[i - 1].timestamp >= cutoff) i--;
      const taken = frameBuffer.splice(i);
      for (let k = 0; k < taken.length; k++) swingClip.push(taken[k]);

      if (swingClip.length < 2) { discardSwingClip(); return; }

      lastCaptureAt = now;
      swingClipViewed = false;
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
      closeFrames(swingClip);
      swingClipViewed = false;
      swingBadge.classList.add("hidden");
      swingBadge.classList.remove("flex");
    }

    // ---------- Timer ----------''',
r'''    // ---------- Recording ----------
    function recordSeconds() { return RECORD_LENGTHS[recordLengthIndex]; }

    function startRecording() {
      clearFrameBuffer();
      recordState = "recording";
      recordStartedAt = performance.now();
      replayFrames = null;
      replayBar.classList.add("hidden");
      recIndicator.classList.remove("hidden");
      recIndicatorText.textContent = "REC " + recordSeconds().toFixed(1) + "s";
      logLine("info", "Recording started", { seconds: recordSeconds(), ai: aiSwingAnalysis });
    }

    function finishRecording() {
      recordState = "review";
      recIndicator.classList.add("hidden");
      if (frameBuffer.length < 2) {
        recordState = "idle";
        showToast("Nothing was recorded - is the camera running?", 4000);
        logLine("warn", "Recording produced no frames");
        return;
      }
      replayFrames = frameBuffer;
      replayIndex = 0;
      replaySpeed = 1;
      btnReplaySpeed.textContent = "1x";
      replayFps = measureBufferFps(frameBuffer);
      replayScrub.max = String(Math.max(1, frameBuffer.length - 1));
      replayBar.classList.remove("hidden");
      sizeMotionTrace();
      setReplayPlaying(true);
      syncReplayUi(true);
      playBeep(880, 0.2);
      logLine("ok", "Recording finished", {
        frames: frameBuffer.length,
        seconds: +(frameBuffer.length / replayFps).toFixed(1),
        actualFps: +replayFps.toFixed(1)
      });
      if (aiSwingAnalysis) showToast("Swing analysis is not built yet", 3000);
    }

    function cancelRecording() {
      recordState = "idle";
      recIndicator.classList.add("hidden");
      replayBar.classList.add("hidden");
      replayFrames = null;
      replayPlaying = false;
    }

    // ---------- Timer ----------''', 'detector -> recording')

# ---------- render loop ----------
sub(r'''      // Not while replaying: the sample would read a paused frame, and a capture
      // would move frames out from under the playhead.
      if (liveReady && appMode !== "replay") {
        sampleMotion(now);
        detectSwing(now);
      }

      // Always recording, so Replay has something to show whichever mode the
      // golfer was in when they swung. Frozen in replay: the clip being watched
      // must not change underneath the playhead.
      if (liveReady && appMode !== "replay" && !bufferBusy &&''',
r'''      // Not while reviewing: the sample would read a paused frame, and the
      // reading is only wanted for frames actually being buffered.
      if (liveReady && recordState !== "review") sampleMotion(now);

      // Only where a buffer is wanted. Live keeps none -- it used to feed the
      // motion trigger, and with that gone the cost has no purchaser.
      const buffering = (appMode === "delay") ||
                        (appMode === "record" && recordState === "recording");

      if (liveReady && buffering && !bufferBusy &&''', 'render gating')

sub(r'''          .then(bitmap => {
            // This resolves a frame or two late. If replay began in between,
            // the buffer is frozen and already measured -- appending here would
            // end the clip on a frame the golfer never saw.
            if (appMode === "replay") {''',
r'''          .then(bitmap => {
            // This resolves a frame or two late. If review began in between,
            // the buffer is frozen and already measured -- appending here would
            // end the clip on a frame the golfer never saw.
            if (recordState === "review" || !buffering) {''', 'late bitmap guard')

sub(r'''      // Prune every frame regardless of async outcome -- except in replay, where
      // dropping the head would slide the clip out from under the playhead.
      if (appMode !== "replay") {
        const maxKeep = MAX_BUFFER_SECONDS * 1000;
        while (frameBuffer.length &&
               (now - frameBuffer[0].timestamp > maxKeep ||
                frameBuffer.length + swingClip.length > MAX_BUFFER_FRAMES)) {
          const old = frameBuffer.shift();
          if (old.bitmap && old.bitmap.close) { try { old.bitmap.close(); } catch (e) {} }
        }
      } else if (replaySourceFrames().length) {
        advanceReplay(now);
        drawMotionTrace();
      }''',
r'''      if (appMode === "delay") {
        // Only what the slider can reach, plus a margin. Holding the full
        // ceiling for a three second delay was memory nobody was spending.
        const maxKeep = Math.min(MAX_BUFFER_SECONDS, delaySeconds + 2) * 1000;
        while (frameBuffer.length &&
               (now - frameBuffer[0].timestamp > maxKeep ||
                frameBuffer.length > MAX_BUFFER_FRAMES)) {
          const old = frameBuffer.shift();
          if (old.bitmap && old.bitmap.close) { try { old.bitmap.close(); } catch (e) {} }
        }
      } else if (appMode === "record" && recordState === "recording") {
        const elapsed = now - recordStartedAt;
        const total = recordSeconds() * 1000;
        recIndicatorText.textContent = "REC " + Math.max(0, (total - elapsed) / 1000).toFixed(1) + "s";
        // A hard frame cap as well as a clock: a slow phone that cannot keep up
        // still must not be allowed to outgrow the ceiling.
        if (elapsed >= total || frameBuffer.length >= MAX_BUFFER_FRAMES) finishRecording();
      } else if (recordState === "review" && frameBuffer.length) {
        advanceReplay(now);
        drawMotionTrace();
      }''', 'prune / record clock')

sub(r'''      } else if (appMode === "replay" && replaySourceFrames().length) {
        const rf = replaySourceFrames()[replayFrameIndex()];''',
r'''      } else if (recordState === "review" && replaySourceFrames().length) {
        const rf = replaySourceFrames()[replayFrameIndex()];''', 'draw review branch')

sub(r'''      } else if (appMode === "live" || frameBuffer.length === 0) {''',
r'''      } else if (appMode !== "delay" || frameBuffer.length === 0) {''', 'live/record draw live')

# ---------- replay source is just the buffer now ----------
sub(r'''    // The held swing when there is one, the live buffer otherwise.
    function replaySourceFrames() {
      return replayFrames || (swingClip.length ? swingClip : frameBuffer);
    }''',
r'''    function replaySourceFrames() {
      return replayFrames || frameBuffer;
    }''', 'replaySourceFrames')

# ---------- countdown ends differently per mode ----------
sub(r'''          countdownOverlay.classList.add("hidden");
          resetTimerButton();
          playBeep(880, 0.25);
          executeMultiFrameBurstScan();''',
r'''          countdownOverlay.classList.add("hidden");
          resetTimerButton();
          playBeep(880, 0.25);
          // The same countdown serves both: it exists to give the golfer time to
          // walk in and settle, which is as true of a recording as of a scan.
          if (appMode === "record") startRecording();
          else executeMultiFrameBurstScan();''', 'countdown branches')

# ---------- mode switching ----------
sub(r'''    btnModeReplay.addEventListener("click", () => setAppMode("replay"));''',
r'''    btnModeRecord.addEventListener("click", () => setAppMode("record"));

    btnRecordLength.addEventListener("click", () => {
      if (recordState === "recording") return;
      recordLengthIndex = (recordLengthIndex + 1) % RECORD_LENGTHS.length;
      btnRecordLength.textContent = recordSeconds() + "s";
      showToast("Recording length " + recordSeconds() + "s");
    });

    btnRecordAi.addEventListener("click", () => {
      aiSwingAnalysis = !aiSwingAnalysis;
      try { localStorage.setItem("golf_ai_swing", aiSwingAnalysis ? "1" : "0"); } catch (e) {}
      syncRecordAiButton();
      showToast(aiSwingAnalysis ? "AI swing analysis on" : "AI swing analysis off");
    });

    function syncRecordAiButton() {
      btnRecordAi.textContent = aiSwingAnalysis ? "AI on" : "AI off";
      btnRecordAi.classList.toggle("text-emerald-300", aiSwingAnalysis);
      btnRecordAi.classList.toggle("border-emerald-500/50", aiSwingAnalysis);
      btnRecordAi.classList.toggle("text-slate-400", !aiSwingAnalysis);
      btnRecordAi.classList.toggle("border-slate-700", !aiSwingAnalysis);
    }''', 'record controls wiring')

sub(r'''      // Refusing early keeps the button honest: nothing buffered means nothing
      // to replay, and silently showing a frozen live frame would look broken.
      // The held swing is preferred: it is centred on what the golfer came to
      // look at, where the live buffer merely ends at whenever they arrived.
      const entering = swingClip.length ? swingClip : frameBuffer;
      if (mode === "replay" && !entering.length) {
        showToast("Nothing recorded yet - give it a few seconds", 3000);
        return;
      }
      if (exportingClip) {
        // Re-entering replay would rewind the playhead under a running
        // recorder; walking out would keep capturing the live feed into a
        // file the golfer asked to be of their replay.
        if (mode === "replay") return;
        stopClipExport();
      }
      appMode = mode;''',
r'''      if (exportingClip) {
        // Re-entering the mode being exported would rewind the playhead under a
        // running recorder; leaving would keep capturing the live feed into a
        // file the golfer asked to be of their clip.
        if (mode === appMode) return;
        stopClipExport();
      }
      if (isCountingDown) cancelHandsFreeTimer();
      // Leaving Record throws the clip away, and going back to it starts clean:
      // a stale review of a recording made two modes ago is a thing to explain
      // rather than a thing to want.
      if (appMode === "record" && mode !== "record") cancelRecording();
      if (mode === "record") { cancelRecording(); clearFrameBuffer(); }
      appMode = mode;''', 'setAppMode guards')

sub(r'''      btnModeReplay.className = MODE_BTN_BASE + (mode === "replay"
        ? "bg-sky-500 text-slate-950 shadow" : MODE_BTN_IDLE);
      delayControls.classList.toggle("opacity-50", mode !== "delay");
      delayControls.classList.toggle("pointer-events-none", mode !== "delay");
      delayIndicator.classList.toggle("hidden", mode !== "delay");
      replayBar.classList.toggle("hidden", mode !== "replay");

      if (mode === "replay") {
        replayFrames = entering;
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
        syncReplayUi(true);
        // actualFps against target is the whole answer on whether 60 is worth
        // asking for: short of target here means the pipeline, not the camera.
        logLine("info", "Replay", {
          source: entering === swingClip ? "captured swing" : "live buffer",
          frames: entering.length,
          seconds: +(entering.length / replayFps).toFixed(1),
          actualFps: +replayFps.toFixed(1),
          targetFps: BUFFER_FPS
        });
      } else {
        replayPlaying = false;
        replayFrames = null;
      }
    }''',
r'''      btnModeRecord.className = MODE_BTN_BASE + (mode === "record"
        ? "bg-rose-500 text-slate-950 shadow" : MODE_BTN_IDLE);
      delayControls.classList.toggle("hidden", mode !== "delay");
      delayControls.classList.toggle("flex", mode === "delay");
      delayControls.classList.toggle("opacity-50", mode !== "delay");
      delayControls.classList.toggle("pointer-events-none", mode !== "delay");
      delayIndicator.classList.toggle("hidden", mode !== "delay");
      recordControls.classList.toggle("hidden", mode !== "record");
      recordControls.classList.toggle("flex", mode === "record");
      exportStatus.textContent = "";

      if (mode === "record") {
        btnRecordLength.textContent = recordSeconds() + "s";
        syncRecordAiButton();
        showToast("Tap Lock to start the countdown", 3000);
      }
    }''', 'setAppMode body')

sub(r'''    btnModeLive.addEventListener("click", () => {
      setAppMode("live");''',
r'''    btnModeLive.addEventListener("click", () => {
      setAppMode("live");
      clearFrameBuffer();''', 'live clears buffer')

# ---------- focus mode + visibility ----------
sub(r'''      replayBar.classList.toggle("hidden", focusMode || appMode !== "replay");''',
r'''      replayBar.classList.toggle("hidden", focusMode || recordState !== "review");''', 'focus hides transport')

sub(r'''        if (exportingClip) stopClipExport();
        if (appMode !== "replay") clearFrameBuffer();''',
r'''        if (exportingClip) stopClipExport();
        if (recordState !== "review") clearFrameBuffer();''', 'visibility guard')

sub(r'''    function resizeCanvas() {
      const dpr''',
r'''    function resizeCanvas() {
      const dpr''', 'resize untouched')

sub(r'''        if (appMode === "replay") sizeMotionTrace();''',
r'''        if (recordState === "review") sizeMotionTrace();''', 'resize trace')

# ---------- guards that named the old mode ----------
sub(r'''      if (exportingClip) return;
      const pos = getCanvasCoords(e);''',
r'''      if (exportingClip || recordState === "recording") return;
      const pos = getCanvasCoords(e);''', 'no dragging while recording')

sub(r'''    const BUILD = "2026-09-06-setup";''',
r'''    const BUILD = "2026-09-06-record";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
