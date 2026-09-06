#!/usr/bin/env python3
"""Analyse a recorded swing across frames: plane, and how much early extension.

Run from the repository root:

    python3 tools/swing-analysis-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing.

A still cannot show a swing. Plane through the backswing and downswing, and
early extension -- which is by definition a change in hip depth between address
and impact -- are only visible over time. So the recorded clip is sampled and
the frames go up together, in order, as one request.

Which frames matters. Ten seconds of recording holds about two of swing, so an
even sample across the whole clip would mostly be the golfer standing still.
The frames are taken from a window centred on the strongest motion in the clip.
That is the same motion reading the deleted auto-capture used, put to the one
job it is fit for: choosing where to look inside a clip the golfer deliberately
recorded. Being wrong here costs one re-run, not a lost swing -- and the frame
it centred on is shown, so a bad choice is visible rather than silent.

The model is asked to report per-frame: which frame it saw each thing in, and a
frame-by-frame note of hip depth. An answer tied to a frame can be checked
against the clip. An answer that cannot name its evidence is the failure mode
this codebase already knows well -- it is what the tush line did before
tushDetected let it decline.

callGemini takes an array of images now. Existing single-image callers pass a
string still, and it accepts either, so the scan path is untouched.
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


# ---------- callGemini takes many images ----------
sub(r'''    async function callGemini(prompt, base64Data, timeoutMs, thinkingLevel) {
      const generationConfig''',
r'''    // Accepts one base64 image or several. Several go up in one request, in
    // order, which is the only way a model can speak about a movement rather
    // than a pose.
    async function callGemini(prompt, base64Data, timeoutMs, thinkingLevel) {
      const images = Array.isArray(base64Data) ? base64Data : (base64Data ? [base64Data] : []);
      const generationConfig''', 'callGemini images')

sub(r'''      const payload = {
        contents: [{
          role: "user",
          parts: [
            { text: prompt },
            { inline_data: { mime_type: "image/jpeg", data: base64Data } }
          ]
        }],
        generationConfig: generationConfig
      };''',
r'''      const payload = {
        contents: [{
          role: "user",
          parts: [{ text: prompt }].concat(
            images.map((b) => ({ inline_data: { mime_type: "image/jpeg", data: b } }))
          )
        }],
        generationConfig: generationConfig
      };''', 'payload parts')

sub(r'''        imageKB: Math.round((base64Data || "").length * 0.75 / 1024),''',
r'''        images: images.length,
        imageKB: Math.round(images.reduce((t, b) => t + b.length, 0) * 0.75 / 1024),''', 'log image count')

# ---------- modal labels become per-analysis ----------
sub(r'''                <i data-lucide="check-circle" class="w-3.5 h-3.5"></i> Setup and pelvic depth''',
r'''                <i data-lucide="check-circle" class="w-3.5 h-3.5"></i> <span id="ai-label-1">Setup and pelvic depth</span>''', 'label 1')

sub(r'''                <i data-lucide="alert-circle" class="w-3.5 h-3.5"></i> Shaft plane and corridor''',
r'''                <i data-lucide="alert-circle" class="w-3.5 h-3.5"></i> <span id="ai-label-2">Shaft plane and corridor</span>''', 'label 2')

sub(r'''                <i data-lucide="zap" class="w-3.5 h-3.5"></i> Rehearsal drill''',
r'''                <i data-lucide="zap" class="w-3.5 h-3.5"></i> <span id="ai-label-3">Rehearsal drill</span>''', 'label 3')

sub(r'''    const aiDrillText = $("ai-drill-text");''',
r'''    const aiDrillText = $("ai-drill-text");
    const aiLabel1 = $("ai-label-1");
    const aiLabel2 = $("ai-label-2");
    const aiLabel3 = $("ai-label-3");''', 'label refs')

# ---------- a transport button to run or re-run it ----------
sub(r'''      <button id="btn-save-clip" class="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 text-[11px] font-semibold active:scale-95 transition" title="Record one pass of this clip to a video file">
        <i data-lucide="download" class="w-3.5 h-3.5"></i> Save clip
      </button>''',
r'''      <button id="btn-save-clip" class="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 text-[11px] font-semibold active:scale-95 transition" title="Record one pass of this clip to a video file">
        <i data-lucide="download" class="w-3.5 h-3.5"></i> Save clip
      </button>
      <button id="btn-analyse-swing" class="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-emerald-600/50 text-emerald-300 text-[11px] font-semibold active:scale-95 transition" title="Analyse this swing with AI">
        <i data-lucide="sparkles" class="w-3.5 h-3.5"></i> Analyse
      </button>''', 'analyse button')

sub(r'''    const btnSaveClip = $("btn-save-clip");''',
r'''    const btnSaveClip = $("btn-save-clip");
    const btnAnalyseSwing = $("btn-analyse-swing");''', 'analyse ref')

# ---------- the analysis ----------
sub(r'''    // ---------- AI review ----------''',
r'''    // ---------- Swing analysis over frames ----------
    // Its own canvas: the frames are rescaled on the way out, and borrowing one
    // of the 64x64 scratch canvases would fight whatever else is using it.
    const swingFrameCanvas = document.createElement("canvas");
    const swingFrameCtx = swingFrameCanvas.getContext("2d");

    const SWING_ANALYSIS_FRAMES = 6;
    // Backswing, downswing and a little follow-through. Wider than this and the
    // sample spreads across seconds of the golfer standing still.
    const SWING_WINDOW_SEC = 3;
    // Small enough that six fit a request comfortably, large enough that a club
    // against a dark floor is still there to be seen.
    const SWING_FRAME_WIDTH = 512;

    function frameToJpeg(bitmap) {
      const scale = Math.min(1, SWING_FRAME_WIDTH / bitmap.width);
      swingFrameCanvas.width = Math.max(1, Math.round(bitmap.width * scale));
      swingFrameCanvas.height = Math.max(1, Math.round(bitmap.height * scale));
      swingFrameCtx.drawImage(bitmap, 0, 0, swingFrameCanvas.width, swingFrameCanvas.height);
      return swingFrameCanvas.toDataURL("image/jpeg", 0.75);
    }

    // Ten seconds of recording holds about two of swing. Sampling the whole clip
    // evenly would mostly capture the golfer standing still, so the window is
    // centred on the strongest motion -- the one job that reading is fit for,
    // now that it decides nothing about when to record.
    function pickSwingFrames(frames) {
      if (frames.length < 2) return [];
      let peak = 0, peakIdx = Math.floor(frames.length / 2);
      for (let i = 0; i < frames.length; i++) {
        const m = frames[i].motion || 0;
        if (m > peak) { peak = m; peakIdx = i; }
      }
      const fps = Math.max(1, measureBufferFps(frames));
      const half = Math.round((SWING_WINDOW_SEC / 2) * fps);
      let lo = Math.max(0, peakIdx - half);
      let hi = Math.min(frames.length - 1, peakIdx + half);
      if (hi - lo < SWING_ANALYSIS_FRAMES) { lo = 0; hi = frames.length - 1; }

      const picked = [];
      for (let k = 0; k < SWING_ANALYSIS_FRAMES; k++) {
        const idx = Math.round(lo + (hi - lo) * (k / (SWING_ANALYSIS_FRAMES - 1)));
        picked.push({ idx: idx, tSec: (idx - lo) / fps });
      }
      return { picked: picked, peakIdx: peakIdx, fps: fps, lo: lo, hi: hi };
    }

    async function analyseRecordedSwing() {
      const frames = replaySourceFrames();
      if (recordState !== "review" || frames.length < 4) {
        showToast("Record a swing first", 3000);
        return;
      }

      const sel = pickSwingFrames(frames);
      if (!sel.picked || !sel.picked.length) { showToast("Not enough frames", 3000); return; }

      const images = [];
      for (let i = 0; i < sel.picked.length; i++) {
        const f = frames[sel.picked[i].idx];
        if (f && f.bitmap) images.push(frameToJpeg(f.bitmap).split(",")[1] || "");
      }
      if (images.length < 3) { showToast("Could not read the frames", 3000); return; }

      // The frame it centred on, so a bad choice of window is visible rather
      // than silently analysed.
      const peakFrame = frames[sel.peakIdx];
      if (peakFrame && peakFrame.bitmap) aiCapturedImg.src = frameToJpeg(peakFrame.bitmap);

      aiModal.classList.remove("hidden");
      aiLoader.classList.remove("hidden");
      aiContentBody.classList.add("hidden");
      aiLabel1.textContent = "Early extension";
      aiLabel2.textContent = "Club on plane";
      aiLabel3.textContent = "Drill";
      btnReAnalyze.textContent = "Analyse again";

      const profile = STANCE_PROFILES[currentStanceIndex];
      const gap = (sel.picked.length > 1 ? (sel.picked[1].tSec - sel.picked[0].tSec) : 0);

      const prompt =
        "You are a PGA instructor. The " + images.length + " images are consecutive frames of ONE golf swing, " +
        "in chronological order, about " + gap.toFixed(2) + " seconds apart, filmed " + profile.label + ". " +
        "Frame 1 is the earliest. Treat them as a sequence, not as separate photos.\n" +
        "Judge two things:\n" +
        "1. SWING PLANE. Follow the shaft through the frames. Say whether the club stayed on, above or under " +
        "plane, and say it separately for the backswing and the downswing. Name the frame numbers you are " +
        "describing.\n" +
        "2. EARLY EXTENSION. This is the hips and pelvis moving TOWARD the ball and the torso standing up " +
        "between address and impact. Compare the hip line frame by frame against where it was in the first " +
        "frame. Report severity as none, mild, moderate or severe, and give hipDepthByFrame: one short note " +
        "per frame describing whether the hips have moved toward the ball versus frame 1.\n" +
        "If the club or the hips genuinely cannot be made out, set detected false and say which frames " +
        "failed rather than describing a swing you cannot see. A confident wrong answer is worse than " +
        "an admission.\n" +
        'Return only JSON: {"detected":true,"score":"short label with a percent",' +
        '"backswing":"...","downswing":"...","planeSummary":"one or two sentences naming frames",' +
        '"earlyExtension":{"severity":"none|mild|moderate|severe","summary":"naming frames",' +
        '"hipDepthByFrame":["f1: ...","f2: ..."]},"drill":"one actionable feel drill"}';

      logLine("info", "Swing analysis", {
        frames: images.length,
        peakFrame: sel.peakIdx,
        windowFrames: (sel.hi - sel.lo + 1),
        fps: +sel.fps.toFixed(1),
        kb: Math.round(images.reduce((t, b) => t + b.length, 0) * 0.75 / 1024)
      });

      const parsed = await callGemini(prompt, images, 90000, "medium");

      aiLoader.classList.add("hidden");
      if (!parsed) {
        aiScore.textContent = "Analysis unavailable" + (lastGeminiError ? " — " + lastGeminiError : "");
        aiSetupText.textContent = "No cloud analysis this time.";
        aiPlaneText.textContent = "Scrub the clip against the green plane line instead: the shaft should track it going back and coming down.";
        aiDrillText.textContent = "Keep the lead glute touching the tush line through impact.";
        aiContentBody.classList.remove("hidden");
        return;
      }

      const ee = parsed.earlyExtension || {};
      const byFrame = Array.isArray(ee.hipDepthByFrame) ? ee.hipDepthByFrame.join("  ·  ") : "";

      if (parsed.detected === false) {
        // Reported, not dressed up. The frames are in the log and on screen, so
        // a refusal is something the golfer can act on.
        aiScore.textContent = "Could not read the swing";
        aiSetupText.textContent = ee.summary || "The hips could not be made out in these frames.";
        aiPlaneText.textContent = parsed.planeSummary || "The club could not be followed through these frames.";
        aiDrillText.textContent = "Try again with the club and hips fully in frame, or a brighter background.";
        aiContentBody.classList.remove("hidden");
        logLine("warn", "Swing analysis declined", parsed.planeSummary || "");
        return;
      }

      aiScore.textContent = parsed.score || "Analysed";
      aiSetupText.textContent =
        (ee.severity ? "Severity: " + ee.severity + ". " : "") +
        (ee.summary || "") + (byFrame ? "\n" + byFrame : "");
      aiPlaneText.textContent =
        (parsed.planeSummary || "") +
        (parsed.backswing ? "\nBackswing: " + parsed.backswing : "") +
        (parsed.downswing ? "\nDownswing: " + parsed.downswing : "");
      aiDrillText.textContent = parsed.drill || "";
      aiContentBody.classList.remove("hidden");
      if (window.lucide) lucide.createIcons();
      logLine("ok", "Swing analysed", { severity: ee.severity || "?", score: parsed.score || "" });
    }

    // ---------- AI review ----------''', 'swing analysis')

# ---------- the setup review restores its own labels ----------
sub(r'''      aiModal.classList.remove("hidden");
      aiLoader.classList.remove("hidden");
      aiContentBody.classList.add("hidden");

      const prompt = "You are a PGA instructor analyzing a golf swing frame. " +''',
r'''      aiModal.classList.remove("hidden");
      aiLoader.classList.remove("hidden");
      aiContentBody.classList.add("hidden");
      // The two analyses share one modal, so each restates its own headings.
      aiLabel1.textContent = "Setup and pelvic depth";
      aiLabel2.textContent = "Shaft plane and corridor";
      aiLabel3.textContent = "Rehearsal drill";
      btnReAnalyze.textContent = "Take new snapshot";

      const prompt = "You are a PGA instructor analyzing a golf swing frame. " +''', 'setup review labels')

# ---------- wiring ----------
sub(r'''    btnSaveFrame.addEventListener("click", saveFrame);''',
r'''    btnAnalyseSwing.addEventListener("click", analyseRecordedSwing);
    btnSaveFrame.addEventListener("click", saveFrame);''', 'analyse wiring')

sub(r'''      if (aiSwingAnalysis) showToast("Swing analysis is not built yet", 3000);''',
r'''      // Only when asked for: an analysis the golfer did not want must never be
      // what stands between them and their clip.
      if (aiSwingAnalysis) analyseRecordedSwing();''', 'auto-run on finish')

sub(r'''    const BUILD = "2026-09-06-record";''',
r'''    const BUILD = "2026-09-06-swingai";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
