# Reframe — HANDOFF (resume here)

*Snapshot: 2026-08-15. A fresh session should read this file first, then
`README.md` for the full API/UX reference. The LLM wiki holds the atomic
observations — `wiki_recall` will surface them.*

## Status in one line

**Fully working, tested locally, and DEPLOYED to Toolforge** (2026-08-14,
updated 2026-08-15): face-aware crops live at **https://reframe.toolforge.org**
— `/crop` (JPEG), `/css` (CSS properties for client-side crops, no pixels
served), and the interactive `/compare` page (incl. a live client-side
reframe preview). Verified live: 200 JPEG with `X-SmartCrop-Face: yes`,
404/400 error paths, CSS-exact recipe pixel-matches `/crop` (MAE ~1–2/255).
Built via **Toolforge Build Service from GitHub**
(`github.com/fuzheado/reframe`, branch `main`).

**Production hardening DEPLOYED to Toolforge (2026-08-15)**: upstream disk
cache (`cache.py`) + per-IP rate limiter (`ratelimit.py`) + fetch guards
(byte cap, concurrency semaphore, request logging). Verified live: cold crop
miss 922 ms → repeat crop hit 463 ms (logs show `cache hit`), /css cached,
headers unchanged, cache dir on overlay disk (95 GB free, NOT tmpfs) at
/workspace/cache with the same sha1 keyed files as local tests. Gunicorn
logs a harmless one-time `Control server error: Permission denied: '/data'`
at boot (non-fatal).

**`eyeline` param DEPLOYED (2026-08-15)**: eyes placeable anywhere in the
frame (`eyeline=0.30` = classic portrait). Default 0.39 ≈ old behavior (1 px).
Tightness zooms around the eye line (was: dragged eyes 27%→55% of frame).
Verified live: three framings byte-identical to local tests (same MD5s),
/css payload carries eyeline, /compare slider + URLs work, 400 validation
live. See Next steps #4.

## Project map

```
~/Documents/ai/reframe/
├── README.md       full reference: API, compare page, deploy, production notes
├── HANDOFF.md      ← you are here
├── cache.py        stdlib disk cache: sha1-keyed files, atomic replace, ttl + size sweeps
├── ratelimit.py    fixed-window per-IP rate limiter (in-process; per-worker semantics)
├── smartcrop.py    core library: YuNet/Haar face detection + crop geometry + CLI (--css flag)
├── proxy.py        Flask app: GET /crop (JPEG) + GET /css (CSS properties JSON) + GET /compare (interactive page)
├── compare.py      CLI dev tool: naive-vs-smart montage JPEG
├── screenshot.png  README screenshot of the compare interface
├── compare_web.py  image compositing for the /compare page (labeled boxes + crops)
├── models/         face_detection_yunet_2023mar.onnx (~230 KB, Apache-2.0) + README
├── requirements.txt  flask, gunicorn, requests, numpy, opencv-python-headless>=4.8,<5
├── Procfile        gunicorn proxy:app --workers=2 (sync workers — YuNet detector
│                  not thread-safe; 4 workers OOM-killed the 512Mi pod, see README)
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
#   /css?file=File:Jade_Raymond_Feb_2012-cropped.jpg&aspect=1:1&tightness=0.85
#   /compare?file=Khagdaev_02.jpg&aspect=1:1&tightness=0.55&gravity=face
```

Verified test cases (all passing, 2026-08-14/15): face crop on portrait, group
photo (largest face wins), no-face → center fallback, SVG→PNG conversion via
Special:FilePath, aspect-only (no resize), square default, 9:16 on landscape
and portrait, all 5 filename input formats, gravity face/auto/center, tightness
sweep 0.35/0.55/0.9, error paths (400/404/502/415), CSS-mode: `css_exact`
recipe pixel-matches `/crop` in a real browser (MAE 1.13 bare recipe, 2.07
compare-page preview) while plain object-fit does NOT (MAE ~29 — CSS can't
zoom). Test images live in `/tmp/smartcrop-test/`.

## API quick reference

`GET /crop?file=...&width=&height=|aspect=&gravity=&tightness=&eyeline=` — cropped JPEG

`GET /css?file=...&aspect=&gravity=&tightness=&eyeline=` — **JSON with CSS properties**
for a client-side crop (no pixels served): `object-position` percentages,
`css` / `background_css` (no-zoom variants), **`css_exact`** — the
`background-size` + `background-position` zoom recipe that reproduces /crop
exactly (pixel-verified MAE ~1–2/255; object-fit CANNOT zoom — see README
"zoom caveat"), `matches_exact` / `cover_window` honesty flags, `source.url`
(any thumbnail size works — percentages are size-invariant), crop rect, and
an example `<div>` using the exact recipe. Same params, headers, and error
semantics as `/crop`. Math: under `object-fit: cover`, visible-window left
edge = `(iw−w)·p/100`, so `p = x/(iw−w)·100` (the same formula
positions a `background-size: iw/w% ih/h%` zoom window — that recipe is
the exact one; plain object-fit cannot zoom, see README "zoom caveat").

- `file` — any of `File:Name.jpg`, `Name.jpg`, `Name_02.jpg`, or a full
  `commons.wikimedia.org/wiki/File:...` URL; normalized to canonical `File:` title
- `width`/`height` (exact size) OR `aspect` (16:9, 1:1, 9:16 …); default square
- `gravity` — `face` (default), `center`, `auto`. **Note: `face` and `auto`
  are behaviorally identical today** (face if found, else center); `auto` is
  the reserved semantics for future subject-aware detection
- `tightness` — 0–1, fraction of crop height filled by head region; default
  0.55; face-aware only; zooms around the eye line (placement stays put)
- `eyeline` — 0–0.9, eye line as fraction of frame height from the top;
  default 0.39 (≈ old 0.13 headroom constant); `0.30` = classic portrait;
  face-aware only. Eyes assumed at 30% of the YuNet face-box height
  (`EYE_RATIO` in smartcrop.py) — a fixed detector means a fixed, calibratable
  constant
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
- **CSS cannot zoom**: plain `object-fit: cover` + `object-position` only
  slides the LARGEST window of the target aspect — it does NOT reproduce
  `/crop`'s tight crops (user-reported mismatch, Jade_Raymond_Feb_2012). The
  exact recipe is `css_exact` (`background-size: iw/w% ih/h%` +
  `background-position`), verified pixel-identical in-browser. `/compare`
  preview uses it; the card shows both recipes + a zoom note. Any future
  "CSS equivalence" claim must be verified against the browser rendering,
  not formula-vs-formula.
- **Stale port squatting**: a leftover server on :8765 caused phantom 404s
  during testing — `lsof -i :8765` before restarting.
- README's original example `File:Umapine_(Wakonkonwelasonmi).jpg` does not
  exist; the real NARA title is long. README now uses verified files only
  (Obama family portrait, Khagdaev 02.jpg).
- `Special:FilePath?width=1200` may return a width slightly ≠1200 (observed
  1280) — harmless, crops verified correct.
- **Flask logging gotcha**: `app.logger.info()` is silently dropped in
  non-debug Flask (root logger defaults to WARNING). `proxy.py` calls
  `logging.basicConfig(level=INFO)` so the per-request cache-hit log lines
  appear (stderr — captured by Toolforge). Don't remove it.
- **Cache is ephemeral**: buildservice deploy uses `--mount=none`, so
  `CACHE_DIR` (default `./cache`) lives on the pod's overlay fs and resets on
  every redeploy/restart. Expected and fine — see README Production notes.
- **Rate limiter is per-worker**: 2 sync workers ⇒ effective cap = 2 ×
  `RATE_LIMIT`. Shared-state (SQLite) limiter is the next step if exactness
  ever matters; not needed for a soft guard.

## Next steps

1. ~~Deploy to Toolforge~~ ✅ **DONE 2026-08-14**: Build Service from GitHub
   (tool `reframe`, domain reframe.toolforge.org, `--mount=none`). Redeploy on
   code change: `toolforge build start https://github.com/fuzheado/reframe`
   then `toolforge webservice buildservice restart`.
2. ~~Production hardening~~ ✅ **DONE + DEPLOYED 2026-08-15** (upstream disk
   cache + rate limiter + fetch guards). Deploy: `git push` → `toolforge build
   start https://github.com/fuzheado/reframe` → `toolforge webservice
   buildservice restart`. Verified live via `kubectl logs`: miss 922 ms → hit
   463 ms; cache dir on overlay disk at /workspace/cache (95 GB free).
   Defaults suffice — no envvars set on Toolforge. Future redeploys: same
   build+restart flow (cache resets each time — expected).
3. **Optional**: detector upgrade for profile/tilted/small faces — SCRFD-2.5G
   (best accuracy/speed, ~3 MB, no new pip dep via `cv2.dnn`) or MediaPipe
   BlazeFace; both plug into `detect_face()` in smartcrop.py (crop geometry
   unchanged). See README "Detector options" for the full ladder incl.
   WIDER FACE hard AP figures.
4. ~~Optional: per-call headroom control (the 0.13 constant)~~ ✅ **DONE
   2026-08-15**: replaced the hardcoded 0.13 headroom with an `eyeline` param
   (0–0.9, default 0.39 ≈ old behavior; 0.30 = classic portrait eyes-a-third-
   down). Tightness now zooms around the eye line instead of dragging it down
   (old: eye_frac = 0.13 + 0.47×tightness → eyes drifted 27%→55%). Wired
   through CLI (--eyeline), /crop, /css payload, and /compare (new slider +
   URLs). Eye position estimated at 30% of face-box height (EYE_RATIO).
