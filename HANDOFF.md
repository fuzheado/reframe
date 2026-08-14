# Reframe — HANDOFF (resume here)

*Snapshot: 2026-08-14. A fresh session should read this file first, then
`README.md` for the full API/UX reference. The LLM wiki holds the atomic
observations — `wiki_recall` will surface them.*

## Status in one line

**Fully working and tested locally** (CLI + `/crop` proxy API + interactive
`/compare` page): face-aware crops with aspect, tightness, and gravity
controls, flexible Commons filename input, clean error semantics. **Not yet
deployed to Toolforge** — tool name `reframe` verified available.

## Project map

```
~/Documents/ai/reframe/
├── README.md       full reference: API, compare page, deploy, production notes
├── HANDOFF.md      ← you are here
├── smartcrop.py    core library: YuNet/Haar face detection + crop geometry + CLI
├── proxy.py        Flask app: GET /crop (thumbnail-style JPEG API) + GET /compare (interactive page)
├── compare.py      CLI dev tool: naive-vs-smart montage JPEG
├── compare_web.py  image compositing for the /compare page (labeled boxes + crops)
├── models/         face_detection_yunet_2023mar.onnx (~230 KB, Apache-2.0) + README
├── requirements.txt  flask, gunicorn, requests, numpy, opencv-python-headless>=4.8,<5
├── Procfile        gunicorn proxy:app --workers=4 (sync workers — YuNet detector not thread-safe)
└── .python-version  3.11 (Toolforge; replaced runtime.txt — modern buildpacks reject it)
```

The old directory `~/Documents/ai/commons-smartcrop/` still exists and is
superseded by this repo (its local proxy may still be running on :8765).

## Run / test (local)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# CLI — face-aware crop with debug overlay
python smartcrop.py photo.jpg --aspect 16:9 --draw
python smartcrop.py photo.jpg --size 300x300 --tightness 0.9   # tight headshot

# Web app — http://localhost:8765
python proxy.py
#   /crop?file=File:Barack_Obama_family_portrait_2011.jpg&width=300&height=200
#   /compare?file=Khagdaev_02.jpg&aspect=1:1&tightness=0.55&gravity=face
```

Verified test cases (all passing, 2026-08-14): face crop on portrait, group
photo (largest face wins), no-face → center fallback, SVG→PNG conversion via
Special:FilePath, aspect-only (no resize), square default, 9:16 on landscape
and portrait, all 5 filename input formats, gravity face/auto/center, tightness
sweep 0.35/0.55/0.9, error paths (400/404/502/415). Test images live in
`/tmp/smartcrop-test/`.

## API quick reference

`GET /crop?file=...&width=&height=|aspect=&gravity=&tightness=`

- `file` — any of `File:Name.jpg`, `Name.jpg`, `Name_02.jpg`, or a full
  `commons.wikimedia.org/wiki/File:...` URL; normalized to canonical `File:` title
- `width`/`height` (exact size) OR `aspect` (16:9, 1:1, 9:16 …); default square
- `gravity` — `face` (default), `center`, `auto`. **Note: `face` and `auto`
  are behaviorally identical today** (face if found, else center); `auto` is
  the reserved semantics for future subject-aware detection
- `tightness` — 0–1, fraction of crop height filled by head region; default
  0.55; face-aware only
- Headers: `Cache-Control: public, max-age=604800, immutable`,
  `X-SmartCrop-Face: yes|no`
- Errors: 400 (bad param), 404 (file not on Commons), 502 (fetch failed),
  415 (undecodable)

## Key decisions & gotchas

- **Name is Reframe**; repo dir is `reframe`. `X-SmartCrop-Face` header kept
  deliberately (API contract, documented) — if renamed, do it before wide
  adoption.
- **opencv-python-headless pinned <5**: OpenCV 5.x removed
  `cv2.CascadeClassifier` and ships no Haar XMLs, which crashed the no-face
  fallback. `smartcrop.py` also guards the fallback with try/except.
- **UA compliance**: `proxy.py` uses `$WIKIMEDIA_USER_AGENT` if set, else
  `Reframe/1.0 (…User:Fuzheado; andrew.lih@gmail.com)`. Never hit
  `Special:FilePath` without a descriptive UA.
- **Stale port squatting**: a leftover server on :8765 caused phantom 404s
  during testing — `lsof -i :8765` before restarting.
- README's original example `File:Umapine_(Wakonkonwelasonmi).jpg` does not
  exist; the real NARA title is long. README now uses verified files only
  (Obama family portrait, Khagdaev 02.jpg).
- `Special:FilePath?width=1200` may return a width slightly ≠1200 (observed
  1280) — harmless, crops verified correct.

## Next steps

1. **Deploy to Toolforge** (Build Service, per README): create tool `reframe`
   at toolsadmin.wikimedia.org, push to
   `gitlab.wikimedia.org/toolforge-repos/reframe.git`,
   `toolforge build start`, `toolforge webservice buildservice start --mount=none`.
2. **Production hardening** (README "Production notes"): rate limiting and/or
   a disk cache before wide public use — the proxy currently has neither.
3. **Optional**: MediaPipe BlazeFace swap for profile/tilted faces (replace
   `detect_face()` in smartcrop.py; crop geometry unchanged).
4. **Optional**: per-call headroom control (the 0.13 constant) if tightness
   alone isn't enough for some consumers.
