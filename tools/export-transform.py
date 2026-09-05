#!/usr/bin/env python3
"""Let the golfer keep a replay: save the frame, or save the clip.

Run from the repository root:

    python3 tools/export-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

Both exports read the main canvas, which already has the video frame and the
guides composited on it. That is the whole trick: no second draw path to keep
in sync, and what lands in the file is exactly what was on screen.

1. Save frame -> PNG, via canvas.toBlob. Works everywhere, needs no codec, and
   for comparing today's impact position against last week's it is often more
   use than video.

2. Save clip -> captureStream + MediaRecorder, recording one pass of the loop
   in real time. Real time is the cost of reusing the on-screen render rather
   than maintaining a second offscreen one; ten seconds is a tolerable wait for
   a path that cannot drift from what the golfer actually saw.

   Guarded, because this is the part that can genuinely be missing: no
   MediaRecorder, no captureStream, or no supported container and the button
   says so and does nothing. iOS Safari is the expected casualty; PNG still
   works there.

3. The delay slider stops at 8s while the buffer now holds 10. Harmless, but it
   left two seconds unreachable for no reason.

Downloads land in the browser's download folder, not the camera roll.
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


# 1. the slider can reach the whole buffer now
sub(r'''      <input id="delay-slider" type="range" min="1" max="8" step="0.5" value="3"''',
r'''      <input id="delay-slider" type="range" min="1" max="10" step="0.5" value="3"''', 'delay slider range')

# 2. the transport becomes two rows: driving on top, keeping underneath. Eight
#    controls on one row is unusable on a phone.
sub(r'''    <div id="replay-bar" class="hidden max-w-xl mx-auto mt-2 flex items-center gap-1.5">
      <button id="btn-replay-play"''',
r'''    <div id="replay-bar" class="hidden max-w-xl mx-auto mt-2 flex flex-col gap-1.5">
     <div class="flex items-center gap-1.5">
      <button id="btn-replay-play"''', 'transport row open')

sub(r'''      <button id="btn-replay-speed" class="shrink-0 px-2 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sky-300 text-[11px] font-bold active:scale-95 transition" title="Playback speed">1x</button>
    </div>
  </footer>''',
r'''      <button id="btn-replay-speed" class="shrink-0 px-2 py-2 rounded-lg bg-slate-800 border border-slate-700 text-sky-300 text-[11px] font-bold active:scale-95 transition" title="Playback speed">1x</button>
     </div>

     <div class="flex items-center gap-1.5">
      <button id="btn-save-frame" class="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 text-[11px] font-semibold active:scale-95 transition" title="Save this frame as a PNG">
        <i data-lucide="image-down" class="w-3.5 h-3.5"></i> Save frame
      </button>
      <button id="btn-save-clip" class="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 text-[11px] font-semibold active:scale-95 transition" title="Record one pass of this clip to a video file">
        <i data-lucide="download" class="w-3.5 h-3.5"></i> Save clip
      </button>
      <span id="export-status" class="text-[10px] text-slate-400 truncate"></span>
     </div>
    </div>
  </footer>''', 'export row')

# 3. refs
sub(r'''    const btnReplaySpeed = $("btn-replay-speed");''',
r'''    const btnReplaySpeed = $("btn-replay-speed");
    const btnSaveFrame = $("btn-save-frame");
    const btnSaveClip = $("btn-save-clip");
    const exportStatus = $("export-status");''', 'export refs')

# 4. export state
sub(r'''    const REPLAY_SPEEDS = [1, 0.5, 0.25];''',
r'''    const REPLAY_SPEEDS = [1, 0.5, 0.25];

    // Clip export records the canvas as it plays, so it holds the transport for
    // one pass. Tracked here so the transport can refuse input while it runs.
    let clipRecorder = null;
    let clipChunks = [];
    let exportingClip = false;''', 'export state')

# 5. one pass of the loop ends the recording
sub(r'''        // Loop. The point of replay is watching the same two seconds again.
        if (replayIndex >= frameBuffer.length) replayIndex = 0;
        syncReplayUi();''',
r'''        // Loop. The point of replay is watching the same two seconds again --
        // except while exporting, where one pass is the whole file.
        if (replayIndex >= frameBuffer.length) {
          replayIndex = 0;
          if (exportingClip) stopClipExport();
        }
        syncReplayUi();
        if (exportingClip) {
          exportStatus.textContent = "Recording " +
            (replayFrameIndex() / BUFFER_FPS).toFixed(1) + "s...";
        }''', 'export stop on wrap')

# 6. the export machinery, beside the replay helpers it drives
sub(r'''    function clearFrameBuffer() {''',
r'''    // Both exports read the main canvas, which already has the frame and the
    // guides composited. No second draw path means the file cannot disagree
    // with what the golfer was looking at when they tapped save.
    function stamp() {
      const d = new Date();
      const p = (v) => String(v).padStart(2, "0");
      return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "-" +
        p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
    }

    function downloadBlob(blob, filename) {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // Revoking immediately can cancel the download on some mobile browsers.
      setTimeout(() => { try { URL.revokeObjectURL(url); } catch (e) {} }, 15000);
    }

    function saveFrame() {
      if (!canvas.toBlob) { showToast("This browser cannot save images", 4000); return; }
      canvas.toBlob((blob) => {
        if (!blob) { showToast("Could not save the frame", 4000); logLine("error", "Frame export produced no blob"); return; }
        const name = "golf-" + stamp() + ".png";
        downloadBlob(blob, name);
        exportStatus.textContent = "Saved " + name;
        logLine("ok", "Frame saved", { name: name, kb: Math.round(blob.size / 1024) });
      }, "image/png");
    }

    // Ordered best-first. An empty result means this browser cannot record,
    // which is a real outcome on iOS rather than an error to work around.
    const CLIP_TYPES = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"];

    function pickClipType() {
      if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return null;
      for (let i = 0; i < CLIP_TYPES.length; i++) {
        if (MediaRecorder.isTypeSupported(CLIP_TYPES[i])) return CLIP_TYPES[i];
      }
      return null;
    }

    function startClipExport() {
      if (exportingClip) return;
      if (!frameBuffer.length) { showToast("Nothing to save", 3000); return; }
      if (!canvas.captureStream) {
        showToast("This browser cannot record video - use Save frame", 5000);
        logLine("warn", "Clip export unavailable: no captureStream");
        return;
      }
      const type = pickClipType();
      if (!type) {
        showToast("This browser cannot record video - use Save frame", 5000);
        logLine("warn", "Clip export unavailable: no supported container");
        return;
      }
      let stream;
      try {
        stream = canvas.captureStream(30);
        clipRecorder = new MediaRecorder(stream, { mimeType: type });
      } catch (err) {
        showToast("Could not start recording", 4000);
        logLine("error", "Clip export failed to start: " + err);
        return;
      }
      clipChunks = [];
      clipRecorder.ondataavailable = (e) => { if (e.data && e.data.size) clipChunks.push(e.data); };
      clipRecorder.onstop = () => {
        const blob = new Blob(clipChunks, { type: type });
        clipChunks = [];
        const name = "golf-" + stamp() + (type.indexOf("mp4") >= 0 ? ".mp4" : ".webm");
        if (!blob.size) {
          exportStatus.textContent = "Recording produced nothing";
          logLine("error", "Clip export produced an empty blob");
        } else {
          downloadBlob(blob, name);
          exportStatus.textContent = "Saved " + name;
          logLine("ok", "Clip saved", { name: name, kb: Math.round(blob.size / 1024), type: type });
        }
        setClipExportUi(false);
      };

      exportingClip = true;
      setClipExportUi(true);
      replayIndex = 0;
      replaySpeed = 1;
      btnReplaySpeed.textContent = "1x";
      setReplayPlaying(true);
      clipRecorder.start();
      logLine("info", "Clip export started", {
        type: type,
        seconds: +(frameBuffer.length / BUFFER_FPS).toFixed(1)
      });
    }

    function stopClipExport() {
      exportingClip = false;
      setReplayPlaying(false);
      if (clipRecorder && clipRecorder.state !== "inactive") {
        try { clipRecorder.stop(); } catch (e) { setClipExportUi(false); }
      } else {
        setClipExportUi(false);
      }
      clipRecorder = null;
    }

    // The transport drives the recording, so letting it be touched mid-pass
    // would put whatever the golfer did into the file.
    function setClipExportUi(busy) {
      [btnReplayPlay, btnReplayPrev, btnReplayNext, btnReplaySpeed, replayScrub, btnSaveFrame, btnSaveClip]
        .forEach((el) => {
          el.disabled = busy;
          el.classList.toggle("opacity-40", busy);
          el.classList.toggle("pointer-events-none", busy);
        });
      if (busy) exportStatus.textContent = "Recording...";
    }

    function clearFrameBuffer() {''', 'export machinery')

# 7. wiring
sub(r'''    btnReplaySpeed.addEventListener("click", () => {''',
r'''    btnSaveFrame.addEventListener("click", saveFrame);
    btnSaveClip.addEventListener("click", startClipExport);

    btnReplaySpeed.addEventListener("click", () => {''', 'export wiring')

# 8. leaving replay mid-record must not leave a recorder running on a canvas
#    that has gone back to showing live video
sub(r'''      if (mode === "replay" && !frameBuffer.length) {
        showToast("Nothing recorded yet - give it a few seconds", 3000);
        return;
      }
      appMode = mode;''',
r'''      if (mode === "replay" && !frameBuffer.length) {
        showToast("Nothing recorded yet - give it a few seconds", 3000);
        return;
      }
      // Walking out mid-record would otherwise keep capturing the live feed
      // into a file the golfer asked to be of their replay.
      if (exportingClip && mode !== "replay") stopClipExport();
      appMode = mode;''', 'stop export on mode change')

sub(r'''      if (mode === "replay") {
        replayIndex = 0;
        replaySpeed = 1;''',
r'''      if (mode === "replay") {
        exportStatus.textContent = "";
        replayIndex = 0;
        replaySpeed = 1;''', 'clear status on entry')

sub(r'''    const BUILD = "2026-09-05-replay";''',
r'''    const BUILD = "2026-09-05-export";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
