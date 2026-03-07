#!/usr/bin/env python3
"""
Entity Extraction Pipeline — Scenes, Characters, Locations

Reads TTS chapter files from foundry/{book_id}/chapters/ and extracts structured
entity data using a single LLM call per chapter.  Results are accumulated into
growing master profiles:

    foundry/{book_id}/characters.json        ← accumulated character profiles
    foundry/{book_id}/locations.json         ← accumulated location profiles
    foundry/{book_id}/analysis/
        chapter_001_analysis.json            ← per-chapter scene breakdown
        ...

Usage:
    python -m audiobook_agent.analyze_entities foundry/pg174 [--model MODEL] [--no-resume]
"""

from __future__ import annotations

import json
import os
import re
import argparse
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.getenv("OPR_ROUTER_API_KEY", "")

# ---------------------------------------------------------------------------
# Model roster — cheapest first
# ---------------------------------------------------------------------------

MODEL_ENTITY_EXTRACTOR = "google/gemini-2.0-flash-lite-001"

# Available alternatives (set via --model or programmatically):
AVAILABLE_MODELS = {
    "flash-lite":    "google/gemini-2.0-flash-lite-001",   # $0.05 / $0.20
    "flash":         "google/gemini-2.5-flash-preview",     # $0.15 / $0.60
    "gpt-mini":      "openai/gpt-4.1-mini",                 # $0.075 / $0.30
    "qwen":          "qwen/qwen3-235b-a22b",                # $0.20 / $0.60
    "kimi":          "moonshot/kimi-k2",                    # $0.40 / $2.00
    "deepseek":      "deepseek/deepseek-chat-v3-0324",      # $0.27 / $1.10
    "glm":           "thudm/glm-4-32b",                     # ~$0.10 / $0.10
}

# ---------------------------------------------------------------------------
# Pydantic models — extraction output (one LLM call per chapter)
# ---------------------------------------------------------------------------

class CharacterMention(BaseModel):
    name: str = Field(description="Canonical name of the character as used in the chapter")
    aliases: list[str] = Field(default_factory=list,
        description="Other names/titles used for this character (e.g. 'Mr Gray', 'Harry')")
    role: str = Field(default="supporting",
        description="One of: protagonist, antagonist, supporting, minor")
    physical_description: str = Field(default="",
        description="NEW physical details visible in this scene only — hair, eyes, build, age. "
                    "Leave empty if nothing new is described.")
    clothing: str = Field(default="",
        description="What they are wearing in this scene. Leave empty if not described.")
    voice_description: str = Field(default="",
        description="Speech style, tone, accent, pace. Leave empty if not described.")
    personality_notes: str = Field(default="",
        description="Character trait or attitude revealed specifically in this scene.")

    # Coerce None → "" for optional string fields (LLMs sometimes return null)
    @field_validator("physical_description", "clothing", "voice_description",
                     "personality_notes", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return v if v is not None else ""

    @field_validator("aliases", mode="before")
    @classmethod
    def _none_list(cls, v):
        return v if v is not None else []


class SceneAnalysis(BaseModel):
    scene_number: int = Field(description="Sequential scene number within the chapter, starting at 1")
    start_para_id: int = Field(description="para_id of the FIRST paragraph belonging to this scene (1-based)")
    end_para_id: int = Field(description="para_id of the LAST paragraph belonging to this scene (inclusive, 1-based)")
    summary: str = Field(description="2-3 sentence description of what happens in this scene")
    location: str = Field(description="Canonical location name (e.g. 'conservatory at Selby Royal')")
    location_description: str = Field(default="",
        description="Visual/atmospheric details — decor, lighting, time of day, weather")
    characters_present: list[str] = Field(default_factory=list,
        description="Canonical names of all characters who appear in this scene")
    character_details: list[CharacterMention] = Field(default_factory=list,
        description="Detailed extraction for each character present")
    mood: str = Field(default="neutral",
        description="Scene mood: tense, comedic, romantic, dramatic, melancholic, ominous, etc.")
    key_events: list[str] = Field(default_factory=list,
        description="3-5 bullet points of the most important things that happen")

    @field_validator("location_description", "mood", mode="before")
    @classmethod
    def _none_to_default(cls, v):
        return v if v is not None else ""

    @field_validator("characters_present", "key_events", "character_details", mode="before")
    @classmethod
    def _none_list(cls, v):
        return v if v is not None else []

    @field_validator("start_para_id", "end_para_id", mode="before")
    @classmethod
    def _none_int(cls, v):
        return v if v is not None else 1


class ChapterAnalysis(BaseModel):
    chapter_index: int = Field(description="Chapter number (integer)")
    chapter_title: str = Field(description="Chapter title as it appears in the book")
    scenes: list[SceneAnalysis] = Field(description="Ordered list of scenes in this chapter")


# ---------------------------------------------------------------------------
# Pydantic models — accumulated master profiles
# ---------------------------------------------------------------------------

class CharacterProfile(BaseModel):
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    role: str = "supporting"
    physical_description: str = ""
    clothing_seen: list[str] = Field(default_factory=list)
    voice_description: str = ""
    personality: str = ""
    first_appears_chapter: int = 0
    appears_in_chapters: list[int] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, d: dict) -> "CharacterProfile":
        return cls(**d)


class LocationProfile(BaseModel):
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    first_appears_chapter: int = 0
    appears_in_chapters: list[int] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, d: dict) -> "LocationProfile":
        return cls(**d)


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _make_llm(model: str, temperature: float = 0.0) -> ChatOpenAI:
    if not OPENROUTER_KEY:
        raise RuntimeError("OPR_ROUTER_API_KEY not set in environment")
    return ChatOpenAI(
        model=model,
        openai_api_key=OPENROUTER_KEY,
        openai_api_base=OPENROUTER_BASE,
        temperature=temperature,
        max_tokens=16000,
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATE = """\
You are a literary analyst extracting structured entity data from a chapter of a novel.

Book: "{title}"
Chapter: {chapter_num} — "{chapter_title}"

Known characters so far (use these canonical names when referring to them):
{known_chars}

Known locations so far (use these canonical names when referring to them):
{known_locs}

Your task:
1. Split the chapter into SCENES. A new scene starts when the location, time, or the
   primary character group significantly changes.
2. For EACH scene you MUST report:
   - start_para_id: the para_id of the first paragraph that belongs to this scene
   - end_para_id: the para_id of the last paragraph that belongs to this scene (inclusive)
   - All scenes together must cover ALL paragraphs in the chapter with no gaps or overlaps.
     The first scene's start_para_id must be 1.
     Each subsequent scene's start_para_id must be exactly end_para_id+1 of the prior scene.
3. Also identify for each scene:
   - Where it takes place (canonical name; reuse from known list if it matches)
   - Who is present (canonical names)
   - NEW physical/clothing/voice/personality details for each character visible ONLY
     in this scene — do NOT repeat information already known from prior chapters
   - The mood and 3-5 key events
4. Keep character details specific and scene-local. Omit empty fields.
5. If a character is NEW (not in the known list), invent a clean canonical name for them.
"""

def _build_messages(
    ch_num: int,
    ch_title: str,
    paragraphs: list[str],
    book_title: str,
    known_chars: list[str],
    known_locs: list[str],
) -> list:
    # Label each paragraph with its 1-based para_id
    paras_text = "\n\n".join(
        f"[para_id={i+1}] {p}" for i, p in enumerate(paragraphs)
    )

    known_chars_str = ", ".join(known_chars) if known_chars else "none yet"
    known_locs_str = ", ".join(known_locs) if known_locs else "none yet"

    system = SYSTEM_TEMPLATE.format(
        title=book_title,
        chapter_num=ch_num,
        chapter_title=ch_title,
        known_chars=known_chars_str,
        known_locs=known_locs_str,
    )
    human = f"Chapter text (each full paragraph labelled with its para_id):\n\n{paras_text}"

    return [SystemMessage(content=system), HumanMessage(content=human)]


# ---------------------------------------------------------------------------
# Profile merging helpers
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Lowercase + strip for fuzzy matching."""
    return re.sub(r"\s+", " ", name.strip().lower())


def _find_profile_key(profiles: dict, name: str, aliases: list[str]) -> Optional[str]:
    """Return the existing key in profiles that matches name or any alias."""
    needle_norm = _normalize(name)
    alias_norms = {_normalize(a) for a in aliases}
    for key in profiles:
        key_norm = _normalize(key)
        if key_norm == needle_norm or needle_norm in alias_norms or key_norm in alias_norms:
            return key
        # also check stored aliases
        stored_aliases = {_normalize(a) for a in profiles[key].get("aliases", [])}
        if needle_norm in stored_aliases or bool(alias_norms & stored_aliases):
            return key
    return None


def _append_if_new(existing: str, new: str, sep: str = " ") -> str:
    """Append `new` text to `existing` only if it adds genuinely new content."""
    if not new:
        return existing
    if not existing:
        return new.strip()
    if _normalize(new) in _normalize(existing):
        return existing  # already contained
    return existing.rstrip() + sep + new.strip()


def _merge_characters(
    profiles: dict,
    analysis: ChapterAnalysis,
    chapter_idx: int,
) -> None:
    """Update profiles (dict of canonical_name → raw dict) in-place."""
    for scene in analysis.scenes:
        for mention in scene.character_details:
            key = _find_profile_key(profiles, mention.name, mention.aliases)
            if key is None:
                # New character
                prof = CharacterProfile(
                    canonical_name=mention.name,
                    aliases=mention.aliases,
                    role=mention.role,
                    physical_description=mention.physical_description,
                    clothing_seen=[mention.clothing] if mention.clothing else [],
                    voice_description=mention.voice_description,
                    personality=mention.personality_notes,
                    first_appears_chapter=chapter_idx,
                    appears_in_chapters=[chapter_idx],
                )
                profiles[mention.name] = prof.to_dict()
            else:
                d = profiles[key]
                # Merge aliases
                existing_aliases = set(_normalize(a) for a in d.get("aliases", []))
                for alias in mention.aliases:
                    if _normalize(alias) not in existing_aliases:
                        d.setdefault("aliases", []).append(alias)
                        existing_aliases.add(_normalize(alias))
                # Update role (more specific > less specific)
                role_priority = {"protagonist": 4, "antagonist": 3, "supporting": 2, "minor": 1}
                if role_priority.get(mention.role, 0) > role_priority.get(d.get("role", "minor"), 0):
                    d["role"] = mention.role
                # Accumulate text fields
                d["physical_description"] = _append_if_new(
                    d.get("physical_description", ""), mention.physical_description, " ")
                d["voice_description"] = _append_if_new(
                    d.get("voice_description", ""), mention.voice_description, " ")
                d["personality"] = _append_if_new(
                    d.get("personality", ""), mention.personality_notes, "; ")
                # Clothing list
                if mention.clothing:
                    cl = d.setdefault("clothing_seen", [])
                    if mention.clothing not in cl:
                        cl.append(mention.clothing)
                # Chapter appearances
                chapters = d.setdefault("appears_in_chapters", [])
                if chapter_idx not in chapters:
                    chapters.append(chapter_idx)
                    chapters.sort()


def _merge_locations(
    profiles: dict,
    analysis: ChapterAnalysis,
    chapter_idx: int,
) -> None:
    """Update location profiles (dict of canonical_name → raw dict) in-place."""
    for scene in analysis.scenes:
        loc_name = scene.location
        if not loc_name:
            continue
        key = _find_profile_key(profiles, loc_name, [])
        if key is None:
            prof = LocationProfile(
                canonical_name=loc_name,
                description=scene.location_description,
                first_appears_chapter=chapter_idx,
                appears_in_chapters=[chapter_idx],
            )
            profiles[loc_name] = prof.to_dict()
        else:
            d = profiles[key]
            d["description"] = _append_if_new(
                d.get("description", ""), scene.location_description, " ")
            chapters = d.setdefault("appears_in_chapters", [])
            if chapter_idx not in chapters:
                chapters.append(chapter_idx)
                chapters.sort()


# ---------------------------------------------------------------------------
# Single-chapter analysis
# ---------------------------------------------------------------------------

def analyze_chapter(
    ch_num: int,
    ch_title: str,
    paragraphs: list[str],
    book_title: str,
    known_chars: list[str],
    known_locs: list[str],
    model: str = MODEL_ENTITY_EXTRACTOR,
    verbose: bool = True,
) -> ChapterAnalysis:
    """Call LLM once to extract scenes/characters/locations for one chapter."""
    llm = _make_llm(model)
    structured_llm = llm.with_structured_output(ChapterAnalysis, method="json_schema")
    messages = _build_messages(ch_num, ch_title, paragraphs, book_title, known_chars, known_locs)
    if verbose:
        print(f"  Analyzing chapter {ch_num:03d}: {ch_title} ...", end=" ", flush=True)
    result: ChapterAnalysis = structured_llm.invoke(messages)
    if verbose:
        print(f"{len(result.scenes)} scene(s)")
    return result


# ---------------------------------------------------------------------------
# Main book-level function
# ---------------------------------------------------------------------------

def analyze_book_entities(
    book_dir: str | Path,
    model: str = MODEL_ENTITY_EXTRACTOR,
    verbose: bool = True,
    resume: bool = True,
) -> dict:
    """
    Analyze all chapters in a foundry book directory and accumulate entity profiles.

    Args:
        book_dir:  Path to foundry/{book_id}/  (must contain chapters/metadata.json)
        model:     OpenRouter model ID
        resume:    If True, skip chapters that already have analysis/*.json output
    Returns:
        {"success": bool, "chapters_analyzed": int, "chapters_skipped": int,
         "characters": int, "locations": int}
    """
    book_dir = Path(book_dir).resolve()
    chapters_dir = book_dir / "chapters"
    analysis_dir = book_dir / "analysis"
    analysis_dir.mkdir(exist_ok=True)

    # Load codex.json for full paragraphs (not TTS chunks)
    codex_path = book_dir / "codex.json"
    if not codex_path.exists():
        raise FileNotFoundError(f"codex.json not found in {book_dir}")

    with open(codex_path, encoding="utf-8") as f:
        codex = json.load(f)

    # Build chapter_number → paragraphs lookup
    codex_paragraphs: dict[int, list[str]] = {
        ch["chapter_number"]: ch["paragraphs"]
        for ch in codex.get("chapters", [])
    }

    book_title = codex.get("title") or codex.get("book_title", "Unknown")

    # Use metadata.json for chapter list (index/title)
    metadata_path = chapters_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"chapters/metadata.json not found in {book_dir}")

    with open(metadata_path, encoding="utf-8") as f:
        meta = json.load(f)

    chapter_list = meta.get("chapters", [])

    if verbose:
        print(f"\n{'='*60}")
        print(f"Entity extraction: {book_title}")
        print(f"Model: {model}")
        print(f"Chapters: {len(chapter_list)}  |  Resume: {resume}")
        print(f"{'='*60}")

    # Load existing profiles (for resume support)
    char_profiles: dict = {}
    loc_profiles: dict = {}
    chars_path = book_dir / "characters.json"
    locs_path = book_dir / "locations.json"

    if resume and chars_path.exists():
        with open(chars_path, encoding="utf-8") as f:
            char_profiles = json.load(f)
        if verbose:
            print(f"Loaded {len(char_profiles)} existing character profiles")

    if resume and locs_path.exists():
        with open(locs_path, encoding="utf-8") as f:
            loc_profiles = json.load(f)
        if verbose:
            print(f"Loaded {len(loc_profiles)} existing location profiles")

    chapters_analyzed = 0
    chapters_skipped = 0

    for ch_meta in chapter_list:
        ch_idx = ch_meta["index"]
        analysis_path = analysis_dir / f"chapter_{ch_idx:03d}_analysis.json"

        if resume and analysis_path.exists():
            chapters_skipped += 1
            if verbose:
                print(f"  Skipping chapter {ch_idx:03d} (already analyzed)")
            # Still need to re-merge into profiles if loaded from file
            # (they were already merged before the file was saved, so skip)
            continue

        # Get full paragraphs from codex
        paragraphs = codex_paragraphs.get(ch_idx, [])
        if not paragraphs:
            if verbose:
                print(f"  WARNING: no paragraphs in codex for chapter {ch_idx}, skipping")
            continue

        ch_title = ch_meta.get("title", f"Chapter {ch_idx}")
        known_chars = sorted(char_profiles.keys())
        known_locs = sorted(loc_profiles.keys())

        try:
            analysis = analyze_chapter(
                ch_idx, ch_title, paragraphs, book_title, known_chars, known_locs,
                model=model, verbose=verbose,
            )
        except Exception as e:
            if "length limit" in str(e) or "max_tokens" in str(e).lower():
                fallback = "openai/gpt-4.1-mini"
                print(f"  Output cap hit — retrying chapter {ch_idx} with {fallback}")
                try:
                    analysis = analyze_chapter(
                        ch_idx, ch_title, paragraphs, book_title, known_chars, known_locs,
                        model=fallback, verbose=verbose,
                    )
                except Exception as e2:
                    print(f"  ERROR on chapter {ch_idx} (fallback): {e2}")
                    continue
            else:
                print(f"  ERROR on chapter {ch_idx}: {e}")
                continue

        # Build para_id (1-based) → text lookup for embedding actual paragraphs
        para_map = {i + 1: p for i, p in enumerate(paragraphs)}
        max_para_id = len(paragraphs)

        # Embed actual paragraphs into each scene
        analysis_dict = analysis.model_dump()
        for scene in analysis_dict["scenes"]:
            s_start = max(1, scene.get("start_para_id", 1))
            s_end = min(max_para_id, scene.get("end_para_id", max_para_id))
            scene["paragraphs"] = [
                para_map[pid]
                for pid in range(s_start, s_end + 1)
                if pid in para_map
            ]

        # Save per-chapter analysis
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(analysis_dict, f, indent=2, ensure_ascii=False)

        # Merge into master profiles
        _merge_characters(char_profiles, analysis, ch_idx)
        _merge_locations(loc_profiles, analysis, ch_idx)

        # Save after each chapter so resume works even if interrupted
        with open(chars_path, "w", encoding="utf-8") as f:
            json.dump(char_profiles, f, indent=2, ensure_ascii=False)
        with open(locs_path, "w", encoding="utf-8") as f:
            json.dump(loc_profiles, f, indent=2, ensure_ascii=False)

        chapters_analyzed += 1

    if verbose:
        print(f"\nDone: {chapters_analyzed} analyzed, {chapters_skipped} skipped")
        print(f"Characters: {len(char_profiles)}  |  Locations: {len(loc_profiles)}")
        print(f"Saved: {chars_path}")
        print(f"Saved: {locs_path}")
        print(f"Analysis files: {analysis_dir}/")

    return {
        "success": True,
        "chapters_analyzed": chapters_analyzed,
        "chapters_skipped": chapters_skipped,
        "characters": len(char_profiles),
        "locations": len(loc_profiles),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract scenes, characters, and locations from foundry chapter files"
    )
    parser.add_argument("book_dir", help="Path to foundry/{book_id}/ directory")
    parser.add_argument(
        "--model", default=MODEL_ENTITY_EXTRACTOR,
        help=f"OpenRouter model ID or shorthand ({', '.join(AVAILABLE_MODELS)}). "
             f"Default: {MODEL_ENTITY_EXTRACTOR}"
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Re-analyze all chapters even if analysis files already exist"
    )
    parser.add_argument("--quiet", action="store_true")

    args = parser.parse_args()
    model = AVAILABLE_MODELS.get(args.model, args.model)
    verbose = not args.quiet

    result = analyze_book_entities(
        args.book_dir,
        model=model,
        verbose=verbose,
        resume=not args.no_resume,
    )
    if not args.quiet:
        print(f"\nResult: {result}")


if __name__ == "__main__":
    main()
