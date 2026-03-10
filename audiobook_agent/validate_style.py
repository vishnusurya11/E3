#!/usr/bin/env python3
"""
Style consistency validator for E3 foundry image prompts.

Checks that ALL image prompts in a foundry book directory use the correct
style prefix/suffix (the "style sandwich").

Data structures (as written by generate_prompts.py):
  characters.json  — dict keyed by canonical_name
                     char["image_prompt"] = {"prompt": "...", "shot_type": "...", "key_features": [...]}
  locations.json   — dict keyed by location name
                     loc["image_prompt"]  = {"prompt": "...", "shot_type": "...", "time_of_day": "..."}
  analysis/*.json  — list of scenes under "scenes" key
                     scene["scene_image_prompt"] = {"prompt": "...", "shot_type": "...", "mood_color": "..."}

Usage:
    python -m audiobook_agent.validate_style foundry/pg174
    python -m audiobook_agent.validate_style foundry/pg174 --style anime
    python -m audiobook_agent.validate_style foundry/pg174 --style classical_illustration --fix
"""

from __future__ import annotations

import json
import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from audiobook_agent.visual_styles import (
    get_style_by_name,
    get_default_style,
    list_styles,
    VisualStyle,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StyleViolation:
    file: str
    entity: str
    field: str
    issue: str      # "missing_prefix" | "missing_suffix" | "both"
    snippet: str    # First 80 chars of the offending prompt


@dataclass
class ValidationReport:
    style_name: str
    total_checked: int
    violations: list[StyleViolation] = field(default_factory=list)
    fixed: int = 0

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0


# ---------------------------------------------------------------------------
# Style detection
# ---------------------------------------------------------------------------

def _detect_style(book_dir: Path) -> Optional[VisualStyle]:
    """
    Detect which visual style is in use.

    Priority:
      1. codex.json["metadata"]["visual_style"]  (written by generate_prompts.py)
      2. Majority-vote across existing image_prompt.prompt fields
    """
    # 1. Authoritative record in codex.json
    codex_path = book_dir / "codex.json"
    if codex_path.exists():
        try:
            codex = json.loads(codex_path.read_text(encoding="utf-8"))
            style_key = codex.get("metadata", {}).get("visual_style")
            if style_key and style_key in list_styles():
                return get_style_by_name(style_key)
        except Exception:
            pass

    # 2. Majority vote
    votes: dict[str, int] = {sk: 0 for sk in list_styles()}

    char_path = book_dir / "characters.json"
    if char_path.exists():
        chars = json.loads(char_path.read_text(encoding="utf-8"))
        if isinstance(chars, dict):
            for char in chars.values():
                ip = char.get("image_prompt")
                prompt = ip.get("prompt", "") if isinstance(ip, dict) else ""
                if prompt:
                    for sk in list_styles():
                        if prompt.startswith(get_style_by_name(sk)["prefix"]):
                            votes[sk] += 1

    loc_path = book_dir / "locations.json"
    if loc_path.exists():
        locs = json.loads(loc_path.read_text(encoding="utf-8"))
        if isinstance(locs, dict):
            for loc in locs.values():
                ip = loc.get("image_prompt")
                prompt = ip.get("prompt", "") if isinstance(ip, dict) else ""
                if prompt:
                    for sk in list_styles():
                        if prompt.startswith(get_style_by_name(sk)["prefix"]):
                            votes[sk] += 1

    best = max(votes, key=lambda k: votes[k])
    return get_style_by_name(best) if votes[best] > 0 else None


# ---------------------------------------------------------------------------
# Prompt check / fix helpers
# ---------------------------------------------------------------------------

def _strip_known_style(prompt: str) -> str:
    """Remove any known style prefix/suffix, returning just the core content."""
    core = prompt.strip()

    for sk in list_styles():
        p = get_style_by_name(sk)["prefix"]
        if core.startswith(p):
            core = core[len(p):].lstrip(" ,")
            break

    for sk in list_styles():
        s = get_style_by_name(sk)["suffix"]
        idx = core.rfind(s)
        if idx != -1 and idx > len(core) // 2:
            core = core[:idx].rstrip(" ,")
            break

    return core.strip()


def _fix_prompt(prompt: str, prefix: str, suffix: str) -> str:
    """Re-wrap prompt with the correct style prefix and suffix."""
    core = _strip_known_style(prompt)
    return f"{prefix} {core}, {suffix}"


def _check_prompt(
    prompt: str,
    prefix: str,
    suffix: str,
    entity: str,
    filename: str,
    field_name: str,
    violations: list[StyleViolation],
    auto_fix: bool,
) -> str:
    """Check one prompt string. Returns (possibly fixed) prompt string."""
    has_prefix = prompt.startswith(prefix)
    has_suffix = suffix in prompt

    if has_prefix and has_suffix:
        return prompt  # correct

    issue = "both" if (not has_prefix and not has_suffix) else (
        "missing_prefix" if not has_prefix else "missing_suffix"
    )
    violations.append(StyleViolation(
        file=filename, entity=entity, field=field_name, issue=issue,
        snippet=prompt[:80],
    ))

    return _fix_prompt(prompt, prefix, suffix) if auto_fix else prompt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_style(
    book_dir: Path,
    style_name: Optional[str] = None,
    auto_fix: bool = False,
) -> ValidationReport:
    """
    Validate (and optionally fix) all image prompts in a foundry book directory.

    Args:
        book_dir:   Path to foundry/{book_id}/
        style_name: Style key (e.g. "classical_illustration"). None = auto-detect.
        auto_fix:   If True, update JSON files with corrected prompt strings.
                    Only the "prompt" field inside each image_prompt dict is
                    updated — shot_type, key_features, etc. are preserved.

    Returns:
        ValidationReport with violations found/fixed.
    """
    book_dir = Path(book_dir)

    style = get_style_by_name(style_name) if style_name else (
        _detect_style(book_dir) or get_default_style()
    )
    prefix = style["prefix"]
    suffix = style["suffix"]
    violations: list[StyleViolation] = []
    total = 0
    fixed = 0

    # -----------------------------------------------------------------------
    # characters.json — dict keyed by canonical_name
    # Each char["image_prompt"] is {"prompt": "...", "shot_type": "...", ...}
    # -----------------------------------------------------------------------
    char_path = book_dir / "characters.json"
    if char_path.exists():
        chars = json.loads(char_path.read_text(encoding="utf-8"))
        if isinstance(chars, dict):
            changed = False
            for canonical_name, char in chars.items():
                ip = char.get("image_prompt")
                if not isinstance(ip, dict):
                    continue
                prompt = ip.get("prompt", "")
                if not prompt:
                    continue
                total += 1
                new_prompt = _check_prompt(
                    prompt, prefix, suffix,
                    canonical_name, "characters.json", "image_prompt.prompt",
                    violations, auto_fix,
                )
                if auto_fix and new_prompt != prompt:
                    char["image_prompt"]["prompt"] = new_prompt
                    fixed += 1
                    changed = True
            if changed:
                char_path.write_text(
                    json.dumps(chars, indent=2, ensure_ascii=False), encoding="utf-8"
                )

    # -----------------------------------------------------------------------
    # locations.json — dict keyed by location name
    # Each loc["image_prompt"] is {"prompt": "...", "shot_type": "...", "time_of_day": "..."}
    # -----------------------------------------------------------------------
    loc_path = book_dir / "locations.json"
    if loc_path.exists():
        locs = json.loads(loc_path.read_text(encoding="utf-8"))
        if isinstance(locs, dict):
            changed = False
            for loc_name, loc in locs.items():
                ip = loc.get("image_prompt")
                if not isinstance(ip, dict):
                    continue
                prompt = ip.get("prompt", "")
                if not prompt:
                    continue
                total += 1
                new_prompt = _check_prompt(
                    prompt, prefix, suffix,
                    loc_name, "locations.json", "image_prompt.prompt",
                    violations, auto_fix,
                )
                if auto_fix and new_prompt != prompt:
                    loc["image_prompt"]["prompt"] = new_prompt
                    fixed += 1
                    changed = True
            if changed:
                loc_path.write_text(
                    json.dumps(locs, indent=2, ensure_ascii=False), encoding="utf-8"
                )

    # -----------------------------------------------------------------------
    # analysis/chapter_*_analysis.json — list of scenes
    # Each scene["scene_image_prompt"] is {"prompt": "...", "shot_type": "...", "mood_color": "..."}
    # -----------------------------------------------------------------------
    analysis_dir = book_dir / "analysis"
    if analysis_dir.exists():
        for af in sorted(analysis_dir.glob("chapter_*_analysis.json")):
            data = json.loads(af.read_text(encoding="utf-8"))
            changed = False
            for scene in data.get("scenes", []):
                sip = scene.get("scene_image_prompt")
                if not isinstance(sip, dict):
                    continue
                prompt = sip.get("prompt", "")
                if not prompt:
                    continue
                total += 1
                scene_id = scene.get("scene_id", scene.get("scene_number", "?"))
                new_prompt = _check_prompt(
                    prompt, prefix, suffix,
                    f"scene {scene_id}", af.name, "scene_image_prompt.prompt",
                    violations, auto_fix,
                )
                if auto_fix and new_prompt != prompt:
                    scene["scene_image_prompt"]["prompt"] = new_prompt
                    fixed += 1
                    changed = True
            if changed:
                af.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )

    return ValidationReport(
        style_name=style["name"],
        total_checked=total,
        violations=violations,
        fixed=fixed,
    )


def print_report(report: ValidationReport, verbose: bool = False) -> None:
    print(f"\n  Style Validator — {report.style_name}")
    print(f"  Checked   : {report.total_checked} prompts")
    if report.violations:
        print(f"  Violations: {len(report.violations)}")
    if report.fixed:
        print(f"  Fixed     : {report.fixed}")
    if report.ok:
        print("  Status    : OK — all prompts consistent")
    else:
        print("  Status    : INCONSISTENT")
        for v in report.violations[:20]:
            print(f"    [{v.file}] {v.entity} — {v.issue}")
            if verbose:
                print(f"      {v.snippet}...")
        if len(report.violations) > 20:
            print(f"    ... and {len(report.violations) - 20} more")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate style consistency of image prompts in a foundry book directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Styles: {', '.join(list_styles())}

Examples:
  # Check only (no changes):
  python -m audiobook_agent.validate_style foundry/pg174

  # Check and auto-fix:
  python -m audiobook_agent.validate_style foundry/pg174 --fix

  # Enforce a specific style (e.g. after changing --style):
  python -m audiobook_agent.validate_style foundry/pg174 --style anime --fix
        """,
    )
    parser.add_argument("book_dir", type=Path, help="Path to foundry book directory")
    parser.add_argument(
        "--style", default=None,
        help="Style to validate against (default: from codex.json or auto-detect)",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Auto-fix prompts with missing/wrong style prefix/suffix",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show prompt snippets for each violation",
    )
    args = parser.parse_args()

    if not args.book_dir.exists():
        print(f"ERROR: Book directory not found: {args.book_dir}")
        sys.exit(1)

    report = validate_style(args.book_dir, style_name=args.style, auto_fix=args.fix)
    print_report(report, verbose=args.verbose)

    if not report.ok and not args.fix:
        print(f"\nRun with --fix to auto-repair {len(report.violations)} violations.")
        sys.exit(1)


if __name__ == "__main__":
    main()
