"""
Visual style definitions for AI image/video generation (audiobook pipeline).

Each style controls aesthetic of generated character, location, and scene images.
Prefix goes at START of prompts; suffix goes at END with quality tags.

Based on 2026 AI prompt engineering best practices:
  - Style keywords work best EARLY in prompts (first 1/3)
  - Reinforced at END with technical quality tags
"""

from __future__ import annotations
from typing import TypedDict


class VisualStyle(TypedDict):
    """Visual style configuration for image generation."""
    name: str
    prefix: str        # Placed at START of every prompt
    suffix: str        # Placed at END with quality tags
    description: str


VISUAL_STYLES: dict[str, VisualStyle] = {
    "classical_illustration": {
        "name": "Classical Illustration",
        "prefix": "Classical illustration artwork,",
        "suffix": (
            "classical illustration style, detailed pen and ink with watercolor wash, "
            "Victorian era aesthetic, rich cross-hatching, warm sepia tones, "
            "museum-quality fine art illustration, highly detailed"
        ),
        "description": "Victorian-era fine art illustration with watercolor and ink",
    },
    "anime": {
        "name": "Anime",
        "prefix": "Anime style illustration,",
        "suffix": (
            "anime art style, cel shaded, vibrant saturated colors, "
            "Studio Ghibli inspired, Japanese animation aesthetic, "
            "clean linework, expressive character design, high quality anime"
        ),
        "description": "Japanese anime/manga style with cel shading and vibrant colors",
    },
    "oil_painting": {
        "name": "Oil Painting",
        "prefix": "Oil painting artwork,",
        "suffix": (
            "oil painting style, classical painting technique, visible brushwork, "
            "rich textures and glazing, chiaroscuro lighting, "
            "old master technique, museum quality fine art"
        ),
        "description": "Traditional oil painting in the style of Victorian masters",
    },
    "gothic_illustration": {
        "name": "Gothic Illustration",
        "prefix": "Gothic dark fantasy illustration,",
        "suffix": (
            "gothic illustration style, dark atmospheric artwork, "
            "Edward Gorey and Aubrey Beardsley inspired, "
            "dramatic shadows, art nouveau linework, Victorian gothic aesthetic, "
            "highly detailed dark illustration"
        ),
        "description": "Gothic Victorian illustration with art nouveau influence",
    },
    "cartoon": {
        "name": "Cartoon",
        "prefix": "Cartoon illustration,",
        "suffix": (
            "cartoon art style, hand-drawn animation quality, "
            "colorful and expressive, bold outlines, "
            "playful character design, professional cartoon art"
        ),
        "description": "Western cartoon style with bold lines and bright colors",
    },
}


def get_default_style() -> VisualStyle:
    """Return the default visual style for audiobook content."""
    return VISUAL_STYLES["classical_illustration"]


def get_style_by_name(style_name: str) -> VisualStyle:
    """
    Get a style by key name.

    Args:
        style_name: Key like "anime", "classical_illustration", etc.

    Returns:
        VisualStyle dict

    Raises:
        KeyError: If style_name is not in VISUAL_STYLES
    """
    return VISUAL_STYLES[style_name]


def list_styles() -> list[str]:
    """Return available style names."""
    return list(VISUAL_STYLES.keys())
