#!/usr/bin/env python3
"""
E3 Audiobook Pipeline — End-to-end: HTML -> YouTube Upload

Phase 1: Parse HTML (parse_novel_langchain)   -> foundry/{id}/codex.json + chapters/
Phase 2: Analyze entities (analyze_entities)  -> foundry/{id}/analysis/ + characters/locations json
Phase 3: Generate prompts (generate_prompts)  -> image prompts added to all entity files
Phase 4: Generate media (generate_media)      -> ComfyUI images + TTS audio + ffmpeg video
Phase 5: YouTube upload (youtube_upload)      -> video uploaded to YouTube channel

Usage:
    # Full pipeline from raw HTML (parse -> analyze -> prompts -> media -> upload)
    python -m audiobook_agent.pipeline foundry/pg174/pg174-images.html

    # Skip parse (book already parsed), run phases 2-5
    python -m audiobook_agent.pipeline foundry/pg174 --from-phase 2

    # Run only specific phases
    python -m audiobook_agent.pipeline foundry/pg174 --phases 3 4 5

    # Upload only (video already generated)
    python -m audiobook_agent.pipeline foundry/pg174 --phases 5

    # Phase 4+5, with timeout override, upload as unlisted
    python -m audiobook_agent.pipeline foundry/pg174 --from-phase 4 --timeout 1800 --privacy unlisted
"""

import sys
import argparse
import time
from pathlib import Path


def _phase_header(n: int, name: str):
    print(f"\n{'#'*60}")
    print(f"# PHASE {n}: {name}")
    print(f"{'#'*60}")


def phase1_parse(html_file: Path, quiet: bool = False) -> Path:
    """Parse Gutenberg HTML -> foundry book directory."""
    _phase_header(1, "Parse HTML")
    from audiobook_agent.parse_novel_langchain import parse_book_with_agents, save_as_codex
    result = parse_book_with_agents(str(html_file), verbose=not quiet)
    codex_path = save_as_codex(result, str(html_file))
    book_dir = codex_path.parent
    print(f">>> Phase 1 complete: {book_dir}")
    return book_dir


def phase2_analyze(book_dir: Path, model: str = None, no_resume: bool = False):
    """Extract scenes/characters/locations via LLM."""
    _phase_header(2, "Analyze Entities")
    from audiobook_agent.analyze_entities import analyze_book_entities
    result = analyze_book_entities(
        book_dir=book_dir,
        model=model or "google/gemini-2.0-flash-lite-001",
        resume=not no_resume,
    )
    print(f">>> Phase 2 complete: {result}")


def phase3_prompts(book_dir: Path, steps: list = None, model: str = None,
                   no_resume: bool = False, style: str = None):
    """Generate AI image prompts for all entities."""
    _phase_header(3, "Generate Image Prompts")
    from audiobook_agent.generate_prompts import generate_book_prompts
    result = generate_book_prompts(
        book_dir=book_dir,
        visual_style_name=style or "classical_illustration",
        model=model or "google/gemini-2.0-flash-lite-001",
        steps=steps or [1, 2, 3, 4],
        resume=not no_resume,
    )
    print(f">>> Phase 3 complete: {result}")


def phase4_media(book_dir: Path, steps: list = None, comfyui_url: str = None,
                 timeout: int = None):
    """Generate images (ComfyUI), audio (TTS), and final video (ffmpeg)."""
    _phase_header(4, "Generate Media")
    from audiobook_agent.generate_media import run_generation
    result = run_generation(
        book_dir=book_dir,
        comfyui_url=comfyui_url,
        steps=steps or [0, 1, 2, 3, 4, 5],
        timeout=timeout,
    )
    if not result.success:
        print(f">>> Phase 4 ERROR: {result.error}")
        sys.exit(1)
    print(f">>> Phase 4 complete")
    return result


def phase5_upload(book_dir: Path, privacy: str = None, model: str = None):
    """Upload final video to YouTube."""
    _phase_header(5, "YouTube Upload")
    from audiobook_agent.youtube_upload import upload_book_video
    result = upload_book_video(book_dir, privacy=privacy, model=model)
    if not result.success:
        print(f">>> Phase 5 ERROR: {result.error}")
        sys.exit(1)
    print(f">>> Phase 5 complete: {result.video_url}")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="E3 end-to-end audiobook pipeline: HTML -> YouTube upload",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline from raw HTML (phases 1-5, ends with YouTube upload):
  python -m audiobook_agent.pipeline foundry/pg174/pg174-images.html

  # Start from analysis (book already parsed), run phases 2-5:
  python -m audiobook_agent.pipeline foundry/pg174 --from-phase 2

  # Run only prompts + media + upload:
  python -m audiobook_agent.pipeline foundry/pg174 --phases 3 4 5

  # Upload only (video already generated):
  python -m audiobook_agent.pipeline foundry/pg174 --phases 5

  # Media only, no images (audio+video), no upload:
  python -m audiobook_agent.pipeline foundry/pg174 --phases 4 --media-steps 4 5

  # Full run, 30-min ComfyUI timeout, upload as unlisted:
  python -m audiobook_agent.pipeline foundry/pg174/pg174-images.html --timeout 1800 --privacy unlisted
        """,
    )

    parser.add_argument(
        "input",
        type=Path,
        help="Gutenberg HTML file (e.g. foundry/pg174/pg174-images.html) "
             "OR existing book dir (e.g. foundry/pg174) when using --from-phase 2+",
    )

    # Phase selection
    phase_group = parser.add_mutually_exclusive_group()
    phase_group.add_argument(
        "--phases", nargs="+", type=int, choices=[1, 2, 3, 4, 5],
        help="Specific phases to run (default: all 1 2 3 4 5)",
    )
    phase_group.add_argument(
        "--from-phase", type=int, choices=[1, 2, 3, 4, 5], default=1,
        help="Start pipeline from this phase (skips earlier phases)",
    )

    # Phase 4 sub-options
    parser.add_argument(
        "--media-steps", nargs="+", type=int, choices=[0, 1, 2, 3, 4, 5],
        help="Phase 4 sub-steps (default: 0 1 2 3 4 5 = all)",
    )
    parser.add_argument(
        "--comfyui-url", default=None,
        help="ComfyUI API URL for image generation",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Per-image ComfyUI timeout in seconds (default from env/config)",
    )

    # Phase 2/3 options
    parser.add_argument(
        "--model", default=None,
        help="LLM model for analysis/prompts (e.g. google/gemini-2.0-flash-lite-001)",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Re-run all phases even if outputs already exist",
    )
    parser.add_argument(
        "--style", default=None,
        help="Visual style for image prompts (e.g. classical_illustration)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress verbose LLM output",
    )

    # Phase 5 options
    parser.add_argument(
        "--privacy",
        choices=["public", "private", "unlisted"],
        default=None,
        help="YouTube privacy status for upload (default: public)",
    )
    parser.add_argument(
        "--upload-model", default=None,
        help="LLM model for YouTube metadata generation (omit = template)",
    )

    args = parser.parse_args()
    input_path = args.input

    # Determine phases to run
    if args.phases:
        phases = sorted(set(args.phases))
    else:
        phases = list(range(args.from_phase, 6))  # from_phase..5

    print(f"\n{'='*60}")
    print("E3 AUDIOBOOK PIPELINE")
    print(f"{'='*60}")
    print(f"Input  : {input_path}")
    print(f"Phases : {phases}")
    if args.media_steps:
        print(f"Media  : steps {args.media_steps}")
    if 5 in phases:
        privacy_label = args.privacy or "public"
        print(f"Upload : {privacy_label}")
    print()

    wall_start = time.time()

    # ------------------------------------------------------------------
    # Phase 1: Parse HTML
    # ------------------------------------------------------------------
    book_dir: Path = None

    if 1 in phases:
        if not input_path.suffix.lower() == ".html":
            print(f"ERROR: Phase 1 (parse) requires an HTML file. Got: {input_path}")
            print("       Use --from-phase 2 if the book is already parsed.")
            sys.exit(1)
        if not input_path.exists():
            print(f"ERROR: HTML file not found: {input_path}")
            sys.exit(1)
        book_dir = phase1_parse(input_path, quiet=args.quiet)
    else:
        # Derive book_dir from the input (directory or HTML inside it)
        if input_path.is_dir():
            book_dir = input_path
        elif input_path.suffix.lower() == ".html":
            book_dir = input_path.parent
        else:
            book_dir = input_path

    if not book_dir or not book_dir.exists():
        print(f"ERROR: Book directory not found: {book_dir}")
        sys.exit(1)

    if not (book_dir / "codex.json").exists():
        print(f"ERROR: codex.json not found in {book_dir}")
        print("       Run phase 1 first: --from-phase 1 with an HTML file")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Phase 2: Analyze entities
    # ------------------------------------------------------------------
    if 2 in phases:
        phase2_analyze(book_dir, model=args.model, no_resume=args.no_resume)

    # ------------------------------------------------------------------
    # Phase 3: Generate image prompts
    # ------------------------------------------------------------------
    if 3 in phases:
        phase3_prompts(book_dir, model=args.model, no_resume=args.no_resume,
                       style=args.style)

    # ------------------------------------------------------------------
    # Phase 4: Generate media (images + audio + video)
    # ------------------------------------------------------------------
    if 4 in phases:
        phase4_media(
            book_dir,
            steps=args.media_steps,
            comfyui_url=args.comfyui_url,
            timeout=args.timeout,
        )

    # ------------------------------------------------------------------
    # Phase 5: YouTube upload
    # ------------------------------------------------------------------
    upload_result = None
    if 5 in phases:
        upload_result = phase5_upload(
            book_dir,
            privacy=args.privacy,
            model=args.upload_model,
        )

    elapsed = time.time() - wall_start
    h, m = divmod(int(elapsed), 3600)
    m, s = divmod(m, 60)
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE  ({h:02d}:{m:02d}:{s:02d})")
    print(f"Book dir: {book_dir}")
    if (book_dir / "videos").exists():
        vids = list((book_dir / "videos").glob("*.mp4"))
        if vids:
            print(f"Video   : {vids[0]}")
    if upload_result and upload_result.success:
        print(f"YouTube : {upload_result.video_url}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
