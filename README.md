# Reframe

Face-aware image cropping for Wikimedia Commons, exposed as a **URL you can use
like a thumbnail**.

Given a Commons file name and a target window (landscape, square, portrait),
this crops the image so the **face stays visible and well-composed** — instead
of the naive center-crop that lands on the torso.

```
https://your-tool.toolforge.org/crop?file=File:Name.jpg&width=300&height=200&gravity=face
```

It's a miniature ["thumbor"](https://github.com/thumbor/thumbor) for Commons:
a tiny face detector + ~30 lines of crop geometry, no GPU, no ML serving stack.

Tightness: the face-aware crop sizes itself so the head region fills a
configurable fraction of the crop height (`tightness`, default 0.55).
Lower (0.3) = looser, more of the subject/scene visible; higher (0.9) = tight
headshot. Face-aware only; naive center crops are unaffected.

## What's inside

| File | Purpose |
|------|---------|
| `smartcrop.py` | Core library: face detection + crop geometry + a CLI |
| `proxy.py` | Flask web service — `/crop` API + `/compare` interactive page |
| `compare.py` | Side-by-side naive-vs-smart comparison montage (CLI dev tool) |
| `compare_web.py` | Image compositing for the `/compare` page |
| `models/` | YuNet face-detection ONNX model (~230 KB) |

## Quickstart (local)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# CLI: crop a local image to 16:9 (default tightness 0.55), annotated debug output
python smartcrop.py photo.jpg --aspect 16:9 --draw
# tight headshot: head fills 90% of the crop height
python smartcrop.py photo.jpg --size 640x360 --tightness 0.9

# Proxy: serve the crop URL locally
python proxy.py
# then open:
#   http://localhost:8765/crop?file=File:Barack_Obama_family_portrait_2011.jpg&width=300&height=200&gravity=face
```

## Proxy API

`GET /crop?file=...&...`

| Param | Required | Description |
|-------|:--------:|-------------|
| `file` | ✅ | Commons file name — see [File name formats](#file-name-formats) below |
| `width` / `height` | either | Exact output size in px. Crops to that aspect, then scales. |
| `aspect` | either | Target ratio instead of exact size, e.g. `16:9`, `1:1`, `9:16` |
| `gravity` | no | `face` (default), `center`, or `auto` (face if found, else center) |
| `tightness` | no | How tight the crop hugs the face: fraction of crop height filled by the head region, `0` (loose) – `1` (face-filling). Default `0.55`. Face-aware only. |

Defaults to a **square** crop if no size/aspect is given.

### File name formats

`file` (on both `/crop` and `/compare`) accepts any of:
`File:Khagdaev 02.jpg` · `File:Khagdaev_02.jpg` · `Khagdaev 02.jpg` ·
`Khagdaev_02.jpg` · `https://commons.wikimedia.org/wiki/File:Khagdaev_02.jpg` —
it is normalized to the canonical `File:` title (spaces/underscores are
equivalent in MediaWiki titles).

### Compare page

`GET /compare?file=File:Name.jpg&aspect=1:1&tightness=0.55&gravity=face` — an interactive HTML page
that shows, for any Commons file: the original annotated with the face box
(light blue), the smart crop (green) and the naive center-crop (red), plus
the dedicated naive and smart crops side by side, and a ready-to-use
`/crop` API URL matching the selected gravity and tightness. Aspect selector: 16:9 · 3:2 ·
4:3 · 1:1 · 3:4 · 2:3 · 9:16, a tightness slider (0.30–0.90), and gravity
radio buttons (face / auto / center) so the differences are visible side by
side. `file` is optional — omit it to get the empty form (useful as a
standalone tool page). The API URL card reflects the chosen gravity and
tightness.

Response headers:
- `Cache-Control: public, max-age=604800, immutable` — output is deterministic,
  so cache aggressively.
- `X-SmartCrop-Face: yes|no` — whether a face was detected and used.

Errors (plain-text body, proper status):
- `400` — missing/invalid parameter (`file`, `aspect`, `gravity`, `tightness`)
- `404` — the file doesn't exist on Commons
- `502` — Commons unreachable or fetch failed
- `415` — fetched bytes aren't a decodable image

## How it works

1. **Fetch** — resolves the `File:` title via
   [`Special:FilePath?width=1200`](https://commons.wikimedia.org/wiki/Special:FilePath),
   so Commons handles format conversion for free (SVG→PNG, PDF→JPEG, video
   keyframe) and we get a bounded-size raster to work with.
2. **Detect** — [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
   returns a face bounding box (~30 ms CPU). Falls back to OpenCV's bundled
   Haar cascade if the ONNX model is missing.
3. **Crop** — the geometry (the actual "smart" part):
   - expand the face box upward for hair/headroom, downward for neck/shoulders
   - place the top of the head ~13% down the crop so we don't decapitate
   - center horizontally on the face, clamp to image bounds
   - largest face wins in group shots; no face → center-crop fallback

## Detector options (all local, no GPU)

| Detector | Size | Dependency | Accuracy | Notes |
|----------|------|-------------|----------|-------|
| **YuNet** | 230 KB | `opencv-python-headless` | good | ✅ default; ships in `models/` |
| Haar cascade | 0 KB | `opencv-python-headless` | OK | zero-download fallback; misses profile/tilted faces |
| MediaPipe BlazeFace | ~2 MB | `mediapipe` | best | upgrade path for tough cases (profile, tilted) |

To switch to MediaPipe, replace `detect_face()` in `smartcrop.py` — the crop
geometry is unchanged.

## Deploying to Toolforge

This is community infrastructure: an OSI license is required (MIT included).
The planned tool name is `reframe` (`reframe.toolforge.org`) — verified
available (no tool by that name is currently running). The repo directory can
stay `commons-smartcrop`; only the tool name matters for the domain.

### Option A — Build Service (recommended)

```bash
# create the tool at https://toolsadmin.wikimedia.org/tools/create
# create a repo for it, then:
git push   # a Procfile + .python-version are already in this repo

ssh <user>@login.toolforge.org
become <tool>
toolforge build start https://gitlab.wikimedia.org/toolforge-repos/<tool>.git
toolforge build show              # wait for "Succeeded"
toolforge webservice buildservice start --mount=none
```

### Option B — Traditional (scp + venv)

```bash
scp -r . <user>@login.toolforge.org:/data/project/<tool>/
ssh <user>@login.toolforge.org
become <tool>
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
webservice --backend=kubernetes python3.11 start
```

Then hit `https://<tool>.toolforge.org/crop?file=...&width=...&height=...`.

### Production notes

- The proxy has no rate limiting or auth. For a public tool, add a simple
  in-memory/disk cache or rate limiter before wide use.
- `gunicorn` sync workers are recommended (one request per worker at a time)
  because the cached YuNet detector is not thread-safe. The `Procfile` uses
  `--workers=4`.
- Pin exact dependency versions (`pip freeze > requirements.txt`) for
  reproducible Toolforge deploys.
- `opencv-python-headless` is pinned to `<5`: OpenCV 5.x removed
  `cv2.CascadeClassifier` and no longer ships the Haar cascade XMLs, which
  breaks the no-face fallback path. 4.x has wheels for Python 3.11 (Toolforge)
  and 3.14.
- The proxy sends a descriptive User-Agent: `$WIKIMEDIA_USER_AGENT` if set
  (already configured on this machine with `andrew.lih@gmail.com` contact),
  else a built-in fallback with the same contact info. Required by Wikimedia
  API etiquette.

## License

MIT. The YuNet model in `models/` is from
[opencv/opencv_zoo](https://github.com/opencv/opencv_zoo) (Apache-2.0) — see
`models/README.md`.
