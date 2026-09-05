#!/usr/bin/env python3
"""Ask the camera for 60fps, buffer at 30, and stop assuming either worked.

Run from the repository root:

    python3 tools/fps-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

Twenty frames a second is too coarse for a golf swing. A clubhead at impact
covers more than two metres between frames at that rate, so a frame at impact
essentially never happens. Thirty is a near-certain capability and buys half
again as many frames through the downswing.

1. The camera was never asked for a frame rate at all -- only facingMode and a
   resolution -- so it handed back whatever it felt like, and nothing recorded
   what that was. It is now asked for 60 (ideal, so an unwilling camera still
   connects) and what it actually settled on is logged and shown on the pill.

2. BUFFER_FPS 20 -> 30.

3. Playback stops assuming it got what it asked for. Both the speed of replay
   and the time readout used BUFFER_FPS as though the buffer really filled at
   that rate. It often will not: createImageBitmap has to keep up, bufferBusy
   drops any frame where it does not, and the camera may simply deliver less.
   Every such gap made replay run fast and the clock lie, and raising the
   target widens the gap. Replay now measures the real rate from the frame
   timestamps it has and drives itself from that, which also puts the true
   figure in the log -- the number that decides whether 60 is worth trying.
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


# 1. ask for 60. "ideal" so a camera that cannot still connects at whatever it has.
sub(r'''      const constraintOptions = [
        { video: { facingMode: { ideal: currentFacingMode }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false },
        { video: { facingMode: currentFacingMode }, audio: false },
        { video: true, audio: false }
      ];''',
r'''      // frameRate is "ideal", never "exact": a camera that cannot do 60 should
      // still connect at whatever it has rather than fall down the ladder.
      const constraintOptions = [
        { video: { facingMode: { ideal: currentFacingMode }, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 60 } }, audio: false },
        { video: { facingMode: { ideal: currentFacingMode }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false },
        { video: { facingMode: currentFacingMode }, audio: false },
        { video: true, audio: false }
      ];''', 'frameRate constraint')

# 2. record what the camera actually gave us
sub(r'''        const resW = s.width || video.videoWidth || 1280;
        const resH = s.height || video.videoHeight || 720;''',
r'''        const resW = s.width || video.videoWidth || 1280;
        const resH = s.height || video.videoHeight || 720;
        // What it granted, not what we asked for. Without this the buffer rate
        // was a guess about a number nobody had ever looked at.
        const camFps = s.frameRate ? Math.round(s.frameRate) : null;
        const fpsLabel = camFps ? " @" + camFps : "";''', 'camera fps settings')

sub(r'''        camDiagText.textContent = "Camera: " + facingLabel + " " + resW + "x" + resH;
        logLine("ok", "Camera connected", { facing: facingLabel, res: resW + "x" + resH });''',
r'''        camDiagText.textContent = "Camera: " + facingLabel + " " + resW + "x" + resH + fpsLabel;
        logLine("ok", "Camera connected", {
          facing: facingLabel,
          res: resW + "x" + resH,
          cameraFps: camFps,
          requestedFps: 60,
          bufferTargetFps: BUFFER_FPS
        });''', 'camera fps logging')

# 3. thirty. A clubhead at impact covers over two metres between frames at 20.
sub(r'''    const BUFFER_FPS = 20;''',
r'''    // A clubhead at impact moves ~45 m/s: at 20fps it crossed more than two
    // metres between frames and a frame at impact essentially never happened.
    const BUFFER_FPS = 30;''', 'buffer fps')

# 4. replay drives itself from the rate the buffer really achieved
sub(r'''    let replayScrubbing = false;''',
r'''    let replayScrubbing = false;
    // The rate the buffer actually achieved, which is not BUFFER_FPS whenever
    // createImageBitmap fell behind or the camera delivered less. Measured on
    // entry to replay so playback speed and the clock stay true either way.
    let replayFps = BUFFER_FPS;''', 'replayFps state')

sub(r'''    function replayFrameIndex() {''',
r'''    function measureBufferFps() {
      if (frameBuffer.length < 2) return BUFFER_FPS;
      const span = frameBuffer[frameBuffer.length - 1].timestamp - frameBuffer[0].timestamp;
      if (span <= 0) return BUFFER_FPS;
      return (frameBuffer.length - 1) / (span / 1000);
    }

    function replayFrameIndex() {''', 'measureBufferFps')

sub(r'''        replayIndex += (dt / 1000) * BUFFER_FPS * replaySpeed;''',
r'''        replayIndex += (dt / 1000) * replayFps * replaySpeed;''', 'advance uses measured fps')

sub(r'''          exportStatus.textContent = "Recording " +
            (replayFrameIndex() / BUFFER_FPS).toFixed(1) + "s...";''',
r'''          exportStatus.textContent = "Recording " +
            (replayFrameIndex() / replayFps).toFixed(1) + "s...";''', 'export status uses measured fps')

sub(r'''      replayTime.textContent = (replayFrameIndex() / BUFFER_FPS).toFixed(1) + "/" +
        (total / BUFFER_FPS).toFixed(1) + "s";''',
r'''      replayTime.textContent = (replayFrameIndex() / replayFps).toFixed(1) + "/" +
        (total / replayFps).toFixed(1) + "s";''', 'clock uses measured fps')

# 5. measure on entry, and log it -- this is the number that decides 60
sub(r'''      if (mode === "replay") {
        exportStatus.textContent = "";
        replayIndex = 0;
        replaySpeed = 1;
        btnReplaySpeed.textContent = "1x";
        setReplayPlaying(true);
        syncReplayUi();
        logLine("info", "Replay", {
          frames: frameBuffer.length,
          seconds: +(frameBuffer.length / BUFFER_FPS).toFixed(1)
        });''',
r'''      if (mode === "replay") {
        exportStatus.textContent = "";
        replayIndex = 0;
        replaySpeed = 1;
        btnReplaySpeed.textContent = "1x";
        replayFps = measureBufferFps();
        setReplayPlaying(true);
        syncReplayUi();
        // actualFps against target is the whole answer on whether 60 is worth
        // asking for: short of target here means the pipeline, not the camera.
        logLine("info", "Replay", {
          frames: frameBuffer.length,
          seconds: +(frameBuffer.length / replayFps).toFixed(1),
          actualFps: +replayFps.toFixed(1),
          targetFps: BUFFER_FPS
        });''', 'measure and log on entry')

sub(r'''      logLine("info", "Clip export started", {
        type: type,
        seconds: +(frameBuffer.length / BUFFER_FPS).toFixed(1)
      });''',
r'''      logLine("info", "Clip export started", {
        type: type,
        seconds: +(frameBuffer.length / replayFps).toFixed(1),
        actualFps: +replayFps.toFixed(1)
      });''', 'clip log uses measured fps')

sub(r'''    const BUILD = "2026-09-05-export";''',
r'''    const BUILD = "2026-09-05-fps30";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
