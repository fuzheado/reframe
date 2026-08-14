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
_DET_LOCK = threading.Lock()


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


def smart_crop(img, aspect, box, tightness=0.55):
    """Compute a crop rectangle of the given aspect that keeps the face visible.

    tightness: fraction of the crop height filled by the head region.
    0.55 (default) = head + some context; 1.0 = face-filling headshot;
    lower values (e.g. 0.35) = looser, more of the subject/scene visible.
    Only applies when a face box is given; center fallback is unaffected.
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

    # Vertical: put the top of the head ~13% down from the crop top (headroom).
    top_of_crop = min(max(top - 0.13 * Hc, 0.0), ih - Hc)

    x = int(cx - Wc / 2.0)
    y = int(top_of_crop)
    w = int(Wc)
    h = int(Hc)

    x = max(0, min(x, iw - w))
    y = max(0, min(y, ih - h))
    return (x, y, w, h)


def crop_image(img, aspect, gravity="face", tightness=0.55):
    """High-level helper: return (cropped_img, rect, face_box).

    gravity: 'face' (face-aware, center fallback), 'center' (always center).
    tightness: 0-1, fraction of crop height filled by the head (see smart_crop).
    """
    ih, iw = img.shape[:2]
    box = detect_face(img) if gravity == "face" else None
    rect = (smart_crop(img, aspect, box, tightness)
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
    ap.add_argument("--out", default=None, help="output path")
    ap.add_argument("--draw", action="store_true",
                    help="also save an annotated image showing face box + crop")
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

    img = cv2.imread(args.input)
    if img is None:
        sys.exit(f"cannot read {args.input}")
    ih, iw = img.shape[:2]

    box = detect_face(img)
    if box is None:
        print("no face detected -> using center crop")

    x, y, w, h = smart_crop(img, aspect, box, args.tightness)
    crop = img[y:y + h, x:x + w]

    if args.size:
        crop = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_AREA)

    out = args.out or os.path.splitext(args.input)[0] + "_cropped.jpg"
    cv2.imwrite(out, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

    print(f"input {iw}x{ih}  aspect={iw/ih:.3f}")
    print(f"face box = {box}")
    print(f"tightness = {args.tightness}")
    print(f"crop     = ({x},{y}) {w}x{h}  aspect={w/h:.3f}")
    print(f"wrote    = {out}")

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
