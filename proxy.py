#!/usr/bin/env python3
"""
Face-aware crop proxy for Wikimedia Commons.

A miniature "thumbor for Commons": given a file name + target dimensions, it
fetches the image from Commons, runs face detection, and returns a crop that
keeps the face visible.

    GET /crop?file=File:Example.jpg&width=300&height=200&gravity=face
    GET /crop?file=File:Example.jpg&aspect=16:9&gravity=face
    GET /crop?file=File:Example.jpg&width=120&gravity=face   (square default)

gravity:  face (default) | center | auto (face if found, else center)

This is the "proxy" pattern: any tool in the ecosystem can point an <img> at
this URL or fetch a cropped JPEG, exactly like a thumbnail.

Deploy on Toolforge (see README) -- bind to $PORT, add an OSI license.
"""
import base64
import io
import json
import os
import re
import urllib.parse

import cv2
import numpy as np
import requests
from flask import Flask, Response, request

from compare_web import build_compare
from smartcrop import detect_face, smart_crop, center_crop, object_position, css_recipe

app = Flask(__name__)

UA = os.environ.get(
    "WIKIMEDIA_USER_AGENT",
    "Reframe/1.0 (https://en.wikipedia.org/wiki/User:Fuzheado; andrew.lih@gmail.com)",
)

# Bounded working resolution for detection (keeps CPU ~30 ms and avoids huge
# downloads). The crop is upscaled to the requested size at the end.
MAX_DETECT_SIDE = 1200

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})


def fetch_commons(file_title):
    """Resolve a File:... title to decoded image bytes via Special:FilePath.

    Piggybacks on Commons' thumbnail pipeline, so SVG -> PNG, PDF/DjVu -> JPEG,
    and video keyframe extraction all work for free (no per-format code here).
    """
    url = ("https://commons.wikimedia.org/wiki/Special:FilePath/"
           + urllib.parse.quote(file_title) + "?width=" + str(MAX_DETECT_SIDE))
    r = SESSION.get(url, timeout=20)
    r.raise_for_status()
    return r.content

def decode_img(data):
    arr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def resolve_gravity(gravity, box):
    """Return effective gravity given the raw param and whether a face was found."""
    if gravity == "center":
        return "center"
    if gravity == "auto" and box is None:
        return "center"
    if box is None:
        return "center"
    return "face"


def normalize_file_input(s):
    """Accept a Commons file name in any friendly form and return the canonical
    `File:Name_With_Underscores.ext` title, or None if empty.

    Accepted:
        File:Khagdaev 02.jpg
        File:Khagdaev_02.jpg
        Khagdaev 02.jpg
        Khagdaev_02.jpg
        https://commons.wikimedia.org/wiki/File:Khagdaev_02.jpg
    """
    s = (s or "").strip()
    if not s:
        return None
    # Full URL form (also tolerates http:// and no File: prefix in the URL).
    m = re.search(r"commons\.wikimedia\.org/wiki/(.+)$", s)
    if m:
        s = urllib.parse.unquote(m.group(1))
    s = re.sub(r"^[Ff][Ii][Ll][Ee]:", "", s)  # drop optional File: prefix
    s = s.replace("_", " ").strip()  # underscores and spaces are equivalent
    if not s:
        return None
    return "File:" + s.replace(" ", "_")


def _parse_params():
    """Shared validation for /crop and /css.

    Returns ((canonical, aspect, aspect_s, w, h, tightness, gravity), None) on
    success, or (None, error_message) — message is plain text for a 400.
    """
    file_title = request.args.get("file", "")
    canonical = normalize_file_input(file_title)
    if canonical is None:
        return None, ("provide ?file= as a valid Commons file name "
                      "(File:Name.jpg, Name.jpg, or a commons.wikimedia.org/wiki/File: URL)")

    w = request.args.get("width", type=int)
    h = request.args.get("height", type=int)
    aspect_s = request.args.get("aspect")
    if aspect_s:
        m = re.match(r"^(\d+):(\d+)$", aspect_s)
        if not m:
            return None, "aspect must be like 16:9"
        aspect = int(m.group(1)) / int(m.group(2))
    elif w and h:
        aspect = w / h
    else:
        aspect = 1.0  # square default

    tightness = 0.55
    tightness_s = request.args.get("tightness")
    if tightness_s:
        try:
            tightness = float(tightness_s)
        except ValueError:
            return None, "tightness must be a number like 0.55"
        if not (0 < tightness <= 1):
            return None, "tightness must be between 0 (loose) and 1 (face-filling)"

    gravity = request.args.get("gravity", "face")
    if gravity not in ("face", "auto", "center"):
        return None, "gravity must be face, auto, or center"
    return (canonical, aspect, aspect_s, w, h, tightness, gravity), None


def _compute_rect(img, aspect, tightness, gravity):
    """Run detection + geometry. Returns (rect, eff) where eff is the effective
    gravity ('face' | 'center') and rect is (x, y, w, h) in source pixels."""
    ih, iw = img.shape[:2]
    box = detect_face(img) if gravity in ("face", "auto") else None
    eff = resolve_gravity(gravity, box)
    rect = (smart_crop(img, aspect, box, tightness)
            if eff == "face" else center_crop(iw, ih, aspect))
    return rect, eff


@app.route("/crop")
def crop():
    params, err = _parse_params()
    if err:
        return Response(err, status=400)
    canonical, aspect, _aspect_s, w, h, tightness, gravity = params

    try:
        raw = fetch_commons(canonical)
    except requests.HTTPError:
        return Response("file not found on Commons: " + canonical, status=404)
    except requests.RequestException:
        return Response("failed to fetch file from Commons", status=502)
    img = decode_img(raw)
    if img is None:
        return Response("cannot decode image", status=415)

    rect, eff = _compute_rect(img, aspect, tightness, gravity)
    x, y, cw, ch = rect
    out = img[y:y + ch, x:x + cw]

    # Resize to exact requested size (if width/height given).
    if w and h:
        out = cv2.resize(out, (w, h), interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        return Response("encode failed", status=500)

    resp = Response(io.BytesIO(buf.tobytes()).getvalue(), mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    resp.headers["X-SmartCrop-Face"] = "yes" if eff == "face" else "no"
    return resp


@app.route("/css")
def css_style():
    """Return CSS properties for a client-side crop instead of a cropped JPEG.

    Same pipeline as /crop (fetch, detect, geometry) but the response is JSON:
    the client loads the source image itself (any Commons thumbnail size — the
    percentages are size-invariant) and reframes it in-browser with
    `object-fit: cover` + `object-position`, or `background-size: cover` +
    `background-position` for CSS backgrounds.
    """
    params, err = _parse_params()
    if err:
        return Response(err, status=400)
    canonical, aspect, aspect_s, w, h, tightness, gravity = params

    try:
        raw = fetch_commons(canonical)
    except requests.HTTPError:
        return Response("file not found on Commons: " + canonical, status=404)
    except requests.RequestException:
        return Response("failed to fetch file from Commons", status=502)
    img = decode_img(raw)
    if img is None:
        return Response("cannot decode image", status=415)

    ih, iw = img.shape[:2]
    rect, eff = _compute_rect(img, aspect, tightness, gravity)
    x, y, cw, ch = rect
    pos, bg_size, matches_exact, cover_window = css_recipe(rect, iw, ih, aspect)
    src_url = ("https://commons.wikimedia.org/wiki/Special:FilePath/"
               + urllib.parse.quote(canonical) + "?width=" + str(MAX_DETECT_SIDE))

    payload = {
        "file": canonical,
        "aspect": aspect_s or (f"{w}:{h}" if w and h else "1:1"),
        "gravity": gravity,
        "tightness": tightness,
        "face_detected": eff == "face",
        "object_fit": "cover",
        "object_position": pos,
        "css": f"object-fit: cover; object-position: {pos};",
        "matches_exact": matches_exact,
        "cover_window": {"w": cover_window[0], "h": cover_window[1]},
        "css_exact": f"background-size: {bg_size}; background-position: {pos};",
        "zoom": {"x": bg_size.split()[0], "y": bg_size.split()[1]},
        "background_css": f"background-size: cover; background-position: {pos};",
        "crop_needed": not (cw == iw and ch == ih),
        "crop_rect": {"x": x, "y": y, "w": cw, "h": ch},
        "source": {
            "url": src_url,
            "width": iw,
            "height": ih,
            "note": "Any thumbnail size of this image works (percentages are "
                     "size-invariant). `css` (object-fit) cannot zoom: it shows "
                     "the largest window of the target aspect, so it matches /crop "
                     "only when matches_exact is true. `css_exact` (background-size "
                     "zoom) always reproduces the /crop framing exactly — verified "
                     "pixel-identical in-browser (MAE ~1/255).",
        },
        "example": (f'<div style="width: 300px; height: '
                     f'{int(300 / aspect)}px; background: url(\'{src_url}\') '
                     f'no-repeat; background-size: {bg_size}; '
                     f'background-position: {pos};"></div>'),
    }

    resp = Response(json.dumps(payload, indent=2), mimetype="application/json")
    resp.headers["Cache-Control"] = "public, max-age=604800, immutable"
    resp.headers["X-SmartCrop-Face"] = "yes" if eff == "face" else "no"
    return resp


@app.route("/")
def index():
    return ("<h2>Reframe proxy</h2>"
            "<p><code>/crop?file=File:Name.jpg&width=300&height=200"
            "&gravity=face</code></p>"
            "<p><code>/css?file=File:Name.jpg&aspect=16:9&gravity=face</code>"
            " — CSS object-position for client-side cropping</p>"
            "<p><a href=\"/compare\">Interactive compare</a></p>")


# --------------------------------------------------------------------------- #
# Interactive compare page
# --------------------------------------------------------------------------- #

def _jpeg_uri(img, quality=85):
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def _aspect_selector(current):
    opts = ["16:9", "3:2", "4:3", "1:1", "3:4", "2:3", "9:16"]
    return "".join(
        f'<option value="{o}"{" selected" if o == current else ""}>{o}</option>'
        for o in opts)


def _compare_page(file_title, aspect_s, tightness_s, gravity, results, error):
    if results:
        (ann, naive, smart, rn, rs, box, iw, ih, api_url, css_url,
         css_pos, src_url, bg_size, matches_exact, css_exact, eff) = results
        legend = ("<span style='color:#7fd4ff'>light blue = face</span> · "
                  "<span style='color:#7dff8a'>green = smart crop</span> · "
                  "<span style='color:#ff8080'>red = naive center-crop</span>")
        if gravity == "center":
            note = ("<p>Face detection <b>skipped</b> (gravity=center) — both "
                    "crops are the naive center crop; the red and green boxes "
                    "coincide.</p>")
        elif box is None:
            note = ("<p><b>No face detected</b> — smart crop falls back to the "
                    "naive center crop (boxes overlap).</p>")
        else:
            fx, fy, fw, fh = box
            note = (f"<p>Face box ({fx},{fy}) {fw}x{fh} · "
                    f"naive crop ({rn[0]},{rn[1]}) {rn[2]}x{rn[3]} · "
                    f"smart crop ({rs[0]},{rs[1]}) {rs[2]}x{rs[3]} · "
                    f"source {iw}x{ih}</p>")
        if eff == "face":
            smart_title = "Smart face-aware crop"
        elif gravity == "center":
            smart_title = "Center crop — naive (gravity=center)"
        else:
            smart_title = "Center crop — no face found"
        zoom_note = ("" if matches_exact else
                     "<p class='hint'><b>Note:</b> this crop is tighter than what "
                     "<code>object-fit: cover</code> can show (CSS cannot zoom) — "
                     "the plain object-position variant shows a wider window. The "
                     "preview below uses the <code>background-size</code> zoom "
                     "recipe, which matches the smart crop exactly.</p>")
        gallery = f"""
        <div class="card">
          <h3>Smart crop API URL</h3>
          <p>Use this URL anywhere an image is expected — it returns the
             selected crop as JPEG (aspect {aspect_s}, no resize):</p>
          <p class="apilink"><a href="{api_url}">{api_url}</a></p>
        </div>
        <div class="card">
          <h3>CSS crop API URL — no pixels served</h3>
          <p>Client-side alternative: load the image yourself and let CSS do
             the reframing. The endpoint returns
             <code>object-fit</code>/<code>object-position</code> JSON valid
             for any box of aspect {aspect_s} (size-invariant — any
             thumbnail size works):</p>
          <p class="apilink"><a href="{css_url}">{css_url}</a></p>
          <p>→ <code>object-fit: cover; object-position: {css_pos};</code>
             <span class="gsub">(simple — cannot zoom)</span></p>
          <p>→ <code>{css_exact}</code>
             <span class="gsub">(exact — matches the smart crop)</span></p>
          {zoom_note}
          <p>Live preview — same source, reframed entirely client-side
             (exact recipe):</p>
          <div class="cssdemo"
               style="width: 100%; aspect-ratio: {aspect_s.replace(':', ' / ')};
                      background: url('{src_url}') no-repeat;
                      background-size: {bg_size};
                      background-position: {css_pos};"></div>
        </div>
        <div class="card">
          <h3>Original — {legend}</h3>
          <img src="{_jpeg_uri(ann)}" alt="annotated original">
          {note}
        </div>
        <div class="row">
          <div class="card"><h3>Naive center-crop</h3><img src="{_jpeg_uri(naive)}" alt="naive crop"></div>
          <div class="card"><h3>{smart_title}</h3><img src="{_jpeg_uri(smart)}" alt="smart crop"></div>
        </div>"""
    else:
        gallery = ""

    err_html = f'<p class="err">{error}</p>' if error else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Reframe compare</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 1100px;
         margin: 24px auto; padding: 0 16px; color: #ddd; background: #14161a; }}
  h1, h2, h3 {{ color: #fff; }}
  input, select {{ font-size: 15px; padding: 6px 8px; border-radius: 6px;
                  border: 1px solid #444; background: #1e2126; color: #ddd; }}
  input[type=text] {{ width: 420px; }}
  button {{ font-size: 15px; padding: 6px 16px; border-radius: 6px; border: 0;
           background: #2d7d46; color: #fff; cursor: pointer; }}
  .card {{ background: #1a1d22; border: 1px solid #2c313a; border-radius: 10px;
          padding: 14px; margin: 14px 0; }}
  .card img {{ max-width: 100%; border-radius: 6px; }}
  .row {{ display: flex; gap: 14px; }}
  .row .card {{ flex: 1; min-width: 0; }}
  .err {{ color: #ff9d9d; }}
  .meta {{ color: #9aa; font-size: 14px; }}
  .hint {{ color: #9aa; font-size: 14px; margin: 8px 0; }}
  .hint code, .apilink {{ background: #1e2126; padding: 2px 6px; border-radius: 4px; }}
  .gsub {{ color: #778; font-size: 12px; }}
  .tightval {{ display: inline-block; min-width: 34px; text-align: center;
              background: #1e2126; border-radius: 4px; padding: 2px 4px; }}
  .apilink {{ font-family: ui-monospace, Menlo, monospace; word-break: break-all; }}
  .apilink a {{ color: #7fd4ff; }}
  .grav {{ display: flex; flex-direction: column; align-items: flex-start;
          gap: 8px; border: 1px solid #2c313a; border-radius: 8px;
          padding: 10px 14px; margin: 10px 0; }}
  .grav legend {{ color: #9aa; font-size: 13px; padding: 0 6px; }}
  .grav label {{ display: flex; gap: 6px; align-items: baseline; font-size: 14px;
                cursor: pointer; color: #ccc; }}
  .grav input {{ accent-color: #2d7d46; }}
</style></head>
<body>
<h1>Reframe compare</h1>
<form method="get" action="/compare">
  <input type="text" name="file" placeholder="File:Name.jpg or Commons URL"
         value="{file_title}">
  <select name="aspect">{_aspect_selector(aspect_s)}</select>
  <label for="tightness">Tightness</label>
  <input type="range" id="tightness" name="tightness" min="0.30" max="0.90"
         step="0.05" value="{tightness_s}" oninput="document.getElementById('tightness_val').textContent=this.value">
  <span id="tightness_val" class="tightval">{tightness_s}</span>
  <fieldset class="grav">
    <legend>Gravity — what the smart crop does with a face</legend>
    <label><input type="radio" name="gravity" value="face"{" checked" if gravity == "face" else ""}> Face
      <span class="gsub">face-aware; center if no face found (default)</span></label>
    <label><input type="radio" name="gravity" value="auto"{" checked" if gravity == "auto" else ""}> Auto
      <span class="gsub">face if found, else center (same as face today)</span></label>
    <label><input type="radio" name="gravity" value="center"{" checked" if gravity == "center" else ""}> Center
      <span class="gsub">always naive, no detection</span></label>
  </fieldset>
  <button type="submit">Compare</button>
</form>
<p class="hint">Operating on <b>Wikimedia Commons</b> images — the box must be a
  valid Commons file name, e.g. <code>File:Khagdaev 02.jpg</code>.</p>
<p class="hint">Accepted: <code>File:Khagdaev 02.jpg</code> · <code>Khagdaev 02.jpg</code> ·
  <code>Khagdaev_02.jpg</code> · <code>https://commons.wikimedia.org/wiki/File:Khagdaev 02.jpg</code></p>
<p class="hint"><b>Tightness</b> = how much of the crop height the head region fills:
  <code>0.30</code> loose (lots of context) · <code>0.55</code> default ·
  <code>0.90</code> tight headshot. Face-only; naive center crops are unaffected.</p>
{err_html}
{gallery}
<p class="meta">Reframe compare · face detection via YuNet · <a href="/">proxy API</a></p>
</body></html>"""


@app.route("/compare")
def compare():
    file_title = request.args.get("file", "").strip()
    canonical = normalize_file_input(file_title)
    aspect_s = request.args.get("aspect", "1:1")
    tightness_s = request.args.get("tightness", "0.55")
    gravity = request.args.get("gravity", "face")
    if gravity not in ("face", "auto", "center"):
        return _compare_page(file_title, aspect_s, tightness_s, "face", None,
                             f"gravity must be face, auto, or center (got '{gravity}')")
    m = re.match(r"^(\d+):(\d+)$", aspect_s)
    if not m:
        return _compare_page(file_title, "1:1", tightness_s, gravity, None,
                             f"aspect must be like 16:9 (got '{aspect_s}')")
    aspect = int(m.group(1)) / int(m.group(2))

    try:
        tightness = float(tightness_s)
    except ValueError:
        return _compare_page(file_title, aspect_s, tightness_s, gravity, None,
                             f"tightness must be a number like 0.55 (got '{tightness_s}')")
    if not (0 < tightness <= 1):
        return _compare_page(file_title, aspect_s, tightness_s, gravity, None,
                             "tightness must be between 0 (loose) and 1 (face-filling)")

    if not file_title:
        return _compare_page(file_title, aspect_s, tightness_s, gravity, None, None)
    if canonical is None:
        return _compare_page(file_title, aspect_s, tightness_s, gravity, None,
                             "that doesn't look like a valid Commons file name")

    try:
        raw = fetch_commons(canonical)
    except requests.HTTPError:
        return _compare_page(file_title, aspect_s, tightness_s, gravity, None,
                             "file not found on Commons: " + file_title)
    except requests.RequestException:
        return _compare_page(file_title, aspect_s, tightness_s, gravity, None,
                             "failed to fetch file from Commons")
    img = decode_img(raw)
    if img is None:
        return _compare_page(file_title, aspect_s, tightness_s, gravity, None,
                             "cannot decode image")

    ih, iw = img.shape[:2]
    box = detect_face(img) if gravity in ("face", "auto") else None
    eff = resolve_gravity(gravity, box)
    ann, naive, smart, rn, rs = build_compare(img, aspect, box, tightness, eff)
    api_url = (request.url_root + "crop?file=" + canonical
               + "&aspect=" + aspect_s + "&gravity=" + gravity)
    css_url = (request.url_root + "css?file=" + canonical
               + "&aspect=" + aspect_s + "&gravity=" + gravity)
    if tightness != 0.55:
        api_url += f"&tightness={tightness}"
        css_url += f"&tightness={tightness}"
    src_url = ("https://commons.wikimedia.org/wiki/Special:FilePath/"
               + urllib.parse.quote(canonical) + "?width=600")
    css_pos, bg_size, matches_exact, _cov = css_recipe(rs, iw, ih, aspect)
    css_exact = f"background-size: {bg_size}; background-position: {css_pos};"
    results = (ann, naive, smart, rn, rs, box, iw, ih, api_url, css_url,
               css_pos, src_url, bg_size, matches_exact, css_exact, eff)
    return _compare_page(file_title, aspect_s, tightness_s, gravity, results, None)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8765)))
