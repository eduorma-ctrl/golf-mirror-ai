#!/usr/bin/env python3
"""Save clips and stills in true orientation, not mirrored.

Run from the repository root:

    python3 tools/export-orientation-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

A mirror is the right thing to practise against and the wrong thing to keep.
The exported clip was faithful to the screen -- verified by comparing a frame
against the snapshot from the same session -- and the screen was mirrored, so
the file was too.

The fix is not simply dropping the mirror on the way out. Guides are drawn in
screen space after ctx.restore() (invariant 2), so un-mirroring the video alone
leaves the tush line on the wrong side of the golfer: correctly oriented and
useless. Both have to move together.

So one flag, read in exactly two places:

- the video draw skips the mirror transform
- vidToPxX mirrors the guide coordinate, which is the single point every guide
  and every hit test already goes through

The guides are not mutated. An export that dies half way -- and there are three
ways for it to, the watchdog included -- would otherwise leave every guide
flipped on the golfer's screen. The flag is set only after MediaRecorder.start()
returns, so the failure path never has to unset it, and stopClipExport() is the
one place that clears it.

Text draws the right way round because nothing is flipped by canvas transform;
the coordinates are simply computed on the other side.

Scanning is refused during an export. Gemini's coordinates come back in the
screen space the guides live in, and for the length of an export that space is
not what the snapshot would show.
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


# 1. the flag, and the mapping that carries it
sub(r'''    function vidToPxX(vx) {
      return videoRect.w > 0 ? videoRect.x + vx * videoRect.w : vx * (canvas.clientWidth || 1);
    }''',
r'''    // A mirror is right for practising and wrong for a file you keep, so exports
    // drop it. Guides live in screen space (invariant 2), so dropping it for the
    // video alone would leave the tush line on the wrong side of the golfer --
    // both have to move together, and this mapping is where the guides move.
    // Read in exactly two places: here, and the video draw.
    let unmirrorForExport = false;
    function mirrorActive() { return isMirrored && !unmirrorForExport; }
    function exportFlipX() { return unmirrorForExport && isMirrored; }

    function vidToPxX(vx) {
      const x = exportFlipX() ? 1 - vx : vx;
      return videoRect.w > 0 ? videoRect.x + x * videoRect.w : x * (canvas.clientWidth || 1);
    }''', 'flag + vidToPxX')

sub(r'''    function pxToVidX(px) {
      return videoRect.w > 0 ? (px - videoRect.x) / videoRect.w : px / (canvas.clientWidth || 1);
    }''',
r'''    function pxToVidX(px) {
      const v = videoRect.w > 0 ? (px - videoRect.x) / videoRect.w : px / (canvas.clientWidth || 1);
      return exportFlipX() ? 1 - v : v;
    }''', 'pxToVidX symmetry')

# 2. the video draw is the other reader
sub(r'''      if (isMirrored) { ctx.translate(w, 0); ctx.scale(-1, 1); }''',
r'''      if (mirrorActive()) { ctx.translate(w, 0); ctx.scale(-1, 1); }''', 'video draw honours flag')

# 3. set it only once start() has actually succeeded, so the failure path has
#    nothing to undo
sub(r'''        logLine("error", "Clip export failed at start(): " + err);
        return;
      }''',
r'''        logLine("error", "Clip export failed at start(): " + err);
        return;
      }
      // After start(), never before: the failure path above must not be able to
      // leave the guides flipped on the golfer's screen.
      unmirrorForExport = isMirrored;''', 'set flag after start')

sub(r'''    function stopClipExport() {
      exportingClip = false;''',
r'''    function stopClipExport() {
      exportingClip = false;
      // The single place this is cleared. Every way an export can end -- the
      // loop wrapping, the watchdog, backgrounding, leaving replay -- comes
      // through here.
      unmirrorForExport = false;''', 'clear flag on stop')

# 4. the still gets the same treatment, so one rule covers both saved artifacts.
#    toBlob reads the canvas at call time, so the flag has to survive a repaint
#    before the read rather than merely being set.
sub(r'''    function saveFrame() {
      if (!canvas.toBlob) { showToast("This browser cannot save images", 4000); return; }
      canvas.toBlob((blob) => {''',
r'''    function saveFrame() {
      if (!canvas.toBlob) { showToast("This browser cannot save images", 4000); return; }
      if (isMirrored && !unmirrorForExport) {
        // Same rule as the clip: what you keep is not mirrored. toBlob reads the
        // canvas as it stands, so the flag has to outlive a repaint before the
        // read -- two frames, because the first only schedules the draw.
        unmirrorForExport = true;
        requestAnimationFrame(() => requestAnimationFrame(() => {
          try { saveFrameNow(); } finally { unmirrorForExport = false; }
        }));
        return;
      }
      saveFrameNow();
    }

    function saveFrameNow() {
      canvas.toBlob((blob) => {''', 'still uses true orientation')

# 5. a scan during an export would be read against a screen space that is not
#    the one the guides are in
sub(r'''    btnInstantScan.addEventListener("click", () => {
      unlockMobileAudio();
      if (isCountingDown) cancelHandsFreeTimer();
      executeMultiFrameBurstScan();
    });''',
r'''    btnInstantScan.addEventListener("click", () => {
      unlockMobileAudio();
      // Gemini's points come back in the screen space the guides live in, and
      // for the length of an export that space is mirrored away from what the
      // snapshot would show.
      if (exportingClip) { showToast("Finish saving the clip first", 3000); return; }
      if (isCountingDown) cancelHandsFreeTimer();
      executeMultiFrameBurstScan();
    });''', 'refuse scan during export')

sub(r'''    const BUILD = "2026-09-05-autoswing";''',
r'''    const BUILD = "2026-09-05-trueorient";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
