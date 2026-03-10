#!/usr/bin/env python3
"""
Audio Script Generation — LangChain agent per scene.

Reads analysis/chapter_*_analysis.json and generates structured audio scripts
for each scene, saved as scene["audio_script"] = [{"speaker", "text", "instruct"}, ...].

The TTS engine (generate_media.py Step 4) reads these scripts instead of
building flat single-chunk scripts inline.

Each chunk is:
  - text:    verbatim prose from scene paragraphs (never paraphrased)
  - instruct: evocative 1-sentence TTS delivery guidance matching the scene mood
  - speaker:  always "NARRATOR" (for single_narrator mode)

Usage:
    python -m audiobook_agent.generate_audio_scripts foundry/pg65238
    python -m audiobook_agent.generate_audio_scripts foundry/pg65238 --no-resume
    python -m audiobook_agent.generate_audio_scripts foundry/pg65238 --model gpt-mini
"""

from __future__ import annotations

import json
import os
import re
import argparse
from pathlib import Path

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.getenv("OPR_ROUTER_API_KEY", "")

MODEL_DEFAULT = "openai/gpt-4.1-mini"

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

class AudioChunk(BaseModel):
    speaker: str = Field(
        description=(
            "Who delivers this chunk. Use 'NARRATOR' for narration, description, and action beats. "
            "For dialogue, use the character name EXACTLY as listed in characters_present. "
            "Never invent a name not in characters_present."
        )
    )
    text: str = Field(
        description="Verbatim prose text from the scene paragraphs — never summarize or paraphrase"
    )
    instruct: str = Field(
        description=(
            "TTS delivery guidance — 1 evocative sentence capturing pace, tone, and emotion. "
            "Example: 'Dry wit, slightly conspiratorial — a man enjoying his own cleverness.'"
        )
    )


class SceneAudioScript(BaseModel):
    chunks: list[AudioChunk] = Field(
        description="Scene prose split into chunks with speaker attribution and delivery guidance"
    )


# =============================================================================
# Prompts
# =============================================================================

_SYSTEM = """\
You are a professional audiobook director preparing narration scripts for a Victorian novel.

Your task: given a scene's prose paragraphs and characters present, split the prose into
natural reading chunks and assign a SPEAKER and INSTRUCT to each chunk.

DIALOGUE vs NARRATION — THE CARDINAL RULE:
A character speaks ONLY the text inside quotation marks ("…").
Everything else is the NARRATOR: attribution phrases, actions, descriptions, narration.

CHARACTER SPEAKER (quoted speech only):
  ✓ "What are you doing?"           ← quoted speech → character speaks this
  ✗ demanded McGrath.                ← attribution → NARRATOR says this
  ✗ Jimmy grinned.                   ← action → NARRATOR says this
  ✗ Anthony sighed.                  ← action → NARRATOR says this
  ✗ He ignored the question.         ← narration → NARRATOR says this

NARRATOR SPEAKER (everything without quotes):
  ✓ Attribution verbs: "said", "asked", "replied", "demanded", "whispered",
    "grinned", "sighed", "chuckled", "remarked", "laughed", "muttered", etc.
  ✓ Any sentence where a character is described in 3rd person
  ✓ All scene description, character actions, thoughts, transitions
  ✓ If characters_present is empty → all chunks use speaker: "NARRATOR"

SPLITTING — YOU MUST SPLIT WITHIN PARAGRAPHS AT QUOTATION BOUNDARIES:
A paragraph like:
    "What the hell are you doing?" demanded McGrath. "Starting a harem."
becomes THREE chunks:
    1. {speaker: "Jimmy McGrath", text: "What the hell are you doing?"}
    2. {speaker: "NARRATOR",      text: "demanded McGrath."}
    3. {speaker: "Jimmy McGrath", text: "Starting a harem."}

A paragraph like:
    Anthony ignored this aspersion.
is ONE NARRATOR chunk (no quotes = narration, never dialogue).

NEVER allow a character to say their own attribution:
    WRONG: speaker=McGrath, text="…demanded McGrath."
    RIGHT: speaker=McGrath, text="…"  +  separate chunk: speaker=NARRATOR, text="demanded McGrath."

OTHER RULES:
- Use ONLY names from the characters_present list — never invent or shorten names
- If you cannot confidently identify the speaker of dialogue → speaker: "NARRATOR"
- Maximum ≤300 words per chunk
- Consecutive narration paragraphs may be grouped into one chunk if ≤300 words total
- DO NOT alter, summarize, or paraphrase — output prose VERBATIM

VERBATIM QUOTES RULE — NEVER STRIP QUOTATION MARKS:
When the original paragraph contains \u201c...\u201d (curly quotes), your output text
MUST include those exact quotation marks. Never output spoken dialogue without its
surrounding quote characters.
  WRONG: text: "Make it strong, James."
  RIGHT: text: "\u201cMake it strong, James.\u201d"

SPLIT-QUOTE ATTRIBUTION — the most common pattern:
When attribution interrupts or follows a quote:
    \u201cHello,\u201d said John. \u201cHow are you?\u201d
Becomes THREE chunks:
    1. {speaker: "John",     text: "\u201cHello,\u201d"}
    2. {speaker: "NARRATOR", text: "said John."}
    3. {speaker: "John",     text: "\u201cHow are you?\u201d"}

INSTRUCT GUIDELINES:
- One sentence, evocative and specific — capture pace, tone, and emotional texture
- Match the scene mood precisely
- Examples:
    "Warm and unhurried — a drawing room at ease."
    "Rising urgency as the situation turns dangerous."
    "Dry wit, slightly conspiratorial — a man enjoying his own cleverness."
    "Heavy silence; each word chosen with care."
    "Brisk and businesslike — two professionals at work."
    "Melancholy seeps through; the narrator's voice carries quiet grief."
- For character dialogue: lean into the line's emotional grain
- DO NOT alter, summarize, or paraphrase the prose text — output it VERBATIM"""


def _build_human_message(scene: dict) -> str:
    scene_num = scene.get("scene_number", "?")
    summary = scene.get("summary", "")
    location = scene.get("location", "")
    loc_desc = scene.get("location_description", "")
    mood = scene.get("mood", "")
    key_events = scene.get("key_events", [])
    paragraphs = scene.get("paragraphs", [])

    mood_color = ""
    sip = scene.get("scene_image_prompt")
    if isinstance(sip, dict):
        mood_color = sip.get("mood_color", "")

    characters_present = scene.get("characters_present", [])

    lines = [
        f"Scene {scene_num}: {summary}",
        f"Location: {location}" + (f" — {loc_desc}" if loc_desc else ""),
        f"Mood: {mood}" + (f" | Atmosphere: {mood_color}" if mood_color else ""),
    ]
    if key_events:
        lines.append(f"Key events: {' | '.join(key_events)}")
    if characters_present:
        lines.append(f"Characters present: {', '.join(characters_present)}")
    else:
        lines.append("Characters present: none (all chunks → speaker: NARRATOR)")

    lines.append("")
    lines.append("PARAGRAPHS (output verbatim, assign speaker per chunk):")
    for para in paragraphs:
        if para.strip():
            lines.append(para.strip())

    return "\n".join(lines)


# =============================================================================
# Post-processing validator
# =============================================================================

_QUOTE_SPLIT_RE = re.compile(
    r'([\u201c\u201d\u201e""][^\u201c\u201d\u201e""]*[\u201c\u201d\u201e""])'
)


def _split_text_by_quotes(text: str) -> list[tuple[str, str]]:
    """
    Split text containing dialogue+attribution into (type, segment) pairs.
    type is 'dialogue' (inside quotes) or 'narration' (between/outside quotes).

    Example:
        '\u201cHello,\u201d said John. \u201cHow are you?\u201d'
        -> [('dialogue', '\u201cHello,\u201d'),
            ('narration', 'said John.'),
            ('dialogue', '\u201cHow are you?\u201d')]
    """
    parts = _QUOTE_SPLIT_RE.split(text)
    segments = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part[0] in ('"', '\u201c', '\u201d', '\u201e', '\u201c', '\u201d'):
            segments.append(('dialogue', part))
        else:
            segments.append(('narration', part))
    return segments


def _post_process_chunks(chunks: list[dict], characters_present: list[str]) -> list[dict]:
    """
    Rule-based validation with three passes:
      Pass 1: character chunk with no quotes → reassign to NARRATOR
      Pass 2: character chunk with mixed dialogue+attribution → split at quote boundaries
      Pass 3: pass through unchanged
    """
    char_set = {c.upper() for c in characters_present}
    out = []

    for chunk in chunks:
        speaker = chunk.get("speaker", "NARRATOR")
        text = chunk.get("text", "")
        instruct = chunk.get("instruct", "")
        is_char = speaker != "NARRATOR" and speaker.upper() in char_set
        has_quotes = any(c in text for c in ('"', '\u201c', '\u201d', '\u201e', '\u201c', '\u201d'))

        # Pass 1: character chunk with no quotes → NARRATOR
        if is_char and not has_quotes:
            out.append({"speaker": "NARRATOR", "text": text, "instruct": instruct})
            continue

        # Pass 2: character chunk with mixed dialogue+attribution → split
        if is_char and has_quotes:
            segments = _split_text_by_quotes(text)
            has_narration = any(t == 'narration' for t, _ in segments)
            has_dialogue = any(t == 'dialogue' for t, _ in segments)
            if has_narration and has_dialogue and len(segments) > 1:
                for seg_type, seg_text in segments:
                    out.append({
                        "speaker": speaker if seg_type == 'dialogue' else "NARRATOR",
                        "text": seg_text,
                        "instruct": instruct,
                    })
                continue

        out.append(chunk)

    # Pass 4: strip quotes from NARRATOR chunks that are duplicated in adjacent character chunks
    # Pattern A: NARRATOR[i] text contains quote Q, CHARACTER[i+1] text == Q → remove Q from NARRATOR[i]
    # Pattern B: exact consecutive duplicate → keep the character version
    # We do a two-pass: first collect all character texts in a lookahead set per position,
    # then strip matching quotes from preceding NARRATOR chunks.
    result = []
    for i, chunk in enumerate(out):
        if chunk["speaker"] != "NARRATOR":
            result.append(chunk)
            continue

        text = chunk["text"]
        instruct = chunk["instruct"]

        # Collect quoted strings from this NARRATOR chunk
        narrator_segs = _split_text_by_quotes(text)
        if not any(t == 'dialogue' for t, _ in narrator_segs):
            # No quotes in narrator chunk — nothing to strip
            result.append(chunk)
            continue

        # Gather texts of immediately following character chunks (look ahead up to 6)
        following_char_texts = set()
        for j in range(i + 1, min(i + 7, len(out))):
            if out[j]["speaker"] != "NARRATOR":
                following_char_texts.add(out[j]["text"].strip())
            else:
                break  # stop at next narrator chunk

        # Strip any dialogue segments whose text appears in following character chunks
        kept_segs = []
        for seg_type, seg_text in narrator_segs:
            if seg_type == 'dialogue' and seg_text.strip() in following_char_texts:
                continue  # drop — character will say this
            kept_segs.append(seg_text)

        # Rebuild narrator text from remaining segments
        new_text = " ".join(s.strip() for s in kept_segs if s.strip())
        if new_text:
            result.append({"speaker": "NARRATOR", "text": new_text, "instruct": instruct})
        # If nothing left, drop the narrator chunk entirely

    # Pass 5: consecutive exact duplicate → keep character version or drop
    deduped = []
    for chunk in result:
        if (deduped and chunk["text"].strip() == deduped[-1]["text"].strip()):
            if deduped[-1]["speaker"] == "NARRATOR" and chunk["speaker"] != "NARRATOR":
                deduped[-1] = chunk
            # else drop the dupe
        else:
            deduped.append(chunk)

    # Pass 6: remove NARRATOR chunks whose text already appears in another NARRATOR chunk
    # (catches non-consecutive duplicates created by quote-stripping, e.g. parentheticals)
    seen_narrator_texts = set()
    final = []
    for chunk in deduped:
        if chunk["speaker"] == "NARRATOR":
            t = chunk["text"].strip()
            if t in seen_narrator_texts:
                continue  # drop duplicate narrator line
            seen_narrator_texts.add(t)
        final.append(chunk)
    return final


def _validate_audio_script(chunks: list[dict]) -> list[int]:
    """Return indices of chunks that have 2+ opening quotes (need re-splitting)."""
    bad = []
    for i, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        opens = sum(1 for c in text if c in ('\u201c', '"'))
        if opens >= 2:
            bad.append(i)
    return bad


def _force_split_chunk(chunk: dict, characters_present: list[str]) -> list[dict]:
    """Force-split a chunk with 2+ quoted segments into separate chunks."""
    segments = _split_text_by_quotes(chunk["text"])
    if len(segments) <= 1:
        return [chunk]

    speaker = chunk["speaker"]
    instruct = chunk["instruct"]
    result = []

    # Determine dialogue speaker
    if speaker != "NARRATOR":
        dial_speaker = speaker
    elif len(characters_present) == 1:
        dial_speaker = characters_present[0]
    else:
        dial_speaker = "NARRATOR"

    for seg_type, seg_text in segments:
        result.append({
            "speaker": dial_speaker if seg_type == 'dialogue' else "NARRATOR",
            "text": seg_text,
            "instruct": instruct,
        })
    return result


MAX_RETRIES = 2


# =============================================================================
# LLM factory
# =============================================================================

def _make_llm(model: str) -> ChatOpenAI:
    resolved = AVAILABLE_MODELS.get(model, model)
    return ChatOpenAI(
        model=resolved,
        openai_api_key=OPENROUTER_KEY,
        openai_api_base=OPENROUTER_BASE,
        temperature=0.4,
    )


# =============================================================================
# Core generation
# =============================================================================

def generate_scene_audio_script(
    scene: dict,
    llm_structured,
    max_retries: int = MAX_RETRIES,
) -> list[dict]:
    """Call LLM to generate audio script, validate, retry if bad chunks found."""
    characters = scene.get("characters_present", [])

    for attempt in range(1 + max_retries):
        human_msg = _build_human_message(scene)
        result: SceneAudioScript = llm_structured.invoke([
            SystemMessage(content=_SYSTEM),
            HumanMessage(content=human_msg),
        ])
        chunks = [
            {"speaker": chunk.speaker or "NARRATOR", "text": chunk.text, "instruct": chunk.instruct}
            for chunk in result.chunks
            if chunk.text.strip()
        ]
        chunks = _post_process_chunks(chunks, characters)
        bad_indices = _validate_audio_script(chunks)

        if not bad_indices:
            return chunks  # clean

        if attempt < max_retries:
            print(f"      RETRY {attempt+1}/{max_retries}: {len(bad_indices)} bad chunk(s) with 2+ quotes")

    # Exhausted retries -- force-split remaining bad chunks
    print(f"      FORCE-SPLIT: {len(bad_indices)} chunk(s) after {max_retries} retries")
    bad_set = set(bad_indices)
    final = []
    for i, chunk in enumerate(chunks):
        if i in bad_set:
            final.extend(_force_split_chunk(chunk, characters))
        else:
            final.append(chunk)
    return final


def generate_book_audio_scripts(
    book_dir: Path,
    model: str = MODEL_DEFAULT,
    resume: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Generate audio scripts for all scenes in a foundry book directory.

    Args:
        book_dir:  Path to foundry/{book_id}/
        model:     OpenRouter model ID or shorthand
        resume:    Skip scenes that already have audio_script (default True)
        verbose:   Print progress

    Returns:
        dict with counts: total_scenes, generated, skipped
    """
    book_dir = Path(book_dir)
    analysis_dir = book_dir / "analysis"

    if not analysis_dir.exists():
        print(f"  ERROR: analysis/ not found in {book_dir}")
        return {"total_scenes": 0, "generated": 0, "skipped": 0}

    analysis_files = sorted(analysis_dir.glob("chapter_*_analysis.json"))
    if not analysis_files:
        print("  No chapter analysis files found.")
        return {"total_scenes": 0, "generated": 0, "skipped": 0}

    llm = _make_llm(model)
    structured = llm.with_structured_output(SceneAudioScript, method="json_schema")

    total = 0
    generated = 0
    skipped = 0

    for af in analysis_files:
        data = json.loads(af.read_text(encoding="utf-8"))
        scenes = data.get("scenes", [])
        chapter_title = data.get("chapter_title", af.stem)
        changed = False

        for scene in scenes:
            total += 1
            scene_id = scene.get("scene_number", total)

            if resume and scene.get("audio_script"):
                skipped += 1
                if verbose:
                    print(f"  [skip] {af.name} scene {scene_id} (already has audio_script)")
                continue

            paragraphs = scene.get("paragraphs", [])
            if not paragraphs:
                skipped += 1
                if verbose:
                    print(f"  [skip] {af.name} scene {scene_id} (no paragraphs)")
                continue

            if verbose:
                word_count = sum(len(p.split()) for p in paragraphs)
                print(f"  [{af.stem} sc{scene_id}] {word_count}w -> generating script...")

            try:
                script = generate_scene_audio_script(scene, structured)
                if script:
                    scene["audio_script"] = script
                    generated += 1
                    changed = True
                    if verbose:
                        print(f"    -> {len(script)} chunk(s): {[c['instruct'][:60] for c in script]}")
                else:
                    skipped += 1
                    if verbose:
                        print(f"    -> empty result, skipping")
            except Exception as e:
                skipped += 1
                if verbose:
                    print(f"    -> ERROR: {e}")

        if changed:
            af.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            if verbose:
                print(f"  Saved: {af.name}")

    if verbose:
        print(f"\n  Audio scripts complete: {generated} generated, {skipped} skipped ({total} total)")

    # Final validation pass over all files
    if verbose:
        print(f"\n  Validation pass...")
    total_bad = 0
    for af in analysis_files:
        data = json.loads(af.read_text(encoding="utf-8"))
        for scene in data.get("scenes", []):
            script = scene.get("audio_script", [])
            bad = _validate_audio_script(script)
            if bad:
                total_bad += len(bad)
                ch = data.get("chapter_title", af.stem)
                sn = scene.get("scene_number", "?")
                if verbose:
                    print(f"    WARN: {ch} scene {sn} still has {len(bad)} bad chunk(s)")
    if verbose:
        if total_bad == 0:
            print(f"  Validation PASSED: all chunks clean")
        else:
            print(f"  Validation FAILED: {total_bad} bad chunk(s) remain")

    return {"total_scenes": total, "generated": generated, "skipped": skipped, "bad_chunks": total_bad}


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate LangChain audio scripts for all scenes in a foundry book",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Models: {', '.join(AVAILABLE_MODELS.keys())} (or any OpenRouter model ID)

Examples:
  python -m audiobook_agent.generate_audio_scripts foundry/pg65238
  python -m audiobook_agent.generate_audio_scripts foundry/pg65238 --no-resume
  python -m audiobook_agent.generate_audio_scripts foundry/pg65238 --model gpt-mini
        """,
    )
    parser.add_argument("book_dir", type=Path, help="Path to foundry/{book_id}/")
    parser.add_argument(
        "--model", default=MODEL_DEFAULT,
        help=f"LLM model (default: {MODEL_DEFAULT})",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Re-generate all scripts even if already present",
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
    print(f"Audio Script Generation")
    print(f"Book : {args.book_dir}")
    print(f"Model: {args.model}")
    print(f"Resume: {not args.no_resume}")
    print(f"{'='*60}\n")

    result = generate_book_audio_scripts(
        book_dir=args.book_dir,
        model=args.model,
        resume=not args.no_resume,
        verbose=not args.quiet,
    )

    print(f"\n{'='*60}")
    print(f"DONE: {result['generated']} scripts generated, {result['skipped']} skipped")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
