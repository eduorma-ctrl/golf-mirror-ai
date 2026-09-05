#!/usr/bin/env python3
"""Turn the Face-On stance profile into a real mode.

Run from the repository root:

    python3 tools/faceon-transform.py

It rewrites index.html in place. Every anchor must appear EXACTLY once; if any
does not, the script prints which one and exits non-zero without writing. That
is deliberate -- a silent partial edit to this file is how coordinate bugs get
introduced. Running it twice fails loudly on the first anchor, which is correct.

After running, verify before pushing:

    python3 - <<'EOF'
    import re, io
    s = io.open('index.html', encoding='utf-8').read()
    io.open('app.js', 'w', encoding='utf-8').write(
        max(re.findall(r'<script(?![^>]*\\bsrc=)[^>]*>(.*?)</script>', s, re.S), key=len))
    EOF
    node --check app.js && rm app.js

What this changes, and why:

1. isFaceOn flag. Face-on and down-the-line disagree about what the purple
   vertical line means, whether the Hogan corridor means anything, and what a
   shaft angle is telling you. One flag, kept in sync by applyStanceCoordinates.

2. Face-on presets. The green line is still the shaft, but seen from the front
   it reads as shaft lean rather than swing plane. The purple line becomes a
   sway reference at the trail hip.

3. A dedicated face-on prompt. It asks for the OUTER EDGE OF THE TRAIL HIP --
   the hip that must not slide away from the target -- instead of the glute
   edge, which has no face-on meaning. The wire format is deliberately shared
   (tushLineX/tushLineY/tushDetected carry whichever vertical reference the
   current view uses) so everything downstream stays one code path.

4. Its own geometric fallback. This branch did not exist, so with no API key
   Face-On received the Righty DTL numbers and put the sway line on the wrong
   side of the golfer entirely.

5. The corridor is off face-on in all three places that can switch it on: the
   preset, a successful scan, and the toggle button.

Handedness note: face-on cannot be inferred from the profile, which carries no
handedness. The model is asked to identify the trail side from the image. The
no-key fallback assumes a right-hander facing the camera, whose trail side
falls on the camera's left -- a starting guess the golfer drags or a scan
replaces.
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


# 1. one flag the whole file can branch on
sub(r'''    let currentStanceIndex = 0;''',
r'''    let currentStanceIndex = 0;

    // Face-on and down-the-line disagree about what the purple vertical line means
    // (glute edge vs trail hip), about whether the Hogan corridor means anything at
    // all, and about what a shaft angle is telling you. Rather than test the profile
    // id in six places, applyStanceCoordinates() keeps this in sync.
    let isFaceOn = false;''', 'isFaceOn flag')

# 2. presets, corridor state and labels all follow from the profile
sub(r'''    function applyStanceCoordinates(profile) {
      if (profile.id === "righty_dtl") {
        guides.planeLine.start = { x: 0.35, y: 0.84 };
        guides.planeLine.end = { x: 0.68, y: 0.22 };
        guides.headBox.x = 0.50; guides.hipLine.x = 0.62;
      } else if (profile.id === "lefty_dtl") {
        guides.planeLine.start = { x: 0.65, y: 0.84 };
        guides.planeLine.end = { x: 0.32, y: 0.22 };
        guides.headBox.x = 0.50; guides.hipLine.x = 0.38;
      } else {
        guides.planeLine.start = { x: 0.48, y: 0.84 };
        guides.planeLine.end = { x: 0.48, y: 0.22 };
        guides.headBox.x = 0.50; guides.hipLine.x = 0.58;
      }
      tushValDisplay.textContent = Math.round(guides.hipLine.x * 100) + "%";
      updatePlaneAngleBadge();
    }''',
r'''    function applyStanceCoordinates(profile) {
      isFaceOn = profile.id === "face_on";
      if (profile.id === "righty_dtl") {
        guides.planeLine.start = { x: 0.35, y: 0.84 };
        guides.planeLine.end = { x: 0.68, y: 0.22 };
        guides.headBox.x = 0.50; guides.hipLine.x = 0.62;
      } else if (profile.id === "lefty_dtl") {
        guides.planeLine.start = { x: 0.65, y: 0.84 };
        guides.planeLine.end = { x: 0.32, y: 0.22 };
        guides.headBox.x = 0.50; guides.hipLine.x = 0.38;
      } else {
        // Face-on. The green line is still the shaft, but seen from the front it
        // reads as shaft lean rather than swing plane, so it starts steep with a
        // slight tilt toward the target. The purple line becomes a sway reference
        // at the trail hip: 0.40 assumes a right-hander facing the camera, whose
        // trail side falls on the camera's left. Both are only starting positions
        // that a scan or a drag replaces.
        guides.planeLine.start = { x: 0.48, y: 0.86 };
        guides.planeLine.end = { x: 0.55, y: 0.26 };
        guides.headBox.x = 0.50; guides.hipLine.x = 0.40;
      }

      // The Hogan corridor brackets the hands against the shaft plane seen edge-on.
      // Face-on there is nothing for it to bracket, so it is switched off rather
      // than drawn as decoration the golfer might read as meaningful.
      guides.corridor.enabled = !isFaceOn;
      btnGuideCorridor.classList.toggle("opacity-40", !guides.corridor.enabled);
      btnGuideCorridor.title = isFaceOn
        ? "Hogan corridor - down-the-line only"
        : "Hogan Shoulder/Elbow Corridor";
      btnGuideHip.title = isFaceOn ? "Sway line (trail hip)" : "Tush Line (Early Extension)";
      tushLabelText.textContent = isFaceOn ? "Sway line" : "Tush line";

      tushValDisplay.textContent = Math.round(guides.hipLine.x * 100) + "%";
      updatePlaneAngleBadge();
    }''', 'applyStanceCoordinates')

# 3. the widget caption needs a handle before it can change
sub(r'''          <span>Tush line</span>''',
r'''          <span id="tush-label-text">Tush line</span>''', 'tush label id')

sub(r'''    const tushAdjustWidget = $("tush-adjust-widget");''',
r'''    const tushAdjustWidget = $("tush-adjust-widget");
    const tushLabelText = $("tush-label-text");''', 'tush label ref')

# 4. the on-canvas caption
sub(r'''        const label = "Tush line";''',
r'''        const label = isFaceOn ? "Sway line" : "Tush line";''', 'canvas label')

# 5. two prompts. The DTL text is untouched: it works, and the point of this change
#    is to stop face-on borrowing it.
sub(r'''      const prompt = "You are a golf computer vision system analyzing an address posture frame (" + profile.label + ").\n" +''',
r'''      // The two views ask the model for genuinely different things. The wire format
      // is deliberately shared -- tushLineX/tushLineY/tushDetected carry whichever
      // vertical reference the current view uses -- so everything downstream stays a
      // single code path and only the meaning changes with the view.
      const dtlPrompt = "You are a golf computer vision system analyzing an address posture frame (" + profile.label + ").\n" +''', 'prompt head')

sub(r'''        '"shaftAngleDegrees":49.2,"confidence":98}';''',
r'''        '"shaftAngleDegrees":49.2,"confidence":98}';

      const faceOnPrompt = "You are a golf computer vision system analyzing a FACE-ON address posture " +
        "frame. The golfer is facing the camera, so their trail side (the right side of the body for a " +
        "right-handed player) appears on one side of the image and their target side on the other.\n" +
        "Return 2D point coordinates on Gemini's native 0-1000 scale (top-left origin, per your spatial " +
        "understanding conventions -- NOT 0.0-1.0) for this player's actual setup:\n" +
        "1. clubHead: the clubhead where it meets the ground\n" +
        "2. gripHands: center of the hands on the grip\n" +
        "3. headCenter: center of the head\n" +
        "4. tushLineX and tushLineY: the OUTER edge of the golfer's TRAIL HIP -- the hip further " +
        "from the target, the one that must not slide away from the target during the backswing. " +
        "This point must lie on the golfer's own body outline. Ignore furniture, bags, beds, walls, " +
        "doors and every other background object; a dark shape behind the golfer is not the golfer. " +
        "Give tushLineY as the height of that point, which sits at hip height: below the hands and " +
        "well below the head.\n" +
        "5. shaftAngleDegrees: the shaft's angle to horizontal as it appears in this frame. Seen " +
        "face-on this reads as shaft lean and is usually steep, often 60 to 85 degrees. Measure it; " +
        "do not snap to 45/50/55.\n" +
        "The club shaft is often thin, dark and low-contrast against a dark floor or mat. " +
        "Trace the straight line running from the hands down to the ground and follow it to its " +
        "lowest end; do not fall back on a generic address position. If the shaft genuinely " +
        "cannot be located, set detected to false rather than inventing coordinates.\n" +
        "Set tushDetected false whenever the hips are out of frame, obscured, or you cannot place " +
        "that edge to within roughly 3% of the frame width. A sway line in the wrong place is worse " +
        "than no sway line at all, so do not guess this one.\n" +
        'Return only JSON: {"detected":true,"clubHead":{"x":480,"y":860},"gripHands":{"x":545,"y":620},' +
        '"headCenter":{"x":500,"y":250},"tushDetected":true,"tushLineX":400,"tushLineY":620,' +
        '"shaftAngleDegrees":74.5,"confidence":98}';

      const prompt = isFaceOn ? faceOnPrompt : dtlPrompt;''', 'face-on prompt')

# 6. the fallback stops inheriting Righty values
sub(r'''      } else {
        // Documented no-key mode: geometric guides, same video-frame space.
        chVx = isLefty ? 0.65 : 0.35; chVy = 0.84;
        ghVx = isLefty ? 0.52 : 0.48; ghVy = 0.58;
        hdVx = 0.50;                  hdVy = 0.28;
        tuVx = isLefty ? 0.38 : 0.62;
      }''',
r'''      } else if (isFaceOn) {
        // Documented no-key mode, face-on. Right-hander facing the camera: the shaft
        // leans toward the target and the trail hip sits on the camera's left. This
        // branch used to be absent, so Face-On silently received the Righty DTL
        // numbers and put the sway line on the wrong side of the golfer entirely.
        chVx = 0.48; chVy = 0.86;
        ghVx = 0.55; ghVy = 0.62;
        hdVx = 0.50; hdVy = 0.26;
        tuVx = 0.40;
      } else {
        // Documented no-key mode: geometric guides, same video-frame space.
        chVx = isLefty ? 0.65 : 0.35; chVy = 0.84;
        ghVx = isLefty ? 0.52 : 0.48; ghVy = 0.58;
        hdVx = 0.50;                  hdVy = 0.28;
        tuVx = isLefty ? 0.38 : 0.62;
      }''', 'fallback')

# 7. a successful scan must not switch the corridor back on face-on
sub(r'''      guides.corridor.enabled = true;''',
r'''      guides.corridor.enabled = !isFaceOn;''', 'scan corridor')

# 8. and neither must the toggle
sub(r'''    btnGuideCorridor.addEventListener("click", () => {
      guides.corridor.enabled = !guides.corridor.enabled;
      btnGuideCorridor.classList.toggle("opacity-40", !guides.corridor.enabled);
    });''',
r'''    btnGuideCorridor.addEventListener("click", () => {
      if (isFaceOn) {
        showToast("The Hogan corridor is a down-the-line guide", 2500);
        return;
      }
      guides.corridor.enabled = !guides.corridor.enabled;
      btnGuideCorridor.classList.toggle("opacity-40", !guides.corridor.enabled);
    });''', 'corridor toggle guard')

# 9. status text follows the view too
sub(r'''        accuracyScoreText.textContent = "Confidence " + confidence + "%" + (tushKept ? " - tush kept" : "");
        if (tushKept) logLine("warn", "Tush line not detected - kept the existing line at " + Math.round(tushX * 100) + "%");''',
r'''        const vLabel = isFaceOn ? "sway" : "tush";
        accuracyScoreText.textContent = "Confidence " + confidence + "%" + (tushKept ? " - " + vLabel + " kept" : "");
        if (tushKept) logLine("warn", "Vertical reference (" + vLabel + ") not detected - kept the existing line at " + Math.round(tushX * 100) + "%");''', 'status label')

sub(r'''    const BUILD = "2026-09-05-videospace";''',
r'''    const BUILD = "2026-09-05-faceon";''', 'build bump')

io.open(SRC, 'w', encoding='utf-8').write(src)
print('applied %d edits -> %d bytes' % (n, len(src)))
