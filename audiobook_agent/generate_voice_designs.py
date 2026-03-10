#!/usr/bin/env python3
"""
Voice Design Generation — LangChain batch agent per book.

Reads foundry/{book_id}/characters.json and generates two TTS fields per character:

  voice_design:    10-15 word acoustic description fed to Qwen3-TTS VoiceDesign model
                   Formula: [gender register], [tonal quality], [delivery style], [personality trait]
                   e.g. "male baritone, warm confident authority, scholarly enthusiasm, steady composure"

  character_style: 5-10 word persistent acting note appended to every line's instruct
                   e.g. "Gruff military commander, clipped authority"

All characters batched in one LLM call. Resume: skips chars that already have voice_design.

Usage:
    python -m audiobook_agent.generate_voice_designs foundry/pg65238
    python -m audiobook_agent.generate_voice_designs foundry/pg65238 --no-resume
    python -m audiobook_agent.generate_voice_designs foundry/pg65238 --model gpt-mini
"""

from __future__ import annotations

import json
import os
import argparse
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY  = os.getenv("OPR_ROUTER_API_KEY", "")

MODEL_DEFAULT = "google/gemini-2.0-flash-lite-001"

AVAILABLE_MODELS: dict[str, str] = {
    "3.1":        "google/gemini-3.1-flash-lite-preview",
    "flash-lite": "google/gemini-2.0-flash-lite-001",
    "flash":      "google/gemini-2.5-flash-preview",
    "gpt-mini":   "openai/gpt-4.1-mini",
    "qwen":       "qwen/qwen3-235b-a22b",
    "kimi":       "moonshot/kimi-k2",
    "deepseek":   "deepseek/deepseek-chat-v3-0324",
    "glm":        "thudm/glm-4-32b",
}


# =============================================================================
# Pydantic schemas
# =============================================================================

class CharacterVoiceDesign(BaseModel):
    character_name: str = Field(
        description="Character name exactly as it appears in characters.json"
    )
    voice_design: str = Field(
        description=(
            "10-15 word acoustic TTS description. "
            "Formula: [gender register], [tonal quality], [delivery style], [personality trait]. "
            "Example: 'male baritone, warm confident authority, scholarly enthusiasm, steady composure'"
        )
    )
    character_style: str = Field(
        description=(
            "5-10 word persistent acting note appended to every line's instruct. "
            "Example: 'Wry English gentleman, quietly amused beneath the surface'"
        )
    )


class BookVoiceDesigns(BaseModel):
    characters: list[CharacterVoiceDesign] = Field(
        description="Voice design for every character in the book"
    )


# =============================================================================
# Prompts
# =============================================================================

_SYSTEM = """\
You are a professional audiobook casting director designing voices for a text-to-speech engine.

For each character you will output:
1. voice_design — 10-15 words describing the ACOUSTIC voice (what it sounds like).
   Formula: [gender register], [tonal quality], [delivery style], [personality trait]
   Registers: male bass / baritone / tenor; female contralto / alto / mezzo-soprano / soprano
   Examples:
     "male baritone, warm confident authority, scholarly enthusiasm, steady composure"
     "female alto, sharp commanding edge, clipped professional diction, detective authority"
     "older male bass, world-weary rumble, slow unhurried calm, gravel undertone"
     "young female soprano, bright eager energy, quick light delivery, earnest curiosity"
     "male tenor, dry sardonic wit, languid drawl, amused detachment"

2. character_style — 5-10 words describing the persistent acting attitude.
   This is appended to every line's instruct. It captures subtext and persona, not acoustic qualities.
   Examples:
     "Wry English gentleman, quietly amused beneath the surface"
     "Battle-hardened soldier, guarded and hypervigilant"
     "Young idealist, burning with suppressed passion"
     "Scheming aristocrat, every word calculated"

RULES:
- Each character must sound DISTINCT from every other character
- voice_design describes the voice acoustics — never emotions or actions
- character_style captures personality and acting approach — not acoustics
- Use the character's role, gender, physical description, and voice notes as input
- NARRATOR gets a rich storytelling voice, not tied to any character"""


def _build_human_message(characters: list[dict]) -> str:
    lines = [f"Generate voice designs for {len(characters)} characters:\n"]
    for i, char in enumerate(characters, 1):
        name = char.get("name", char.get("canonical_name", "Unknown"))
        role = char.get("role", "")
        gender = char.get("gender", "")
        phys = char.get("physical_description", "")
        voice_notes = char.get("voice_description", "")
        personality = char.get("personality", "")

        lines.append(f"{i}. {name}")
        if role:
            lines.append(f"   Role: {role}")
        if gender:
            lines.append(f"   Gender: {gender}")
        if phys:
            lines.append(f"   Appearance: {str(phys)[:150]}")
        if voice_notes and str(voice_notes).strip() and str(voice_notes) != "None":
            lines.append(f"   Voice notes: {str(voice_notes)[:200]}")
        if personality:
            lines.append(f"   Personality: {str(personality)[:150]}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# LLM factory
# =============================================================================

def _make_llm(model: str) -> ChatOpenAI:
    resolved = AVAILABLE_MODELS.get(model, model)
    return ChatOpenAI(
        model=resolved,
        openai_api_key=OPENROUTER_KEY,
        openai_api_base=OPENROUTER_BASE,
        temperature=0.5,
    )


# =============================================================================
# Core generation
# =============================================================================

def _infer_gender(char: dict) -> str:
    """Best-effort gender from name/physical description when not explicit."""
    gender = char.get("gender", "").strip().lower()
    if gender in ("male", "female"):
        return gender
    phys = str(char.get("physical_description", "")).lower()
    name = str(char.get("name", char.get("canonical_name", ""))).lower()
    female_hints = {"she", "her", "lady", "mrs", "miss", "madame", "duchess", "countess",
                    "princess", "queen", "woman", "girl"}
    male_hints   = {"he", "his", "lord", "mr", "sir", "duke", "count", "prince",
                    "king", "man", "boy", "gentleman"}
    for hint in female_hints:
        if hint in name.split() or hint in phys.split():
            return "female"
    for hint in male_hints:
        if hint in name.split() or hint in phys.split():
            return "male"
    return ""


def _fallback_voice_design(char: dict) -> tuple[str, str]:
    """Rule-based fallback when LLM fails."""
    name = char.get("name", char.get("canonical_name", "Character"))
    gender = _infer_gender(char)
    role = char.get("role", "supporting").lower()

    if gender == "female":
        register = "female mezzo-soprano"
    elif gender == "male":
        register = "male baritone"
    else:
        register = "mid-range voice"

    if "protagonist" in role:
        tone = "grounded firm presence, steady composure"
        style = "Determined hero, quiet inner resolve"
    elif "antagonist" in role or "villain" in role:
        tone = "dark commanding edge, steely intensity"
        style = "Cold calculated menace beneath civility"
    elif "minor" in role:
        tone = "clear neutral delivery, unremarkable tone"
        style = "Background figure, functional and direct"
    else:
        tone = "clear warm delivery, balanced reliability"
        style = "Steadfast supporting presence"

    voice_design = f"{register}, {tone}"
    return voice_design, style


def generate_voice_designs(
    book_dir: Path,
    model: str = MODEL_DEFAULT,
    resume: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Generate voice_design + character_style for all characters in a book.

    Args:
        book_dir:  Path to foundry/{book_id}/
        model:     OpenRouter model ID or shorthand
        resume:    Skip characters that already have voice_design (default True)
        verbose:   Print progress

    Returns:
        dict with counts: total, generated, skipped
    """
    book_dir = Path(book_dir)
    chars_path = book_dir / "characters.json"

    if not chars_path.exists():
        print(f"  ERROR: characters.json not found in {book_dir}")
        return {"total": 0, "generated": 0, "skipped": 0}

    chars_data = json.loads(chars_path.read_text(encoding="utf-8"))
    if not chars_data:
        print("  No characters found.")
        return {"total": 0, "generated": 0, "skipped": 0}

    # Identify which characters need generation
    to_generate = []
    skipped_count = 0
    for name, char in chars_data.items():
        if resume and char.get("voice_design"):
            skipped_count += 1
            if verbose:
                print(f"  [skip] {name} (already has voice_design)")
            continue
        entry = dict(char)
        entry["name"] = name
        to_generate.append((name, entry))

    total = len(chars_data)

    if not to_generate:
        if verbose:
            print(f"  All {total} characters already have voice_design — nothing to do")
        return {"total": total, "generated": 0, "skipped": skipped_count}

    if verbose:
        print(f"  {len(to_generate)} characters need voice design ({skipped_count} already done)")

    llm = _make_llm(model)
    structured = llm.with_structured_output(BookVoiceDesigns, method="json_schema")

    # Send all characters in one batch
    human_msg = _build_human_message([entry for _, entry in to_generate])
    generated_count = 0

    try:
        result: BookVoiceDesigns = structured.invoke([
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=human_msg),
        ])

        # Build lookup by character name
        by_name = {vd.character_name: vd for vd in result.characters}

        for name, entry in to_generate:
            # Try exact match first, then case-insensitive
            vd = by_name.get(name)
            if not vd:
                for k, v in by_name.items():
                    if k.lower() == name.lower():
                        vd = v
                        break

            if vd:
                chars_data[name]["voice_design"] = vd.voice_design
                chars_data[name]["character_style"] = vd.character_style
                generated_count += 1
                if verbose:
                    print(f"  [done] {name}")
                    print(f"         voice_design   : {vd.voice_design}")
                    print(f"         character_style: {vd.character_style}")
            else:
                # Fallback for any not returned by LLM
                vd_str, cs_str = _fallback_voice_design(entry)
                chars_data[name]["voice_design"] = vd_str
                chars_data[name]["character_style"] = cs_str
                generated_count += 1
                if verbose:
                    print(f"  [fallback] {name} → {vd_str}")

    except Exception as e:
        if verbose:
            print(f"  LLM error: {e} — using rule-based fallback for all")
        for name, entry in to_generate:
            vd_str, cs_str = _fallback_voice_design(entry)
            chars_data[name]["voice_design"] = vd_str
            chars_data[name]["character_style"] = cs_str
            generated_count += 1

    # Save back
    chars_path.write_text(
        json.dumps(chars_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if verbose:
        print(f"\n  Saved: {chars_path.name}")
        print(f"  Voice designs complete: {generated_count} generated, {skipped_count} skipped ({total} total)")

    return {"total": total, "generated": generated_count, "skipped": skipped_count}


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate TTS voice designs for all characters in a foundry book",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Models: {', '.join(AVAILABLE_MODELS.keys())} (or any OpenRouter model ID)

Examples:
  python -m audiobook_agent.generate_voice_designs foundry/pg65238
  python -m audiobook_agent.generate_voice_designs foundry/pg65238 --no-resume
  python -m audiobook_agent.generate_voice_designs foundry/pg65238 --model gpt-mini
        """,
    )
    parser.add_argument("book_dir", type=Path, help="Path to foundry/{book_id}/")
    parser.add_argument(
        "--model", default=MODEL_DEFAULT,
        help=f"LLM model (default: {MODEL_DEFAULT})",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Re-generate all voice designs even if already present",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress verbose output",
    )
    args = parser.parse_args()

    if not args.book_dir.exists():
        print(f"ERROR: Book directory not found: {args.book_dir}")
        raise SystemExit(1)

    print(f"\n{'='*60}")
    print("Voice Design Generation")
    print(f"Book : {args.book_dir}")
    print(f"Model: {args.model}")
    print(f"Resume: {not args.no_resume}")
    print(f"{'='*60}\n")

    result = generate_voice_designs(
        book_dir=args.book_dir,
        model=args.model,
        resume=not args.no_resume,
        verbose=not args.quiet,
    )

    print(f"\n{'='*60}")
    print(f"DONE: {result['generated']} generated, {result['skipped']} skipped")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
