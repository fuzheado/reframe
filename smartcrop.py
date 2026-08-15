#!/usr/bin/env python3
"""
Face-aware smart crop.

Given a portrait (or any) photo and a target window aspect ratio (landscape,
square, portrait, etc.), crop so the face stays visible and well-composed --
instead of the naive center-crop that lands on the torso/chest.

Detector: OpenCV YuNet (face_detection_yunet_2023mar.onnx, ~230 KB).
           Falls back to Haar cascade (ships with OpenCV, zero download) if the
           ONNX model is missing.

Usage:
    python smartcrop.py INPUT.jpg --aspect 16:9     # or 1:1, 4:3, 9:16 ...
    python smartcrop.py INPUT.jpg --size 640x360
    python smartcrop.py INPUT.jpg --aspect 1:1 --out out.jpg --draw
"""

import argparse
import os
import sys
import threading

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
YUNET = os.path.join(HERE, "models", "face_detection_yunet_2023mar.onnx")

# --------------------------------------------------------------------------- #
# Detector (cached -- model load is the expensive part, ~20-50 ms)
# --------------------------------------------------------------------------- #
_DET_CACHE = {}
_DET_LOCK = threading.Lock()      # guards detector creation
_DETECT_LOCK = threading.Lock()  # guards detector USE — YuNet detect() is not
                                 # thread-safe (concurrent calls return garbage;
                                 # observed live with Flask's threaded dev server)


def parse_aspect(s):
    if ":" in s:
        w, h = s.split(":")
        return float(w) / float(h)
    return float(s)


def get_detector(img_w, img_h, score_thresh=0.6, top_k=100):
    """Return a cached YuNet detector for the given input size, or None."""
    if not os.path.exists(YUNET):
        return None
    key = (img_w, img_h, score_thresh)
    with _DET_LOCK:
        det = _DET_CACHE.get(key)
        if det is None:
            det = cv2.FaceDetectorYN.create(
                YUNET, "", (img_w, img_h), score_thresh, 0.3, top_k
            )
            _DET_CACHE[key] = det
        return det


def detect_face(img, score_thresh=0.6):
    """Return (x, y, w, h) of the primary face, or None. Tries YuNet then Haar."""
    ih, iw = img.shape[:2]
    box = None

    # --- YuNet (primary, accurate) ---
    det = get_detector(iw, ih, score_thresh)
    if det is not None:
        try:
            with _DETECT_LOCK:
                _, faces = det.detect(img)
            if faces is not None and len(faces) > 0:
                best = max(faces, key=lambda f: f[2] * f[3])
                box = tuple(int(v) for v in best[:4])
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"YuNet failed ({e}); falling back to Haar\n")
            box = None

    # --- Haar cascade (fallback, zero-download) ---
    # OpenCV 5.x removed cv2.CascadeClassifier and the shipped XMLs, so guard
    # against both the attribute and the files being absent (degrade to None).
    if box is None:
        try:
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            if not cascade.empty():
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
                if len(faces) > 0:
                    x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                    box = (int(x), int(y), int(fw), int(fh))
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"Haar fallback unavailable ({e}); continuing without it\n")

    return box


# --------------------------------------------------------------------------- #
# Crop geometry (the "smart" part -- ~80% of the result, 20% the detector)
# --------------------------------------------------------------------------- #
def center_crop(iw, ih, aspect):
    """Standard centered crop of the target aspect ratio."""
    if iw / ih > aspect:  # too wide -> crop width
        w = int(ih * aspect)
        h = ih
        x = (iw - w) // 2
        y = 0
    else:  # too tall -> crop height
        h = int(iw / aspect)
        w = iw
        y = (ih - h) // 2
        x = 0
    return (x, y, w, h)


# Eyes sit ~30% of the face-box height below its top (YuNet boxes span roughly
# forehead -> chin). Used to place the eye line in the crop. A fixed detector
# means this is a calibratable constant, not a per-image guess.
EYE_RATIO = 0.30

def smart_crop(img, aspect, box, tightness=0.55, eyeline=0.39):
    """Compute a crop rectangle of the given aspect that keeps the face visible.

    tightness: fraction of the crop height filled by the head region.
    0.55 (default) = head + some context; 1.0 = face-filling headshot;
    lower values (e.g. 0.35) = looser, more of the subject/scene visible.
    Only applies when a face box is given; center fallback is unaffected.

    eyeline: fraction of the crop height (from the top) where the eye line
    sits. 0.30 = classic portrait placement (eyes a third of the way down);
    lower = face higher in the frame, higher = more headroom. Default 0.39
    reproduces the pre-eyeline headroom constant (0.13) at tightness 0.55.
    The eye line is estimated at EYE_RATIO of the face-box height; tightness
    zooms AROUND the eye line, so zooming no longer shifts the eyes in the
    frame (previously: eye_frac = 0.13 + 0.47*tightness, so tight crops
    pushed the eyes toward the bottom).
    """
    ih, iw = img.shape[:2]

    if box is None:
        return center_crop(iw, ih, aspect)

    fx, fy, fw, fh = box

    # Expand the face box into a "head region": hair above, neck/shoulders below,
    # a little side margin. Multipliers are relative to face size.
    top = fy - 0.45 * fh
    bottom = fy + 1.15 * fh
    head_h = bottom - top
    face_cx = fx + fw / 2.0

    # Target crop size: head occupies `tightness` of crop height (leaves
    # body/context for the rest).
    Hc = head_h / max(tightness, 0.05)
    Wc = Hc * aspect

    # Fit within the image.
    if Wc > iw:
        Wc = float(iw)
        Hc = Wc / aspect
    if Hc > ih:
        Hc = float(ih)
        Wc = Hc * aspect
        if Wc > iw:
            Wc = float(iw)
            Hc = Wc / aspect

    # Horizontal: center on the face.
    cx = min(max(face_cx, Wc / 2.0), iw - Wc / 2.0)

    # Vertical: place the estimated eye line at `eyeline` of the crop height.
    eye_y = fy + EYE_RATIO * fh
    top_of_crop = min(max(eye_y - eyeline * Hc, 0.0), ih - Hc)

    x = int(cx - Wc / 2.0)
    y = int(top_of_crop)
    w = int(Wc)
    h = int(Hc)

    x = max(0, min(x, iw - w))
    y = max(0, min(y, ih - h))
    return (x, y, w, h)


def object_position(rect, iw, ih):
    """Convert a crop rect (x, y, w, h) into CSS object-position percentages.

    With `object-fit: cover` on a box of the same aspect ratio, setting
    `object-position: p% q%` shows exactly the crop rect: the point p% across
    the source image aligns with the point p% across the box, so the visible
    window's left edge sits at (iw - w) * p/100 source pixels. Because both the
    numerator and denominator scale with image size, the percentages are
    size-invariant — they work for any thumbnail of the same image.

    Returns (x_pct, y_pct) floats in [0, 100]. Dimensions that aren't cropped
    (rect == full image) get 50% (the position is irrelevant there).
    """
    x, y, w, h = rect
    if w >= iw:
        x_pct = 50.0
    else:
        x_pct = 100.0 * x / (iw - w)
    if h >= ih:
        y_pct = 50.0
    else:
        y_pct = 100.0 * y / (ih - h)
    return (max(0.0, min(x_pct, 100.0)), max(0.0, min(y_pct, 100.0)))


def css_recipe(rect, iw, ih, aspect):
    """CSS properties that reproduce a crop rect client-side.

    Returns (position, bg_size, matches_exact, cover_window):

    - position: `p% q%` — works with object-position AND background-position
      (same alignment semantics: the point at p% of the image aligns with p%
      of the box). Size-invariant: valid for any thumbnail of the image.
    - bg_size: `W% H%` for background-size — this is what makes the crop
      EXACT. Plain `object-fit: cover` cannot zoom: it only shows the largest
      window of the target aspect that fits the image, and object-position can
      merely slide it. background-size percentages scale the image against the
      box, so `background-size: iw/w*100% ih/h*100%` zooms the exact crop
      window into view.
    - matches_exact: True when the crop rect IS the cover window (i.e. plain
      object-fit + object-position alone already reproduce the crop).
    - cover_window: (w, h) in source px of the largest aspect window.
    """
    x, y, w, h = rect
    x_pct, y_pct = object_position(rect, iw, ih)
    pos = f"{x_pct:.1f}% {y_pct:.1f}%"
    if iw / ih >= aspect:
        cov_w, cov_h = aspect * ih, ih
    else:
        cov_w, cov_h = iw, iw / aspect
    matches_exact = abs(w - cov_w) < 2 and abs(h - cov_h) < 2
    bg_w = 100.0 * iw / w
    bg_h = 100.0 * ih / h
    bg_size = f"{bg_w:.1f}% {bg_h:.1f}%"
    return pos, bg_size, matches_exact, (round(cov_w), round(cov_h))


def crop_image(img, aspect, gravity="face", tightness=0.55, eyeline=0.39):
    """High-level helper: return (cropped_img, rect, face_box).

    gravity: 'face' (face-aware, center fallback), 'center' (always center).
    tightness: 0-1, fraction of crop height filled by the head (see smart_crop).
    eyeline: 0-0.9, eye line as fraction of crop height from the top.
    """
    ih, iw = img.shape[:2]
    box = detect_face(img) if gravity == "face" else None
    rect = (smart_crop(img, aspect, box, tightness, eyeline)
            if gravity == "face" else center_crop(iw, ih, aspect))
    x, y, w, h = rect
    return img[y:y + h, x:x + w], rect, box


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--aspect", type=parse_aspect, default=None,
                    help="target aspect ratio, e.g. 16:9, 1:1, 4:3, 9:16")
    ap.add_argument("--size", default=None, help="target WxH, e.g. 640x360")
    ap.add_argument("--tightness", type=float, default=0.55,
                    help="head fills this fraction of crop height (0.3 loose - 1.0 tight headshot)")
    ap.add_argument("--eyeline", type=float, default=0.39,
                    help="eye line at this fraction of crop height from the top "
                         "(0.30 = classic portrait, eyes a third down; default 0.39)")
    ap.add_argument("--out", default=None, help="output path")
    ap.add_argument("--draw", action="store_true",
                    help="also save an annotated image showing face box + crop")
    ap.add_argument("--css", action="store_true",
                    help="also print the equivalent CSS object-position (client-side crop)")
    args = ap.parse_args()

    if args.aspect is None and args.size is None:
        ap.error("provide --aspect (16:9) or --size (640x360)")

    if args.size:
        tw, th = (int(v) for v in args.size.lower().split("x"))
        aspect = tw / th
    else:
        aspect = args.aspect

    if not (0 < args.tightness <= 1):
        ap.error("--tightness must be between 0 and 1 (e.g. 0.55)")
    if not (0 <= args.eyeline <= 0.9):
        ap.error("--eyeline must be between 0 and 0.9 (e.g. 0.30)")

    img = cv2.imread(args.input)
    if img is None:
        sys.exit(f"cannot read {args.input}")
    ih, iw = img.shape[:2]

    box = detect_face(img)
    if box is None:
        print("no face detected -> using center crop")

    x, y, w, h = smart_crop(img, aspect, box, args.tightness, args.eyeline)
    crop = img[y:y + h, x:x + w]

    if args.size:
        crop = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA)

    out = args.out or os.path.splitext(args.input)[0] + "_cropped.jpg"
    cv2.imwrite(out, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

    print(f"input {iw}x{ih}  aspect={iw/ih:.3f}")
    print(f"face box = {box}")
    print(f"tightness = {args.tightness}  eyeline = {args.eyeline}")
    print(f"crop     = ({x},{y}) {w}x{h}  aspect={w/h:.3f}")
    print(f"wrote    = {out}")

    if args.css:
        pos, bg_size, _m, _cov = css_recipe((x, y, w, h), iw, ih, aspect)
        print(f"css      = object-fit: cover; object-position: {pos}")
        print(f"           exact: background-size: {bg_size}; background-position: {pos}")
        print(f"           (client-side crop: any box of aspect {w/h:.3f} with this style)")

    if args.draw:
        ann = img.copy()
        if box:
            fx, fy, fw, fh = box
            cv2.rectangle(ann, (fx, fy), (fx + fw, fy + fh), (0, 255, 0), 3)
        cv2.rectangle(ann, (x, y), (x + w, y + h), (0, 0, 255), 3)
        aout = os.path.splitext(out)[0] + "_annotated.jpg"
        cv2.imwrite(aout, ann, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        print(f"annotated = {aout}")


if __name__ == "__main__":
    main()
