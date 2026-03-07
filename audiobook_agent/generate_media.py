#!/usr/bin/env python3
"""
Generate images and audio using ComfyUI for the E3 audiobook pipeline.

Reads from E3 foundry structure (foundry/{book_id}/):
  characters.json, locations.json, analysis/chapter_*_analysis.json,
  thumbnail_prompts.json, codex.json

Step 0: Character Portraits (1024x1024 square)
Step 1: Location Images (1280x720 landscape)
Step 2: Scene Images (one per scene, 1280x720)
Step 3: Thumbnails/Posters
Step 4: Audio (Qwen3-TTS Direct Inference)

Usage:
    python -m audiobook_agent.generate_media foundry/pg174
    python -m audiobook_agent.generate_media foundry/pg174 --steps 4
    python -m audiobook_agent.generate_media foundry/pg174 --steps 0 1 2 3 --comfyui-url http://127.0.0.1:8188
"""

import os
import sys
import re
import json
import time
import random
import argparse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Configuration — override via environment variables in .env
# ---------------------------------------------------------------------------

_host = os.environ.get("COMFYUI_HOST", "127.0.0.1")
_port = os.environ.get("COMFYUI_PORT", "8188")
DEFAULT_COMFYUI_URL = f"http://{_host}:{_port}"
DEFAULT_COMFYUI_TIMEOUT = int(os.environ.get("COMFYUI_TIMEOUT", "1800"))
VIDEO_GENERATION_TIMEOUT = 1800
AUDIO_GENERATION_TIMEOUT = 1800

# ComfyUI output directory — where SaveImage nodes write files.
# Set COMFYUI_OUTPUT_DIR in .env to match your local ComfyUI installation.
COMFYUI_OUTPUT_DIR = os.environ.get(
    "COMFYUI_OUTPUT_DIR",
    r"D:\Projects\KingdomOfViSuReNa\alpha\ComfyUI_windows_portable\ComfyUI\output",
)

# Workflow file directory and individual workflow names.
# Override via COMFYUI_WORKFLOWS_DIR or individual WF_* env vars.
_WF_DIR = Path(os.environ.get(
    "COMFYUI_WORKFLOWS_DIR",
    r"D:\Projects\KingdomOfViSuReNa\alpha\house_of_novels\workflows",
))

COMFYUI_WORKFLOWS = {
    "character":            str(_WF_DIR / os.environ.get("WF_CHARACTER",         "z_image_turbo_characters.json")),
    "location":             str(_WF_DIR / os.environ.get("WF_LOCATION",          "z_image_turbo_locations.json")),
    "scene":                str(_WF_DIR / os.environ.get("WF_SCENE",             "z_image_turbo_example.json")),
    "scene_location_edit":  str(_WF_DIR / os.environ.get("WF_SCENE_LOC_EDIT",   "image_qwen_image_edit_location.json")),
    "scene_character_edit": str(_WF_DIR / os.environ.get("WF_SCENE_CHAR_EDIT",  "image_qwen_image_edit_2511_two_images.json")),
    "thumbnail":            str(_WF_DIR / os.environ.get("WF_THUMBNAIL",         "z_image_turbo_example.json")),
}

# TTS — Qwen3-TTS Direct Inference (Step 4)
TTS_NARRATION_MODE          = os.environ.get("TTS_NARRATION_MODE", "single_narrator")
TTS_DEVICE                  = os.environ.get("TTS_DEVICE", "cuda")
TTS_PRECISION               = os.environ.get("TTS_PRECISION", "bfloat16")
TTS_MODEL_SIZE              = os.environ.get("TTS_MODEL_SIZE", "1.7B")
TTS_LANGUAGE                = os.environ.get("TTS_LANGUAGE", "English")
TTS_PAUSE_BETWEEN_SPEAKERS  = int(os.environ.get("TTS_PAUSE_BETWEEN_SPEAKERS_MS", "500"))
TTS_PAUSE_WITHIN_SPEAKER    = int(os.environ.get("TTS_PAUSE_WITHIN_SPEAKER_MS", "250"))
TTS_LORA_ADAPTER_DIR        = os.environ.get("TTS_LORA_ADAPTER_DIR", "")
TTS_LORA_FALLBACK_TO_DESIGN = os.environ.get("TTS_LORA_FALLBACK_TO_DESIGN", "true").lower() == "true"
TTS_NARRATOR_VOICE = {
    "type":            os.environ.get("TTS_NARRATOR_TYPE", "custom"),
    "speaker":         os.environ.get("TTS_NARRATOR_SPEAKER", "Ryan"),
    "clone_ref_audio": os.environ.get("TTS_NARRATOR_CLONE_AUDIO", ""),
    "clone_ref_text":  os.environ.get("TTS_NARRATOR_CLONE_TEXT", ""),
}

# SVG AI-disclosure stamp (applied to generated thumbnails/posters)
SVG_STAMP_PATH = Path(__file__).parent.parent / "svg" / "AI_stamp_1.svg"

# ---------------------------------------------------------------------------
# Local imports — no house_of_novels dependencies
# ---------------------------------------------------------------------------
from audiobook_agent.comfyui_trigger import trigger_comfy


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    codex_path: Path
    success: bool
    poster_count: int = 0
    character_portrait_count: int = 0
    location_image_count: int = 0
    scene_image_count: int = 0
    shot_frame_count: int = 0
    video_count: int = 0
    audio_count: int = 0
    step_timings: dict = field(default_factory=dict)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def get_workflow_path(workflow_type: str) -> str:
    """Return absolute path to a ComfyUI workflow JSON."""
    path = COMFYUI_WORKFLOWS.get(workflow_type)
    if not path:
        raise ValueError(
            f"Unknown workflow type: {workflow_type!r}. "
            f"Available: {list(COMFYUI_WORKFLOWS)}"
        )
    return path


def generate_seed() -> int:
    """Generate a random 15-digit seed for ComfyUI."""
    return random.randint(100_000_000_000_000, 999_999_999_999_999)


def sanitize_filename(name: str) -> str:
    """Convert a name to lowercase-with-underscores safe for filenames."""
    clean = name.lower().replace(" ", "_").replace("'", "")
    return re.sub(r"[^a-z0-9_]", "", clean)


def get_timestamp_from_codex_path(codex_path: Path) -> str:
    """Extract timestamp/ID from codex path for output organisation."""
    name = codex_path.stem  # e.g. codex_20260305104324
    if "_" in name:
        return name.split("_", 1)[1]
    return codex_path.parent.name


def load_codex(codex_path: Path) -> dict:
    with open(codex_path, encoding="utf-8") as f:
        return json.load(f)


def save_codex(codex: dict, codex_path: Path) -> None:
    with open(codex_path, "w", encoding="utf-8") as f:
        json.dump(codex, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Image generation helpers
# ---------------------------------------------------------------------------

def _generate_image(
    prompt_text: str,
    filename_prefix: str,
    label: str,
    workflow_path: str,
    comfyui_url: str,
    timeout: int,
) -> tuple:
    """Generate a single image.

    Returns (success, generation_data):
        success=True  → completed
        success=False → failed (non-fatal)
        success=None  → connection error (fatal)
    """
    seed = generate_seed()
    try:
        result = trigger_comfy(
            workflow_json_path=workflow_path,
            replacements={
                "10_filename_prefix": filename_prefix,
                "5_seed": seed,
                "11_text": prompt_text,
            },
            comfyui_url=comfyui_url,
            timeout=timeout,
        )
        gen_data = {
            "prompt_id": result["prompt_id"],
            "status": result["status"],
            "execution_time": result["execution_time"],
            "output_path": f"{filename_prefix}_00001_.png",
            "seed": seed,
            "generated_at": datetime.now().isoformat(),
        }
        if result["status"] == "completed":
            print(f"        Completed in {result['execution_time']:.1f}s")
            return True, gen_data
        else:
            err = result.get("error", "Unknown error")
            print(f"        Failed: {err}")
            gen_data["error"] = err
            return False, gen_data

    except ConnectionError as e:
        print(f"        Connection error: {e}")
        return None, {"status": "error", "error": str(e), "generated_at": datetime.now().isoformat()}
    except TimeoutError as e:
        print(f"        Timeout: {e}")
        return False, {"status": "timeout", "error": str(e), "seed": seed, "generated_at": datetime.now().isoformat()}
    except Exception as e:
        print(f"        Error: {e}")
        return False, {"status": "error", "error": str(e), "generated_at": datetime.now().isoformat()}


def _find_comfyui_output(filename_prefix: str) -> Optional[Path]:
    """Find the latest ComfyUI output file matching a SaveImage prefix.

    ComfyUI appends ``_{NNNNN}_.png`` to the prefix.
    Returns the most recently modified match, or None.
    """
    parent = (Path(COMFYUI_OUTPUT_DIR) / filename_prefix).parent
    stem = Path(filename_prefix).name
    if not parent.exists():
        return None
    matches = list(parent.glob(f"{stem}_*_.png"))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def _apply_ai_stamp(
    image_path: Path,
    svg_path: Path,
    corner: str = "top-right",
    scale: float = 0.15,
    padding_fraction: float = 0.02,
) -> bool:
    """Overlay an SVG AI-disclosure stamp onto a generated image.

    Args:
        image_path: Path to the PNG to stamp.
        svg_path: Path to the SVG stamp file.
        corner: "top-right" | "top-left" | "bottom-right" | "bottom-left"
        scale: Stamp height as a fraction of image height (0.15 = 15%).
        padding_fraction: Edge padding as fraction of image height.

    Returns True on success, False on error.
    """
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        from PIL import Image
        import io

        poster = Image.open(image_path).convert("RGBA")
        width, height = poster.size
        stamp_size = max(32, int(height * scale))
        pad = max(4, int(height * padding_fraction))

        drawing = svg2rlg(str(svg_path))
        if drawing is None:
            print(f"      WARNING: Could not parse SVG: {svg_path}")
            return False

        sx = stamp_size / drawing.width
        sy = stamp_size / drawing.height
        drawing.width = stamp_size
        drawing.height = stamp_size
        drawing.scale(sx, sy)

        # Double-render trick to extract true alpha (white bg + black bg)
        png_white = renderPM.drawToString(drawing, fmt="PNG", bg=0xFFFFFF)
        png_black = renderPM.drawToString(drawing, fmt="PNG", bg=0x000000)
        img_w = Image.open(io.BytesIO(png_white)).convert("RGB")
        img_b = Image.open(io.BytesIO(png_black)).convert("RGB")

        stamp = Image.new("RGBA", img_w.size)
        pw, pb, ps = img_w.load(), img_b.load(), stamp.load()
        for y in range(stamp.height):
            for x in range(stamp.width):
                rw, gw, bw = pw[x, y]
                rb, gb, bb = pb[x, y]
                a = max(0, min(255, 255 - ((rw - rb) + (gw - gb) + (bw - bb)) // 3))
                if a < 2:
                    ps[x, y] = (0, 0, 0, 0)
                else:
                    ps[x, y] = (
                        min(255, rb * 255 // a),
                        min(255, gb * 255 // a),
                        min(255, bb * 255 // a),
                        a,
                    )

        if corner == "top-right":
            pos = (width - stamp_size - pad, pad)
        elif corner == "top-left":
            pos = (pad, pad)
        elif corner == "bottom-right":
            pos = (width - stamp_size - pad, height - stamp_size - pad)
        elif corner == "bottom-left":
            pos = (pad, height - stamp_size - pad)
        else:
            pos = (width - stamp_size - pad, pad)

        poster.paste(stamp, pos, stamp)
        poster.convert("RGB").save(image_path, "PNG")
        return True

    except Exception as e:
        print(f"      WARNING: Failed to apply AI stamp: {e}")
        return False


# ---------------------------------------------------------------------------
# Location-edit layer (single-image Qwen Image Edit workflow)
# ---------------------------------------------------------------------------

def _generate_location_layer(
    prompt: str,
    base_image_name: str,
    filename_prefix: str,
    label: str,
    workflow_path: str,
    comfyui_url: str,
    timeout: int,
) -> tuple:
    seed = generate_seed()
    try:
        result = trigger_comfy(
            workflow_json_path=workflow_path,
            replacements={
                "78_image": base_image_name,
                "102:76_prompt": prompt,
                "102:3_seed": seed,
                "60_filename_prefix": filename_prefix,
            },
            comfyui_url=comfyui_url,
            timeout=timeout,
        )
        gen_data = {
            "prompt_id": result["prompt_id"],
            "status": result["status"],
            "execution_time": result["execution_time"],
            "filename_prefix": filename_prefix,
            "seed": seed,
            "layer_type": "location",
            "input_image": base_image_name,
            "generated_at": datetime.now().isoformat(),
        }
        if result["status"] == "completed":
            output_path = _find_comfyui_output(filename_prefix)
            gen_data["output_path"] = str(output_path) if output_path else ""
            print(f"        Completed in {result['execution_time']:.1f}s")
            return True, gen_data
        else:
            err = result.get("error", "Unknown error")
            print(f"        Failed: {err}")
            gen_data["error"] = err
            return False, gen_data
    except ConnectionError as e:
        print(f"        Connection error: {e}")
        return None, {"status": "error", "error": str(e), "layer_type": "location",
                       "generated_at": datetime.now().isoformat()}
    except TimeoutError as e:
        print(f"        Timeout: {e}")
        return False, {"status": "timeout", "error": str(e), "seed": seed,
                        "layer_type": "location", "generated_at": datetime.now().isoformat()}
    except Exception as e:
        print(f"        Error: {e}")
        return False, {"status": "error", "error": str(e), "layer_type": "location",
                        "generated_at": datetime.now().isoformat()}


# ---------------------------------------------------------------------------
# Character-composite layer (two-image Qwen Image Edit workflow)
# ---------------------------------------------------------------------------

def _generate_character_layer(
    prompt: str,
    scene_image_name: str,
    portrait_image_name: str,
    filename_prefix: str,
    label: str,
    workflow_path: str,
    comfyui_url: str,
    timeout: int,
) -> tuple:
    seed = generate_seed()
    try:
        result = trigger_comfy(
            workflow_json_path=workflow_path,
            replacements={
                "41_image": scene_image_name,
                "83_image": portrait_image_name,
                "91:68_prompt": prompt,
                "91:65_seed": seed,
                "92_filename_prefix": filename_prefix,
            },
            comfyui_url=comfyui_url,
            timeout=timeout,
        )
        gen_data = {
            "prompt_id": result["prompt_id"],
            "status": result["status"],
            "execution_time": result["execution_time"],
            "filename_prefix": filename_prefix,
            "seed": seed,
            "layer_type": "character",
            "input_scene": scene_image_name,
            "input_portrait": portrait_image_name,
            "generated_at": datetime.now().isoformat(),
        }
        if result["status"] == "completed":
            output_path = _find_comfyui_output(filename_prefix)
            gen_data["output_path"] = str(output_path) if output_path else ""
            print(f"        Completed in {result['execution_time']:.1f}s")
            return True, gen_data
        else:
            err = result.get("error", "Unknown error")
            print(f"        Failed: {err}")
            gen_data["error"] = err
            return False, gen_data
    except ConnectionError as e:
        print(f"        Connection error: {e}")
        return None, {"status": "error", "error": str(e), "layer_type": "character",
                       "generated_at": datetime.now().isoformat()}
    except TimeoutError as e:
        print(f"        Timeout: {e}")
        return False, {"status": "timeout", "error": str(e), "seed": seed,
                        "layer_type": "character", "generated_at": datetime.now().isoformat()}
    except Exception as e:
        print(f"        Error: {e}")
        return False, {"status": "error", "error": str(e), "layer_type": "character",
                        "generated_at": datetime.now().isoformat()}


# ---------------------------------------------------------------------------
# Two-pass scene pipeline helpers
# ---------------------------------------------------------------------------

def _build_layered_result(layers_data: list, total_attempted: int, error: str = None) -> dict:
    completed = sum(1 for l in layers_data if l.get("status") == "completed")
    result = {
        "pipeline": "layered",
        "status": "error",
        "output_path": "",
        "total_layers_attempted": total_attempted,
        "total_layers_completed": completed,
        "layers": layers_data,
        "generated_at": datetime.now().isoformat(),
    }
    if error:
        result["error"] = error
    return result


def _run_location_pass(
    scene_prompt_data: dict,
    timestamp: str,
    ch_num: int,
    sc_num: int,
    comfyui_url: str,
    timeout: int,
    shot_num: int = 0,
) -> dict:
    """Pass 1: resolve base location image, apply location edit if needed."""
    location_id = scene_prompt_data.get("location_id", "")
    location_layer = scene_prompt_data.get("location_layer", {})
    location_name = scene_prompt_data.get("location_name", "unknown")
    shot_prefix = f"ch{ch_num:02d}_sc{sc_num:02d}_sh{shot_num:02d}"

    base_loc_prefix = f"api/{timestamp}/locations/{location_id}"
    current_scene_path = _find_comfyui_output(base_loc_prefix)
    if current_scene_path is None:
        error_msg = f"Base location image not found: {base_loc_prefix}"
        print(f"        {error_msg}")
        return {"current_scene_path": None, "shot_prefix": shot_prefix,
                "layer_index": 0, "layers_data": [], "location_ok": False, "error": error_msg}

    layer_index = 0
    layers_data = []

    if location_layer.get("requires_modification"):
        loc_prefix = f"api/{timestamp}/scenes/{shot_prefix}_layer{layer_index:02d}_loc"
        print(f"      Layer {layer_index}: Location edit ({location_name})")

        success, gen_data = _generate_location_layer(
            prompt=location_layer.get("prompt", ""),
            base_image_name=str(current_scene_path),
            filename_prefix=loc_prefix,
            label=f"{shot_prefix}_layer{layer_index:02d}_loc",
            workflow_path=get_workflow_path("scene_location_edit"),
            comfyui_url=comfyui_url,
            timeout=timeout,
        )
        gen_data["layer_index"] = layer_index
        layers_data.append(gen_data)

        if success is None:
            return {"current_scene_path": None, "shot_prefix": shot_prefix,
                    "layer_index": layer_index + 1, "layers_data": layers_data, "location_ok": None}
        if not success:
            return {"current_scene_path": None, "shot_prefix": shot_prefix,
                    "layer_index": layer_index + 1, "layers_data": layers_data, "location_ok": False}

        current_scene_path = _find_comfyui_output(loc_prefix)
        if current_scene_path is None:
            error_msg = f"Location layer output not found: {loc_prefix}"
            print(f"        {error_msg}")
            return {"current_scene_path": None, "shot_prefix": shot_prefix,
                    "layer_index": layer_index + 1, "layers_data": layers_data,
                    "location_ok": False, "error": error_msg}
        layer_index += 1

    return {"current_scene_path": current_scene_path, "shot_prefix": shot_prefix,
            "layer_index": layer_index, "layers_data": layers_data, "location_ok": True}


def _run_character_pass(
    scene_state: dict,
    scene_prompt_data: dict,
    timestamp: str,
    comfyui_url: str,
    timeout: int,
) -> tuple:
    """Pass 2: composite each character layer onto the scene."""
    current_scene_path = scene_state["current_scene_path"]
    shot_prefix = scene_state["shot_prefix"]
    layer_index = scene_state["layer_index"]
    layers_data = list(scene_state["layers_data"])

    character_layers = scene_prompt_data.get("character_layers", [])
    location_layer = scene_prompt_data.get("location_layer", {})
    total_layers = (1 if location_layer.get("requires_modification") else 0) + len(character_layers)
    char_edit_workflow = get_workflow_path("scene_character_edit")
    last_layer_prefix = ""

    for i, char_layer in enumerate(character_layers):
        char_id = char_layer.get("character_id", f"char_{i+1:03d}")
        char_name = char_layer.get("character_name", char_id)
        char_prompt = char_layer.get("prompt", "")

        portrait_prefix = f"api/{timestamp}/characters/{char_id}"
        portrait_path = _find_comfyui_output(portrait_prefix)
        if portrait_path is None:
            error_msg = f"Character portrait not found: {portrait_prefix}"
            print(f"        {error_msg}")
            gen_data = {"layer_type": "character", "layer_index": layer_index,
                        "character_id": char_id, "character_name": char_name,
                        "status": "error", "error": error_msg,
                        "generated_at": datetime.now().isoformat()}
            layers_data.append(gen_data)
            return False, _build_layered_result(layers_data, layer_index + 1)

        char_prefix = f"api/{timestamp}/scenes/{shot_prefix}_layer{layer_index:02d}_{char_id}"
        print(f"      Layer {layer_index}: Character {char_name} ({char_id})")

        success, gen_data = _generate_character_layer(
            prompt=char_prompt,
            scene_image_name=str(current_scene_path),
            portrait_image_name=str(portrait_path),
            filename_prefix=char_prefix,
            label=f"{shot_prefix}_layer{layer_index:02d}_{char_id}",
            workflow_path=char_edit_workflow,
            comfyui_url=comfyui_url,
            timeout=timeout,
        )
        gen_data["layer_index"] = layer_index
        gen_data["character_id"] = char_id
        gen_data["character_name"] = char_name
        layers_data.append(gen_data)

        if success is None:
            return None, _build_layered_result(layers_data, layer_index + 1)
        if not success:
            return False, _build_layered_result(layers_data, layer_index + 1)

        current_scene_path = _find_comfyui_output(char_prefix)
        if current_scene_path is None:
            print(f"        Character layer output not found: {char_prefix}")
            return False, _build_layered_result(layers_data, layer_index + 1)
        last_layer_prefix = char_prefix
        layer_index += 1

    final_path = _find_comfyui_output(last_layer_prefix) if last_layer_prefix else current_scene_path
    return True, {
        "pipeline": "layered",
        "status": "completed",
        "output_path": str(final_path) if final_path else "",
        "final_layer_prefix": last_layer_prefix,
        "total_layers_attempted": total_layers,
        "total_layers_completed": total_layers,
        "layers": layers_data,
        "generated_at": datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Error result builder
# ---------------------------------------------------------------------------

def _make_error_result(codex_path: Path, error: str, **counts) -> GenerationResult:
    return GenerationResult(
        codex_path=codex_path,
        success=False,
        error=error,
        poster_count=counts.get("poster_count", 0),
        character_portrait_count=counts.get("character_portrait_count", 0),
        location_image_count=counts.get("location_image_count", 0),
        scene_image_count=counts.get("scene_image_count", 0),
        shot_frame_count=counts.get("shot_frame_count", 0),
        video_count=counts.get("video_count", 0),
        audio_count=counts.get("audio_count", 0),
    )


# ---------------------------------------------------------------------------
# Step name constants
# ---------------------------------------------------------------------------

STEP_NAMES = {
    0: "Character Portraits",
    1: "Location Images",
    2: "Scene Images",
    3: "Thumbnails/Posters",
    4: "Audio (Qwen3-TTS Direct)",
    5: "Video (future)",
}


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

def run_generation(
    book_dir: Path,
    comfyui_url: str = None,
    steps: list = None,
    timeout: int = None,
) -> GenerationResult:
    """
    Generate images and media from an E3 foundry book directory.

    Reads prompts from:
      - characters.json         → Step 0 (character portraits)
      - locations.json          → Step 1 (location images)
      - analysis/chapter_*.json → Step 2 (scene images) + Step 4 (audio)
      - thumbnail_prompts.json  → Step 3 (thumbnails/posters)
      - codex.json              → book title for audio

    Args:
        book_dir: Path to foundry book directory (e.g. foundry/pg174).
        comfyui_url: ComfyUI API URL (default from env / config).
        steps: Step numbers to run; default [0, 1, 2, 3, 4].
        timeout: Per-generation timeout in seconds.

    Returns:
        GenerationResult with counts and status.
    """
    book_dir = Path(book_dir)
    book_id = book_dir.name          # e.g. "pg174"
    codex = load_codex(book_dir / "codex.json")
    book_title = codex.get("title", "Unknown")

    comfyui_url = comfyui_url or DEFAULT_COMFYUI_URL
    timeout = timeout or DEFAULT_COMFYUI_TIMEOUT
    steps_to_run = list(steps) if steps is not None else [0, 1, 2, 3, 4]

    analysis_dir = book_dir / "analysis"

    print(f"\n{'='*60}")
    print("MEDIA GENERATION")
    print(f"{'='*60}")
    print(f">>> Book dir : {book_dir}")
    print(f">>> Book ID  : {book_id}")
    print(f">>> Title    : {book_title}")
    print(f">>> ComfyUI  : {comfyui_url}")
    print(f">>> Timeout  : {timeout}s")
    print(f">>> Steps    : {', '.join(f'{s}-{STEP_NAMES[s]}' for s in steps_to_run if s in STEP_NAMES)}")

    metadata_path = book_dir / "generation_metadata.json"
    metadata = {
        "book_id": book_id,
        "comfyui_url": comfyui_url,
        "workflows_used": {},
        "steps_executed": [],
        "generated_at": datetime.now().isoformat(),
    }

    metadata = {
        "comfyui_url": comfyui_url,
        "workflows_used": {},
        "steps_executed": [],
        "generated_at": datetime.now().isoformat(),
    }
    step_timings: dict = {}

    # Running counters
    character_portrait_count = 0
    location_image_count = 0
    scene_image_count = 0
    poster_count = 0
    audio_count = 0
    video_count = 0
    shot_frame_count = 0

    def _counts():
        return dict(
            character_portrait_count=character_portrait_count,
            location_image_count=location_image_count,
            scene_image_count=scene_image_count,
            poster_count=poster_count,
            audio_count=audio_count,
            video_count=video_count,
            shot_frame_count=shot_frame_count,
        )

    # =========================================================================
    # Step 0: Character Portraits
    # =========================================================================
    if 0 in steps_to_run:
        step_start = time.time()
        char_workflow = get_workflow_path("character")
        metadata["workflows_used"]["character"] = Path(char_workflow).name

        print(f"\n{'='*60}")
        print("STEP 0: Character Portraits")
        print(f"  Workflow: {Path(char_workflow).name}")
        print(f"{'='*60}")

        chars_path = book_dir / "characters.json"
        if not chars_path.exists():
            print(">>> characters.json not found, skipping")
        else:
            characters = json.load(open(chars_path, encoding="utf-8"))
            chars_with_prompts = [(n, c) for n, c in characters.items()
                                   if c.get("image_prompt", {}).get("prompt")]
            if not chars_with_prompts:
                print(">>> No character image prompts found — run generate_prompts.py --steps 1 first")
            else:
                print(f">>> Generating {len(chars_with_prompts)} character portraits...")
                for i, (char_name, char) in enumerate(chars_with_prompts):
                    prompt_text = char["image_prompt"]["prompt"]
                    char_id = sanitize_filename(char.get("canonical_name", char_name))
                    filename_prefix = f"api/{book_id}/characters/{char_id}"
                    print(f"    [{i+1}/{len(chars_with_prompts)}] {char_name}")
                    success, gen_data = _generate_image(
                        prompt_text, filename_prefix, char_name,
                        workflow_path=char_workflow,
                        comfyui_url=comfyui_url,
                        timeout=timeout,
                    )
                    char["image_prompt"]["generation"] = gen_data
                    if success is None:
                        print(f"\n>>> ERROR: Cannot connect to ComfyUI at {comfyui_url}")
                        return _make_error_result(book_dir, f"Cannot connect to ComfyUI: {gen_data.get('error')}", **_counts())
                    elif success:
                        character_portrait_count += 1

                print(f">>> Characters complete: {character_portrait_count}/{len(chars_with_prompts)}")
                with open(chars_path, "w", encoding="utf-8") as f:
                    json.dump(characters, f, indent=2, ensure_ascii=False)

        metadata["steps_executed"].append(0)
        step_timings["step0_characters"] = round(time.time() - step_start, 2)
        print(f">>> Step 0 complete ({step_timings['step0_characters']:.1f}s)")

    # =========================================================================
    # Step 1: Location Images
    # =========================================================================
    if 1 in steps_to_run:
        step_start = time.time()
        loc_workflow = get_workflow_path("location")
        metadata["workflows_used"]["location"] = Path(loc_workflow).name

        print(f"\n{'='*60}")
        print("STEP 1: Location Images")
        print(f"  Workflow: {Path(loc_workflow).name}")
        print(f"{'='*60}")

        locs_path = book_dir / "locations.json"
        if not locs_path.exists():
            print(">>> locations.json not found, skipping")
        else:
            locations = json.load(open(locs_path, encoding="utf-8"))
            locs_with_prompts = [(n, l) for n, l in locations.items()
                                  if l.get("image_prompt", {}).get("prompt")]
            if not locs_with_prompts:
                print(">>> No location image prompts found — run generate_prompts.py --steps 2 first")
            else:
                print(f">>> Generating {len(locs_with_prompts)} location images...")
                for i, (loc_name, loc) in enumerate(locs_with_prompts):
                    prompt_text = loc["image_prompt"]["prompt"]
                    loc_id = sanitize_filename(loc.get("canonical_name", loc_name))
                    filename_prefix = f"api/{book_id}/locations/{loc_id}"
                    print(f"    [{i+1}/{len(locs_with_prompts)}] {loc_name}")
                    success, gen_data = _generate_image(
                        prompt_text, filename_prefix, loc_name,
                        workflow_path=loc_workflow,
                        comfyui_url=comfyui_url,
                        timeout=timeout,
                    )
                    loc["image_prompt"]["generation"] = gen_data
                    if success is None:
                        print(f"\n>>> ERROR: Cannot connect to ComfyUI at {comfyui_url}")
                        return _make_error_result(book_dir, f"Cannot connect to ComfyUI: {gen_data.get('error')}", **_counts())
                    elif success:
                        location_image_count += 1

                print(f">>> Locations complete: {location_image_count}/{len(locs_with_prompts)}")
                with open(locs_path, "w", encoding="utf-8") as f:
                    json.dump(locations, f, indent=2, ensure_ascii=False)

        metadata["steps_executed"].append(1)
        step_timings["step1_locations"] = round(time.time() - step_start, 2)
        print(f">>> Step 1 complete ({step_timings['step1_locations']:.1f}s)")

    # =========================================================================
    # Step 2: Scene Images (Flat — one image per scene)
    # =========================================================================
    if 2 in steps_to_run:
        step_start = time.time()
        scene_workflow = get_workflow_path("scene")

        print(f"\n{'='*60}")
        print("STEP 2: Scene Images")
        print(f"  Workflow: {Path(scene_workflow).name}")
        print(f"{'='*60}")

        if not analysis_dir.exists():
            print(">>> analysis/ directory not found, skipping")
        else:
            analysis_files = sorted(analysis_dir.glob("chapter_*_analysis.json"))
            # Count total scenes that have prompts
            total_scenes = sum(
                1 for af in analysis_files
                for sc in json.load(open(af, encoding="utf-8")).get("scenes", [])
                if sc.get("scene_image_prompt", {}).get("prompt")
            )
            if total_scenes == 0:
                print(">>> No scene image prompts found — run generate_prompts.py --steps 3 first")
            else:
                print(f">>> Generating {total_scenes} scene images...")
                scene_global_idx = 0

                for analysis_file in analysis_files:
                    analysis = json.load(open(analysis_file, encoding="utf-8"))
                    ch_num = analysis.get("chapter_index", 0)
                    modified = False

                    for scene in analysis.get("scenes", []):
                        sc_num = scene.get("scene_number", 0)
                        prompt_text = scene.get("scene_image_prompt", {}).get("prompt", "")
                        if not prompt_text:
                            continue
                        scene_global_idx += 1
                        location = scene.get("location", "unknown")
                        filename_prefix = f"api/{book_id}/scenes/ch{ch_num:02d}_sc{sc_num:02d}"
                        print(f"    [{scene_global_idx}/{total_scenes}] Ch{ch_num} Sc{sc_num} — {location}")
                        success, gen_data = _generate_image(
                            prompt_text, filename_prefix, f"ch{ch_num}_sc{sc_num}",
                            workflow_path=scene_workflow, comfyui_url=comfyui_url, timeout=timeout,
                        )
                        scene["scene_image_prompt"]["generation"] = gen_data
                        modified = True
                        if success is None:
                            print(f"\n>>> ERROR: Cannot connect to ComfyUI at {comfyui_url}")
                            with open(analysis_file, "w", encoding="utf-8") as f:
                                json.dump(analysis, f, indent=2, ensure_ascii=False)
                            return _make_error_result(book_dir, f"Cannot connect to ComfyUI: {gen_data.get('error', 'unknown')}", **_counts())
                        elif success:
                            scene_image_count += 1

                    if modified:
                        with open(analysis_file, "w", encoding="utf-8") as f:
                            json.dump(analysis, f, indent=2, ensure_ascii=False)

                print(f">>> Scene images complete: {scene_image_count}/{total_scenes}")

        metadata["steps_executed"].append(2)
        step_timings["step2_scenes"] = round(time.time() - step_start, 2)
        print(f">>> Step 2 complete ({step_timings['step2_scenes']:.1f}s)")

    # =========================================================================
    # Step 3: Thumbnails / Posters
    # =========================================================================
    if 3 in steps_to_run:
        step_start = time.time()
        thumb_workflow = get_workflow_path("thumbnail")
        metadata["workflows_used"]["thumbnail"] = Path(thumb_workflow).name

        print(f"\n{'='*60}")
        print("STEP 3: Thumbnails/Posters")
        print(f"  Workflow: {Path(thumb_workflow).name}")
        print(f"{'='*60}")

        thumb_path = book_dir / "thumbnail_prompts.json"
        if not thumb_path.exists():
            print(">>> thumbnail_prompts.json not found, skipping")
            print(">>> (Run generate_prompts.py --steps 4 to generate thumbnail prompts)")
        else:
            thumb_data = json.load(open(thumb_path, encoding="utf-8"))
            poster_prompts = thumb_data.get("prompts", [])  # list of strings (top 5)
            if not poster_prompts:
                print(">>> No thumbnail prompts found in thumbnail_prompts.json")
            else:
                print(f">>> Generating {len(poster_prompts)} poster images...")
                poster_gens = []
                for i, prompt_text in enumerate(poster_prompts):
                    if not prompt_text:
                        continue
                    filename_prefix = f"api/{book_id}/posters/poster_{i+1:04d}"
                    print(f"    [{i+1}/{len(poster_prompts)}] poster_{i+1}")
                    success, gen_data = _generate_image(
                        prompt_text, filename_prefix, f"poster_{i+1}",
                        workflow_path=thumb_workflow, comfyui_url=comfyui_url, timeout=timeout,
                    )
                    if success is None:
                        print(f"\n>>> ERROR: Cannot connect to ComfyUI at {comfyui_url}")
                        thumb_data["poster_generations"] = poster_gens
                        with open(thumb_path, "w", encoding="utf-8") as f:
                            json.dump(thumb_data, f, indent=2, ensure_ascii=False)
                        return _make_error_result(book_dir, f"Cannot connect to ComfyUI: {gen_data.get('error')}", **_counts())
                    elif success:
                        poster_count += 1
                        output_file = _find_comfyui_output(filename_prefix)
                        if output_file and SVG_STAMP_PATH.exists():
                            if _apply_ai_stamp(output_file, SVG_STAMP_PATH):
                                print(f"      AI stamp applied to {output_file.name}")
                            gen_data["stamped"] = True
                        elif not SVG_STAMP_PATH.exists():
                            print(f"      WARNING: SVG stamp not found at {SVG_STAMP_PATH}")
                    poster_gens.append({"prompt_index": i, "filename_prefix": filename_prefix,
                                        "generation": gen_data})

                print(f">>> Posters complete: {poster_count}/{len(poster_prompts)}")
                thumb_data["poster_generations"] = poster_gens
                with open(thumb_path, "w", encoding="utf-8") as f:
                    json.dump(thumb_data, f, indent=2, ensure_ascii=False)

        metadata["steps_executed"].append(3)
        step_timings["step3_thumbnails"] = round(time.time() - step_start, 2)
        print(f">>> Step 3 complete ({step_timings['step3_thumbnails']:.1f}s)")

    # =========================================================================
    # Step 4: Audio (Qwen3-TTS Direct Inference)
    # =========================================================================
    if 4 in steps_to_run:
        step_start = time.time()
        print(f"\n{'='*60}")
        print("STEP 4: Audio (Qwen3-TTS Direct Inference)")
        print(f"{'='*60}")
        print(f"    Mode: {TTS_NARRATION_MODE}")
        print(f"    Device: {TTS_DEVICE}, Precision: {TTS_PRECISION}")
        print(f"    Model: Qwen3-TTS-{TTS_MODEL_SIZE}")

        try:
            from audiobook_agent.qwen_tts_engine import (
                QwenTTSEngine, CustomVoiceConfig, CloneVoiceConfig, LoRAVoiceConfig,
            )
        except ImportError as e:
            print(f">>> ERROR: Cannot import QwenTTSEngine: {e}")
            print(">>> Ensure qwen_tts, torch, soundfile, numpy are installed.")
            return _make_error_result(book_dir, f"TTS import error: {e}", **_counts())

        if not analysis_dir.exists():
            print(">>> analysis/ directory not found, skipping audio")
        else:
            # Build narrator voice config
            if TTS_NARRATOR_VOICE.get("type") == "clone":
                narrator_config = CloneVoiceConfig(
                    ref_audio=TTS_NARRATOR_VOICE.get("clone_ref_audio", ""),
                    ref_text=TTS_NARRATOR_VOICE.get("clone_ref_text", ""),
                )
            else:
                narrator_config = CustomVoiceConfig(
                    speaker=TTS_NARRATOR_VOICE.get("speaker", "Ryan"),
                )

            tts_engine = QwenTTSEngine(
                device=TTS_DEVICE,
                precision=TTS_PRECISION,
                model_size=TTS_MODEL_SIZE,
                narrator_voice=narrator_config,
                narration_mode=TTS_NARRATION_MODE,
                pause_between_speakers_ms=TTS_PAUSE_BETWEEN_SPEAKERS,
                pause_within_speaker_ms=TTS_PAUSE_WITHIN_SPEAKER,
            )

            lora_dir = (TTS_LORA_ADAPTER_DIR or str(book_dir / "lora_adapters")) if TTS_NARRATION_MODE == "lora" else None
            voice_map = tts_engine.setup_voice_map(
                characters=[],          # E3 doesn't have structured characters for TTS
                narrator_config=narrator_config,
                lora_adapter_dir=lora_dir,
                fallback_to_design=TTS_LORA_FALLBACK_TO_DESIGN,
            )
            print(f"    Voice map: {len(voice_map)} entries")

            audio_dir = book_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)

            # Clear stale files from previous runs
            old_wavs = list(audio_dir.glob("*.wav"))
            if old_wavs:
                for old_wav in old_wavs:
                    old_wav.unlink()
                print(f"    Cleared {len(old_wavs)} old audio files")

            audio_items = []
            audio_generated_count = 0
            seq_num = 0

            # Book title audio
            if book_title:
                seq_num += 1
                title_path = audio_dir / f"{seq_num:03d}_title.wav"
                print(f"\n    [{seq_num}] Book Title: \"{book_title}\"")
                title_script = [{"speaker": "NARRATOR", "text": book_title,
                                 "instruct": "Grand, resonant announcement with gravitas."}]
                success, duration = tts_engine.generate_scene_audio(
                    audio_script=title_script, voice_map=voice_map,
                    output_path=title_path, language=TTS_LANGUAGE,
                )
                audio_items.append({
                    "sequence": seq_num, "type": "title",
                    "status": "completed" if success else "failed",
                    "output_path": str(title_path), "duration": duration,
                    "generated_at": datetime.now().isoformat(),
                })
                if success:
                    audio_generated_count += 1

            # Chapter titles + scene audio — read from analysis files
            for analysis_file in sorted(analysis_dir.glob("chapter_*_analysis.json")):
                analysis = json.load(open(analysis_file, encoding="utf-8"))
                ch_num = analysis.get("chapter_index", 0)
                ch_title = analysis.get("chapter_title", f"Chapter {ch_num}")

                # Chapter title audio
                seq_num += 1
                ch_title_path = audio_dir / f"{seq_num:03d}_ch{ch_num:02d}_title.wav"
                print(f"\n    [{seq_num}] Ch{ch_num} Title: \"{ch_title}\"")
                ch_script = [{"speaker": "NARRATOR", "text": f"Chapter {ch_num}. {ch_title}",
                              "instruct": "Clear, measured chapter announcement."}]
                success, duration = tts_engine.generate_scene_audio(
                    audio_script=ch_script, voice_map=voice_map,
                    output_path=ch_title_path, language=TTS_LANGUAGE,
                )
                audio_items.append({
                    "sequence": seq_num, "type": "chapter_title", "chapter_number": ch_num,
                    "status": "completed" if success else "failed",
                    "output_path": str(ch_title_path), "duration": duration,
                    "generated_at": datetime.now().isoformat(),
                })
                if success:
                    audio_generated_count += 1

                # Scene audio: join scene paragraphs as single NARRATOR chunk
                for scene in analysis.get("scenes", []):
                    sc_num = scene.get("scene_number", 0)
                    paragraphs = scene.get("paragraphs", [])
                    if not paragraphs:
                        print(f"\n    [skip] Ch{ch_num} Sc{sc_num}: No paragraphs")
                        continue
                    prose = " ".join(paragraphs)
                    audio_script = [{"speaker": "NARRATOR", "text": prose,
                                     "instruct": "Grounded, deliberate narration."}]

                    seq_num += 1
                    scene_path = audio_dir / f"{seq_num:03d}_ch{ch_num:02d}_sc{sc_num:02d}.wav"
                    print(f"\n    [{seq_num}] Ch{ch_num} Sc{sc_num} ({len(paragraphs)} paragraphs)")
                    success, duration = tts_engine.generate_scene_audio(
                        audio_script=audio_script, voice_map=voice_map,
                        output_path=scene_path, language=TTS_LANGUAGE,
                    )
                    audio_items.append({
                        "sequence": seq_num, "type": "scene",
                        "chapter_number": ch_num, "scene_number": sc_num,
                        "status": "completed" if success else "failed",
                        "output_path": str(scene_path), "duration": duration,
                        "paragraphs": len(paragraphs),
                        "generated_at": datetime.now().isoformat(),
                    })
                    if success:
                        audio_generated_count += 1

                    # Save progress after each scene
                    audio_gen_data = {"items": audio_items, "total_generated": audio_generated_count}
                    with open(book_dir / "audio_generation.json", "w", encoding="utf-8") as f:
                        json.dump(audio_gen_data, f, indent=2, ensure_ascii=False)

            audio_count = audio_generated_count
            tts_engine.close()

            # Final audio generation log
            with open(book_dir / "audio_generation.json", "w", encoding="utf-8") as f:
                json.dump({"items": audio_items, "total_generated": audio_count}, f,
                          indent=2, ensure_ascii=False)

        metadata["steps_executed"].append(4)
        metadata["tts_engine"] = "qwen3-tts-direct"
        metadata["narration_mode"] = TTS_NARRATION_MODE
        step_timings["step4_audio"] = round(time.time() - step_start, 2)
        print(f"\n>>> Step 4 complete ({step_timings['step4_audio']:.1f}s): {audio_count} audio files")

    # =========================================================================
    # =========================================================================
    # Step 5: Final Video (ffmpeg — combine audio WAVs + poster → MP4)
    # =========================================================================
    if 5 in steps_to_run:
        step_start = time.time()
        print(f"\n{'='*60}")
        print("STEP 5: Final Video")
        print(f"{'='*60}")

        import subprocess

        audio_dir = book_dir / "audio"
        video_dir = book_dir / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)

        # --- 1. Collect sorted WAV files ---
        wav_files = sorted(audio_dir.glob("*.wav")) if audio_dir.exists() else []
        if not wav_files:
            print(">>> No audio WAV files found — run --steps 4 first")
        else:
            print(f">>> Found {len(wav_files)} audio files to combine")

            # --- 2. Combine WAVs with ffmpeg concat ---
            combined_audio = video_dir / f"{book_id}_combined.wav"
            concat_list = video_dir / "concat_list.txt"
            with open(concat_list, "w", encoding="utf-8") as f:
                for wav in wav_files:
                    f.write(f"file '{wav.as_posix()}'\n")

            concat_cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c", "copy", str(combined_audio),
            ]
            print(f">>> Combining audio...")
            proc = subprocess.run(concat_cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                print(f">>> ERROR combining audio: {proc.stderr[-500:]}")
            else:
                print(f"    Combined audio: {combined_audio.name}")

                # --- 3. Find best poster image ---
                poster_dir = Path(COMFYUI_OUTPUT_DIR) / "api" / book_id / "posters"
                scene_dir  = Path(COMFYUI_OUTPUT_DIR) / "api" / book_id / "scenes"

                poster_candidates = (
                    sorted(poster_dir.glob("poster_0001_*_.png")) if poster_dir.exists() else []
                )
                if not poster_candidates:
                    poster_candidates = (
                        sorted(scene_dir.glob("*.png")) if scene_dir.exists() else []
                    )

                if not poster_candidates:
                    print(">>> No poster/scene image found — run --steps 3 (or 2) first")
                else:
                    cover_image = poster_candidates[0]
                    print(f"    Cover image : {cover_image.name}")

                    # --- 4. ffmpeg image+audio → MP4 ---
                    output_mp4 = video_dir / f"{book_id}.mp4"
                    ffmpeg_cmd = [
                        "ffmpeg", "-y",
                        "-loop", "1", "-i", str(cover_image),
                        "-i", str(combined_audio),
                        "-c:v", "libx264", "-tune", "stillimage",
                        "-c:a", "aac", "-b:a", "192k",
                        "-b:v", "1000k",
                        "-pix_fmt", "yuv420p",
                        "-shortest",
                        "-movflags", "+faststart",
                        str(output_mp4),
                    ]
                    print(f">>> Encoding video (this takes a while for long audio)...")
                    proc = subprocess.Popen(ffmpeg_cmd, stderr=subprocess.PIPE,
                                            universal_newlines=True)
                    for line in proc.stderr:
                        if "time=" in line:
                            ts = line.split("time=")[1].split()[0]
                            print(f"\r    Progress: {ts}", end="", flush=True)
                    proc.wait()
                    print()

                    if proc.returncode == 0 and output_mp4.exists():
                        size_mb = output_mp4.stat().st_size / 1_048_576
                        print(f">>> Video created: {output_mp4} ({size_mb:.1f} MB)")
                        video_count += 1
                        metadata["video_output"] = str(output_mp4)
                    else:
                        print(f">>> ERROR: ffmpeg failed (return code {proc.returncode})")

        metadata["steps_executed"].append(5)
        step_timings["step5_video"] = round(time.time() - step_start, 2)
        print(f">>> Step 5 complete ({step_timings['step5_video']:.1f}s)")

    # Save generation metadata
    metadata["step_timings"] = step_timings
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"\n>>> Generation complete!")
    print(f"    Character portraits : {character_portrait_count}")
    print(f"    Location images     : {location_image_count}")
    print(f"    Scene images        : {scene_image_count}")
    print(f"    Posters/Thumbnails  : {poster_count}")
    print(f"    Audio files         : {audio_count}")
    print(f"    Videos              : {video_count}")
    print(f">>> Metadata: {metadata_path}")

    return GenerationResult(
        codex_path=book_dir,
        success=True,
        poster_count=poster_count,
        character_portrait_count=character_portrait_count,
        location_image_count=location_image_count,
        scene_image_count=scene_image_count,
        shot_frame_count=shot_frame_count,
        video_count=video_count,
        audio_count=audio_count,
        step_timings=step_timings,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate images and audio from E3 foundry book directory (Phase 3)"
    )
    parser.add_argument(
        "book_dir",
        type=Path,
        help="Path to foundry book directory (e.g. foundry/pg174)",
    )
    parser.add_argument(
        "--comfyui-url",
        default=None,
        help=f"ComfyUI API URL (default: {DEFAULT_COMFYUI_URL})",
    )
    parser.add_argument(
        "--steps",
        nargs="+",
        type=int,
        choices=[0, 1, 2, 3, 4, 5],
        help="Steps to run: 0=Characters 1=Locations 2=Scenes 3=Thumbnails 4=Audio 5=Video",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help=f"Per-generation timeout in seconds (default: {DEFAULT_COMFYUI_TIMEOUT})",
    )
    args = parser.parse_args()

    if not args.book_dir.exists() or not (args.book_dir / "codex.json").exists():
        print(f"ERROR: Not a valid book directory: {args.book_dir}")
        sys.exit(1)

    result = run_generation(
        args.book_dir,
        comfyui_url=args.comfyui_url,
        steps=args.steps,
        timeout=args.timeout,
    )

    if not result.success:
        print(f"\n>>> ERROR: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
