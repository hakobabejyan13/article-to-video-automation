# Workflow

How to set up the pipeline on Windows and make a video from one article. This file
grows as tasks are built: T7 completed the run section, T8 added the n8n section.

## Setup on Windows (PowerShell, once)

1. Install the system tools:

   ```powershell
   winget install Python.Python.3.12 Gyan.FFmpeg Git.Git
   ```

   and Node 24, from the installer on nodejs.org or with
   `winget install OpenJS.NodeJS --version <24.x>`. `doctor` checks that Node's major
   version is 24. Open a new PowerShell window afterwards so the new PATH is used.

2. In the project folder, make the Python environment and install the packages:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Render project (Remotion; versions are fixed by `render/package-lock.json`):

   ```powershell
   cd render
   npm ci
   node node_modules/@remotion/cli/remotion-cli.js browser ensure
   cd ..
   ```

   `npm ci` took 45 s on the laptop. `browser ensure` downloads Chrome Headless Shell
   (120 MB, from storage.googleapis.com) once; without it the first render downloads
   it. npm may warn that esbuild's install script was not run; rendering works anyway.

4. Copy `.env.example` to `.env` and add the Gemini key (and the Anthropic key, only
   if `llm.provider` is set to `anthropic`):

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

   `.env` is git-ignored. Never share it.

5. For n8n, tell it where the project folder is (replace the placeholder with the
   full path of your project folder):

   ```powershell
   setx A2V_PROJECT_DIR "<project folder>"
   ```

6. Check the setup:

   ```powershell
   python -m pipeline doctor
   ```

   No line may say `FAIL` (doctor then exits with code 2). `WARN` lines are not errors:
   before the first voiceover run the Kokoro model and the spaCy model show `WARN`
   (the first `tts` run downloads them), and the LLM key shows `WARN` when it is empty.
   In every new PowerShell window, run `.venv\Scripts\activate` first (or write
   `.venv\Scripts\python` instead of `python`).

7. For n8n (T8), once:

   ```powershell
   npm install -g n8n@2.46.6
   ```

   Then see "Run with n8n" below for how to start it and import the workflow.

8. espeak-ng: **not needed.** T4 checked on Windows with no system espeak-ng: the
   `espeakng-loader` package that misaki installs brings its own copy.

Notes from T4 (voiceover):
- `pip install -r requirements.txt` took about 9.5 minutes on the laptop. The first
  `tts` run downloads the Kokoro model (about 330 MB, into the Hugging Face cache in
  your user folder) and installs the spaCy model `en_core_web_sm`; that run took about
  5 minutes. Later runs load the model from the cache. Measured load times differ by run
  and by machine state (free memory, other programs): 17-19 s in the T4 cached runs,
  28.4 s in the final article-01 run (T7) and 40.6 s in the article-02 run (T9).
- Voicing article-01 (8 scenes, 107 s of audio) took about 80 s of speech time; the
  process peaks at about 2.0 GB of memory. Close other programs first: with about
  0.8 GB free before the run it still finished.
- Hugging Face warns that symlinks need Windows Developer Mode; without it the cache
  just uses more disk. Harmless.
Notes from T5a (render):
- Rendering the 80 s test video (2387 frames, concurrency 1) took about 3 minutes on
  the laptop (about 2.2x the video length) and peaked at about 870 MB of memory.
  `render.concurrency` in `pipeline/config.yaml` stays 1 on an 8 GB, 2-core machine.
- A text that cannot fit even at `render.min_font_px` stops the render at once with
  "Scene N: the <element> does not fit ..." (exit 1): shorten that text and run
  `--from scenes` (or edit the scenes file and run `--from verify`).
- The render tests that need Remotion skip until `npm ci` has run in render/. To
  render the whole test video as well: `$env:A2V_RENDER_TESTS="1"; .venv\Scripts\python -m pytest -q tests/test_render.py`.
- The intermediate video is `render/out/<id>.mp4` (voice included, no
  music yet); its props are in `render/out/<id>.props.json`. To preview the design,
  run `npm run studio` in render/.
- To see time and peak memory of any step:
  `.venv\Scripts\python -m pipeline.tools.measure -- .venv\Scripts\python -m pipeline run source/article-XX.md --from tts`
Notes from T6 (music and final checks):
- The music bed is `music.file` in `pipeline/config.yaml` (`assets/music/contemplation.mp3`,
  CC0, see `docs/licenses.md`). It is not in the project download: get it from the
  track page named in `docs/licenses.md` into `assets/music/`. `doctor` has a Music row.
- `mux` copies the video stream of `render/out/<id>.mp4` unchanged, measures the mean
  level of the voice and of the music, and mixes the music `music.duck_db` (-20 dB)
  below the voice, looped if needed, with a 1 s fade-in and a 2 s fade-out, cut to the
  video's exact length. Output: `output/<id>/<id>.mp4`.
- `check` writes its results under `"check"` in `output/<id>/verify-report.json`:
  1920x1080, H.264, AAC, fps, duration in range, frame count equals the timing total,
  audio and video lengths within one frame, and each scene's speech starting within
  100 ms of its start (silencedetect on the voice track in `render/out/<id>.mp4`,
  because the music fills the pauses in the final file). Any failure exits 1.
- To render the fixture and then run mux and check on it:
  `$env:A2V_RENDER_TESTS="1"; .venv\Scripts\python -m pytest -q tests/test_mux.py`.
- Cloud container only: set `HF_HUB_DISABLE_XET=1` so the model download uses plain
  HTTPS (the xet transfer hosts are not on the allowlist).

## Make a video from a new article

1. Save the article as `source/article-XX.md` with front matter at the top. A person
   sets these values, never the LLM:

   ```yaml
   ---
   publisher: <name as written in the article>
   promotional: true        # the publisher ranks or promotes itself
   url: <optional>
   ---
   ```

   If you add front matter to an article that already exists, check the text below it
   is unchanged: run `python -m pipeline.tools.body_hash source/article-XX.md --expect <sha256 of the original file>`.

2. Run up to the review point:

   ```powershell
   python -m pipeline run source/article-XX.md --review
   ```

3. Read `output/article-XX/factsheet.md`. Then make the audio and video:

   ```powershell
   python -m pipeline run source/article-XX.md --from tts
   ```

   This voices the scenes, writes the fact sheet and script again with timecodes,
   renders, adds the music and runs the final checks. The finished files are in
   `output/article-XX/`: `article-XX.mp4`, `script.md`, `factsheet.md`,
   `factsheet.csv` and `verify-report.json` (checker and final-check results).

4. If the fact sheet needs a change, edit `scenes/article-XX.scenes.json` (keep every
   fact in the words and numbers of a cited sentence), then check it and write the
   fact sheet again, still stopping for review:

   ```powershell
   python -m pipeline run source/article-XX.md --from verify --review
   ```

   Then run step 3. A run without `--review` goes from the article to the final MP4
   in one command, with no stop.

If a stage fails, its message says what to do:
- `scenes`: the LLM's answer failed the checker more than `llm.max_retries` times
  (exit 1) or every model was busy or out of quota (HTTP 503/429, exit 3). Wait a
  minute (the free Gemini tier has a per-minute token limit) and run `--from scenes`.
- `tts`: "Voiceover is N s; the target is 60-90 s" (exit 1). The words-per-minute
  estimate the checker uses is only an estimate; run `--from scenes` for new scenes,
  or shorten/lengthen the scenes file by hand and run `--from verify --review`.
- `render`: "Scene N: the <element> does not fit" (exit 1): shorten that text.
- `check`: a `[FAIL]` line names the check and the scene.

How long it takes (article-01, 7 scenes, 70 s video): `scenes` 1-2 minutes
(longer when Gemini is busy); in the cloud (4 cores) `--from tts` took 213 s with a
peak of 1.7 GB; laptop numbers are in the run log below. Close other programs before
the run on an 8 GB laptop.

To see time and peak memory, put `.venv\Scripts\python -m pipeline.tools.measure --`
in front of the command.

`--from <stage>` re-runs one stage and everything after it. Stage names:
`sentences`, `scenes`, `verify`, `docs`, `tts`, `render`, `mux`, `check`.
`python -m pipeline --help` lists them with a short description.

Exit codes: 0 success (or stopped at the review point), 1 checker or length failure,
2 missing setup or input, 3 provider unavailable after retries.

## Run with n8n

n8n is only a wrapper: the workflow calls the same two CLI commands as above, with a
review gate between them. It has 6 nodes and no other logic:

| # | Node | What it does |
|---|---|---|
| 1 | Article form (Form Trigger) | Asks for the article path, relative to the project folder, for example `source/article-XX.md` |
| 2 | Scenes and fact sheet (--review) (Execute Command) | `cd /d "%A2V_PROJECT_DIR%" && .venv\Scripts\python -m pipeline run "<path>" --review` |
| 3 | Review approval (Wait, on form submitted) | Shows the step 2 output and waits. Read `output/<article id>/factsheet.md` and `script.md`, then press Approve |
| 4 | Voiceover and video (--from tts) (Execute Command) | `cd /d "%A2V_PROJECT_DIR%" && .venv\Scripts\python -m pipeline run "<path>" --from tts` |
| 5 | Stop on failure (Stop and Error) | Reached from the error output of node 2 or 4; fails the execution with the CLI's error message |
| 6 | List output files (Execute Command) | `cd /d "%A2V_PROJECT_DIR%\output" && dir /b "<article id>"` (the id is the file name of the path without `.md`) |

The workflow file is `pipeline/n8n/article-to-video.workflow.json`. The project folder
comes from the environment variable `A2V_PROJECT_DIR` (setup step 5); nothing in the
workflow names a folder or an article.

**Start n8n** (PowerShell, every time; open a new window after `setx` so the variable is
there):

```powershell
$env:NODES_EXCLUDE="[]"; $env:N8N_LISTEN_ADDRESS="127.0.0.1"; n8n start
```

- `NODES_EXCLUDE=[]`: n8n 2.x turns the Execute Command node off unless this is set.
- `N8N_LISTEN_ADDRESS=127.0.0.1`: the form has no login and runs a command on this
  computer, so n8n must only listen on this computer, never on the network.

**Import, once:** stop n8n (Ctrl+C), then in the project folder:

```powershell
n8n import:workflow --input=pipeline\n8n\article-to-video.workflow.json
n8n list:workflow                      # prints <id>|Article to video
n8n publish:workflow --id=<id>
```

and start n8n again. (In the editor at http://localhost:5678 you can also use
Import from File, then Publish.) Publishing makes the form URL live.

**Make a video:**
1. Open http://localhost:5678/form/a2v-article-form, enter `source/article-XX.md`,
   press Start. The page waits while step 2 runs (1-2 minutes, the LLM call).
2. The approval page appears with step 2's output. Read the fact sheet and script in
   `output/article-XX/`. Press Approve to make the voiceover and video (about 5 minutes
   on the laptop). To reject, do not press Approve: stop the execution in n8n
   (Executions list), edit the scenes JSON, check it with
   `python -m pipeline run source/article-XX.md --from verify --review`, and start the
   form again (or finish with the CLI).
3. The finished files are in `output/article-XX/`, the same files the CLI makes.

**When something fails:** the Execute Command node treats any non-zero exit code as an
error and puts the command's stderr in the message (or "Command failed with exit code
N" when stderr is empty). Its error output goes to "Stop on failure", so the execution
ends as failed with, for example, "Pipeline failed (non-zero exit code). error: article
file not found: source/does-not-exist.md". The exit code number itself is not in the
error item; the message is what the CLI printed (exit codes are listed above). Open the
execution in n8n to see it.

Notes:
- The path is put inside double quotes in a `cmd.exe` command. Type only a plain file
  path (no `"`, `&` or `%`).
- n8n 2.46.6 needs Node 24. Its native parts (isolated-vm, sqlite) are built for the Node
  version that ran `npm install`; if Node is changed later, reinstall n8n.
- n8n keeps its data (workflows, executions) in `%USERPROFILE%\.n8n` unless
  `N8N_USER_FOLDER` is set.

## Helper scripts

- `python -m pipeline.tools.docx_text check brief.docx docs/brief.md`: confirms the
  Markdown copy of the brief matches the Word file word for word.
- `python -m pipeline.tools.body_hash <article>`: prints the SHA-256 of the article
  text below the front matter.

## Run log

One line per real article run. Times are wall time of the whole command.

| Date | Where | Command | Result | Time, peak memory |
|---|---|---|---|---|
| 2026-11-07 | Cloud | `run source/article-01.md --review` | Scenes regenerated (attempt 1 Flash-Lite failed the checker, attempt 2 gemini-3.6-flash passed): 7 scenes, 141 words; stopped for review | 96 s |
| 2026-11-07 | Cloud | `--from tts` | 68.0 s video, every check passed | 198 s, 1.7 GB |
| 2026-11-07 | Cloud (copy) | `run source/article-01.md` (one command, from nothing) | Every stage ran in order; stopped at the tts length check (exit 1, 54.9 s): the Flash models were out of quota and Flash-Lite's scenes were short | 67 s, 1.7 GB |
| 2026-11-07 | Cloud | `--from verify --review` after Hakob's review edits (scenes 4, 6, 7) | PASS, 7 scenes, 23 claims, 147 words | a few seconds |
| 2026-11-07 | Cloud | `--from tts` | 69.9 s video, every check passed; each clip's speech starts at 50 ms | 213 s, 1.7 GB |
| 2026-11-07 | Laptop (final) | `.venv\Scripts\python -m pipeline.tools.measure -- .venv\Scripts\python -m pipeline run source/article-01.md --from verify` (reviewed scenes, no LLM) | Exit 0. 69.9 s video, 4.6 MB, every check passed; each clip's speech starts at 50 ms. Model load 28 s, speech 42 s, render 175 s, mux 7.8 s. 1.85 GB free before the run. Log: `output/article-01/laptop-run.log` | 262 s, 1.85 GB |
| 2026-11-07 | Laptop, n8n | Form with `source/article-01.md` (execution 1) | Failed at step 1 (Gemini HTTP 403, key's project had no free tier); stopped at "Stop on failure". Reviewed files restored | about 2 s |
| 2026-11-07 | Laptop, n8n | Form with `source/does-not-exist.md` (execution 2, forced failure) | Stopped at "Stop on failure": "error: article file not found" | about 2 s |
| 2026-11-07 | Laptop, n8n | Form with `source/article-01.md` (execution 4, new key) | Step 1: Gemini 51 s, verify PASS, 7 scenes, 126 words, stopped at the review gate (62 s). Approved; step 2: 60.5 s video, every check passed. Last node failed (bug, fixed afterwards). Test outputs kept in `_t8-backup/n8n-run/`; Hakob's reviewed files restored (20 of 20 sums match) | about 6 min, 1.96 GB |
| 2026-11-07 | Laptop, n8n (fix) | "List output files" node changed to `cd /d "%A2V_PROJECT_DIR%\output" && dir /b "{{ id }}"` (n8n read `\{{` as a literal brace in execution 4); the laptop's imported workflow replaced with the fixed file | Not an article run; first run with the fix is execution 5 below | - |
| 2026-11-07 | Laptop, n8n | Form with `source/article-02.md` (execution 5, step 1) | gemini-3.6-flash answered on attempt 1 (47 s, 14,900 tokens, no 429); verify PASS, 6 scenes, 23 claims, 165 words; stopped at the review gate | 49 s |
| 2026-11-07 | Laptop | `run source/article-02.md --from verify --review` after Hakob's review fix (scene 4 bars: Planned column) and the new source tag template | PASS, 6 scenes, 23 claims, 165 words | not timed |
| 2026-11-07 | Laptop, n8n | Execution 5 approved (step 2, `--from tts`) | 81.2 s video (2,435 frames), every check passed; tts 90 s (model load 40.6 s), render 181 s, mux 2.5 s, check 1 s. Every node succeeded, including "List output files" | 276 s, about 2.06 GB for all python, node and chrome processes (free memory fell to 407 MB) |
| 2026-11-07 | Laptop | verify and docs only, after Hakob added sentences 48 and 49 to the scene 4 bar citations (timing.json `scenes_sha256` updated to the new scenes hash; audio and MP4 unchanged) | PASS, 23 claims; fact sheet kept its timecodes; script.md unchanged | not timed |
