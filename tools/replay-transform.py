#!/usr/bin/env python3
"""Turn the delay buffer into a scrubbable replay.

Run from the repository root:

    python3 tools/replay-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.
Running it twice fails loudly on the first anchor, which is correct.

The recording already existed. frameBuffer has always held the last few seconds
as ImageBitmaps -- delay mode just reads it at a fixed offset from now. So this
adds no capture pipeline. It makes the buffer always-on, freezes it on demand,
and points a playhead at it.

1. Always buffering. The buffer used to fill only in delay mode and was cleared
   on the way out, so a swing hit in Live was gone before you could ask to see
   it. It now fills in every mode except replay, where it must stay frozen.

2. Ten seconds instead of eight, which is what the golfer asked for. These are
   raw bitmaps, so this is the wrong lever to keep pulling: much past this and
   a phone will feel it. Longer clips want MediaRecorder, not a bigger array.

3. A replay mode with a playhead: play/pause, scrub, single-frame step, and
   quarter/half speed. It loops, because the point is watching the same two
   seconds over and over.

4. Pruning and the backgrounding handler both learn to leave the buffer alone
   during replay. Without that the clip erodes under the golfer while they
   watch it, which looks like a rendering bug and is not one.

Not included, by agreement: download. Replay is deliberately ephemeral for now
-- leave replay and the clip is gone.
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


# 1. the third mode button
sub(r'''        <button id="btn-mode-delay" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition">
          Delayed
        </button>
      </div>''',
r'''        <button id="btn-mode-delay" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition">
          Delayed
        </button>
        <button id="btn-mode-replay" class="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition">
          Replay
        </button>
      </div>''', 'replay mode button')

# 2. the transport, on its own row so the mode row keeps its layout on a phone
sub(r'''        <input id="delay-slider" type="range" min="1" max="8" step="0.5" value="3" class="w-20 sm:w-32 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500" />
      </div>
    </div>
  </footer>''',
r'''        <input id="delay-slider" type="range" min="1" max="8" step="0.5" value="3" class="w-20 sm:w-32 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-emerald-500" />
      </div>
    </div>

    <div id="replay-bar" class="hidden max-w-xl mx-auto mt-2 flex items-center gap-1.5">
      <button id="btn-replay-play" class="shrink-0 p-2 rounded-lg bg-sky-500 text-slate-950 active:scale-95 transition" title="Play / pause">
        <i data-lucide="pause" class="w-4 h-4"></i>
      </button>
      <button id="btn-replay-prev" class="shrink-0 p-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 active:scale-95 transition" title="Previous frame">
        <i data-lucide="chevron-left" class="w-4 h-4"></i>
      </button>
      <button id="btn-replay-next" class="shrink-0 p-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 active:scale-95 transition" title="Next frame">
        <i data-lucide="chevron-right" class="w-4 h-4"></i>
      </button>
      <input id="replay-scrub" type="range" min="0" max="1" step="1" value="0" class="flex-1 min-w-0 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-sky-400" />
      <span id="replay-time" class="shrink-0 text-[10px] font-mono text-sky-300 w-14 text-right">0.0/0.0s</span>
      <button id="btn-replay-speed" class="shrink-0 px-2 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sky-300 text-[11px] font-bold active:scale-95 transition" title="Playback speed">1x</button>
    </div>
  </footer>''', 'replay transport bar')

# 3. ten seconds, and the playhead state
sub(r'''    const MAX_BUFFER_SECONDS = 8;''',
r'''    // Raw bitmaps, so this is the wrong lever to keep pulling. Much past ten
    // seconds and a phone will feel it; longer clips want MediaRecorder.
    const MAX_BUFFER_SECONDS = 10;''', 'buffer seconds')

sub(r'''    let bufferBusy = false;''',
r'''    let bufferBusy = false;

    // Replay reads the same buffer delay does, but from a playhead the golfer
    // drives instead of a fixed offset from now. Held as a float so fractional
    // speeds accumulate smoothly rather than stalling on a rounded index.
    let replayIndex = 0;
    let replayPlaying = false;
    let replaySpeed = 1;
    let replayLastTick = 0;
    let replayScrubbing = false;
    const REPLAY_SPEEDS = [1, 0.5, 0.25];''', 'replay state')

# 4. element refs
sub(r'''    const btnModeDelay = $("btn-mode-delay");''',
r'''    const btnModeDelay = $("btn-mode-delay");
    const btnModeReplay = $("btn-mode-replay");
    const replayBar = $("replay-bar");
    const btnReplayPlay = $("btn-replay-play");
    const btnReplayPrev = $("btn-replay-prev");
    const btnReplayNext = $("btn-replay-next");
    const replayScrub = $("replay-scrub");
    const replayTime = $("replay-time");
    const btnReplaySpeed = $("btn-replay-speed");''', 'replay refs')

# 5. buffer in every mode except replay, where it must stay frozen
sub(r'''      // Buffer frames for delayed replay, only while in delay mode
      if (liveReady && appMode === "delay" && !bufferBusy &&''',
r'''      // Always recording, so Replay has something to show whichever mode the
      // golfer was in when they swung. Frozen in replay: the clip being watched
      // must not change underneath the playhead.
      if (liveReady && appMode !== "replay" && !bufferBusy &&''', 'buffer always on')

# 6. pruning stops during replay too, or the clip erodes while it plays
sub(r'''      // Prune every frame regardless of async outcome
      const maxKeep = MAX_BUFFER_SECONDS * 1000;
      while (frameBuffer.length && now - frameBuffer[0].timestamp > maxKeep) {
        const old = frameBuffer.shift();
        if (old.bitmap && old.bitmap.close) { try { old.bitmap.close(); } catch (e) {} }
      }
      if (appMode !== "delay" && frameBuffer.length) clearFrameBuffer();''',
r'''      // Prune every frame regardless of async outcome -- except in replay, where
      // dropping the head would slide the clip out from under the playhead.
      if (appMode !== "replay") {
        const maxKeep = MAX_BUFFER_SECONDS * 1000;
        while (frameBuffer.length && now - frameBuffer[0].timestamp > maxKeep) {
          const old = frameBuffer.shift();
          if (old.bitmap && old.bitmap.close) { try { old.bitmap.close(); } catch (e) {} }
        }
      } else if (frameBuffer.length) {
        advanceReplay(now);
      }''', 'prune guard + advance')

# 7. the replay branch has to be tested before the live one
sub(r'''      } else if (appMode === "live" || frameBuffer.length === 0) {''',
r'''      } else if (appMode === "replay" && frameBuffer.length) {
        const rf = frameBuffer[replayFrameIndex()];
        if (rf && rf.bitmap) drawContain(rf.bitmap, rf.bitmap.width, rf.bitmap.height, w, h);
        else drawContain(video, video.videoWidth, video.videoHeight, w, h);
      } else if (appMode === "live" || frameBuffer.length === 0) {''', 'replay draw branch')

# 8. playhead + transport, next to the buffer helpers they work on
sub(r'''    function clearFrameBuffer() {''',
r'''    function replayFrameIndex() {
      return Math.max(0, Math.min(frameBuffer.length - 1, Math.floor(replayIndex)));
    }

    function advanceReplay(now) {
      if (replayPlaying && !replayScrubbing) {
        const dt = now - replayLastTick;
        // Wall-clock rather than one-index-per-render: playback stays true to
        // the capture rate even when the render loop drops frames.
        replayIndex += (dt / 1000) * BUFFER_FPS * replaySpeed;
        // Loop. The point of replay is watching the same two seconds again.
        if (replayIndex >= frameBuffer.length) replayIndex = 0;
        syncReplayUi();
      }
      replayLastTick = now;
    }

    function syncReplayUi() {
      const total = frameBuffer.length;
      replayScrub.max = String(Math.max(1, total - 1));
      if (!replayScrubbing) replayScrub.value = String(replayFrameIndex());
      replayTime.textContent = (replayFrameIndex() / BUFFER_FPS).toFixed(1) + "/" +
        (total / BUFFER_FPS).toFixed(1) + "s";
    }

    function setReplayPlaying(playing) {
      replayPlaying = playing;
      replayLastTick = performance.now();
      btnReplayPlay.innerHTML = '<i data-lucide="' + (playing ? "pause" : "play") + '" class="w-4 h-4"></i>';
      if (window.lucide) lucide.createIcons();
    }

    function stepReplay(delta) {
      setReplayPlaying(false);
      replayIndex = replayFrameIndex() + delta;
      if (replayIndex < 0) replayIndex = frameBuffer.length - 1;
      if (replayIndex > frameBuffer.length - 1) replayIndex = 0;
      syncReplayUi();
    }

    function clearFrameBuffer() {''', 'replay helpers')

# 9. one place that owns the mode, instead of two handlers repeating class strings
sub(r'''    btnModeLive.addEventListener("click", () => {
      appMode = "live";
      btnModeLive.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 text-white shadow transition";
      btnModeDelay.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition";
      delayControls.classList.add("opacity-50", "pointer-events-none");
      delayIndicator.classList.add("hidden");''',
r'''    const MODE_BTN_BASE = "px-3 py-1.5 rounded-lg text-xs font-semibold transition ";
    const MODE_BTN_IDLE = "bg-slate-800 text-slate-400 border border-slate-700 hover:text-white";

    function setAppMode(mode) {
      // Refusing early keeps the button honest: nothing buffered means nothing
      // to replay, and silently showing a frozen live frame would look broken.
      if (mode === "replay" && !frameBuffer.length) {
        showToast("Nothing recorded yet - give it a few seconds", 3000);
        return;
      }
      appMode = mode;
      btnModeLive.className = MODE_BTN_BASE + (mode === "live"
        ? "bg-emerald-600 text-white shadow" : MODE_BTN_IDLE);
      btnModeDelay.className = MODE_BTN_BASE + (mode === "delay"
        ? "bg-amber-500 text-slate-950 shadow" : MODE_BTN_IDLE);
      btnModeReplay.className = MODE_BTN_BASE + (mode === "replay"
        ? "bg-sky-500 text-slate-950 shadow" : MODE_BTN_IDLE);
      delayControls.classList.toggle("opacity-50", mode !== "delay");
      delayControls.classList.toggle("pointer-events-none", mode !== "delay");
      delayIndicator.classList.toggle("hidden", mode !== "delay");
      replayBar.classList.toggle("hidden", mode !== "replay");

      if (mode === "replay") {
        replayIndex = 0;
        replaySpeed = 1;
        btnReplaySpeed.textContent = "1x";
        setReplayPlaying(true);
        syncReplayUi();
        logLine("info", "Replay", {
          frames: frameBuffer.length,
          seconds: +(frameBuffer.length / BUFFER_FPS).toFixed(1)
        });
      } else {
        replayPlaying = false;
      }
    }

    btnModeReplay.addEventListener("click", () => setAppMode("replay"));

    btnReplayPlay.addEventListener("click", () => setReplayPlaying(!replayPlaying));
    btnReplayPrev.addEventListener("click", () => stepReplay(-1));
    btnReplayNext.addEventListener("click", () => stepReplay(1));

    replayScrub.addEventListener("pointerdown", () => { replayScrubbing = true; });
    ["pointerup", "pointercancel"].forEach((ev) =>
      replayScrub.addEventListener(ev, () => { replayScrubbing = false; }));
    replayScrub.addEventListener("input", (e) => {
      setReplayPlaying(false);
      replayIndex = parseInt(e.target.value, 10) || 0;
      replayTime.textContent = (replayFrameIndex() / BUFFER_FPS).toFixed(1) + "/" +
        (frameBuffer.length / BUFFER_FPS).toFixed(1) + "s";
    });

    btnReplaySpeed.addEventListener("click", () => {
      replaySpeed = REPLAY_SPEEDS[(REPLAY_SPEEDS.indexOf(replaySpeed) + 1) % REPLAY_SPEEDS.length];
      btnReplaySpeed.textContent = replaySpeed === 1 ? "1x" : String(replaySpeed).replace("0.", ".") + "x";
      replayLastTick = performance.now();
    });

    btnModeLive.addEventListener("click", () => {
      setAppMode("live");''', 'setAppMode + transport wiring')

sub(r'''    btnModeDelay.addEventListener("click", () => {
      appMode = "delay";
      btnModeDelay.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-500 text-slate-950 shadow transition";
      btnModeLive.className = "px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-400 border border-slate-700 hover:text-white transition";
      delayControls.classList.remove("opacity-50", "pointer-events-none");
      delayIndicator.classList.remove("hidden");''',
r'''    btnModeDelay.addEventListener("click", () => {
      setAppMode("delay");''', 'delay handler via setAppMode')

# 10. backgrounding must not destroy the clip being watched
sub(r'''      if (document.hidden) { clearFrameBuffer(); }''',
r'''      // Dropping the buffer on the way out is how the camera gets released
      // cleanly, but doing it during replay throws away the clip the golfer
      // paused on and came back to.
      if (document.hidden) { if (appMode !== "replay") clearFrameBuffer(); }''', 'visibility guard')

# 11. the replay transport is UI like any other; practice view hides it
sub(r'''      [guideToggles, tushAdjustWidget, planeStatusBadge, diagnosticsPill].forEach((el) => {
        if (el) el.classList.toggle("hidden", focusMode);
      });''',
r'''      [guideToggles, tushAdjustWidget, planeStatusBadge, diagnosticsPill].forEach((el) => {
        if (el) el.classList.toggle("hidden", focusMode);
      });
      replayBar.classList.toggle("hidden", focusMode || appMode !== "replay");''', 'focus mode hides transport')

sub(r'''    const BUILD = "2026-09-05-faceon";''',
r'''    const BUILD = "2026-09-05-replay";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
