#!/usr/bin/env python3
"""Fix the seven performance and stability defects found reviewing replay/export.

Run from the repository root:

    python3 tools/hardening-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

1. The frame gate silently defeated the 30fps change. "now - last > 1000/30"
   is "> 33.333...", and two rAF intervals on a 60Hz screen land at 33.33 --
   not greater. Capture waited a third interval and ran at 20fps, the rate the
   change existed to leave behind. A few ms of tolerance fixes it at 60Hz and
   120Hz alike without over-capturing.

2. Memory had no ceiling independent of the frame rate. Pruning is by age, so
   raising fps multiplied the resident frames: 10s went from 200 to 300, and
   60fps would have made it 600 without anyone choosing that. A frame cap
   alongside the age cap turns the rate/duration trade automatic -- ask for
   more fps and you keep fewer seconds, at constant memory.

3. Clip export could run forever. advanceReplay() is what notices the loop
   wrapping and stops the recorder, and it only runs while frameBuffer has
   frames: flip the camera mid-record and the buffer empties, the wrap never
   comes, and MediaRecorder encodes into a growing chunk list until reload.
   Backgrounding did the same by stopping rAF. Now a watchdog outside that
   gate ends the recording on an empty buffer or a passed deadline, and
   hiding the page stops it outright.

4. clipRecorder.start() sat outside the try/catch guarding the constructor,
   after the UI was already disabled, so a throw left a dead transport with no
   message and no file.

5. The capture stream was never released. Each export left a live 30fps canvas
   capture running for the life of the page.

6. Scrubbing janked itself: the input handler called setReplayPlaying(false)
   on every pointer tick, and that rewrites innerHTML and runs a document-wide
   lucide.createIcons(). It now fires once, on the tick that actually pauses.

7. A createImageBitmap in flight when replay was entered resolved afterwards
   and pushed a live frame into the frozen buffer, past the point where its
   length and rate were measured -- so the clip ended on a frame the golfer
   never saw. Late arrivals are now discarded and closed.
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


# 1 + 2. a frame ceiling, and the gate tolerance
sub(r'''    // A clubhead at impact moves ~45 m/s: at 20fps it crossed more than two
    // metres between frames and a frame at impact essentially never happened.
    const BUFFER_FPS = 30;''',
r'''    // A clubhead at impact moves ~45 m/s: at 20fps it crossed more than two
    // metres between frames and a frame at impact essentially never happened.
    const BUFFER_FPS = 30;

    // Pruning by age alone let the frame rate set the memory bill: 10s went
    // from 200 frames to 300 when the rate rose, and 60fps would have made it
    // 600 without anyone choosing that. Capping frames as well makes the trade
    // automatic -- a higher rate keeps fewer seconds, at constant memory.
    const MAX_BUFFER_FRAMES = MAX_BUFFER_SECONDS * BUFFER_FPS;

    // "> 1000/BUFFER_FPS" is "> 33.333..." at 30fps, and two rAF intervals on a
    // 60Hz screen land at 33.33 -- not greater. Capture waited a third interval
    // and ran at 20fps. A few ms of slack lands on the right interval at 60Hz
    // and 120Hz alike without capturing early.
    const BUFFER_GAP_MS = 1000 / BUFFER_FPS - 4;''', 'frame cap + gate tolerance')

sub(r'''          now - lastBufferPushTime > 1000 / BUFFER_FPS &&''',
r'''          now - lastBufferPushTime > BUFFER_GAP_MS &&''', 'gate uses tolerance')

# 7. a bitmap in flight when replay starts must not land in the frozen buffer
sub(r'''        createImageBitmap(video)
          .then(bitmap => { frameBuffer.push({ timestamp: performance.now(), bitmap }); })
          .catch(() => {})
          .finally(() => { bufferBusy = false; });''',
r'''        createImageBitmap(video)
          .then(bitmap => {
            // This resolves a frame or two late. If replay began in between,
            // the buffer is frozen and already measured -- appending here would
            // end the clip on a frame the golfer never saw.
            if (appMode === "replay") {
              if (bitmap && bitmap.close) { try { bitmap.close(); } catch (e) {} }
              return;
            }
            frameBuffer.push({ timestamp: performance.now(), bitmap });
          })
          .catch(() => {})
          .finally(() => { bufferBusy = false; });''', 'discard late bitmaps')

# 2b. prune on both limits
sub(r'''      if (appMode !== "replay") {
        const maxKeep = MAX_BUFFER_SECONDS * 1000;
        while (frameBuffer.length && now - frameBuffer[0].timestamp > maxKeep) {
          const old = frameBuffer.shift();
          if (old.bitmap && old.bitmap.close) { try { old.bitmap.close(); } catch (e) {} }
        }
      } else if (frameBuffer.length) {
        advanceReplay(now);
      }''',
r'''      if (appMode !== "replay") {
        const maxKeep = MAX_BUFFER_SECONDS * 1000;
        while (frameBuffer.length &&
               (now - frameBuffer[0].timestamp > maxKeep ||
                frameBuffer.length > MAX_BUFFER_FRAMES)) {
          const old = frameBuffer.shift();
          if (old.bitmap && old.bitmap.close) { try { old.bitmap.close(); } catch (e) {} }
        }
      } else if (frameBuffer.length) {
        advanceReplay(now);
      }''', 'prune on frames too')

# 3. a watchdog that does not depend on the buffer or on rAF still running
sub(r'''      const now = performance.now();

      const liveReady = !isSimulatedFeed && videoStream && video.videoWidth > 0 && video.readyState >= 2;''',
r'''      const now = performance.now();

      const liveReady = !isSimulatedFeed && videoStream && video.videoWidth > 0 && video.readyState >= 2;

      // advanceReplay() is what notices the loop wrapping and ends a recording,
      // and it only runs while the buffer has frames. Empty it mid-record --
      // flipping the camera does exactly that -- and the recording never ends.
      // This check sits outside that gate deliberately.
      if (exportingClip && (!frameBuffer.length || now - clipStartedAt > clipDeadlineMs)) {
        logLine("warn", "Clip export ended by watchdog", {
          frames: frameBuffer.length,
          elapsedMs: Math.round(now - clipStartedAt)
        });
        stopClipExport();
      }''', 'export watchdog')

# 4 + 5. release the stream, and let start() fail like the constructor does
sub(r'''    let clipRecorder = null;
    let clipChunks = [];
    let exportingClip = false;''',
r'''    let clipRecorder = null;
    let clipStream = null;
    let clipChunks = [];
    let exportingClip = false;
    let clipStartedAt = 0;
    let clipDeadlineMs = 0;''', 'clip state')

sub(r'''      let stream;
      try {
        stream = canvas.captureStream(30);
        clipRecorder = new MediaRecorder(stream, { mimeType: type });
      } catch (err) {''',
r'''      try {
        clipStream = canvas.captureStream(30);
        clipRecorder = new MediaRecorder(clipStream, { mimeType: type });
      } catch (err) {
        releaseClipStream();''', 'capture stream tracked')

sub(r'''          logLine("ok", "Clip saved", { name: name, kb: Math.round(blob.size / 1024), type: type });
        }
        setClipExportUi(false);
      };''',
r'''          logLine("ok", "Clip saved", { name: name, kb: Math.round(blob.size / 1024), type: type });
        }
        releaseClipStream();
        setClipExportUi(false);
      };''', 'release on stop')

sub(r'''      exportingClip = true;
      setClipExportUi(true);
      replayIndex = 0;
      replaySpeed = 1;
      btnReplaySpeed.textContent = "1x";
      setReplayPlaying(true);
      clipRecorder.start();
      logLine("info", "Clip export started", {''',
r'''      exportingClip = true;
      clipStartedAt = performance.now();
      // One pass, plus slack for a slow encoder. Past this the watchdog above
      // ends it rather than letting the recorder run on.
      clipDeadlineMs = (frameBuffer.length / replayFps) * 1000 + 4000;
      setClipExportUi(true);
      replayIndex = 0;
      replaySpeed = 1;
      btnReplaySpeed.textContent = "1x";
      setReplayPlaying(true);
      // start() throws on its own account, and by here the transport is already
      // disabled -- letting it escape left a dead UI with nothing said.
      try {
        clipRecorder.start();
      } catch (err) {
        exportingClip = false;
        clipRecorder = null;
        releaseClipStream();
        setReplayPlaying(false);
        setClipExportUi(false);
        showToast("Could not start recording", 4000);
        logLine("error", "Clip export failed at start(): " + err);
        return;
      }
      logLine("info", "Clip export started", {''', 'guarded start')

sub(r'''    function stopClipExport() {
      exportingClip = false;
      setReplayPlaying(false);
      if (clipRecorder && clipRecorder.state !== "inactive") {
        try { clipRecorder.stop(); } catch (e) { setClipExportUi(false); }
      } else {
        setClipExportUi(false);
      }
      clipRecorder = null;
    }''',
r'''    function releaseClipStream() {
      if (!clipStream) return;
      // A canvas capture keeps running at 30fps until its tracks are stopped,
      // so leaving it attached costs for the life of the page.
      try { clipStream.getTracks().forEach((t) => t.stop()); } catch (e) {}
      clipStream = null;
    }

    function stopClipExport() {
      exportingClip = false;
      setReplayPlaying(false);
      if (clipRecorder && clipRecorder.state !== "inactive") {
        // onstop does the release and the UI; only the failure path needs both
        // done here.
        try { clipRecorder.stop(); } catch (e) { releaseClipStream(); setClipExportUi(false); }
      } else {
        releaseClipStream();
        setClipExportUi(false);
      }
      clipRecorder = null;
    }''', 'release helper + stop')

# 3b. backgrounding stops the recording rather than encoding a frozen canvas
sub(r'''      if (document.hidden) { if (appMode !== "replay") clearFrameBuffer(); }''',
r'''      if (document.hidden) {
        // rAF stops when hidden, so the watchdog stops with it and the recorder
        // would encode one frozen frame for as long as the page stayed away.
        if (exportingClip) stopClipExport();
        if (appMode !== "replay") clearFrameBuffer();
      }''', 'stop export when hidden')

# 6. pause once, not on every tick of the drag
sub(r'''    replayScrub.addEventListener("input", (e) => {
      setReplayPlaying(false);
      replayIndex = parseInt(e.target.value, 10) || 0;
      syncReplayUi();
    });''',
r'''    replayScrub.addEventListener("input", (e) => {
      // setReplayPlaying rewrites innerHTML and runs a document-wide
      // lucide.createIcons(); "input" fires on every tick of the drag, so
      // calling it unconditionally janked the very gesture it serves.
      if (replayPlaying) setReplayPlaying(false);
      replayIndex = parseInt(e.target.value, 10) || 0;
      syncReplayUi();
    });''', 'scrub pauses once')

sub(r'''    const BUILD = "2026-09-05-fps30";''',
r'''    const BUILD = "2026-09-05-hardened";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
