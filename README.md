# E3 — Audiobook Production Pipeline

Turns Project Gutenberg HTML books into fully-produced audiobooks with AI-generated illustrations, narration, and video — then uploads them to YouTube. Uses OpenRouter LLMs for text analysis and image prompt generation, ComfyUI for image generation, Qwen3-TTS for narration, and ffmpeg for video assembly.

## Quick Start

```bash
# Setup
uv venv && .venv\Scripts\activate       # Windows
uv venv && source .venv/bin/activate    # Linux/Mac
uv pip install -r requirements.txt && uv pip install -e .

# Set OpenRouter key in .env
echo "OPR_ROUTER_API_KEY=your_key_here" > .env

# Run full pipeline (HTML → YouTube)
uv run python -m audiobook_agent.pipeline foundry/pg174/pg174-images.html
```

---

## Architecture

```
HTML Book ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5
  Parse        Analyze     Prompts     Media       Upload
    │             │            │          │            │
 codex.json   characters   image_prompt  images/    YouTube
 chapters/    locations    fields added  audio/
              analysis/    thumbnails    videos/
```

### Phase 1 — Parse (`parse_novel_langchain.py`)
3-agent LangChain pipeline (Structure Analyst → Chapter Extractor → Quality Reviewer) converts Gutenberg HTML into `codex.json` (full paragraphs per chapter) and `chapters/` (TTS-sized chunks of 400-500 chars).

### Phase 2 — Entity Extraction (`analyze_entities.py`)
Processes codex paragraphs chapter-by-chapter. An LLM extracts scenes, characters, and locations per chapter. Character profiles **accumulate** across chapters — each chapter adds only new physical details, deduplicated via substring matching. Known character/location names are injected into each chapter's LLM call to keep canonical names consistent and prevent entity splitting.

Outputs: `characters.json`, `locations.json`, `analysis/chapter_NNN_analysis.json`

### Phase 3 — Image Prompt Generation (`generate_prompts.py`)
Generates image prompts in 4 steps, all wrapped in the selected visual style:

| Step | Output | Description |
|------|--------|-------------|
| 1 | `image_prompt` per character | Portrait prompts from accumulated physical profiles |
| 2 | `image_prompt` per location | Environment prompts using richest scene description found |
| 3 | `scene_image_prompt` per scene | Cinematic prompts with full character profile lookup |
| 4 | `thumbnail_prompts.json` | 4-agent council generates candidates, 5th agent votes top 5 |

### Phase 4 — Media Generation (`generate_media.py`)
| Step | What | Tool | Resolution |
|------|------|------|------------|
| 0 | Character portraits | ComfyUI | 1024x1024 |
| 1 | Location images | ComfyUI | 1280x720 |
| 2 | Scene images | ComfyUI | 1280x720 |
| 3 | Thumbnails / posters | ComfyUI | — |
| 4 | Audio narration | Qwen3-TTS | — |
| 5 | Video assembly | ffmpeg | — |

### Phase 5 — YouTube Upload (`youtube_upload.py`)
Generates title, description, tags, and schedule using an LLM, then uploads via YouTube Data API v3.

---

## How Styling Consistency Works

The pipeline achieves consistent visuals across all characters, locations, and scenes through three mechanisms:

### 1. Style Sandwich
Every generated prompt is bookended with the same style strings. The LLM system messages enforce: *"START your prompt with EXACTLY this prefix... END with EXACTLY this suffix."* This gives every image the same aesthetic DNA regardless of subject.

### 2. Accumulated Character Profiles
Phase 2 builds growing master profiles across chapters. Physical descriptions accumulate (new details only, deduplicated). In Phase 3, every scene prompt performs a **profile lookup** — even in Chapter 20, the scene gets Lord Henry's full physical description from all prior chapters.

### 3. No-Names Rule
All prompts describe characters by physical appearance only — never by name. This forces the image generator to rely on consistent visual descriptions: *"a man with an olive-coloured face, dark eyebrows, and yellow gloves"* rather than *"Lord Henry"*.

---

## Visual Styles

Select with `--style <name>`:

| Style | Best For | Aesthetic |
|-------|----------|-----------|
| `classical_illustration` (default) | Victorian / classic lit | Pen & ink, watercolor wash, sepia tones, cross-hatching |
| `anime` | Light novels, modern fiction | Cel shaded, Studio Ghibli, vibrant, clean linework |
| `oil_painting` | Historical epics, drama | Old master brushwork, chiaroscuro |
| `gothic_illustration` | Horror, dark fiction | Edward Gorey / Aubrey Beardsley, art nouveau |
| `cartoon` | Children's books, comedy | Bold outlines, hand-drawn, playful |

Add custom styles in `audiobook_agent/visual_styles.py`.

---

## LLM Models

Select with `--model <shorthand>`:

| Shorthand | Model | Cost (in/out per M tokens) |
|-----------|-------|---------------------------|
| `flash-lite` (default) | `google/gemini-2.0-flash-lite-001` | $0.05 / $0.20 |
| `flash` | `google/gemini-2.5-flash-preview` | $0.15 / $0.60 |
| `gpt-mini` | `openai/gpt-4.1-mini` | $0.075 / $0.30 |
| `qwen` | `qwen/qwen3-235b-a22b` | $0.20 / $0.60 |
| `kimi` | `moonshot/kimi-k2` | $0.40 / $2.00 |
| `deepseek` | `deepseek/deepseek-chat-v3-0324` | $0.27 / $1.10 |
| `glm` | `thudm/glm-4-32b` | ~$0.10 / $0.10 |

Full OpenRouter model IDs are also accepted.

---

## Foundry Structure

Each book gets its own directory under `foundry/`:

```
foundry/pg174/                          # The Picture of Dorian Gray
├── pg174-images.html                   # Source HTML
├── codex.json                          # Parsed book (chapters → paragraphs)
├── chapters/                           # TTS chunks (400-500 char splits)
│   ├── metadata.json
│   └── chapter_NNN.json
├── characters.json                     # Accumulated profiles + image_prompt per character
├── locations.json                      # Location profiles + image_prompt
├── analysis/
│   └── chapter_NNN_analysis.json       # Scenes with character_details + scene_image_prompt
├── thumbnail_prompts.json              # Top 5 voted thumbnail prompts
├── images/                             # Generated images (characters, locations, scenes)
├── audio/                              # Generated TTS audio per chapter
└── videos/                             # Final assembled videos
```

---

## Running the Pipeline

### Full run (all 5 phases)
```bash
uv run python -m audiobook_agent.pipeline foundry/pg174/pg174-images.html
```

### Start from a specific phase
```bash
uv run python -m audiobook_agent.pipeline foundry/pg174 --from-phase 2
```

### Run specific phases only
```bash
uv run python -m audiobook_agent.pipeline foundry/pg174 --phases 3 4      # prompts + media
uv run python -m audiobook_agent.pipeline foundry/pg174 --phases 5         # upload only
uv run python -m audiobook_agent.pipeline foundry/pg174 --phases 1 2 3 4   # skip upload
```

### Key options
```bash
--model gpt-mini              # LLM model (default: flash-lite)
--style anime                 # Visual style (default: classical_illustration)
--timeout 1800                # ComfyUI timeout per image (seconds)
--media-steps 4 5             # Run only audio + video in phase 4
--privacy unlisted            # YouTube privacy (public/private/unlisted)
--no-resume                   # Re-run even if outputs exist
--quiet                       # Suppress verbose output
```

### Run individual phases
```bash
python -m audiobook_agent.parse_novel_langchain foundry/pg174/pg174-images.html
python -m audiobook_agent.analyze_entities foundry/pg174 --model gpt-mini
python -m audiobook_agent.generate_prompts foundry/pg174 --steps 1 2 3 4 --style anime
python -m audiobook_agent.generate_media foundry/pg174 --steps 0 1 2 3 4 5
```

---

## Project Structure

```
E3/
├── audiobook_agent/              # Core pipeline modules
│   ├── pipeline.py               # End-to-end orchestrator (phases 1-5)
│   ├── parse_novel_langchain.py  # Phase 1: HTML → codex.json
│   ├── analyze_entities.py       # Phase 2: scenes, characters, locations
│   ├── generate_prompts.py       # Phase 3: styled image prompts via LLM
│   ├── visual_styles.py          # Style definitions (prefix/suffix per style)
│   ├── generate_media.py         # Phase 4: ComfyUI + TTS + ffmpeg
│   ├── youtube_upload.py         # Phase 5: YouTube upload
│   └── qwen_tts_engine.py       # Qwen3-TTS narration engine
├── comfyui_agent/                # ComfyUI job queue agent
├── gutenberg_agent/              # Project Gutenberg book fetcher
├── foundry/                      # Book data directories (gitignored)
├── svg/                          # AI stamp SVG overlay assets
├── .env                          # API keys and config
└── config/                       # Environment-specific YAML configs
```

---

## Environment Variables

### Required
| Variable | Description |
|----------|-------------|
| `OPR_ROUTER_API_KEY` | OpenRouter API key for all LLM calls |

### ComfyUI (defaults work for local setup)
| Variable | Default | Description |
|----------|---------|-------------|
| `COMFYUI_HOST` | `127.0.0.1` | ComfyUI server host |
| `COMFYUI_PORT` | `8188` | ComfyUI server port |
| `COMFYUI_TIMEOUT` | `1800` | Per-image timeout (seconds) |
| `COMFYUI_OUTPUT_DIR` | ComfyUI default | Where SaveImage nodes write files |

### YouTube (for Phase 5)
| Variable | Description |
|----------|-------------|
| `YOUTUBE_CLIENT_ID` | Google OAuth client ID |
| `YOUTUBE_CLIENT_SECRET` | Google OAuth client secret |
| `YOUTUBE_CHANNEL_ID` | Target YouTube channel |
| `YOUTUBE_DEFAULT_PRIVACY` | `public` / `private` / `unlisted` |

### TTS (optional)
| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_DEVICE` | `cuda` | PyTorch device |
| `TTS_MODEL_SIZE` | `1.7B` | Qwen3-TTS model size |
| `TTS_LANGUAGE` | `English` | TTS language |
| `TTS_NARRATOR_SPEAKER` | `Ryan` | Default narrator voice |

---

## ComfyUI Agent

Standalone job queue that monitors folders for YAML configs → queues in SQLite → executes via ComfyUI API.

```bash
python -m comfyui_agent.cli start --ui-port 8081    # All services
python -m comfyui_agent.cli monitor                  # Folder watcher only
python -m comfyui_agent.cli run                      # Job executor only
```

Web UI at http://localhost:8081 — view queue, retry failed jobs, adjust priorities.

---

## YouTube Token Management

```bash
python youtube_token_manager.py status     # Check token status
python youtube_token_manager.py validate   # Validate credentials
python youtube_token_manager.py reauth     # Re-authenticate
```

Token stored in `youtube_credentials.json` (gitignored). First run triggers browser OAuth flow.

---

## Troubleshooting

- **ComfyUI connection refused** — ensure ComfyUI is running: `python main.py --listen 0.0.0.0 --port 8188`
- **Image generation timeouts** — increase with `--timeout 3600` or `COMFYUI_TIMEOUT` in `.env`
- **Access denied on Windows (.venv)** — close programs using the folder, `rmdir /s /q .venv`, recreate
