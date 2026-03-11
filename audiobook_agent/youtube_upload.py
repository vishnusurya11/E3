#!/usr/bin/env python3
"""
YouTube upload for the E3 foundry audiobook pipeline.

Reads from E3 foundry structure (foundry/{book_id}/):
  codex.json, videos/{book_id}.mp4, analysis/chapter_*_analysis.json

Usage:
    python -m audiobook_agent.youtube_upload foundry/pg174
    python -m audiobook_agent.youtube_upload foundry/pg174 --privacy unlisted
    python -m audiobook_agent.youtube_upload foundry/pg174 --model google/gemini-2.0-flash-lite-001
"""

import os
import sys
import json
import re
import time
import random
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
YOUTUBE_CATEGORY     = os.environ.get("YOUTUBE_CATEGORY_ID", "27")   # Education
YOUTUBE_TOKEN_FILE   = Path("youtube_credentials.json")               # existing E3 token

COMFYUI_OUTPUT_DIR = Path(os.environ.get(
    "COMFYUI_OUTPUT_DIR",
    r"D:\Projects\KingdomOfViSuReNa\alpha\ComfyUI_windows_portable\ComfyUI\output",
))


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class UploadResult:
    success: bool
    video_id: str = ""
    video_url: str = ""
    title: str = ""
    playlist_id: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _get_youtube_service():
    """Return authenticated YouTube API service, refreshing/triggering OAuth as needed."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            "YouTube API libraries not installed. Run: "
            "pip install google-api-python-client google-auth-oauthlib"
        )

    creds = None
    if YOUTUBE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(YOUTUBE_TOKEN_FILE), YOUTUBE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("  Refreshing YouTube token...")
            creds.refresh(Request())
        else:
            print("  Starting YouTube OAuth flow (browser will open)...")
            client_id     = os.environ.get("YOUTUBE_CLIENT_ID")
            client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
            if not client_id or not client_secret:
                raise RuntimeError(
                    "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env"
                )
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uris": ["http://localhost"],
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                    }
                },
                YOUTUBE_SCOPES,
            )
            creds = flow.run_local_server(port=8080)

        # Persist refreshed/new token
        YOUTUBE_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        print(f"  Token saved to {YOUTUBE_TOKEN_FILE}")

    return build("youtube", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Environment-specific playlist
# ---------------------------------------------------------------------------

def _get_playlist_id() -> Optional[str]:
    env = os.environ.get("E3_ENV", "alpha").lower()
    if env == "alpha":
        return os.environ.get("YOUTUBE_ALPHA_PLAYLIST_ID")
    return os.environ.get("YOUTUBE_PROD_PLAYLIST_ID")


# ---------------------------------------------------------------------------
# Metadata generation
# ---------------------------------------------------------------------------

def _template_metadata(book_title: str, author: str):
    title = f"{book_title} by {author} - Full Audiobook"[:100]
    description = (
        f"Complete Audiobook: {book_title} by {author}\n\n"
        f"A classic work of literature presented as a full audiobook with original narration "
        f"and hand-crafted artwork.\n\n"
        f"Perfect for commuting, exercising, or relaxing while enjoying great storytelling.\n\n"
        f"#audiobook #{book_title.replace(' ', '').lower()} "
        f"#{author.replace(' ', '').lower()} #classiclit #literature #fullaudiobook"
    )
    tags = [
        "audiobook", "classic literature", "full audiobook", "unabridged",
        book_title.lower(), author.lower(), "literature", "audiobooks",
        "storytelling", "classic books",
    ]
    return title, description, tags


def _llm_metadata(book_dir: Path, book_title: str, author: str, api_key: str, model: str):
    """Generate YouTube metadata via OpenRouter LLM."""
    import httpx

    # Gather a few sample scene paragraphs for context
    analysis_dir = book_dir / "analysis"
    samples = []
    for f in sorted(analysis_dir.glob("chapter_*_analysis.json"))[:3]:
        data = json.loads(f.read_text(encoding="utf-8"))
        for scene in data.get("scenes", [])[:2]:
            paras = scene.get("paragraphs", [])
            if paras:
                samples.append(paras[0][:300])
            if len(samples) >= 4:
                break
        if len(samples) >= 4:
            break

    sample_text = " ... ".join(samples[:3])

    prompt = (
        f"Generate YouTube metadata for an audiobook.\n\n"
        f"Title: {book_title}\n"
        f"Author: {author}\n"
        f"Sample content: {sample_text}\n\n"
        f"Return ONLY valid JSON with these fields:\n"
        f'{{"title": "...", "description": "...", "tags": ["..."]}}\n\n'
        f"Rules:\n"
        f"- title: include the exact book title and author name, max 100 chars, no emojis\n"
        f"- description: 500-800 chars, include hashtags, do NOT mention AI or AI-generated\n"
        f"- tags: 10-15 keywords (genre, characters, themes, audiobook)"
    )

    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

    # Extract JSON block from response
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        raise ValueError("No JSON found in LLM response")
    data = json.loads(m.group())
    return data["title"], data["description"], data["tags"]


def _generate_metadata(book_dir: Path, book_title: str, author: str, model: Optional[str]):
    """Try LLM metadata; fall back to template."""
    api_key = os.environ.get("OPR_ROUTER_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if api_key and model:
        try:
            print(f"  Generating YouTube metadata via LLM ({model})...")
            return _llm_metadata(book_dir, book_title, author, api_key, model)
        except Exception as e:
            print(f"  LLM metadata failed, using template: {e}")
    return _template_metadata(book_title, author)


# ---------------------------------------------------------------------------
# Resumable upload with exponential backoff
# ---------------------------------------------------------------------------

def _resumable_upload(insert_request, max_retries: int = 10):
    """Execute a resumable YouTube upload with exponential backoff."""
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        raise RuntimeError("google-api-python-client not installed")

    retry = 0
    while retry < max_retries:
        try:
            return insert_request.execute()
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504):
                wait = min((2 ** retry) + random.random(), 64)
                print(f"  HTTP {e.resp.status} — retrying in {wait:.1f}s (attempt {retry+1}/{max_retries})...")
                time.sleep(wait)
                retry += 1
            else:
                raise
    raise RuntimeError(f"Upload failed after {max_retries} retries")


# ---------------------------------------------------------------------------
# Thumbnail + playlist helpers
# ---------------------------------------------------------------------------

def _set_thumbnail(youtube, video_id: str, book_id: str):
    """Set first available poster image as video thumbnail."""
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return

    poster_dir = COMFYUI_OUTPUT_DIR / "api" / book_id / "posters"
    posters = sorted(poster_dir.glob("*.png")) if poster_dir.exists() else []
    if not posters:
        print("  No poster image found — skipping thumbnail")
        return

    poster = posters[0]
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(poster), mimetype="image/png"),
        ).execute()
        print(f"  Thumbnail set: {poster.name}")
    except Exception as e:
        print(f"  Thumbnail upload failed (non-fatal): {e}")


def _add_to_playlist(youtube, video_id: str, playlist_id: str):
    """Add uploaded video to a YouTube playlist."""
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        ).execute()
        print(f"  Added to playlist: {playlist_id}")
    except Exception as e:
        print(f"  Playlist add failed (non-fatal): {e}")


def _create_playlist(youtube, title: str, description: str = "") -> Optional[str]:
    """Create a new public YouTube playlist. Returns playlist_id or None on failure."""
    try:
        response = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title[:150],
                    "description": description or f"Complete audiobook: {title}",
                },
                "status": {
                    "privacyStatus": "public",
                },
            },
        ).execute()
        playlist_id = response["id"]
        print(f"  Playlist created: {title} ({playlist_id})")
        return playlist_id
    except Exception as e:
        print(f"  Playlist creation failed (non-fatal): {e}")
        return None


# ---------------------------------------------------------------------------
# Main upload function
# ---------------------------------------------------------------------------

def upload_book_video(
    book_dir,
    privacy: str = None,
    model: str = None,
) -> UploadResult:
    """
    Upload the final video for a foundry book directory to YouTube.

    Args:
        book_dir: Path to foundry/{book_id}/ directory
        privacy:  "public" | "private" | "unlisted" (default from env or "public")
        model:    OpenRouter model for LLM metadata (None = template only)

    Returns:
        UploadResult with video_id, video_url, etc.
    """
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return UploadResult(
            success=False,
            error="google-api-python-client not installed. Run: pip install google-api-python-client google-auth-oauthlib",
        )

    book_dir = Path(book_dir)
    book_id  = book_dir.name

    # --- Find video ---
    video_path = book_dir / "videos" / f"{book_id}.mp4"
    if not video_path.exists():
        return UploadResult(
            success=False,
            error=f"Video not found: {video_path}. Run Phase 4 first.",
        )

    # --- Load codex ---
    codex_path = book_dir / "codex.json"
    if not codex_path.exists():
        return UploadResult(success=False, error=f"codex.json not found in {book_dir}")
    codex = json.loads(codex_path.read_text(encoding="utf-8"))
    book_title = codex.get("title", book_id)
    author     = codex.get("author", "Unknown")

    print(f"\nYouTube Upload: {book_title} by {author}")
    print(f"  Video : {video_path}")
    print(f"  Env   : {os.environ.get('E3_ENV', 'alpha')}")

    # --- Generate metadata ---
    title, description, tags = _generate_metadata(book_dir, book_title, author, model)
    print(f"  Title : {title}")

    # --- Authenticate ---
    try:
        youtube = _get_youtube_service()
    except Exception as e:
        return UploadResult(success=False, error=f"Auth failed: {e}")

    # --- Privacy ---
    privacy_status = privacy or os.environ.get("YOUTUBE_DEFAULT_PRIVACY", "public")

    # --- Upload ---
    print(f"  Uploading ({privacy_status})...")
    try:
        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10 MB chunks
        )
        insert_request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title[:100],
                    "description": description,
                    "tags": tags[:20],
                    "categoryId": YOUTUBE_CATEGORY,
                    "defaultLanguage": "en",
                    "defaultAudioLanguage": "en",
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            },
            media_body=media,
        )
        response = _resumable_upload(insert_request)
    except Exception as e:
        return UploadResult(success=False, error=f"Upload failed: {e}")

    video_id  = response["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"  Uploaded: {video_url}")

    # --- Thumbnail ---
    _set_thumbnail(youtube, video_id, book_id)

    # --- Playlist ---
    playlist_id = _get_playlist_id()
    if playlist_id:
        _add_to_playlist(youtube, video_id, playlist_id)

    # --- Save to codex ---
    codex.setdefault("metadata", {})["youtube"] = {
        "video_id":      video_id,
        "video_url":     video_url,
        "title":         title,
        "privacy_status": privacy_status,
        "playlist_id":   playlist_id or "",
    }
    codex_path.write_text(json.dumps(codex, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved to codex.json")

    return UploadResult(
        success=True,
        video_id=video_id,
        video_url=video_url,
        title=title,
        playlist_id=playlist_id or "",
    )


# ---------------------------------------------------------------------------
# Per-chapter upload with schedule integration
# ---------------------------------------------------------------------------

def _chapter_metadata(book_title: str, author: str, chapter_title: str, part: int, total: int):
    """Generate programmatic YouTube metadata for a single chapter."""
    title = f"{book_title} - Part {part} of {total}"[:100]
    description = (
        f"{book_title} by {author}\n\n"
        f"Chapter {part}: {chapter_title}\n"
        f"Part {part} of {total}\n\n"
        f"Listen to the complete audiobook — subscribe and turn on notifications "
        f"so you never miss a chapter.\n\n"
        f"#audiobook #{book_title.replace(' ', '').lower()[:30]} "
        f"#{author.split(',')[0].replace(' ', '').lower()[:20]} "
        f"#classiclit #literature #booktube"
    )
    tags = [
        "audiobook", "classic literature", book_title.lower()[:40],
        author.lower()[:30], "literature", "audiobooks", "storytelling",
        f"part {part}", "chapter audiobook", "classic books",
    ]
    return title, description, tags


@dataclass
class ChapterUploadResult:
    success: bool
    total_chapters: int = 0
    uploaded: int = 0
    playlist_id: str = ""
    chapters: list = field(default_factory=list)
    error: str = ""


def upload_book_chapters(
    book_dir,
    privacy: str = None,
    model: str = None,
) -> ChapterUploadResult:
    """
    Upload per-chapter videos with schedule database integration.

    Discovers chapter videos at videos/chapters/chXX.mp4, claims schedule
    slots from visurena_studio.db, and uploads each chapter with scheduled
    publishing and shared thumbnail.
    """
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return ChapterUploadResult(
            success=False,
            error="google-api-python-client not installed. Run: pip install google-api-python-client google-auth-oauthlib",
        )

    book_dir = Path(book_dir)
    book_id = book_dir.name

    # --- Discover chapter videos ---
    chapters_dir = book_dir / "videos" / "chapters"
    if not chapters_dir.exists():
        return ChapterUploadResult(
            success=False,
            error=f"No chapters directory: {chapters_dir}. Run Phase 4 step 5 first.",
        )

    # Match chXX.mp4 (skip ch00_title.mp4)
    chapter_vids = sorted([
        f for f in chapters_dir.glob("ch*.mp4")
        if not f.name.endswith("_title.mp4") and f.name != "ch00.mp4"
    ])
    if not chapter_vids:
        return ChapterUploadResult(
            success=False,
            error=f"No chapter videos found in {chapters_dir}",
        )

    total = len(chapter_vids)
    print(f"\nYouTube Per-Chapter Upload: {total} chapters")

    # --- Load codex ---
    codex_path = book_dir / "codex.json"
    if not codex_path.exists():
        return ChapterUploadResult(success=False, error=f"codex.json not found in {book_dir}")
    codex = json.loads(codex_path.read_text(encoding="utf-8"))
    book_title = codex.get("title", book_id)
    author = codex.get("author", "Unknown")
    chapters_meta = codex.get("chapters", [])

    print(f"  Book   : {book_title} by {author}")
    print(f"  Videos : {total} chapters")

    # --- Claim schedule slots ---
    try:
        from audiobook_agent.youtube_schedule import claim_slots, release_slots
        slots = claim_slots(book_id, book_title, total)
        print(f"  Slots  : {total} claimed ({slots[0]['time_slot']} -> {slots[-1]['time_slot']})")
    except Exception as e:
        print(f"  Schedule: FAILED ({e}) — uploading without schedule")
        slots = [{"part": i + 1, "time_slot": "", "publish_at": ""} for i in range(total)]

    # --- Authenticate ---
    try:
        youtube = _get_youtube_service()
    except Exception as e:
        return ChapterUploadResult(success=False, error=f"Auth failed: {e}")

    # --- Privacy ---
    privacy_status = privacy or os.environ.get("YOUTUBE_DEFAULT_PRIVACY", "public")

    # --- Shared thumbnail ---
    poster_dir = COMFYUI_OUTPUT_DIR / "api" / book_id / "posters"
    posters = sorted(poster_dir.glob("*.png")) if poster_dir.exists() else []
    shared_thumb = posters[0] if posters else None
    print(f"  Thumb  : {shared_thumb.name if shared_thumb else 'none'}")

    # --- Create playlist for this book ---
    playlist_id = _create_playlist(youtube, book_title)

    # --- Upload each chapter ---
    uploaded_chapters = []
    for i, vid_path in enumerate(chapter_vids):
        slot = slots[i]
        part = slot["part"]
        publish_at = slot.get("publish_at", "")

        # Get chapter title from codex if available
        ch_title = ""
        if i < len(chapters_meta):
            ch_title = chapters_meta[i].get("chapter_title", "")
        if not ch_title:
            ch_title = vid_path.stem  # fallback to filename

        title, description, tags = _chapter_metadata(
            book_title, author, ch_title, part, total,
        )

        print(f"\n  [{part}/{total}] {title}")
        print(f"    Video: {vid_path.name} ({vid_path.stat().st_size / 1024 / 1024:.1f} MB)")
        if publish_at:
            print(f"    Schedule: {publish_at}")

        # Build upload body
        status_body = {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        }
        if publish_at:
            status_body["publishAt"] = publish_at

        try:
            media = MediaFileUpload(
                str(vid_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=10 * 1024 * 1024,
            )
            insert_request = youtube.videos().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": title,
                        "description": description,
                        "tags": tags[:20],
                        "categoryId": YOUTUBE_CATEGORY,
                        "defaultLanguage": "en",
                        "defaultAudioLanguage": "en",
                    },
                    "status": status_body,
                },
                media_body=media,
            )
            response = _resumable_upload(insert_request)
        except Exception as e:
            print(f"    UPLOAD FAILED: {e}")
            uploaded_chapters.append({
                "chapter_number": part,
                "part": f"Part {part} of {total}",
                "error": str(e),
            })
            continue

        video_id = response["id"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"    Uploaded: {video_url}")

        # Set thumbnail
        if shared_thumb:
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(shared_thumb), mimetype="image/png"),
                ).execute()
                print(f"    Thumbnail set")
            except Exception as e:
                print(f"    Thumbnail failed (non-fatal): {e}")

        # Add to playlist
        if playlist_id:
            _add_to_playlist(youtube, video_id, playlist_id)

        uploaded_chapters.append({
            "chapter_number": part,
            "part": f"Part {part} of {total}",
            "video_id": video_id,
            "video_url": video_url,
            "title": title,
            "publish_at": publish_at,
            "time_slot": slot.get("time_slot", ""),
        })

    # --- Save to codex ---
    codex.setdefault("metadata", {})["youtube"] = {
        "upload_mode": "per_chapter",
        "total_chapters": total,
        "shared_thumbnail": shared_thumb.name if shared_thumb else "",
        "playlist_id": playlist_id or "",
        "chapters": uploaded_chapters,
    }
    codex_path.write_text(json.dumps(codex, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Saved to codex.json")

    uploaded_count = sum(1 for c in uploaded_chapters if "video_id" in c)
    print(f"\n  Upload complete: {uploaded_count}/{total} chapters uploaded")

    return ChapterUploadResult(
        success=uploaded_count > 0,
        total_chapters=total,
        uploaded=uploaded_count,
        playlist_id=playlist_id or "",
        chapters=uploaded_chapters,
        error="" if uploaded_count == total else f"{total - uploaded_count} chapters failed",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Upload E3 foundry audiobook video to YouTube",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload with default privacy (public):
  python -m audiobook_agent.youtube_upload foundry/pg174

  # Upload as unlisted for review:
  python -m audiobook_agent.youtube_upload foundry/pg174 --privacy unlisted

  # Upload with LLM-generated metadata:
  python -m audiobook_agent.youtube_upload foundry/pg174 --model google/gemini-2.0-flash-lite-001
        """,
    )
    parser.add_argument(
        "book_dir",
        type=Path,
        help="Path to foundry book directory (e.g. foundry/pg174)",
    )
    parser.add_argument(
        "--privacy",
        choices=["public", "private", "unlisted"],
        default=None,
        help="YouTube privacy status (default: from YOUTUBE_DEFAULT_PRIVACY env or 'public')",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenRouter model for LLM metadata generation (omit = template)",
    )
    parser.add_argument(
        "--mode",
        choices=["single", "chapters"],
        default="chapters",
        help="Upload mode: 'chapters' (per-chapter, default) or 'single' (one final video)",
    )

    args = parser.parse_args()

    if not args.book_dir.exists():
        print(f"ERROR: Book directory not found: {args.book_dir}")
        sys.exit(1)
    if not (args.book_dir / "codex.json").exists():
        print(f"ERROR: codex.json not found in {args.book_dir}")
        sys.exit(1)

    if args.mode == "chapters":
        result = upload_book_chapters(args.book_dir, privacy=args.privacy, model=args.model)
        if result.success:
            print(f"\nUpload complete: {result.uploaded}/{result.total_chapters} chapters")
        else:
            print(f"\nUpload FAILED: {result.error}")
            sys.exit(1)
    else:
        result = upload_book_video(args.book_dir, privacy=args.privacy, model=args.model)
        if result.success:
            print(f"\nUpload complete: {result.video_url}")
        else:
            print(f"\nUpload FAILED: {result.error}")
            sys.exit(1)


if __name__ == "__main__":
    main()
