#!/usr/bin/env python3
"""Generate a side-by-side comparison: naive center-crop vs face-aware smart crop."""
import cv2
import numpy as np
from smartcrop import detect_face, smart_crop, center_crop


def label(text, w, h=56):
    t = np.full((h, w, 3), 28, np.uint8)
    cv2.putText(t, text, (10, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return t


def rsz(im, w):
    return cv2.resize(im, (w, int(im.shape[0] * w / im.shape[1])), interpolation=cv2.INTER_AREA)


def padh(im, h, w):
    p = np.full((h - im.shape[0], w, 3), 20, np.uint8)
    return np.vstack([im, p])


def montage(path, aspect, out, W=480):
    img = cv2.imread(path)
    ih, iw = img.shape[:2]
    box = detect_face(img)

    naive = center_crop(iw, ih, aspect)
    smart = smart_crop(img, aspect, box)

    c_naive = img[naive[1]:naive[1] + naive[3], naive[0]:naive[0] + naive[2]]
    c_smart = img[smart[1]:smart[1] + smart[3], smart[0]:smart[0] + smart[2]]

    ann = img.copy()
    x, y, w, h = naive
    cv2.rectangle(ann, (x, y), (x + w, y + h), (0, 0, 255), 5)
    x, y, w, h = smart
    cv2.rectangle(ann, (x, y), (x + w, y + h), (0, 200, 0), 5)
    if box:
        fx, fy, fw, fh = box
        cv2.rectangle(ann, (fx, fy), (fx + fw, fy + fh), (255, 255, 0), 3)

    ann = rsz(ann, 2 * W)
    title = label("ORIGINAL  (RED = naive center-crop,  GREEN = smart crop,  YELLOW = face)",
                  ann.shape[1])
    top = np.vstack([title, ann])

    r_l = rsz(c_naive, W)
    r_r = rsz(c_smart, W)
    H = max(r_l.shape[0], r_r.shape[0])
    r_l = padh(r_l, H, W)
    r_r = padh(r_r, H, W)
    lrow = np.hstack([label("NAIVE center-crop", W), label("SMART face-aware", W)])
    bot = np.hstack([r_l, r_r])

    outimg = np.vstack([top, lrow, bot])
    cv2.imwrite(out, outimg, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

    ok = "n/a"
    if box:
        fx, fy, fw, fh = box
        sx, sy, sw, sh = smart
        inside = (fx >= sx and fy >= sy and fx + fw <= sx + sw and fy + fh <= sy + sh)
        ok = f"face {'INSIDE' if inside else 'OUTSIDE'} smart crop"
    print(f"{path}: {ok}  naive={naive}  smart={smart}  -> {out}")


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:] or ["example.jpg"]:
        montage(p, 16 / 9, p.rsplit(".", 1)[0] + "_compare.jpg")
