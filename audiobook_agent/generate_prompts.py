#!/usr/bin/env python3
"""
Prompt Generation Pipeline — Characters, Locations, Scenes, Thumbnails, Chapter Cards

Reads entity data from foundry/{book_id}/ and generates AI image prompts.

Step 1: Character image prompts  (characters.json → adds image_prompt per character)
Step 2: Location image prompts   (derived from scene data → updates locations.json)
Step 3: Scene image prompts      (analysis/chapter_*_analysis.json → scene_image_prompt per scene)
Step 4: Thumbnail prompts        (4-agent council → thumbnail_prompts.json)
Step 5: Chapter card prompt      (codex.json → metadata.chapter_card_prompt + per-chapter edit prompts)

Output layout (all added inside foundry/{book_id}/):
    characters.json       — character.image_prompt added
    locations.json        — location.image_prompt added
    analysis/*.json       — scene.scene_image_prompt added
    thumbnail_prompts.json — top 5 thumbnail prompts + metadata

Usage:
    python -m audiobook_agent.generate_prompts foundry/pg174
    python -m audiobook_agent.generate_prompts foundry/pg174 --steps 1 2 3
    python -m audiobook_agent.generate_prompts foundry/pg174 --no-resume --model gpt-mini
"""

from __future__ import annotations

import json
import os
import re
import argparse
import glob as _glob
import io
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

from audiobook_agent.visual_styles import get_default_style, get_style_by_name, list_styles, VisualStyle, get_chapter_card_font

load_dotenv()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.getenv("OPR_ROUTER_API_KEY", "")

MODEL_DEFAULT = "google/gemini-2.0-flash-lite-001"

AVAILABLE_MODELS: dict[str, str] = {
    "flash-lite": "google/gemini-2.0-flash-lite-001",
    "flash":      "google/gemini-2.5-flash-preview",
    "gpt-mini":   "openai/gpt-4.1-mini",
    "qwen":       "qwen/qwen3-235b-a22b",
    "kimi":       "moonshot/kimi-k2",
    "deepseek":   "deepseek/deepseek-chat-v3-0324",
    "glm":        "thudm/glm-4-32b",
}


# =============================================================================
# Pydantic schemas for structured LLM output
# =============================================================================

class CharacterImagePrompt(BaseModel):
    prompt: str = Field(
        description="Detailed portrait prompt for AI image generation, 200-300 words, single paragraph"
    )
    shot_type: str = Field(
        description="Shot type: portrait, bust, medium, or full_body"
    )
    key_features: list[str] = Field(
        default_factory=list,
        description="3-5 key visual features included in the prompt",
    )

    @field_validator("prompt", "shot_type", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return v or ""

    @field_validator("key_features", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        return v if isinstance(v, list) else []


class LocationImagePrompt(BaseModel):
    prompt: str = Field(
        description="Detailed environment prompt for AI image generation, 200-300 words, single paragraph"
    )
    shot_type: str = Field(
        description="Shot type: wide_shot, interior, aerial, or ground_level"
    )
    time_of_day: str = Field(
        description="Time of day: day, night, golden_hour, dusk, or dawn"
    )

    @field_validator("prompt", "shot_type", "time_of_day", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return v or ""


class SceneImagePrompt(BaseModel):
    prompt: str = Field(
        description="Cinematic scene image prompt, 150-250 words, single paragraph"
    )
    shot_type: str = Field(
        description="Shot type: wide, medium, two_shot, close, or over_shoulder"
    )
    mood_color: str = Field(
        description="Dominant mood color palette (e.g., 'deep crimson and amber tones')"
    )

    @field_validator("prompt", "shot_type", "mood_color", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        return v or ""


# =============================================================================
# LLM factory
# =============================================================================

def _make_llm(model: str, temperature: float = 0.5) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        openai_api_key=OPENROUTER_KEY,
        openai_api_base=OPENROUTER_BASE,
        temperature=temperature,
        max_tokens=4000,
    )


# =============================================================================
# System prompt templates
# =============================================================================

_CHAR_SYSTEM = """You are a master prompt engineer for AI image generation (Flux, SDXL, Wan2.1).
Generate a detailed CHARACTER PORTRAIT prompt for a character from "{book_title}".

VISUAL STYLE: {style_name}
STYLE PREFIX — start your prompt with EXACTLY this text: {style_prefix}
STYLE SUFFIX — end your prompt with EXACTLY this text: {style_suffix}

RULES:
- NEVER use the character's name — describe ONLY by physical appearance
- START the prompt with the style prefix
- END the prompt with the style suffix + quality tags: 8k resolution, highly detailed, professional portrait, sharp focus
- 200-300 words, single flowing paragraph, natural language (not keyword spam)
- Focus on: age/gender, face shape, skin tone/texture, eyes (color+expression), hair (color+style+length),
  clothing (fabric type, color, fit, condition), pose, expression, mood
- Background: simple neutral backdrop — keep focus on the character
- Period-appropriate style: Victorian England (1890s), upper-class aesthetic"""

_LOC_SYSTEM = """You are a master prompt engineer for AI image generation (Flux, SDXL, Wan2.1).
Generate a detailed ENVIRONMENT / LOCATION prompt for a setting from "{book_title}".

VISUAL STYLE: {style_name}
STYLE PREFIX — start your prompt with EXACTLY this text: {style_prefix}
STYLE SUFFIX — end your prompt with EXACTLY this text: {style_suffix}

RULES:
- START the prompt with the style prefix
- END the prompt with the style suffix + quality tags: 8k resolution, matte painting, concept art, cinematic composition
- 200-300 words, single flowing paragraph, natural language
- Include: shot type, time of day, architecture/materials (era-appropriate), vegetation, atmospheric lighting,
  volumetric effects (fog, dust motes, smoke), depth layers (foreground/mid/background), color palette
- Period: Victorian England (1890s), upper-class London interiors and streets unless otherwise specified"""

_SCENE_SYSTEM = """You are a master prompt engineer for AI image generation (Flux, SDXL, Wan2.1).
Generate a cinematic SCENE IMAGE prompt for a scene from "{book_title}".

VISUAL STYLE: {style_name}
STYLE PREFIX — start your prompt with EXACTLY this text: {style_prefix}
STYLE SUFFIX — end your prompt with EXACTLY this text: {style_suffix}

RULES:
- NEVER use character names — describe characters ONLY by physical appearance
- START the prompt with the style prefix
- END the prompt with the style suffix + quality tags: 8k resolution, cinematic lighting, detailed illustration
- 150-250 words, single flowing paragraph
- Include: shot type (wide/medium/close/two-shot), location atmosphere, character positions described
  physically (hair color, clothing), interaction/action, mood lighting, color palette
- Match the scene's emotional tone and period setting (Victorian England, 1890s)"""


# =============================================================================
# Step 1: Character image prompts
# =============================================================================

def _build_char_human(char: dict, book_title: str) -> str:
    """Build human message for character prompt generation."""
    lines = [f"Generate a detailed portrait prompt for this character from '{book_title}'."]
    lines.append("")
    lines.append(f"CHARACTER NAME (for context only, DO NOT use in prompt): {char.get('canonical_name', '?')}")
    lines.append(f"Role: {char.get('role', 'supporting')}")

    phys = char.get("physical_description", "")
    if phys and phys.lower() not in ("n/a", "none", ""):
        lines.append(f"Physical description: {phys[:600]}")

    clothing = char.get("clothing_seen", [])
    if clothing:
        notable = [c for c in clothing if c.lower() not in ("n/a", "none", "")][:3]
        if notable:
            lines.append(f"Clothing seen: {' | '.join(notable)}")

    voice = char.get("voice_description", "")
    if voice and voice.lower() not in ("n/a", "none", ""):
        lines.append(f"Voice/presence: {voice[:200]}")

    personality = char.get("personality", "")
    if personality and personality.lower() not in ("n/a", "none", ""):
        lines.append(f"Personality traits: {personality[:200]}")

    lines.append("")
    lines.append(
        "Generate a portrait prompt. Remember: NO character name in the prompt text. "
        "Describe appearance only through physical details."
    )
    return "\n".join(lines)


def generate_character_prompts(
    book_dir: Path,
    book_title: str,
    visual_style: VisualStyle,
    model: str,
    resume: bool,
    verbose: bool,
) -> int:
    """Generate image prompts for all characters. Returns count generated."""
    chars_path = book_dir / "characters.json"
    if not chars_path.exists():
        if verbose:
            print("  Step 1: characters.json not found, skipping")
        return 0

    with open(chars_path, encoding="utf-8") as f:
        chars: dict = json.load(f)

    system_msg = _CHAR_SYSTEM.format(
        book_title=book_title,
        style_name=visual_style["name"],
        style_prefix=visual_style["prefix"],
        style_suffix=visual_style["suffix"],
    )

    llm = _make_llm(model)
    structured = llm.with_structured_output(CharacterImagePrompt, method="json_schema")

    count = 0
    skipped = 0
    total = len(chars)

    for i, (canonical_name, char) in enumerate(chars.items(), 1):
        # Skip author meta-entries and characters with no physical data
        if char.get("role") == "author":
            skipped += 1
            continue
        phys = char.get("physical_description", "")
        if phys.lower().strip() in ("n/a", "none", "", "not mentioned", "not described"):
            if verbose:
                print(f"  [{i}/{total}] Skipping {canonical_name} (no physical description)")
            skipped += 1
            continue

        if resume and char.get("image_prompt"):
            if verbose:
                print(f"  [{i}/{total}] Skipping {canonical_name} (already has prompt)")
            skipped += 1
            continue

        if verbose:
            print(f"  [{i}/{total}] {canonical_name} ...", end=" ", flush=True)

        try:
            human = _build_char_human(char, book_title)
            result: CharacterImagePrompt = structured.invoke([
                SystemMessage(content=system_msg),
                HumanMessage(content=human),
            ])
            char["image_prompt"] = {
                "prompt": result.prompt,
                "shot_type": result.shot_type,
                "key_features": result.key_features,
            }
            count += 1
            if verbose:
                print(f"ok ({result.shot_type})")
        except Exception as e:
            if verbose:
                print(f"ERROR: {e}")

    with open(chars_path, "w", encoding="utf-8") as f:
        json.dump(chars, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"  Step 1 done: {count} prompts generated, {skipped} skipped")
        print(f"  Saved: {chars_path}")
    return count


# =============================================================================
# Step 2: Location image prompts
# =============================================================================

def _collect_locations_from_scenes(analysis_dir: Path) -> dict[str, str]:
    """
    Collect unique (location_name → best description) from all scene analysis files.
    Uses the richest description found across all scenes for each location.
    """
    locs: dict[str, str] = {}
    for path in sorted(analysis_dir.glob("chapter_*_analysis.json")):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for scene in data.get("scenes", []):
            loc_name = (scene.get("location") or "").strip()
            loc_desc = (scene.get("location_description") or "").strip()
            if not loc_name or loc_name.lower() in ("unknown", ""):
                continue
            # Keep the longest/richest description
            existing = locs.get(loc_name, "")
            if len(loc_desc) > len(existing):
                locs[loc_name] = loc_desc
    return locs


def _build_loc_human(loc_name: str, loc_description: str, book_title: str) -> str:
    lines = [f"Generate a detailed environment prompt for this location from '{book_title}'."]
    lines.append("")
    lines.append(f"LOCATION NAME: {loc_name}")
    if loc_description:
        lines.append(f"DESCRIPTION: {loc_description[:800]}")
    lines.append("")
    lines.append(
        "Generate a rich environment/atmosphere prompt for this location. "
        "Include architecture, materials, lighting, atmosphere, and depth layers."
    )
    return "\n".join(lines)


def generate_location_prompts(
    book_dir: Path,
    book_title: str,
    visual_style: VisualStyle,
    model: str,
    resume: bool,
    verbose: bool,
) -> int:
    """
    Generate image prompts for all unique locations found in scene analysis data.
    Overwrites/merges with existing locations.json.
    Returns count generated.
    """
    analysis_dir = book_dir / "analysis"
    if not analysis_dir.exists():
        if verbose:
            print("  Step 2: analysis/ not found, skipping")
        return 0

    # Collect unique locations from scene data
    scene_locs = _collect_locations_from_scenes(analysis_dir)
    if not scene_locs:
        if verbose:
            print("  Step 2: No named locations found in scenes, skipping")
        return 0

    # Load existing locations.json (may have old/poor data)
    locs_path = book_dir / "locations.json"
    locs: dict = {}
    if locs_path.exists():
        with open(locs_path, encoding="utf-8") as f:
            locs = json.load(f)

    system_msg = _LOC_SYSTEM.format(
        book_title=book_title,
        style_name=visual_style["name"],
        style_prefix=visual_style["prefix"],
        style_suffix=visual_style["suffix"],
    )

    llm = _make_llm(model)
    structured = llm.with_structured_output(LocationImagePrompt, method="json_schema")

    count = 0
    skipped = 0
    total = len(scene_locs)

    for i, (loc_name, loc_desc) in enumerate(scene_locs.items(), 1):
        existing_entry = locs.get(loc_name, {})
        if resume and existing_entry.get("image_prompt"):
            if verbose:
                print(f"  [{i}/{total}] Skipping {loc_name!r} (already has prompt)")
            skipped += 1
            continue

        if verbose:
            print(f"  [{i}/{total}] {loc_name!r} ...", end=" ", flush=True)

        try:
            human = _build_loc_human(loc_name, loc_desc, book_title)
            result: LocationImagePrompt = structured.invoke([
                SystemMessage(content=system_msg),
                HumanMessage(content=human),
            ])
            # Upsert into locs dict
            entry = locs.setdefault(loc_name, {
                "canonical_name": loc_name,
                "description": loc_desc,
                "aliases": [],
                "first_appears_chapter": 0,
                "appears_in_chapters": [],
            })
            entry["image_prompt"] = {
                "prompt": result.prompt,
                "shot_type": result.shot_type,
                "time_of_day": result.time_of_day,
            }
            count += 1
            if verbose:
                print(f"ok ({result.shot_type}, {result.time_of_day})")
        except Exception as e:
            if verbose:
                print(f"ERROR: {e}")

    with open(locs_path, "w", encoding="utf-8") as f:
        json.dump(locs, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"  Step 2 done: {count} prompts generated, {skipped} skipped")
        print(f"  Saved: {locs_path}")
    return count


# =============================================================================
# Step 3: Scene image prompts
# =============================================================================

def _build_scene_human(scene: dict, chars_lookup: dict, book_title: str) -> str:
    """Build human message for scene prompt generation."""
    lines = [f"Generate a cinematic scene image prompt for this scene from '{book_title}'."]
    lines.append("")

    loc = scene.get("location", "")
    loc_desc = scene.get("location_description", "")
    if loc and loc.lower() not in ("unknown", ""):
        lines.append(f"LOCATION: {loc}")
    if loc_desc:
        lines.append(f"LOCATION DESCRIPTION: {loc_desc[:400]}")

    lines.append(f"MOOD: {scene.get('mood', 'neutral')}")

    key_events = scene.get("key_events", [])
    if key_events:
        lines.append("KEY EVENTS:")
        for ev in key_events[:4]:
            lines.append(f"  - {ev}")

    # Build character appearance descriptions (NO names)
    char_details = scene.get("character_details", [])
    present = scene.get("characters_present", [])

    if char_details or present:
        lines.append("CHARACTERS IN SCENE (describe by appearance only, no names):")
        described = set()
        for cd in char_details:
            name = cd.get("name", "")
            if not name or name in described:
                continue
            described.add(name)

            # Pull richer description from master profiles
            profile = chars_lookup.get(name.upper(), {})
            phys = (profile.get("physical_description") or cd.get("physical_description") or "").strip()
            clothing = cd.get("clothing") or ""
            if not clothing and profile.get("clothing_seen"):
                clothing_list = [c for c in profile["clothing_seen"] if c.lower() not in ("n/a", "none", "")]
                clothing = clothing_list[0] if clothing_list else ""

            desc_parts = []
            if phys and phys.lower() not in ("n/a", "none", "not mentioned"):
                desc_parts.append(phys[:200])
            if clothing and clothing.lower() not in ("n/a", "none", ""):
                desc_parts.append(f"wearing: {clothing[:100]}")

            if desc_parts:
                lines.append(f"  - Character: {' | '.join(desc_parts)}")

    # Include a short prose excerpt for context
    paragraphs = scene.get("paragraphs", [])
    if paragraphs:
        excerpt = paragraphs[0][:300]
        lines.append(f"SCENE EXCERPT: {excerpt}")

    lines.append("")
    lines.append(
        "Generate a cinematic scene image prompt. No character names — describe appearance only. "
        "Include shot type, location atmosphere, character actions/positions, mood lighting."
    )
    return "\n".join(lines)


def generate_scene_prompts(
    book_dir: Path,
    book_title: str,
    visual_style: VisualStyle,
    model: str,
    resume: bool,
    verbose: bool,
) -> int:
    """Generate image prompts for all scenes in all analysis files. Returns total count."""
    analysis_dir = book_dir / "analysis"
    if not analysis_dir.exists():
        if verbose:
            print("  Step 3: analysis/ not found, skipping")
        return 0

    # Load character master profiles for richer descriptions
    chars_lookup: dict = {}
    chars_path = book_dir / "characters.json"
    if chars_path.exists():
        with open(chars_path, encoding="utf-8") as f:
            chars_lookup = json.load(f)

    system_msg = _SCENE_SYSTEM.format(
        book_title=book_title,
        style_name=visual_style["name"],
        style_prefix=visual_style["prefix"],
        style_suffix=visual_style["suffix"],
    )

    llm = _make_llm(model)
    structured = llm.with_structured_output(SceneImagePrompt, method="json_schema")

    chapter_files = sorted(analysis_dir.glob("chapter_*_analysis.json"))
    total_scenes = 0
    count = 0
    skipped = 0

    for ch_file in chapter_files:
        with open(ch_file, encoding="utf-8") as f:
            chapter_data: dict = json.load(f)

        scenes = chapter_data.get("scenes", [])
        chapter_modified = False

        for scene in scenes:
            total_scenes += 1
            sc_num = scene.get("scene_number", "?")

            if resume and scene.get("scene_image_prompt"):
                skipped += 1
                continue

            if verbose:
                ch_idx = chapter_data.get("chapter_index", "?")
                print(f"  Ch{ch_idx} Sc{sc_num} ...", end=" ", flush=True)

            try:
                human = _build_scene_human(scene, chars_lookup, book_title)
                result: SceneImagePrompt = structured.invoke([
                    SystemMessage(content=system_msg),
                    HumanMessage(content=human),
                ])
                scene["scene_image_prompt"] = {
                    "prompt": result.prompt,
                    "shot_type": result.shot_type,
                    "mood_color": result.mood_color,
                }
                count += 1
                chapter_modified = True
                if verbose:
                    print(f"ok ({result.shot_type})")
            except Exception as e:
                if verbose:
                    print(f"ERROR: {e}")

        if chapter_modified:
            with open(ch_file, "w", encoding="utf-8") as f:
                json.dump(chapter_data, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"  Step 3 done: {count}/{total_scenes} scene prompts generated, {skipped} skipped")
    return count


# =============================================================================
# Step 4: Thumbnail prompts — 4-agent council
# =============================================================================

# Genre-neutral cinematic poster examples — demonstrate composition format
_POSTER_EXAMPLES = [
    (
        "Classical illustration artwork, cinematic book poster composition, a dramatic "
        "one-sheet key art depicting a brooding figure in period attire standing at the "
        "threshold of a grand doorway, half in warm golden candlelight, half in cold "
        "moonlit shadow — a visual metaphor for moral duality. Volumetric fog drifts "
        "through the scene creating atmospheric depth layers. Background: a sweeping "
        "cityscape silhouette with spires and gaslit streets. Foreground: symbolic objects "
        "(wilting flowers, an ornate mirror) ground the narrative. Title typography: "
        "\"BOOK TITLE\" in bold cinematic display font with metallic gold effects, centered "
        "upper third. \"by Author Name\" in elegant smaller serif below. Palette: deep "
        "midnight black, burnished gold, blood crimson accents, ivory highlights. Film "
        "grain texture, dramatic chiaroscuro lighting, theatrical poster layout. "
        "classical illustration style, detailed pen and ink with watercolor wash, "
        "Victorian era aesthetic, rich cross-hatching, warm sepia tones, museum-quality "
        "fine art illustration, highly detailed"
    ),
    (
        "Anime style illustration, cinematic book poster key art, a striking split "
        "composition: the protagonist's face dominates the upper half — intense eyes "
        "reflecting a pivotal moment, wind-swept hair, dramatic rim lighting. Below, "
        "a sweeping landscape establishing the story world — architecture, atmospheric "
        "weather, tiny figures suggesting scale and adventure. Bold diagonal energy lines "
        "connect the two halves. Title typography: \"BOOK TITLE\" in bold modern display "
        "font with subtle glow effects across the center divide. \"by Author Name\" in "
        "clean sans-serif at bottom. Palette: teal and orange complementary contrast, "
        "with accent hot pink and electric blue. Volumetric god rays, lens flare, "
        "anamorphic bokeh. anime art style, cel shaded, vibrant saturated colors, "
        "Studio Ghibli inspired, expressive character design, high quality anime"
    ),
]

_THUMBNAIL_AGENT_ROLES = {
    "visual_director": {
        "name": "Visual Composition Director",
        "focus": (
            "CINEMATIC POSTER COMPOSITION: bold one-sheet key art layout, strong focal "
            "point, dramatic depth layers (foreground objects, mid-ground subject, "
            "background atmosphere), colors that pop against YouTube's white interface, "
            "theatrical lighting, film grain texture"
        ),
    },
    "story_specialist": {
        "name": "Story Visual Specialist",
        "focus": (
            "EMOTIONAL CORE: capture the book's central conflict and emotional tension, "
            "the protagonist's defining struggle, the story's most iconic visual moment "
            "— convey the theme through character pose, symbolic objects, and atmospheric mood"
        ),
    },
    "engagement_expert": {
        "name": "Engagement Psychology Expert",
        "focus": (
            "MAXIMUM CLICK-THROUGH: curiosity triggers (split compositions, hidden details, "
            "dramatic reveals), bold saturated palette, mobile-optimized hierarchy, "
            "attention-grabbing title placement, cinematic color grading (teal-orange, "
            "complementary contrast)"
        ),
    },
    "genre_master": {
        "name": "Genre & Period Visual Master",
        "focus": (
            "GENRE AUTHENTICITY: period-accurate visual conventions, genre-defining aesthetic "
            "tropes, art movement references appropriate to the era, authentic atmospheric "
            "details (architecture, fashion, lighting technology of the period)"
        ),
    },
}

_AGENT_PROMPT = """\
You are a {agent_name} creating CINEMATIC BOOK POSTERS for a YouTube audiobook.

BOOK: "{book_title}" by {author}
PERIOD/SETTING: {period_setting}

VISUAL STYLE: {style_name}
STYLE PREFIX (start EVERY prompt with this): "{style_prefix}"
STYLE SUFFIX (end EVERY prompt with this): "{style_suffix}"

YOUR FOCUS: {focus}

KEY CHARACTERS (describe by appearance ONLY, never by name):
{char_descriptions}

KEY STORY MOMENTS:
{key_moments}

REFERENCE EXAMPLES (follow this cinematic poster composition format):
{examples}

TASK: Generate exactly 3 cinematic book poster prompts that:
1. START with the style prefix
2. Use MOVIE POSTER composition: one-sheet key art layout, dramatic focal point,
   atmospheric depth layers (foreground/mid/background), cinematic lighting
3. Include TITLE TYPOGRAPHY: "{book_title}" in BOLD cinematic display font,
   prominent and readable — upper or center placement
4. Include AUTHOR CREDIT: "by {author}" in elegant smaller font below the title
5. Combine 3-5 iconic story elements into ONE striking poster composition
6. Include a specific NAMED COLOR PALETTE that pops on YouTube
7. Add cinematic texture: film grain, volumetric lighting, dramatic shadows
8. END with the style suffix

POSTER KEYWORDS to weave in: cinematic book poster, key art, one-sheet composition,
theatrical lighting, dramatic chiaroscuro, depth of field, film grain texture

Each prompt: 150-250 words, single flowing paragraph.
Output EXACTLY 3 prompts separated by blank lines.
No numbering, no headers — just 3 paragraphs."""

_VOTING_PROMPT = """\
Score these {n} cinematic book poster prompts for "{book_title}" by {author}.

Criteria (1-10 each):
1. visual_impact  — instantly grabs attention? bold cinematic composition and focal point?
2. story_capture  — captures the book's central theme, conflict, and emotional essence?
3. style_match    — properly uses the {style_name} style (prefix and suffix present)?
4. typography     — title "{book_title}" + author "by {author}" integrated as readable display text?
5. poster_quality — looks like a professional movie/book poster (not just a scene illustration)?
6. color_impact   — bold, cinematic color palette optimized for YouTube thumbnails?

PROMPTS:
{prompts_text}

Output ONLY valid JSON, no other text:
{{"scores": [{{"index": 0, "visual_impact": 8, "story_capture": 7, "style_match": 9, "typography": 8, "poster_quality": 7, "color_impact": 8, "total": 47}}, ...], "top_pick_index": 2}}"""


def _extract_prompts_from_text(text: str) -> list[str]:
    """Extract 3 individual prompts from agent response text."""
    text = text.strip()
    # Remove markdown headers and list markers
    text = re.sub(r'^#+\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\*\*.*?\*\*\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+[\.\)]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-•]\s*', '', text, flags=re.MULTILINE)

    paragraphs = re.split(r'\n\s*\n', text)
    prompts = []
    for para in paragraphs:
        para = para.strip()
        if len(para) > 100 and any(
            kw in para.lower() for kw in [
                "illustration", "anime", "thumbnail", "classical", "gothic",
                "poster", "cinematic", "key art", "oil painting", "cartoon",
            ]
        ):
            prompts.append(para)

    return prompts[:3]


def _build_char_descriptions_for_thumbnail(chars: dict, max_chars: int = 5) -> str:
    """Build compact character description list for thumbnail context."""
    lines = []
    count = 0
    for canonical_name, char in chars.items():
        if char.get("role") == "author":
            continue
        phys = char.get("physical_description", "")
        if phys.lower().strip() in ("n/a", "none", "", "not mentioned"):
            continue
        role = char.get("role", "supporting")
        lines.append(f"- {canonical_name} ({role}): {phys[:150].strip()}")
        count += 1
        if count >= max_chars:
            break
    return "\n".join(lines) if lines else "Characters not available."


def _build_key_moments(analysis_dir: Path, max_moments: int = 5) -> str:
    """Extract key scene summaries as thumbnail inspiration."""
    moments = []
    for ch_file in sorted(analysis_dir.glob("chapter_*_analysis.json")):
        if len(moments) >= max_moments:
            break
        with open(ch_file, encoding="utf-8") as f:
            data = json.load(f)
        for scene in data.get("scenes", []):
            summary = scene.get("summary", "")
            if summary and len(summary) > 30:
                moments.append(f"- {summary[:200]}")
                if len(moments) >= max_moments:
                    break
    return "\n".join(moments) if moments else "Key moments not available."


def _derive_period_setting(book_dir: Path) -> str:
    """Derive period/setting from analysis data for thumbnail context."""
    # Gather unique locations from first few analysis files
    analysis_dir = book_dir / "analysis"
    locations: list[str] = []
    if analysis_dir.exists():
        for ch_file in sorted(analysis_dir.glob("chapter_*_analysis.json"))[:5]:
            with open(ch_file, encoding="utf-8") as f:
                data = json.load(f)
            for scene in data.get("scenes", []):
                loc = scene.get("location", "")
                loc_desc = scene.get("location_description", "")
                if loc and loc.lower() not in ("unknown", "n/a", ""):
                    entry = f"{loc}: {loc_desc[:80]}" if loc_desc else loc
                    if entry not in locations:
                        locations.append(entry)
                    if len(locations) >= 5:
                        break
    if locations:
        return "; ".join(locations[:5])
    return "(derive period and setting from the story's characters and themes)"


def generate_thumbnail_prompts(
    book_dir: Path,
    book_title: str,
    author: str,
    visual_style: VisualStyle,
    model: str,
    verbose: bool,
) -> dict:
    """
    Generate YouTube thumbnail prompts via 4-agent council with voting.
    Returns dict with top prompts + metadata.
    """
    if verbose:
        print("\n  === Thumbnail Agent Council ===")

    chars_path = book_dir / "characters.json"
    chars = {}
    if chars_path.exists():
        with open(chars_path, encoding="utf-8") as f:
            chars = json.load(f)

    analysis_dir = book_dir / "analysis"
    key_moments = _build_key_moments(analysis_dir) if analysis_dir.exists() else "Not available."
    char_descriptions = _build_char_descriptions_for_thumbnail(chars)

    # Derive period/setting from analysis data
    period_setting = _derive_period_setting(book_dir)

    style_name = visual_style["name"]
    style_prefix = visual_style["prefix"]
    style_suffix = visual_style["suffix"]
    examples_text = "\n\n".join(_POSTER_EXAMPLES)

    llm_creative = _make_llm(model, temperature=0.8)
    llm_analytical = _make_llm(model, temperature=0.2)

    # Step 1: 4 agents generate 3 prompts each = 12 candidates
    all_prompts: list[str] = []
    agent_contributions: dict[str, int] = {}

    for agent_key, agent_info in _THUMBNAIL_AGENT_ROLES.items():
        agent_prompt = _AGENT_PROMPT.format(
            agent_name=agent_info["name"],
            book_title=book_title,
            author=author,
            period_setting=period_setting,
            style_name=style_name,
            style_prefix=style_prefix,
            style_suffix=style_suffix,
            focus=agent_info["focus"],
            char_descriptions=char_descriptions,
            key_moments=key_moments,
            examples=examples_text,
        )
        if verbose:
            print(f"  [{agent_info['name']}] generating 3 prompts ...", end=" ", flush=True)
        try:
            response = llm_creative.invoke(agent_prompt)
            prompts = _extract_prompts_from_text(response.content)
            all_prompts.extend(prompts)
            agent_contributions[agent_key] = len(prompts)
            if verbose:
                print(f"got {len(prompts)}")
        except Exception as e:
            agent_contributions[agent_key] = 0
            if verbose:
                print(f"ERROR: {e}")

    if verbose:
        print(f"\n  Total candidates: {len(all_prompts)}")

    if not all_prompts:
        fallback = (
            f'{style_prefix} cinematic book poster for "{book_title}" by {author}, '
            f"dramatic one-sheet key art composition, protagonist in atmospheric setting, "
            f"bold title typography in cinematic display font, film grain texture, "
            f"volumetric lighting, dramatic chiaroscuro. {style_suffix}"
        )
        return {
            "prompts": [fallback],
            "all_candidates": [fallback],
            "voting_results": [],
            "style": visual_style,
            "metadata": {"error": "no_prompts_generated", "fallback": True},
        }

    # Step 2: Voting to select top 5
    if verbose:
        print("  Voting on candidates ...", end=" ", flush=True)

    prompts_text = "\n\n".join(f"[Prompt {i}]\n{p}" for i, p in enumerate(all_prompts))
    voting_prompt = _VOTING_PROMPT.format(
        n=len(all_prompts),
        book_title=book_title,
        author=author,
        style_name=style_name,
        prompts_text=prompts_text,
    )

    vote_results: list[tuple[int, float]] = []
    try:
        vote_response = llm_analytical.invoke(voting_prompt)
        json_match = re.search(r'\{[\s\S]*\}', vote_response.content)
        if json_match:
            parsed = json.loads(json_match.group())
            for score_item in parsed.get("scores", []):
                idx = score_item.get("index", 0)
                total = score_item.get("total", 0)
                vote_results.append((idx, total))
    except Exception as e:
        if verbose:
            print(f"parse error ({e}), using default ranking")

    if vote_results:
        ranked = sorted(
            [(all_prompts[i], score) for i, score in vote_results if i < len(all_prompts)],
            key=lambda x: x[1],
            reverse=True,
        )
        top_5 = [p for p, _ in ranked[:5]]
        if verbose:
            print(f"done. Top score: {ranked[0][1] if ranked else 0}")
    else:
        top_5 = all_prompts[:5]
        if verbose:
            print("done (fallback order)")

    return {
        "prompts": top_5,
        "all_candidates": all_prompts,
        "voting_results": vote_results,
        "style": visual_style,
        "metadata": {
            "book_title": book_title,
            "author": author,
            "total_candidates": len(all_prompts),
            "agent_contributions": agent_contributions,
        },
    }


# =============================================================================
# SVG AI stamp utility
# =============================================================================

def apply_ai_stamp(
    image_path: Path,
    svg_path: Path,
    corner: str = "top-right",
    scale: float = 0.15,
    padding_fraction: float = 0.02,
) -> bool:
    """
    Overlay an SVG AI-disclosure stamp onto a generated image.

    Dynamically sizes the stamp relative to image dimensions (~15% of height).

    Args:
        image_path:        Absolute path to the PNG/JPEG image to stamp.
        svg_path:          Absolute path to the SVG stamp file.
        corner:            Placement: "top-right", "top-left", "bottom-right", "bottom-left".
        scale:             Stamp height as fraction of image height (0.15 = 15%).
        padding_fraction:  Edge padding as fraction of image height (0.02 = 2%).

    Returns:
        True on success, False on any error.
    """
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        from PIL import Image
    except ImportError:
        print(
            "      WARNING: svglib/reportlab/PIL not installed. "
            "Install with: pip install svglib reportlab pillow"
        )
        return False

    try:
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

        # Double-render trick to recover true alpha (no chroma-key fringing)
        png_white = renderPM.drawToString(drawing, fmt="PNG", bg=0xFFFFFF)
        png_black = renderPM.drawToString(drawing, fmt="PNG", bg=0x000000)
        img_w = Image.open(io.BytesIO(png_white)).convert("RGB")
        img_b = Image.open(io.BytesIO(png_black)).convert("RGB")

        import numpy as np
        arr_w = np.array(img_w, dtype=float)
        arr_b = np.array(img_b, dtype=float)
        alpha = 255 - (arr_w - arr_b).max(axis=2)
        alpha = np.clip(alpha, 0, 255).astype(np.uint8)
        rgb = arr_b.astype(np.uint8)
        stamp = Image.fromarray(
            np.dstack([rgb, alpha[:, :, None]]),
            mode="RGBA",
        )

        # Position stamp
        sw, sh = stamp.size
        if corner == "top-right":
            pos = (width - sw - pad, pad)
        elif corner == "top-left":
            pos = (pad, pad)
        elif corner == "bottom-right":
            pos = (width - sw - pad, height - sh - pad)
        else:  # bottom-left
            pos = (pad, height - sh - pad)

        poster.paste(stamp, pos, mask=stamp)
        poster.save(image_path)
        return True

    except Exception as e:
        print(f"      WARNING: SVG stamp error: {e}")
        return False


# =============================================================================
# Step 5: Chapter card template prompt
# =============================================================================

_CHAPTER_CARD_SYSTEM = """\
You are a cinematic concept artist creating a CHAPTER TITLE CARD background image prompt.

The image will serve as a reusable template for all chapter cards in the audiobook.
Actual chapter titles will be overlaid via AI image editing in post-production.

VISUAL STYLE:
START your prompt with EXACTLY this prefix: "{style_prefix}"
END your prompt with EXACTLY this suffix: "{style_suffix}"

COMPOSITION RULES:
- Book cover layout composition — atmospheric scene inspired by the book's world
- CENTER of the image must contain PLACEHOLDER TEXT: "CHAPTER I" on one line,
  "CHAPTER TITLE" below in larger font — use {font_style} typography
- The center area must remain visually clean so text is readable
- All world details (objects, architecture, symbols) around the EDGES of the frame
- Heavy dark vignette on all four edges, darkest at corners
- Subject/environment in lower third, negative space with fog/shadow in upper area

ATMOSPHERE:
- Cinematic, symmetrical, similar to movie/TV title cards (Game of Thrones, True Detective)
- Hint at the world and lore of the book through iconic objects, locations, symbols
- Muted desaturated palette, maximum two dominant tones + accent color
- Volumetric fog, chiaroscuro lighting, film grain texture
- Do NOT recreate specific scenes — focus on mood, symbolism, atmosphere

FONT STYLE:
- The placeholder text should be described as: {font_style}
- This establishes the typography style so the AI editor maintains it per chapter

Generate EXACTLY ONE image generation prompt. Single flowing paragraph, 150-250 words.
"""


def generate_chapter_card_prompt(
    book_dir: Path,
    book_title: str,
    visual_style: VisualStyle,
    visual_style_name: str,
    model: str,
    resume: bool = True,
    verbose: bool = True,
) -> int:
    """Generate a chapter card template prompt and per-chapter edit prompts.

    Stores:
      - codex.json → metadata.chapter_card_prompt  (the image generation prompt)
      - codex.json → chapters[].chapter_card_edit_prompt  (per-chapter edit instruction)

    Returns: 1 if prompt was generated, 0 if skipped (resume).
    """
    codex_path = book_dir / "codex.json"
    if not codex_path.exists():
        print("  codex.json not found, skipping")
        return 0

    with open(codex_path, encoding="utf-8") as f:
        codex = json.load(f)

    meta = codex.setdefault("metadata", {})

    # Resume check
    if resume and meta.get("chapter_card_prompt"):
        if verbose:
            print("  Chapter card prompt already exists, skipping (use --no-resume to regenerate)")
        return 0

    font_style = get_chapter_card_font(visual_style_name)

    system_prompt = _CHAPTER_CARD_SYSTEM.format(
        style_prefix=visual_style["prefix"],
        style_suffix=visual_style["suffix"],
        font_style=font_style,
    )

    # Build a brief book summary for context
    chapters = codex.get("chapters", [])
    chapter_titles = [ch.get("title", f"Chapter {ch.get('chapter_number', i+1)}")
                      for i, ch in enumerate(chapters)]
    chapters_summary = ", ".join(chapter_titles[:10])
    if len(chapter_titles) > 10:
        chapters_summary += f"... ({len(chapter_titles)} chapters total)"

    human_msg = (
        f'BOOK: "{book_title}"\n'
        f"CHAPTERS: {chapters_summary}\n\n"
        f"Generate ONE chapter title card template prompt for this book."
    )

    llm = ChatOpenAI(
        model=model,
        openai_api_key=OPENROUTER_KEY,
        openai_api_base=OPENROUTER_BASE,
        temperature=0.8,
    )

    if verbose:
        print(f"  Generating chapter card template prompt...")

    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=human_msg)])
    prompt_text = response.content.strip()

    # Store the template prompt
    meta["chapter_card_prompt"] = prompt_text
    meta["chapter_card_font_style"] = font_style

    # Generate per-chapter edit prompts
    for ch in chapters:
        ch_num = ch.get("chapter_number", 0)
        ch_title = ch.get("title", f"Chapter {ch_num}")
        ch["chapter_card_edit_prompt"] = (
            f"Replace 'CHAPTER I' with 'CHAPTER {_roman(ch_num)}' and "
            f"'CHAPTER TITLE' with '{ch_title}' in the same font style"
        )

    with open(codex_path, "w", encoding="utf-8") as f:
        json.dump(codex, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"  Chapter card prompt generated ({len(prompt_text)} chars)")
        print(f"  Edit prompts added for {len(chapters)} chapters")

    return 1


def _roman(num: int) -> str:
    """Convert an integer to a Roman numeral string."""
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    result = ""
    for value, numeral in vals:
        while num >= value:
            result += numeral
            num -= value
    return result


# =============================================================================
# Main orchestrator
# =============================================================================

def generate_book_prompts(
    book_dir: str | Path,
    visual_style_name: str = "classical_illustration",
    model: str = MODEL_DEFAULT,
    steps: list[int] | None = None,
    resume: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Generate image prompts for all entities in a foundry book directory.

    Args:
        book_dir:           Path to foundry/{book_id}/
        visual_style_name:  Style key from visual_styles.py (default: classical_illustration)
        model:              OpenRouter model ID or shorthand
        steps:              Which steps to run (default: [1,2,3,4,5])
        resume:             Skip entities that already have prompts
        verbose:            Print progress

    Returns:
        dict with success status and counts per step
    """
    book_dir = Path(book_dir).resolve()
    steps_to_run = steps if steps is not None else [1, 2, 3, 4, 5]

    # Resolve model shorthand
    model = AVAILABLE_MODELS.get(model, model)

    # Load visual style
    try:
        visual_style = get_style_by_name(visual_style_name)
    except KeyError:
        visual_style = get_default_style()

    # Get book metadata from codex.json
    codex_path = book_dir / "codex.json"
    book_title = "Unknown"
    author = "Unknown"
    if codex_path.exists():
        with open(codex_path, encoding="utf-8") as f:
            codex = json.load(f)
        book_title = codex.get("title") or codex.get("book_title", "Unknown")
        author = codex.get("author", "Unknown")

    if verbose:
        print(f"\n{'='*60}")
        print(f"Prompt Generation: {book_title}")
        print(f"Visual Style: {visual_style['name']}")
        print(f"Model: {model}")
        print(f"Steps: {steps_to_run}  |  Resume: {resume}")
        print(f"{'='*60}")

    results: dict = {"success": True, "book_title": book_title}

    # Step 1: Character prompts
    if 1 in steps_to_run:
        print("\n>>> Step 1: Character image prompts")
        count = generate_character_prompts(book_dir, book_title, visual_style, model, resume, verbose)
        results["characters_prompted"] = count

    # Step 2: Location prompts
    if 2 in steps_to_run:
        print("\n>>> Step 2: Location image prompts")
        count = generate_location_prompts(book_dir, book_title, visual_style, model, resume, verbose)
        results["locations_prompted"] = count

    # Step 3: Scene prompts
    if 3 in steps_to_run:
        print("\n>>> Step 3: Scene image prompts")
        count = generate_scene_prompts(book_dir, book_title, visual_style, model, resume, verbose)
        results["scenes_prompted"] = count

    # Step 4: Thumbnail prompts
    if 4 in steps_to_run:
        print("\n>>> Step 4: Thumbnail prompts (agent council)")
        thumbnail_result = generate_thumbnail_prompts(
            book_dir, book_title, author, visual_style, model, verbose
        )
        # Save to foundry/{book_id}/thumbnail_prompts.json
        thumb_path = book_dir / "thumbnail_prompts.json"
        with open(thumb_path, "w", encoding="utf-8") as f:
            # Don't serialize VisualStyle TypedDict as-is, save key fields
            out = {k: v for k, v in thumbnail_result.items() if k != "style"}
            out["style_name"] = visual_style["name"]
            json.dump(out, f, indent=2, ensure_ascii=False)
        if verbose:
            n = len(thumbnail_result["prompts"])
            total_cands = len(thumbnail_result.get("all_candidates", []))
            print(f"  Step 4 done: {n} thumbnail prompts selected from {total_cands} candidates")
            print(f"  Saved: {thumb_path}")
        results["thumbnail_prompts"] = len(thumbnail_result["prompts"])

    # Step 5: Chapter card template prompt
    if 5 in steps_to_run:
        print("\n>>> Step 5: Chapter card template prompt")
        count = generate_chapter_card_prompt(
            book_dir, book_title, visual_style, visual_style_name, model, resume, verbose
        )
        results["chapter_card_prompted"] = count

    # Persist which visual style was used — read by validate_style.py and future Phase 3 re-runs
    # Re-read from disk first so we don't overwrite chapter_card_prompt written by Step 5
    if codex_path.exists():
        with open(codex_path, encoding="utf-8") as f:
            codex = json.load(f)
        codex.setdefault("metadata", {})["visual_style"] = visual_style_name
        with open(codex_path, "w", encoding="utf-8") as f:
            json.dump(codex, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"\n{'='*60}")
        print("Prompt generation complete!")
        for k, v in results.items():
            if k not in ("success", "book_title"):
                print(f"  {k}: {v}")
        print(f"{'='*60}")

    return results


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate AI image prompts for foundry book entities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Steps:
  1: Character image prompts  (characters.json)
  2: Location image prompts   (from scene analysis data)
  3: Scene image prompts      (analysis/chapter_*_analysis.json)
  4: Thumbnail prompts        (4-agent council → thumbnail_prompts.json)
  5: Chapter card prompt      (codex.json → metadata.chapter_card_prompt)

Models:
  {', '.join(AVAILABLE_MODELS.keys())}

Visual Styles:
  {', '.join(list_styles())}

Examples:
  python -m audiobook_agent.generate_prompts foundry/pg174
  python -m audiobook_agent.generate_prompts foundry/pg174 --steps 1 2
  python -m audiobook_agent.generate_prompts foundry/pg174 --model gpt-mini --style anime
  python -m audiobook_agent.generate_prompts foundry/pg174 --no-resume
        """,
    )
    parser.add_argument("book_dir", help="Path to foundry/{book_id}/ directory")
    parser.add_argument(
        "--model", default=MODEL_DEFAULT,
        help=f"OpenRouter model ID or shorthand. Default: {MODEL_DEFAULT}",
    )
    parser.add_argument(
        "--style", default="classical_illustration",
        choices=list_styles(),
        help="Visual style for all prompts. Default: classical_illustration",
    )
    parser.add_argument(
        "--steps", nargs="+", type=int, choices=[1, 2, 3, 4, 5],
        help="Steps to run (default: all 5). Example: --steps 1 2",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Re-generate prompts even if they already exist",
    )
    parser.add_argument("--quiet", action="store_true")

    args = parser.parse_args()
    model = AVAILABLE_MODELS.get(args.model, args.model)

    result = generate_book_prompts(
        book_dir=args.book_dir,
        visual_style_name=args.style,
        model=model,
        steps=args.steps,
        resume=not args.no_resume,
        verbose=not args.quiet,
    )

    if not result.get("success"):
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
