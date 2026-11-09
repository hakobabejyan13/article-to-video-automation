# article-to-video-automation

This project turns one blog article into a 1920x1080 MP4 explainer of 60 to 90 seconds,
with an English AI voiceover, music, and animated charts made from the article's own
numbers. With each video it also writes a script and a fact sheet that links every
claim to the sentence in the article it came from, and a checker refuses to make the
video if any claim cannot be traced.

The repository holds only the code. The two example articles, their scenes and
finished videos are in the deliverables zip. To start fresh, put your own article in
source/ (see Make a video).

The three rules:
1. **Every fact comes only from the article.** No outside knowledge, and numbers are
   never rounded or reworded.
2. **Publisher claims are attributed.** If an article ranks or promotes its own
   publisher, the video says "according to ..." instead of stating it as fact.
3. **One command per article.** A new article needs only a new input file. No code
   changes.

**Stages:** sentences → scenes (LLM) → verify → docs → *review stop* → tts (voice) →
docs again (with timecodes) → render → mux (music) → check.

**Windows only.** The commands below, the n8n workflow (it runs `cmd.exe` with
`cd /d` and `.venv\Scripts\python`) and every measured time are for Windows
PowerShell. The pipeline code itself is plain Python and Node. Tested on Windows only; the unit tests also run on Linux.

## Setup on Windows (once, in PowerShell)

0. Clone the repository or unzip the deliverables zip, and open PowerShell in the
   folder it makes: `cd <where you cloned or unzipped it>\article-to-video-automation`. Every command below runs
   from there.
1. Install Python 3.12, FFmpeg and Git:
   `winget install Python.Python.3.12 Gyan.FFmpeg Git.Git`.
   Install Node 24 from nodejs.org. Open a new PowerShell window afterwards.
2. Make the Python environment:
   `py -3.12 -m venv .venv`, then `.venv\Scripts\activate`, then
   `pip install -r requirements.txt` (this took about 9.5 minutes on a 2-core laptop).
   **In every new PowerShell window, run `.venv\Scripts\activate` again** before the
   `python -m pipeline` commands below (the prompt then starts with `(.venv)`). If
   PowerShell refuses with "running scripts is disabled on this system", skip the
   activation and type `.venv\Scripts\python` instead of `python` in every command.
3. Set up the renderer: `cd render`, then `npm ci`, then
   `node node_modules/@remotion/cli/remotion-cli.js browser ensure`, then `cd ..`.
4. Add your API key: `Copy-Item .env.example .env`, then `notepad .env` and fill in
   `GEMINI_API_KEY=` with a free-tier Gemini key made in Google AI Studio
   (aistudio.google.com, "Get API key"). If the first run fails with HTTP 403, the key's
   Google Cloud project does not have the Gemini API switched on or has no free tier:
   switch the API on, or make the key in a new project (this happened in T8). `ANTHROPIC_API_KEY` is needed only if you
   switch `llm.provider` to `anthropic` in `pipeline/config.yaml`. Never share `.env`.
5. Check everything: `python -m pipeline doctor`. No line may say `FAIL` (it exits
   with code 2 if one does). Before the first video, two `WARN` lines are normal: the
   Kokoro model and the spaCy model are downloaded by the first voiceover run (about
   330 MB from huggingface.co, plus the spaCy model from github.com; that run took about
   5 minutes). The `Music` row needs `assets/music/contemplation.mp3`, which is in this
   zip; if it is missing, see "Music track" below.
6. Optional, for n8n: `setx A2V_PROJECT_DIR "<full path of this folder>"`, then open a
   **new** PowerShell window (setx does not change the window it runs in), then
   `npm install -g n8n@2.46.6` (about 17 minutes on the laptop). See
   `docs/workflow.md`, "Run with n8n", for starting n8n and importing the workflow.

### Music track

The music bed is "Contemplation" by Joth (CC0 1.0), shipped in this zip as
`assets/music/contemplation.mp3` with its saved license page
`assets/music/LICENSE-contemplation.html`. If the file is missing, download it again
from https://opengameart.org/sites/default/files/Contemplation.mp3 (track page
https://opengameart.org/content/contemplation-0) and save it as
`assets/music/contemplation.mp3`. It should be 2,405,271 bytes with SHA-256
283962d3a975c93613c46cda30c9f0816176ae3e2899f961591a49e2d41b4bf3
(`Get-FileHash assets\music\contemplation.mp3`). To use another track, put it in
`assets/music/`, set `music.file` in `pipeline/config.yaml`, and log its license in
`docs/licenses.md`.

## Make a video

1. Save the article as `source/article-XX.md` (the file name becomes the article id:
   `output/article-XX/`, `scenes/article-XX.*`). Put the article text in Markdown
   exactly as published (tables as Markdown tables), and at the very top add the front
   matter block, between two `---` lines:
   ```
   ---
   publisher: <name as written in the article>
   promotional: true        # true if the publisher ranks or promotes itself, else false
   url: <optional>
   ---
   ```
   A person sets these, never the LLM (see `source/article-01.md`). There is no
   automatic download: `docs/workflow.md` ("Make a video from a new article") and
   `docs/next-ten-videos.md` ("How articles get in") describe the hand extraction.
2. `python -m pipeline run source/article-XX.md --review`
   (writes the scenes and fact sheet, then stops).
3. Read `output/article-XX/factsheet.md` and `script.md`. To fix something, edit
   `scenes/article-XX.scenes.json` and run `--from verify --review` again.
4. `python -m pipeline run source/article-XX.md --from tts`
   (voice, render, music, final checks; about 5 minutes on a 2-core laptop).
5. Find the video and its documents in `output/article-XX/`: `article-XX.mp4`,
   `script.md`, `factsheet.md`, `factsheet.csv` and `verify-report.json` (the
   `"check"` part must say `"result": "pass"`). A run without `--review` does all of
   it in one command, without the review stop.

Exit codes: 0 done (or stopped at review), 1 checker or length failure, 2 missing setup
or input, 3 LLM unavailable (wait a minute and run `--from scenes`). Close other
programs before step 4 on an 8 GB machine.

## Make a video with n8n (optional)

The CLI above is the engine; the n8n workflow only calls the same two commands, with a
review stop between them. Needs setup step 6.

1. Start n8n: `$env:NODES_EXCLUDE="[]"; $env:N8N_LISTEN_ADDRESS="127.0.0.1"; n8n start`
   (the address keeps n8n on this computer only).
2. Open http://localhost:5678. If the workflow is not there, use Import from File with
   `pipeline/n8n/article-to-video.workflow.json`, then Publish.
3. Open http://localhost:5678/form/a2v-article-form, enter `source/article-XX.md`, press Start.
4. At the review step, read `output/article-XX/factsheet.md` and `script.md`, then press Approve.
5. The finished files are in `output/article-XX/`, the same files the CLI makes.

## Folder map

| Folder or file | What is in it |
|---|---|
| `source/` | The articles, with front matter (the examples article-01 and article-02 come with the deliverables zip) |
| `scenes/` | Sentence list and scenes JSON for each article (the example files come with the deliverables zip) |
| `output/` | Finished MP4, script, fact sheet (.md and .csv) and checker report per article (the example files come with the deliverables zip) |
| `pipeline/` | The Python code, `config.yaml`, voice lexicon, LLM prompt, n8n workflow export (`n8n/`) |
| `render/` | The Remotion video project |
| `assets/` | Music track and its saved license page |
| `audio/` | Voice clips (made by each run) |
| `tests/` | Unit tests (`pytest`) |
| `docs/` | Setup and workflow, licenses, next-ten-videos note |
| `PLAN.md`, `DECISIONS.md` | The approved plan and every tool choice with its reason |

CLAUDE.md (the build agent's rules) and STATUS.md (the build log) are not included; DECISIONS.md and PLAN.md refer to them as history.

## Read next

- `docs/workflow.md`: the full setup, the n8n workflow and what to do when a stage fails.
- `docs/licenses.md`: every package, font, icon and music license. Two points matter
  before scaling: **Remotion** is free only for individuals and companies of up to 3
  people (a larger team needs a paid license; MoviePy is the documented fallback), and
  **Kokoro** is Apache-2.0 but pip installs GPL and LGPL sub-packages with it (not
  shipped in this zip).
- `docs/next-ten-videos.md`: time, cost, batching and review for the next ten videos.
