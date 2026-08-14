#!/usr/bin/env python3
"""Interactive compare: build the three comparison images for the web app.

Given a decoded image + aspect ratio + face box, produce:
  1. annotated original -- face box (light blue), smart crop (green),
     naive center crop (red), each labeled
  2. the naive center crop
  3. the smart face-aware crop
"""
import cv2
import numpy as np

from smartcrop import center_crop, smart_crop

FACE = (230, 216, 173)   # BGR light blue
SMART = (0, 200, 0)      # BGR green
NAIVE = (0, 0, 255)      # BGR red

DISPLAY_WIDTH = 900      # annotated original is downscaled to this width


def _draw_box(img, x, y, w, h, color, text, thickness):
    """Draw a labeled rectangle. Label sits above the box on a dark chip."""
    cv2.rectangle(img, (x, y), (x + w, y + h), color, thickness)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
    ly = max(y - th - 10, 4)
    lx = max(x, 2)
    cv2.rectangle(img, (lx, ly), (lx + tw + 8, ly + th + 8), (20, 20, 20), -1)
    cv2.putText(img, text, (lx + 4, ly + th + 3),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)


def _rsz(im, w):
    return cv2.resize(im, (w, int(im.shape[0] * w / im.shape[1])),
                      interpolation=cv2.INTER_AREA)


def _crop(img, rect):
    x, y, w, h = rect
    return img[y:y + h, x:x + w]


def build_compare(img, aspect, box, tightness=0.55, smart_gravity="face"):
    """Return (annotated, naive_crop, smart_crop, rect_naive, rect_smart).

    smart_gravity: effective gravity for the smart panel ('face' or 'center').
    """
    ih, iw = img.shape[:2]
    rect_naive = center_crop(iw, ih, aspect)
    rect_smart = (smart_crop(img, aspect, box, tightness)
                  if smart_gravity == "face" else rect_naive)

    ann = img.copy()
    t = max(2, iw // 400)
    if box is not None:
        _draw_box(ann, *box, FACE, "face", t)
    _draw_box(ann, *rect_naive, NAIVE, "naive", t)
    _draw_box(ann, *rect_smart, SMART, "smart", t)
    if ann.shape[1] > DISPLAY_WIDTH:
        ann = _rsz(ann, DISPLAY_WIDTH)

    return ann, _crop(img, rect_naive), _crop(img, rect_smart), rect_naive, rect_smart
