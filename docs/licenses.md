# Licenses

Every font, icon set, music track and package the pipeline ships with or installs,
with its license and where the license was checked. Each task fills in its rows when
it adds the item (project rule: check and log licenses). "Planned" rows come from
PLAN.md section 8 and are confirmed when the item is installed.

Status values: **planned** (approved, not installed yet), **checked** (license read
at the source on the date given), **not re-checked** (could not be read at the source
from the build machine; the reason is in the row), **removed**.

## Fonts

| Item | Version | License | Where it is used | Source checked | Date | Status |
|---|---|---|---|---|---|---|
| Inter (via `@fontsource/inter`) | 5.2.8 | OFL-1.1 (package metadata says OFL-1.1 for the font files it ships) | All on-screen text, weights 400-700 | installed package metadata and LICENSE | 2026-11-07 | checked |

## Icons

| Item | Version | License | Where it is used | Source checked | Date | Status |
|---|---|---|---|---|---|---|
| Lucide (via `lucide-react`) | 1.52.0 | ISC | Generic scene icons; never stands for a claim | installed package metadata | 2026-11-07 | checked |

## Music

| Track | Artist | License | Track page (URL) | Saved license page | Date | Status |
|---|---|---|---|---|---|---|
| Contemplation (`assets/music/contemplation.mp3`: MP3, 120.06 s, 44.1 kHz stereo, 2,405,271 bytes, SHA-256 283962d3a975c93613c46cda30c9f0816176ae3e2899f961591a49e2d41b4bf3) | Joth | CC0 1.0 (the track page's License(s) field lists CC0 only, linked to creativecommons.org/publicdomain/zero/1.0/) | https://opengameart.org/content/contemplation-0 (file: https://opengameart.org/sites/default/files/Contemplation.mp3) | `assets/music/LICENSE-contemplation.html` (the page saved unchanged, 32,055 bytes) | 2026-11-07 | checked |

## Images

None. No stock photos and no company logos (DECISIONS.md).

## Python packages (`requirements.txt`)

| Package | Version | License | Why | Source checked | Date | Status |
|---|---|---|---|---|---|---|
| kokoro | 0.9.4 | Apache-2.0 | TTS (T4) | installed package metadata | 2026-11-07 | checked |
| Kokoro-82M model and voices (`hexgrad/Kokoro-82M` on Hugging Face) | v1.0 weights, voice `af_heart` | Apache-2.0 | The voice model; downloaded to the Hugging Face cache, never shipped | model card on huggingface.co | 2026-11-07 | checked |
| misaki[en] (with kokoro) | 0.9.4 | Apache-2.0 | Kokoro text front end | installed package metadata | 2026-11-07 | checked |
| torch (with kokoro) | 2.15.0 (CPU) | BSD-3-Clause style bundle (metadata: Apache-2.0, BSD-2/3-Clause, MIT and others for bundled parts) | Kokoro model runtime | installed package metadata | 2026-11-07 | checked |
| phonemizer-fork (with misaki) | 3.3.2 | GPL-3.0-or-later | Misaki's espeak fallback for unknown words | installed package metadata | 2026-11-07 | checked |
| espeakng-loader (with misaki) | 0.2.4 | not stated on PyPI; bundles the espeak-ng library, which is GPL-3.0 | Ships espeak-ng, so no system espeak-ng install is needed (Windows checked in T4) | PyPI page | 2026-11-07 | checked |
| num2words (with misaki) | 0.5.14 | LGPL-2.1 | Numbers to words | installed package metadata | 2026-11-07 | checked |
| spaCy (with misaki) | 3.8.18 | MIT | Misaki's tokenizer | installed package metadata | 2026-11-07 | checked |
| spaCy model `en_core_web_sm` | 3.8.0, installed by misaki on the first tts run | MIT | Needed by misaki | installed package metadata | 2026-11-07 | checked |
| soundfile | 0.14.0 | BSD-3-Clause | Write WAV files | installed package metadata | 2026-11-07 | checked |
| PyYAML | 6.0.3 | MIT | Config, lexicon, front matter | installed package metadata | 2026-11-07 | checked |
| jsonschema | 4.26.0 | MIT | Validate the scenes JSON | installed package metadata | 2026-11-07 | checked |
| anthropic | 2.6.0 | Apache-2.0 (PLAN.md section 8 said MIT; the package metadata says Apache-2.0) | Haiku 5.5 fallback adapter | installed package metadata | 2026-11-07 | checked |
| pytest (dev) | 9.2.0 | MIT | Tests | installed package metadata | 2026-11-07 | checked |

The GPL and LGPL items are installed by `pip` on the machine that runs the pipeline
and are not copied into the deliverables zip; the pipeline calls them as libraries.
The MP4 and WAV files they help make are output, not copies of the software.

## npm packages (`render/package.json`, T5a)

| Package | Version | License | Why | Source checked | Date | Status |
|---|---|---|---|---|---|---|
| remotion, @remotion/cli | 4.0.539 | Remotion License. Installed `LICENSE.md`: free for an individual, a for-profit organization with up to 3 employees, a non-profit, or while evaluating; commercial use allowed. License FAQ (remotion.dev/docs/license/faq): "an organization or team of individuals with up to 3 people"; contractors operating the project count toward the headcount; Company License USD 25 per month per person writing Remotion code, or USD 0.01 per render with a USD 100 monthly minimum. The LICENSE.md says the terms change slightly in Remotion 5.0 | Rendering | installed package LICENSE.md (re-read 2026-11-09); remotion.dev license FAQ | 2026-11-09 | checked |
| @remotion/layout-utils | 4.0.539 | MIT (package metadata; PLAN.md said Remotion License) | Auto-fit text | installed package metadata | 2026-11-07 | checked |
| @remotion/renderer, bundler and the other @remotion packages (with @remotion/cli) | 4.0.539 | Remotion License | Rendering engine, bundler | installed package metadata | 2026-11-07 | checked |
| Chrome Headless Shell (downloaded by Remotion on first render, into render/node_modules/.remotion) | 157 | Chromium licenses (BSD-3-Clause and others) | Draws the frames | remotion.dev docs | 2026-11-07 | checked |
| react, react-dom | 19.2.0 | MIT | Remotion components | installed package metadata | 2026-11-07 | checked |
| typescript (dev) | 5.9.3 | Apache-2.0 | Type checking | installed package metadata | 2026-11-07 | checked |
| @types/react (dev) | 19.2.18 | MIT | Type checking | installed package metadata | 2026-11-07 | checked |
| @fontsource/inter | 5.2.8 | OFL-1.1 | Inter font files | installed package metadata | 2026-11-07 | checked |
| lucide-react | 1.52.0 | ISC | Icons | installed package metadata | 2026-11-07 | checked |

## Tools and services

| Item | Version | License or terms | Why | Source checked | Date | Status |
|---|---|---|---|---|---|---|
| Python | 3.12.10 (laptop `.venv\pyvenv.cfg`; the build machine uses 3.12 too) | PSF License Version 2 (the `LICENSE` file of the v3.12.10 tag in the CPython repository; documentation examples under Zero-Clause BSD) | Pipeline | LICENSE at github.com/python/cpython tag v3.12.10 | 2026-11-09 | checked |
| Node.js | 24.18.0 (the version that ran `npm install -g n8n` in T8, DECISIONS.md) | MIT for Node.js itself (the `LICENSE` file of the v24.18.0 tag); bundled third-party parts (V8, ICU, OpenSSL and others) carry their own licenses, listed in the same file | Remotion, n8n | LICENSE at github.com/nodejs/node tag v24.18.0 | 2026-11-09 | checked |
| FFmpeg (Windows build, Gyan via winget) | 9.0.2 (Gyan full_build via winget) | GPL-3.0 (configured with --enable-gpl --enable-version3; `ffmpeg -L` and the build's LICENSE file, full GPL v3 text; README.txt says License: GPL v3) | `mux` music bed and `check` stage; run as a separate program, never shipped in the zip | LICENSE and README.txt in the installed build, ffmpeg -L | 2026-11-07 | checked |
| n8n | 2.46.6 | Sustainable Use License 1.0 (`LICENSE.md` in the npm package): use or modify only for your own internal business purposes or for non-commercial or personal use; distribute only free of charge for non-commercial purposes; keep the licensor's notices. Files with `.ee.` in the name need an n8n Enterprise License (not used here). Installed globally with npm, never shipped in the project zip; the workflow JSON is our own file | Workflow wrapper (T8) | installed package LICENSE.md | 2026-11-07 | checked |
| Gemini API (free tier) | gemini-3.6-flash | Gemini API Additional Terms of Service (not re-checked: never read at the source; ai.google.dev/gemini-api/terms now redirects to aistudio.google.com/docs/terms, and both are blocked from the build machine, HTTP 403 on 2026-11-09). Read them in Google AI Studio before relying on the free tier | Scene generation | not read | - | not re-checked |
| Claude Haiku 5.5 (paid fallback) | claude-haiku-5-5 | Anthropic Commercial Terms of Service (effective Jun 17, 2025, as shown on the page). Price USD 0.10 / 0.50 per million input / output tokens for prompts up to 100,000 tokens (USD 0.50 / 2.50 above), from the pricing page. Not used live yet (STATUS issue 16) | Scene generation fallback | anthropic.com/legal/commercial-terms; platform.claude.com/docs/en/about-claude/pricing | 2026-11-09 | checked |
