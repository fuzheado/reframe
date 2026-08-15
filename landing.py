#!/usr/bin/env python3
"""Landing page for the Reframe proxy (GET /).

Self-contained HTML (dark theme matching the /compare page), no external
dependencies. The "Try it" demo is driven by the live /css API: type a
Commons file name, drag the sliders, and compare the server-side /crop JPEG
with the client-side reframe — the demo IS the pitch.
"""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reframe — face-aware cropping for Wikimedia Commons</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 1000px;
         margin: 24px auto; padding: 0 16px; color: #ddd; background: #14161a; }
  h1, h2, h3 { color: #fff; }
  h1 { font-size: 34px; margin-bottom: 4px; }
  h1 .dot { color: #2d7d46; }
  .tagline { font-size: 17px; color: #c8c; margin-top: 2px; }
  a { color: #7fd4ff; }
  code { background: #1e2126; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
  pre { background: #1e2126; border: 1px solid #2c313a; border-radius: 8px;
        padding: 12px 14px; overflow-x: auto; font-size: 13px; line-height: 1.5; }
  input, select { font-size: 15px; padding: 6px 8px; border-radius: 6px;
                  border: 1px solid #444; background: #1e2126; color: #ddd; }
  input[type=text] { width: 100%; box-sizing: border-box; }
  input[type=range] { accent-color: #2d7d46; }
  button { font-size: 15px; padding: 6px 16px; border-radius: 6px; border: 0;
           background: #2d7d46; color: #fff; cursor: pointer; }
  .card { background: #1a1d22; border: 1px solid #2c313a; border-radius: 10px;
          padding: 14px; margin: 14px 0; }
  .row { display: flex; gap: 14px; flex-wrap: wrap; }
  .row > .card { flex: 1; min-width: 280px; margin: 0; }
  .hint { color: #9aa; font-size: 14px; margin: 8px 0; }
  .gsub { color: #778; font-size: 12px; }
  .meta { color: #9aa; font-size: 13px; margin-top: 26px; padding-top: 12px;
          border-top: 1px solid #2c313a; }
  .err { color: #ff9d9d; }
  .ok  { color: #7dff8a; }
  .apilink { font-family: ui-monospace, Menlo, monospace; word-break: break-all; font-size: 13px; }
  .tightval { display: inline-block; min-width: 34px; text-align: center;
              background: #1e2126; border-radius: 4px; padding: 2px 4px; }
  .dinputs { display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }
  .dinputs input[type=text] { flex: 1; min-width: 240px; }
  .drow { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; margin: 8px 0; }
  .drow label { font-size: 14px; color: #ccc; }
  .drow .grp { display: flex; gap: 10px; align-items: baseline; }
  .dpanes { display: flex; gap: 14px; flex-wrap: wrap; margin: 12px 0; }
  .pane { flex: 1; min-width: 240px; }
  .plabel { color: #9aa; font-size: 13px; margin-bottom: 6px; }
  .demobox { width: 100%; background-repeat: no-repeat; border-radius: 6px;
             border: 1px solid #2c313a; }
  .naivebox { border-color: #ff8080; }
  .smartbox { border-color: #2d7d46; }
  .plabel.naive { color: #ff9d9d; }
  .plabel.smart { color: #7dff8a; }
  table { border-collapse: collapse; width: 100%; font-size: 14px; margin: 10px 0; }
  th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #2c313a; }
  th { color: #fff; font-weight: 600; }
  td:first-child { white-space: nowrap; font-family: ui-monospace, Menlo, monospace; font-size: 13px; }
  ol.steps { padding-left: 20px; }
  ol.steps li { margin: 8px 0; }
  .badges { margin: 10px 0 0; display: flex; gap: 8px; flex-wrap: wrap; }
  .badge { border: 1px solid #2c313a; border-radius: 20px; padding: 3px 12px;
           font-size: 12px; color: #9aa; }
  .badge b { color: #ccc; font-weight: 600; }
</style>
</head>
<body>

<header>
  <h1>Reframe<span class="dot">.</span></h1>
  <p class="tagline">Face-aware image cropping for <b>Wikimedia Commons</b> — a URL you can use like a thumbnail.</p>
  <p class="hint">Give it a Commons file and a target window (landscape, square, portrait). It finds the face
    and crops so the eyes land where a portrait photographer would put them. The problem it solves:
    standard thumbnailing center-crops, and for photos of people that means a sliced-off forehead or a
    crop that lands on the chest. Reframe costs a few tens of milliseconds of CPU per request — no GPU,
    no ML serving stack, just a tiny face detector and some crop geometry.</p>
  <div class="badges">
    <span class="badge"><b>/crop</b> JPEG</span>
    <span class="badge"><b>/css</b> CSS recipe, no pixels</span>
    <span class="badge"><b>/compare</b> interactive</span>
    <span class="badge">~50&nbsp;ms CPU</span>
    <span class="badge">MIT</span>
    <span class="badge">Toolforge</span>
  </div>
</header>

<section class="card" id="demo">
  <h2>Try it</h2>
  <p class="hint">Type any Commons file name and drag the sliders. <b>Left:</b> what a naive center crop does
    to a person photo — the default framing below slices the top of the head clean off.
    <b>Right:</b> the Reframe crop, composed around the face with the eyes placed by the
    <b>eyeline</b> setting. Both panels render entirely client-side from the <code>/css</code>
    endpoint — no pixels served by us.</p>
  <div class="dinputs">
    <input type="text" id="d_file" value="File:African American man, full-length portrait, standing LCCN2006688033.jpg"
           placeholder="File:Name.jpg or Commons URL" spellcheck="false">
    <select id="d_aspect">
      <option value="16:9" selected>16:9</option><option value="3:2">3:2</option>
      <option value="4:3">4:3</option><option value="1:1">1:1</option>
      <option value="3:4">3:4</option><option value="2:3">2:3</option>
      <option value="9:16">9:16</option>
    </select>
  </div>
  <div class="drow">
    <label>Tightness <span class="tightval" id="d_tight_val">0.55</span>
      <input type="range" id="d_tight" min="0.30" max="0.90" step="0.05" value="0.55"></label>
    <label>Eyeline <span class="tightval" id="d_eyeline_val">0.39</span>
      <input type="range" id="d_eyeline" min="0.10" max="0.70" step="0.01" value="0.39"></label>
    <span class="gsub">tightness = zoom · eyeline = where the eyes sit in the frame</span>
  </div>
  <p id="d_status" class="hint">loading…</p>
  <div class="dpanes">
    <div class="pane">
      <div class="plabel naive">Naive center crop — what default thumbnailing gives you</div>
      <div id="d_naive_box" class="demobox naivebox"></div>
      <p class="gsub">for people photos the head usually gets cut, or the crop lands on the chest</p>
    </div>
    <div class="pane">
      <div class="plabel smart">Reframe — face-aware smart crop</div>
      <div id="d_css_box" class="demobox smartbox"></div>
      <p class="gsub">the same window, composed around the face</p>
    </div>
  </div>
  <p class="hint">Crop URL: <span class="apilink"><a id="d_crop_url" href="#"></a></span></p>
  <p class="hint">CSS&nbsp; URL: <span class="apilink"><a id="d_css_url" href="#"></a></span></p>
  <noscript><p class="err">The demo needs JavaScript — the API endpoints below work fine without it.</p></noscript>
</section>

<section>
  <h2>Endpoints</h2>
  <div class="row">
    <div class="card">
      <h3><code>/crop</code> — cropped JPEG</h3>
      <p>The thumbnail endpoint: use this URL anywhere an image is expected — <code>&lt;img&gt;</code>,
        wiki embeds, CSS backgrounds. Aspect-only or exact pixel size; square by default.</p>
      <p class="apilink"><a href="/crop?file=File:Khagdaev_02.jpg&amp;width=300&amp;height=200">
        /crop?file=File:Khagdaev_02.jpg&amp;width=300&amp;height=200</a></p>
      <p class="hint">Deterministic output → <code>Cache-Control: public, max-age=604800, immutable</code>,
        plus an <code>X-SmartCrop-Face: yes|no</code> header so callers know what happened.</p>
    </div>
    <div class="card">
      <h3><code>/css</code> — the recipe, not the pixels</h3>
      <p>Same pipeline, but the response is JSON: <code>object-position</code> plus the exact
        <code>background-size</code> zoom recipe — size-invariant, so it works for any thumbnail
        size. The client loads the image itself and reframes it in-browser.</p>
      <p class="apilink"><a href="/css?file=File:Khagdaev_02.jpg&amp;aspect=1:1&amp;tightness=0.85">
        /css?file=File:Khagdaev_02.jpg&amp;aspect=1:1&amp;tightness=0.85</a></p>
      <p class="hint">The demo above runs entirely on this endpoint.</p>
    </div>
    <div class="card">
      <h3><code>/compare</code> — side by side</h3>
      <p>Interactive tool: face box vs. smart crop vs. naive center-crop on any Commons file,
        with aspect, tightness, eyeline and gravity controls — and ready-made API URLs for the
        framing you settle on.</p>
      <p><a href="/compare"><button type="button">Open the compare tool</button></a></p>
    </div>
  </div>
</section>

<section>
  <h2>Parameters</h2>
  <table>
    <tr><th>param</th><th>required</th><th>meaning</th></tr>
    <tr><td>file</td><td>yes</td><td>Commons file: <code>File:Name.jpg</code>, <code>Name_02.jpg</code>, or a full commons.wikimedia.org URL</td></tr>
    <tr><td>width / height</td><td>either</td><td>exact output size in px — crop to that aspect, then scale</td></tr>
    <tr><td>aspect</td><td>either</td><td>target ratio instead of a size: <code>16:9</code>, <code>1:1</code>, <code>9:16</code> …</td></tr>
    <tr><td>gravity</td><td>no</td><td><code>face</code> (default) · <code>center</code> (naive) · <code>auto</code> (face if found, else center)</td></tr>
    <tr><td>tightness</td><td>no</td><td>how much of the crop height the head fills, <code>0</code> loose – <code>1</code> headshot; default <code>0.55</code>. Zooms around the eye line</td></tr>
    <tr><td>eyeline</td><td>no</td><td>where the eyes sit in the frame, fraction from the top; default <code>0.39</code>, <code>0.30</code> = classic portrait</td></tr>
  </table>
  <p class="hint">Errors are plain text with honest status codes: <code>400</code> bad param · <code>404</code> not on Commons ·
    <code>502</code> fetch failed · <code>415</code> not an image.</p>
</section>

<section>
  <h2>How it works</h2>
  <ol class="steps">
    <li><b>Fetch</b> — resolves the file via <code>Special:FilePath?width=1200</code>, so Commons does format
      conversion for free (SVG→PNG, PDF→JPEG, video keyframe) and we get a bounded raster. Fetches are
      disk-cached by title (7 days; 404s for 10 minutes).</li>
    <li><b>Detect</b> — YuNet ONNX face detector (~230 KB, ~1.6 ms CPU); largest face wins in group shots.
      No face → clean center-crop fallback.</li>
    <li><b>Crop</b> — expands the face box to a head region (hair, neck, shoulders), places the eye line at
      <code>eyeline</code> of the frame height, and sizes the crop so the head fills <code>tightness</code>
      of it. Tightness zooms <em>around</em> the eye line, so the composition holds at any zoom.</li>
    <li><b>Serve</b> — the crop as JPEG (<code>/crop</code>), or as the equivalent CSS recipe
      (<code>/css</code>, verified pixel-identical in a real browser).</li>
  </ol>
</section>

<section>
  <h2>Embed it</h2>
  <p class="hint">The classic case — a face-aware thumbnail in an <code>&lt;img&gt;</code>:</p>
  <pre>&lt;img src="https://reframe.toolforge.org/crop?file=File:Khagdaev_02.jpg&amp;width=300&amp;height=200"
     alt="Khagdaev 02"&gt;</pre>
  <p>renders as:</p>
  <p><img src="/crop?file=File:Khagdaev_02.jpg&amp;width=300&amp;height=200"
          alt="face-aware crop example" style="border-radius:6px;border:1px solid #2c313a"></p>
  <p class="hint">Or skip the proxy entirely — reframe any box of the target aspect client-side
    (<code>/css</code> returns the exact values):</p>
  <pre>&lt;div style="width: 300px; height: 300px;
            background: url('https://commons.wikimedia.org/wiki/Special:FilePath/File:Khagdaev_02.jpg?width=1200') no-repeat;
            background-size: 364.7% 273.5%;
            background-position: 28.8% 21.3%;"&gt;&lt;/div&gt;</pre>
</section>

<footer class="meta">
  <p>Reframe · MIT license · <a href="https://github.com/fuzheado/reframe">source on GitHub</a> ·
     face detection via <a href="https://github.com/opencv/opencv_zoo">YuNet</a> (Apache-2.0) ·
     runs on <a href="https://wikitech.wikimedia.org/wiki/Portal:Toolforge">Wikimedia Toolforge</a> ·
     built by Andrew Lih (<a href="https://en.wikipedia.org/wiki/User:Fuzheado">User:Fuzheado</a>)</p>
</footer>

<script>
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var smartBox = $("d_css_box");
  var naiveBox = $("d_naive_box");

  function debounce(fn, ms) {
    var t;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }

  function applyRecipe(box, d, aspect) {
    box.style.aspectRatio = aspect.replace(":", " / ");
    box.style.backgroundImage = "url('" + d.source.url + "')";
    var m = d.css_exact.match(/background-size: ([^;]+); background-position: ([^;]+);/);
    if (m) { box.style.backgroundSize = m[1]; box.style.backgroundPosition = m[2]; }
  }

  async function refresh() {
    var file = $("d_file").value.trim();
    var aspect = $("d_aspect").value;
    var tightness = $("d_tight").value;
    var eyeline = $("d_eyeline").value;
    $("d_tight_val").textContent = tightness;
    $("d_eyeline_val").textContent = eyeline;
    var status = $("d_status");
    status.className = "hint";
    if (!file) { status.textContent = "enter a Commons file name to preview"; return; }
    var q = "file=" + encodeURIComponent(file) +
            "&aspect=" + aspect +
            "&tightness=" + tightness + "&eyeline=" + eyeline;
    var smartUrl = "/css?" + q + "&gravity=face";
    var naiveUrl = "/css?" + q + "&gravity=center";
    var cropUrl = "/crop?" + q + "&gravity=face";
    $("d_crop_url").href = cropUrl;
    $("d_crop_url").textContent = cropUrl;
    $("d_css_url").href = smartUrl;
    $("d_css_url").textContent = smartUrl;
    status.textContent = "…";
    try {
      var sr = await fetch(smartUrl);
      var nr = await fetch(naiveUrl);
      if (!sr.ok) {
        status.className = "err";
        status.textContent = "error " + sr.status + ": " + (await sr.text());
        return;
      }
      if (!nr.ok) {
        status.className = "err";
        status.textContent = "error " + nr.status + ": " + (await nr.text());
        return;
      }
      var smart = await sr.json();
      var naive = await nr.json();
      applyRecipe(smartBox, smart, aspect);
      applyRecipe(naiveBox, naive, aspect);
      status.className = "ok";
      if (!smart.face_detected) {
        status.textContent = "no face detected — the smart crop falls back to the same center crop (" +
          "source " + smart.source.width + "×" + smart.source.height + ")";
      } else {
        status.textContent = "face detected: yes · source " + smart.source.width + "×" +
          smart.source.height + " · tightness " + tightness + " · eyeline " + eyeline;
      }
    } catch (e) {
      status.className = "err";
      status.textContent = "request failed: " + e;
    }
  }

  var r = debounce(refresh, 350);
  $("d_file").addEventListener("input", r);
  $("d_aspect").addEventListener("change", r);
  $("d_tight").addEventListener("input", r);
  $("d_eyeline").addEventListener("input", r);
  refresh();
})();
</script>
</body>
</html>
"""
