# E3 — Audiobook & Media Pipeline

Converts Project Gutenberg books into fully-produced audiobooks and uploads them to YouTube.

**Pipeline:** HTML → Parse → Entity Analysis → Image Prompts → Media (ComfyUI + TTS + ffmpeg) → YouTube Upload

---

## Quick Start

```bash
# Install and activate
uv venv && .venv\Scripts\activate
uv pip install -r requirements.txt && uv pip install -e .

# Run full pipeline (HTML → YouTube)
uv run python -m audiobook_agent.pipeline foundry/pg174/pg174-images.html
```

---

## Project Structure

```
E3/
├── .env                          # API keys, hosts, environment config
├── config/
│   ├── global_alpha.yaml         # Alpha environment settings
│   └── global_prod.yaml          # Production environment settings
├── audiobook_agent/              # Core pipeline modules
│   ├── pipeline.py               # End-to-end orchestrator (phases 1-5)
│   ├── parse_novel_langchain.py  # Phase 1: HTML -> codex.json
│   ├── analyze_entities.py       # Phase 2: scenes, characters, locations
│   ├── generate_prompts.py       # Phase 3: image prompts via LLM
│   ├── generate_media.py         # Phase 4: ComfyUI images + TTS + ffmpeg
│   ├── youtube_upload.py         # Phase 5: YouTube upload
│   └── ...                       # Legacy pipeline modules
├── foundry/                      # Book data (gitignored)
│   └── pg174/
│       ├── codex.json            # Parsed book structure
│       ├── characters.json       # Character profiles + image prompts
│       ├── locations.json        # Location profiles + image prompts
│       ├── thumbnail_prompts.json
│       ├── analysis/             # Per-chapter scene analysis + prompts
│       ├── audio/                # TTS-generated WAV files
│       └── videos/               # Final MP4 output
├── comfyui_agent/                # ComfyUI job queue agent
├── gutenberg_agent/              # Project Gutenberg book fetcher
└── svg/                          # AI stamp overlay assets
```

---

## Environment Setup

### `.env` (copy from `.env.example` and fill in)

```
E3_ENV=alpha                      # alpha | prod

OPR_ROUTER_API_KEY=...            # OpenRouter (LLM for analysis + prompts)

COMFYUI_HOST=127.0.0.1
COMFYUI_PORT=8188
COMFYUI_TIMEOUT=1800
COMFYUI_OUTPUT_DIR=D:\...\ComfyUI\output
COMFYUI_WORKFLOWS_DIR=D:\...\workflows

YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_CHANNEL_ID=...
YOUTUBE_ALPHA_PLAYLIST_ID=...
YOUTUBE_PROD_PLAYLIST_ID=...
YOUTUBE_DEFAULT_PRIVACY=public
```

---

## Foundry Pipeline

### Phase reference

| Phase | Command module | What it does |
|-------|---------------|--------------|
| 1 | `parse_novel_langchain` | HTML → `codex.json` + chapter chunks |
| 2 | `analyze_entities` | LLM scene/character/location extraction |
| 3 | `generate_prompts` | LLM image prompt generation |
| 4 | `generate_media` | ComfyUI images + Qwen TTS + ffmpeg video |
| 5 | `youtube_upload` | Upload MP4 to YouTube |

### Pipeline commands

```bash
# Full run: HTML -> YouTube (phases 1-5)
uv run python -m audiobook_agent.pipeline foundry/pg174/pg174-images.html

# Resume from analysis (book already parsed)
uv run python -m audiobook_agent.pipeline foundry/pg174 --from-phase 2

# Media + upload only
uv run python -m audiobook_agent.pipeline foundry/pg174 --from-phase 4

# Upload only (video already exists)
uv run python -m audiobook_agent.pipeline foundry/pg174 --phases 5

# Upload as unlisted for review
uv run python -m audiobook_agent.pipeline foundry/pg174 --phases 5 --privacy unlisted

# Skip upload, generate media only
uv run python -m audiobook_agent.pipeline foundry/pg174 --phases 1 2 3 4
```

### Individual modules

```bash
# Phase 4 sub-steps: 0=characters 1=locations 2=scenes 3=posters 4=audio 5=video
uv run python -m audiobook_agent.generate_media foundry/pg174 --steps 4 5

# Upload with LLM-generated metadata
uv run python -m audiobook_agent.youtube_upload foundry/pg174 --model google/gemini-2.0-flash-lite-001
```

---

## ComfyUI Agent

Monitors folders for YAML job configs → queues in SQLite → executes via ComfyUI API.

```bash
# Start all services
python -m comfyui_agent.cli start --ui-port 8081

# Or separately
python -m comfyui_agent.cli monitor    # Terminal 1
python -m comfyui_agent.cli run        # Terminal 2
python -m comfyui_agent.ui_server 8080 # Terminal 3 (Web UI)
```

Submit a job:
```bash
cp samples/test_job_t2i.yaml comfyui_jobs/processing/image/
```

Web UI: http://localhost:8081 — view queue, retry failed jobs, adjust priorities.

---

## YouTube Token Management

```bash
python youtube_token_manager.py status    # Check token status
python youtube_token_manager.py validate  # Validate credentials
python youtube_token_manager.py reauth    # Re-authenticate (clears token)
```

Token is stored in `youtube_credentials.json` (gitignored). First run triggers a browser OAuth flow.

---

## Troubleshooting

**ComfyUI connection refused** — ensure ComfyUI is running: `python main.py --listen 0.0.0.0 --port 8188`

**YouTube upload timeout** — increase `COMFYUI_TIMEOUT` in `.env` (default: 1800s)

**Phase 4 image timeouts** — use `--timeout 1800` flag: `--phases 4 --timeout 1800`

**Access denied on Windows (.venv)** — close all programs using the folder, then `rmdir /s /q .venv` and recreate
