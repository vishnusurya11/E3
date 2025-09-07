"""
Audiobook Agent Package

Modular audiobook processing pipeline with individual step functions
and orchestrated CLI workflow.

Each module can run independently or be imported by the CLI orchestrator:
- parse_novel.py / parse_novel_tts.py - Text parsing and chunking
- create_tts_audio_jobs.py - TTS job creation
- create_audio_jobs.py - Audio processing jobs
- generate_subtitles.py - Subtitle generation
- generate_videos.py - Video creation
- cli.py - Main orchestrator (formerly generate_audiobook.py)

Usage:
    # Individual step
    python audiobook_agent/parse_novel_tts.py book_id
    
    # Full workflow
    python audiobook_agent/cli.py book_id
"""

__version__ = "1.0.0"
__author__ = "E3 Developer"