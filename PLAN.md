# PLAN

Approved by Hakob on 2026-11-07. This file is the single source of truth. It changes
only with Hakob's knowledge (CLAUDE.md rule 2).

Article-to-video pipeline: one article file in, one command, a 1920x1080 MP4 with an
English AI voiceover, plus script and fact sheet out. Article-01 (a self-ranking
guide to AI SEO companies) is only the test input. Nothing in code or templates is
specific to one article, URL or publisher.

## 0. How it works

```
python -m pipeline run source/article-XX.md [--review] [--from <stage>]
```

Stages, in order:

| # | Stage | What it does | Writes |
|---|---|---|---|
| 1 | `sentences` | Splits the article into numbered sentences and table rows (code, no LLM) | `scenes/article-XX.sentences.json` |
| 2 | `scenes` | The LLM writes the scenes JSON and cites sentences **by number**; code copies the cited text in verbatim | `scenes/article-XX.scenes.json` |
| 3 | `verify` | Plain-code checker (section 4). On failure the errors go back to the LLM, up to `llm.max_retries` times, then the run stops with the report | `output/article-XX/verify-report.json` |
| 4 | `docs` | Script and fact sheet, without timecodes | `output/article-XX/script.md`, `factsheet.md`, `factsheet.csv` |
| - | review gate | With `--review`, the run stops here (exit code 0, message "review, then run --from tts") | |
| 5 | `tts` | Applies the lexicon to make the spoken text, one audio clip per scene, measures lengths. Stops with a clear message if the total is outside `video.target_seconds` | `audio/article-XX/scene-NN.wav`, `audio/article-XX/timing.json` |
| 6 | `docs` (again) | Same outputs, now with timecodes from `timing.json` | same as stage 4 |
| 7 | `render` | Remotion renders video with each scene's audio inside its own Sequence | `render/out/article-XX.mp4` |
| 8 | `mux` | FFmpeg adds the ducked music bed and copies the video stream | `output/article-XX/article-XX.mp4` |
| 9 | `check` | ffprobe and sync checks on the final file (section 4) | appended to `verify-report.json` |

There is **no automatic skipping** based on file dates. `run` without `--from` runs
every stage. `--from <stage>` runs that stage and everything after it, and refuses to
start if a file it needs is missing. `python -m pipeline doctor` checks Python, Node,
FFmpeg, the Kokoro model, the spaCy model, the LLM key and the folder layout.

Exit codes: 0 success (or stopped cleanly at the review gate), 1 checker or length
failure, 2 missing setup or input, 3 provider unavailable after retries.

## 1. Task breakdown (one thread per task)

| # | Task | Goal | Inputs | Outputs | Done check |
|---|---|---|---|---|---|
| T1 | Skeleton | Folders, Python package, CLI with stage stubs, `--from`, `doctor`, config, `.env` loading, license log, brief conversion, front matter for article-01 | PLAN.md, brief.docx, article-01.md | `pipeline/` package, `pipeline/config.yaml`, `requirements.txt`, `.env.example`, `.gitignore` entries, `docs/licenses.md`, `docs/brief.md`, front matter added to `source/article-01.md` | `python -m pipeline --help` lists every stage; `--from` validates stage names; `doctor` reports each item; a script confirms `docs/brief.md` matches the .docx text word for word; article-01 body unchanged below the front matter (checksum of the body) |
| T2 | Splitter, schema, checker, fact sheet, script | `sentences`, `verify`, `docs` stages. No LLM | Sections 3-4, article-01, Gemini prototype | `pipeline/sentences.py`, `pipeline/schema/scenes.schema.json`, `pipeline/verify.py`, `pipeline/docs.py`, `tests/` with fixtures | Tests pass. The good fixture passes. Bad fixtures each fail with a clear message: changed word, changed number, ordinal matched to a count, label paired with the wrong value, missing attribution, missing disclosure, number in a no-claim element, wrong length. Every splitter entry is found verbatim in the article |
| T3 | Scene generation | `scenes` stage with Gemini and Anthropic adapters, streaming, fallback models, checker retry loop | T2, prototype in `/mnt/project-files/plan/gemini-test/` | `pipeline/llm.py`, `pipeline/scenes.py`, `pipeline/prompts/scenes.md`, `scenes/article-01.scenes.json` | article-01 scenes pass `verify` with no manual edits; switching to Haiku is a config change (adapter unit-tested with a recorded response if no Anthropic key) |
| T4 | Voiceover | `tts` stage with Kokoro, regex lexicon, spoken vs. checked text, length stop | Scenes fixture | `pipeline/tts.py`, `pipeline/lexicon.yaml`, `audio/article-XX/*` | US female voice; lexicon unit tests (GBP 1,500, 48/50, #1, $8,000, GEO, AEO, CRO); a too-long fixture stops with the length message; espeak-ng question answered on Windows (section 2) |
| T5a | Render frame and text scenes | Remotion project, composition from JSON + timing, audio per Sequence, `card`, `bullets`, `quote`, auto-fit text, source tag | Scenes + timing fixtures | `render/` project, `pipeline/render.py` | Fixture renders at 1920x1080, 30 fps; long-text fixture fits without overflow; source tag shows on publisher scenes; composition length equals `timing.json` total |
| T5b | Render data scenes | `big_number`, `bar_chart`, `price_cards` with motion | T5a | added components | Fixture with every visual type renders; every number on screen comes from the JSON |
| T6 | Music and mux | Pick and log the music track, FFmpeg music bed, final checks | Rendered video, music file | `pipeline/mux.py`, `assets/music/` + saved license page, `output/article-XX/article-XX.mp4` | `check` stage passes (section 4); track name, URL and CC0 proof logged |
| T7 | End to end | Wire all stages; run article-01 in the cloud, then the final run on the laptop | T1-T6 | `pipeline/__main__.py` complete, `docs/workflow.md`, run log | One command produces every article-01 output; `--review` then `--from tts` works; a grep test fails if a publisher name or article id appears in `pipeline/` or `render/` code |
| T8 | n8n wrapper | 6-node workflow with the review gate (section 2) | Working CLI on the laptop | `pipeline/n8n/article-to-video.workflow.json`, n8n section of `docs/workflow.md` | Imported into a fresh n8n on the laptop and run on article-01: the same set of output files as the CLI, and `verify` passes. A forced failure (bad article path) stops the workflow at the error branch |
| T9 | Reuse test and deliverables | Second article (Hakob picks), next-ten note, walkthrough outline, zip | Everything | `docs/next-ten-videos.md`, `docs/walkthrough-outline.md`, `output/deliverables.zip` | Second article runs with no code change; every brief item maps to a file (section 6); zip contents match the list Hakob approves |

Order: T1 first. Then T2, T4 and T5a in any order (they use fixtures). T3 after T2.
T5b after T5a. T6 after T4 and T5b. T7 after T1-T6. T8 after T7. T9 last.

Where each task is built and tested is in STATUS.md.

## 2. Tools per step

**Scene generation (LLM): Gemini free tier by default, Claude Haiku 5.5 as the paid
fallback.** Tested on article-01 (section 8).

```yaml
llm:
  provider: gemini                 # gemini | anthropic
  model: gemini-3.6-flash
  fallback_models: [gemini-3.5-flash, gemini-flash-lite-latest]   # tried in order on 429/5xx
  api_key_env: GEMINI_API_KEY      # anthropic: ANTHROPIC_API_KEY, model claude-haiku-5-5
  stream: true                     # long non-streamed calls were cut at 30 s in the cloud
  max_retries: 3                   # checker retries, separate from HTTP retries
```

Gemini is called with Python's standard library (REST, streaming); Anthropic with its
official SDK. Never Claude Code headless (`claude -p`).

**API keys.** Read from the environment variable named in `api_key_env`. On the laptop
it comes from `.env` in the project folder, loaded by a few lines of our own code.
`.env` is git-ignored and never shared; `.env.example` with empty values is committed.
If the variable is empty, the request goes out without a key header (the cloud setup,
where the network adds the key). Keys are never logged; errors show only the HTTP
status and the API's message.

**TTS: Kokoro-82M (kokoro 0.9.4), local, Apache-2.0.** American English, female voice
`af_heart`.

```yaml
tts:
  provider: kokoro      # adapters for others can be added later
  voice: af_heart       # US English female; af_bella is the alternative
  lang_code: a          # American English
  speed: 1.0
```

- Kokoro needs Python 3.10-3.12 (its own requirement).
- **espeak-ng:** Kokoro's text front end (misaki[en]) installs `espeakng-loader`, a
  wheel that bundles the espeak-ng library, including for Windows. So a separate
  espeak-ng install is probably not needed. T4 confirms this on Windows by running with
  no system espeak-ng, and the setup steps keep it only if needed.
- misaki downloads the spaCy model `en_core_web_sm` from GitHub on first use; `doctor`
  checks for it.
- kokoro-onnx is evaluated only if kokoro + torch fails on Windows, and only after
  Hakob approves adding it.

**Lexicon (spoken text).** The voiceover text that the checker verifies is never
changed. The `tts` stage makes a separate spoken text by applying ordered regex rules
from `pipeline/lexicon.yaml`, for example:

```yaml
rules:
  - {pattern: 'GBP ([\d,]+)', replace: '\1 pounds'}
  - {pattern: '\$([\d,]+)', replace: '\1 dollars'}
  - {pattern: '\b(\d+)/(\d+)\b', replace: '\1 out of \2'}
  - {pattern: '#(\d+)\b', replace: 'number \1'}
  - {pattern: '\bAEO\b', replace: 'A E O'}
  - {pattern: '\bGEO\b', replace: 'G E O'}
  - {pattern: '\bCRO\b', replace: 'C R O'}
```

The exact spoken forms are tuned by ear in T4. Both texts are stored in the scenes
JSON (`text` and `spoken`) and both appear in the fact sheet and script where they
differ.

**Rendering: Remotion 4 (React), with MoviePy as the documented fallback.**
- License, checked 2026-11-07 on Remotion's LICENSE.md and license FAQ: free for
  individuals, for-profit organizations with up to 3 employees, non-profits, and
  evaluation. Larger companies need a Company License (from $25 per month per person
  writing Remotion code, or $0.01 per render with a $100 monthly minimum for
  automation). Headcount counts the whole company, plus contractors who operate the
  project. Logged in DECISIONS.md and repeated in `docs/next-ten-videos.md`.
- Remotion downloads its own headless Chrome on first render.
- Each scene's audio is an `<Audio>` inside that scene's `<Sequence>`, so picture and
  voice cannot drift apart.
- v1 visual types (6): `card` (variants `title`, `disclosure`, `outro`),
  `big_number` (count-up), `bar_chart` (animated bars from an article table),
  `price_cards`, `bullets` (appear one by one), `quote`.
- Long text auto-fits: the font size shrinks to fit the box down to a minimum, then
  wraps (`@remotion/layout-utils`). Below the minimum, render fails with the scene
  number instead of overflowing.
- On every scene with `claim_owner: publisher`, a fixed tag renders on screen from
  config, never from the LLM: `source_tag: "Source: {publisher}"`. For
  `company:<name>` scenes: `"Source: {company}, via {publisher}"`.

**Music: one CC0 track, picked in T6.** T6 names the exact track and its URL, checks
the CC0 statement on the track's own page (not the site in general), and saves that
page to `assets/music/LICENSE-<track>.html` (or `.pdf`). If the cloud cannot download
it, Hakob downloads it into `assets/music/`. FFmpeg mixes it under the voice (about
-20 dB, `music.duck_db` in config).

**Fonts: Inter (SIL Open Font License)**, from the `@fontsource/inter` npm package,
loaded locally by the render project.

**Icons: Lucide (ISC license)**, from `lucide-react`. Generic symbols only; an icon
never stands for a claim the article does not make.

**Orchestration: the Python CLI is the engine; n8n (self-hosted) is a thin wrapper.**
Workflow, at most 6 nodes, no logic beyond calling the CLI:

1. Form trigger: article path (for example `source/article-02.md`).
2. Execute Command: `cd /d "%A2V_PROJECT_DIR%" && .venv\Scripts\python -m pipeline run "<path>" --review`
3. Wait node ("on form submitted"): an approval form; the reviewer reads the fact
   sheet, then approves.
4. Execute Command: `cd /d "%A2V_PROJECT_DIR%" && .venv\Scripts\python -m pipeline run "<path>" --from tts`
5. Stop and Error: reached from the error output of node 2 or 4 (non-zero exit code).
6. (Optional) a final Execute Command that prints the output file list.

Windows notes: the Execute Command node runs through `cmd.exe`, so `cd /d` is used,
with the project folder from the environment variable `A2V_PROJECT_DIR` (set once with
`setx`), never hardcoded. n8n 2.x disables Execute Command by default; start n8n with
`NODES_EXCLUDE=[]`. T8 tests how the node reports a non-zero exit code and wires the
error output accordingly.

**Versions pinned:** Python 3.12, Node 24 (n8n 2.46.6, the current release, requires
Node >= 24; Remotion supports it), FFmpeg (current Windows build), n8n 2.46.6.

## 3. Folder structure and data formats

```
source/       article-XX.md (front matter + article), optional raw .html
scenes/       article-XX.sentences.json, article-XX.scenes.json
audio/        article-XX/scene-NN.wav, timing.json
render/       Remotion project; render/out/ (silent intermediates, not shared)
output/       article-XX/article-XX.mp4, script.md, factsheet.md, factsheet.csv, verify-report.json
docs/         brief.md, licenses.md, workflow.md, next-ten-videos.md, walkthrough-outline.md
pipeline/     Python package, config.yaml, lexicon.yaml, prompts/, schema/, n8n/
assets/       fonts/, music/, icons/ (each with its license file)
tests/        unit tests and fixtures
brief.docx    original brief, unchanged
.env.example  committed; .env is local only
PLAN.md  STATUS.md  DECISIONS.md
```

**Article input.** One file per article with YAML front matter. `publisher` and
`promotional` are required and set by a person, never by the LLM; the run stops with a
clear message if either is missing.

```yaml
---
publisher: <name as written in the article>
promotional: true        # the publisher ranks or promotes itself
url: <optional>
---
<article markdown, unchanged>
```

**Sentences file** (code-made). One entry per sentence or table row:
`{"n": 12, "section": "...", "line": 11, "kind": "text", "text": "..."}`. Table rows
also keep `"cells": {"<header>": "<value>", ...}` so the checker can pair a label with
its value and tell rank columns from counts.

**Scenes JSON.** Every fact-bearing element carries its own `source_ids`, so the fact
sheet can have one row per claim.

```json
{
  "article": {"id": "article-01", "title": "...", "publisher": "<from front matter>", "promotional": true},
  "scenes": [
    {
      "id": 2,
      "claim_owner": "publisher",
      "visual": {
        "type": "bar_chart",
        "icon": "bar-chart-3",
        "items": [
          {"label": "<company A>", "value": "48", "source_ids": [14]},
          {"label": "<company B>", "value": "44", "source_ids": [15]}
        ]
      },
      "on_screen": [
        {"role": "headline", "text": "Scores out of 50", "source_ids": [12]}
      ],
      "voiceover": [
        {"text": "According to <publisher>, each company was scored out of 50.", "source_ids": [12],
         "spoken": null}
      ],
      "duration_s": null
    }
  ]
}
```

Field rules:
- `voiceover`: a list of lines; each line is one claim with its own `source_ids`.
  `spoken` is filled by the `tts` stage from the lexicon.
- `on_screen`: headline, sub and bullet texts, each with `source_ids` (empty for text
  that makes no claim; such text may not contain numbers).
- `visual.items`: chart bars, price cards, big numbers; each `label` + `value` pair has
  its own `source_ids`.
- `claim_owner`: `publisher`, `company:<name>`, or `none`.
- `source_sentence` is not stored by the LLM: the checker and fact sheet look up the
  text from `source_ids` in the sentences file.
- The source tag on screen comes from config (section 2), not from this file.
- List items are not numbered by the LLM; the renderer numbers them where needed.

## 4. Fact sheet, script and verification

**Fact sheet** (`docs` stage, no LLM): **one row per claim**. A claim is each
voiceover line, each on-screen text with `source_ids`, and each visual item (every bar
value, price and label pair). Columns: scene, timecode (after TTS), element (voiceover,
headline, bar, price card...), text shown or spoken, spoken form (if different),
attributed to, sentence number(s), the cited sentence(s) verbatim, section, line.
Review warnings are listed at the top. Output: `factsheet.md` and `factsheet.csv`.

**Script** (`output/article-XX/script.md`): per scene, the scene number, timecode,
voiceover lines, on-screen text, and the spoken form wherever it differs from the text.

**Checker** (`verify` stage, plain Python). Normalisation for comparing text: curly
quotes and apostrophes to straight, non-breaking spaces to spaces, whitespace runs to
one space, Markdown markup removed, front matter removed.

Hard checks (fail the run):
1. **Schema**: JSON Schema validation; every `source_ids` number exists.
2. **Verbatim**: the text of every cited sentence is found in the normalised article
   (true by construction; the check guards against hand edits).
3. **Counts**: every cardinal number in a claim (digits like `$3,000`, `8.9%`,
   `68,631`, `48/50`, years; words like `nine`, `twenty`) appears in that claim's
   cited sentences, after removing thousands separators and units. No rounding.
4. **Ordinals, separately**: ordinals (`first`, `1st`, `#1`, `No. 1`, "ranked 1")
   must match an ordinal in the cited sentences: an ordinal word, a `(1)`-style list
   marker, or a value in a table column whose header means rank or position. An
   ordinal never matches a plain count, so "ranked first" cannot be supported by "1
   minimum".
5. **Label-value pairing**: for each visual item, the label and the value both appear
   in the same cited sentence or the same table row (for tables, in that row's cells).
6. **No-claim text**: on-screen text with empty `source_ids` contains no numbers.
7. **Attribution** (when the front matter says `promotional: true`): scene 1 is a
   `card` of variant `disclosure` that names the publisher and says both that it
   publishes the piece and that it ranks itself; every other `publisher` scene has an
   attribution phrase in its voiceover ("according to {publisher}", "{publisher}
   says", "{publisher} reports", "{publisher}'s guide", ...); `company:<name>` scenes
   name that company in the voiceover. Phrases live in config.
8. **Length before TTS**: total voiceover words inside the range from
   `video.target_seconds` and `speech.words_per_minute`.

Review warnings (listed, do not fail): inference words ("that means", "which means",
"so", "therefore"); judging words not in the cited sentences ("transparent",
"verified", "trusted", "leading"); all citations from fewer than 3 sections.

**After TTS**: if the total audio length is outside `video.target_seconds`, the run
stops: "Voiceover is 94.2 s; the target is 60-90 s. Shorten the scenes and run
`--from scenes`, or change video.target_seconds."

**Final checks** (`check` stage):
- ffprobe: 1920x1080, H.264 video, AAC audio, `fps` from config, duration inside the
  target range.
- **"In sync" means**: (a) the Remotion composition length in frames equals the sum of
  the scene lengths in `timing.json` (unit test); (b) in the final file, the video and
  audio stream durations differ by at most one frame (33 ms at 30 fps); (c) FFmpeg
  `silencedetect` on the final voice track finds each scene's speech starting within
  100 ms of that scene's start time in `timing.json`.

What no check catches: a real sentence used for a claim it does not make, or a dull
script. The human review of the fact sheet (`--review`) is required for every video.

## 5. Reusability and configuration

- New article: add `source/article-02.md` with front matter, then
  `python -m pipeline run source/article-02.md --review`, read the fact sheet, then
  `--from tts`. Or start the n8n workflow with the path.
- The article id comes from the file name; every output path derives from it.
- Everything else is in `pipeline/config.yaml`:

```yaml
video: {target_seconds: [60, 90], width: 1920, height: 1080, fps: 30}
render: {concurrency: 1}           # 8 GB laptop; raise on bigger machines
speech: {words_per_minute: 150}     # measured from Kokoro in T4
llm: {...}                          # section 2
tts: {...}                          # section 2
music: {file: assets/music/<track>, duck_db: -20}
source_tag: {publisher: "Source: {publisher}", company: "Source: {company}, via {publisher}"}
attribution_phrases: [...]
disclosure_words: {publish: [...], rank: [...]}
review_warnings: {inference_words: [...], judging_words: [...], min_sections: 3}
```

- The default length is 60-90 s; the brief sets none. The reasoning is in
  DECISIONS.md. The word budget is computed from it (150-225 words at 150 wpm).
- The LLM prompt is a template with no article content; its example is made up.

## 6. Deliverable mapping

| Brief item | Produced by | File |
|---|---|---|
| 1. The MP4 | T6, final run in T7 | `output/article-01/article-01.mp4` |
| 2. The script | T2 generator, content from T3, timecodes from T4 | `output/article-01/script.md` |
| 3. Fact sheet | T2 generator, final run in T7 | `output/article-01/factsheet.md` (+ `.csv`, `verify-report.json`) |
| 4. Decision log | Every thread | `DECISIONS.md`, `docs/licenses.md` |
| 5. Next ten videos note | T9 | `docs/next-ten-videos.md` |
| 6. Project files + workflow export | T7, T8, T9 | the project files, `pipeline/n8n/article-to-video.workflow.json`, `docs/workflow.md`, `output/deliverables.zip` |
| 7. Walkthrough recording | **Hakob** | outline below, saved as `docs/walkthrough-outline.md` in T9 |

**`docs/next-ten-videos.md` must cover:** time per video (human and machine), cost
(Gemini free tier vs. Haiku 5.5), running a batch, the review step, how consistent
quality is kept, how articles get in (today: hand extraction; later: the ingest
option), and the Remotion license point (a larger team may need a paid license;
MoviePy is the documented fallback).

**Deliverables zip** (decided in T9 with Hakob). Always excluded: the brief (both
files), raw HTML, `.env`, `.venv`, `node_modules`, Kokoro model weights, `render/out`,
caches. T9 asks Hakob whether `source/article-XX.md` goes in. No document in the zip
contains Hakob's local folder path.

**Walkthrough outline (about 5 minutes)**
1. The brief and the three rules: facts only from the article, attribution for
   self-ranking pieces, one command per article (30 s).
2. Folder tour: article with front matter, sentences file, scenes JSON, outputs (30 s).
3. A recorded n8n run on article-01: review pause, approval, then the rest (45 s).
4. The fact sheet: one bar value next to its cited table row (45 s).
5. Break it on purpose: change one number in the scenes JSON, run `verify`, show the
   failure; undo it (30 s).
6. Play the video (60-90 s).
7. The second article running with no code change (30 s).
8. Decision log, license log, next-ten-videos note (30 s).

## 7. Where it runs

**Native Windows** on Hakob's laptop for the final runs, with WSL2 as the fallback if
Kokoro fails on Windows. Building and unit tests happen in the cloud container. Which
task is built and tested where is in STATUS.md.

Laptop-only steps (Kokoro, Remotion and n8n on Windows) run in a **Remote Control
session** started from that task's thread: it runs commands on the laptop with
Hakob's approval, so Hakob does not have to copy commands by hand. Fallback: the thread
posts exact PowerShell commands and Hakob pastes back the output. The laptop sandbox
that Claude's folder tools use has no network and cannot run these.

Setup (PowerShell, once; T1 writes it into `docs/workflow.md`):
1. `winget install Python.Python.3.12 Gyan.FFmpeg Git.Git`, and Node 24 (installer
   from nodejs.org, or `winget install OpenJS.NodeJS --version <24.x>`); `doctor`
   checks Node's major version is 24.
2. In the project folder: `py -3.12 -m venv .venv`, `.venv\Scripts\activate`,
   `pip install -r requirements.txt`.
3. `cd render` then `npm install` (after T5a).
4. Copy `.env.example` to `.env` and add the Gemini key (and the Anthropic key if used).
5. `setx A2V_PROJECT_DIR "<project folder>"` (for n8n).
6. `python -m pipeline doctor` reports everything green.
7. For n8n (T8): `npm install -g n8n@2.46.6`, then `$env:NODES_EXCLUDE="[]"; n8n start`,
   open http://localhost:5678, import the workflow JSON.
8. Only if T4 finds it is needed: install espeak-ng from its official Windows installer.

**Cloud hosts to allow before T4 and T5a** (Hakob adds them in one go):

| Host | Needed for |
|---|---|
| `huggingface.co` | Kokoro model and voice files (hexgrad/Kokoro-82M) |
| `cdn-lfs.huggingface.co`, `cdn-lfs.hf.co`, `cas-bridge.xethub.hf.co` | Hugging Face file downloads (the big files are served from these) |
| `github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com` | spaCy model `en_core_web_sm` (GitHub release download) |
| `download.pytorch.org` | CPU-only torch wheel on Linux (the default PyPI wheel pulls about 2 GB of GPU libraries) |
| `remotion.media`, `storage.googleapis.com` | Remotion's headless Chrome download (in the cloud it can also use the preinstalled Chromium) |
| `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org` | Python and npm packages (already reachable) |
| the music site | named in T6; not needed if Hakob downloads the track |

T4 and T5a re-check this list against the real redirects at the start and report any
missing host before doing anything else.

## 8. Dependencies (approving this file approves exactly this list)

Anything not listed needs Hakob's approval first (CLAUDE.md rule 7).

**System:** Python 3.12, Node 24, FFmpeg, Git. espeak-ng only if T4 shows it is needed.

**Python (`requirements.txt`)**

| Package | Why | License |
|---|---|---|
| `kokoro==0.9.4` | TTS. Brings its own requirements: `misaki[en]` (with `espeakng-loader`, `phonemizer-fork`, `num2words`, `spacy`, `spacy-curated-transformers`), `torch`, `transformers`, `huggingface-hub`, `numpy`, `loguru` | Apache-2.0 (kokoro, misaki) |
| spaCy model `en_core_web_sm` | Needed by misaki; downloaded on first use | MIT |
| `soundfile` | Write WAV files | BSD-3-Clause |
| `PyYAML` | Read `config.yaml`, `lexicon.yaml`, front matter | MIT |
| `jsonschema` | Validate the scenes JSON | MIT |
| `anthropic` | Haiku 5.5 fallback adapter | MIT |
| `pytest` (dev) | Tests | MIT |

Not used on purpose: no Gemini SDK (standard-library HTTP), no `python-dotenv` (own
`.env` loader), no `python-docx` (the brief is converted with the standard library),
no MoviePy (documented fallback only).

**npm (`render/package.json`)**

| Package | Why | License |
|---|---|---|
| `remotion`, `@remotion/cli` (4.x, pinned in T5a) | Rendering | Remotion License (section 2) |
| `@remotion/layout-utils` | Auto-fit text | Remotion License |
| `react`, `react-dom` | Remotion templates | MIT |
| `typescript`, `@types/react` (dev) | Type checking | Apache-2.0, MIT |
| `@fontsource/inter` | Inter font files | OFL-1.1 (font), MIT (package) |
| `lucide-react` | Icons | ISC |

**Global:** `n8n@2.46.6` (Sustainable Use License, free for internal use; T8 logs the
terms).

## 9. Gemini test (2026-11-07)

A throwaway prototype (kept in `/mnt/project-files/plan/gemini-test/`) split article-01
into 409 numbered entries (all found verbatim), sent them to Gemini, let code fill the
sentences from the cited numbers, and ran the checker with retries.

| Run | Model | Result | Attempts | Time per attempt |
|---|---|---|---|---|
| 1-3 | gemini-3.5-flash-lite | PASS, all three | 2, 3, 2 | about 5 s |
| 4 | gemini-3.6-flash (streamed) | PASS | 2 | 25-32 s |

Flash-Lite used only the article's first 11 sentences each time; Flash covered the
whole article. A human read of run 4 found two small drifts the checker missed (an
inferred "That means" link, and "on this page" turned into "on the company's own
website"). Errors seen: 404 for `gemini-2.5-flash` (retired for new users), 503 "high
demand" on gemini-3.8/3.7-flash and gemini-flash-latest, and 502 "upstream request
failed" at exactly 30 s on long non-streamed calls in the cloud (fixed by streaming).

## 10. Risks

- **Paraphrase drift**: mitigated by sentence numbers, per-claim citations, the
  checker, review warnings and the required human review.
- **Free-tier capacity and model churn**: fallback models in config, then Haiku 5.5.
- **Self-ranking article**: disclosure card first, attribution in every publisher
  claim, the source tag on screen for muted viewers.
- **One fact stated two ways** in article-01 ("8.9%" and "91%"): the video quotes one
  exactly and never derives one from the other.
- **Pronunciation**: lexicon rules, tuned by ear in T4.
- **Slow laptop** (2-core i3, no GPU, 8 GB RAM with about 1 GB free in normal use):
  renders and TTS take minutes. T4 and T5a measure time and peak memory; Remotion
  renders with `render.concurrency: 1` by default; heavy runs start with other apps
  closed.
- **Cloud network**: hosts in section 7 must be added before T4 and T5a.
- **Remotion license**: free for Hakob now; a larger team may need a paid license.

## 11. Later options (not part of this plan)

- An ingest task: URL to raw HTML to clean Markdown, checked word for word against the
  page text (today article-01 was extracted by hand).
- Switching the renderer away from Remotion (MoviePy is the documented fallback).
- A second LLM pass that checks whether each cited sentence supports its claim.
