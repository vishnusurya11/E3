#!/usr/bin/env python3
"""
LangChain Multi-Agent Book Parser for Project Gutenberg HTML

3-agent sequential pipeline:
  Agent 1 (Gemini flash-lite): HTML Structure Analyst — inspects HTML, identifies TOC/chapter patterns
  Agent 2 (Gemini flash-lite): Chapter Extractor — extracts chapters using BeautifulSoup tools
  Agent 3 (GPT-4.1-mini):     Quality Reviewer — cross-validates; triggers Python fallback if needed

Key design: file_path is NEVER passed by the LLM. Tools are closures with file_path baked in,
so the LLM only reasons about anchor IDs, patterns, and text — never about file system paths.

Usage:
    python -m audiobook_agent.parse_novel_langchain <html_file> [--output-dir <dir>] [--verbose]
"""

import json
import re
import os
import argparse
from pathlib import Path
from bs4 import BeautifulSoup

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_KEY = os.getenv("OPR_ROUTER_API_KEY", "")

MODEL_ANALYST = "openai/gpt-4.1-mini"
MODEL_EXTRACTOR = "openai/gpt-4.1-mini"
MODEL_REVIEWER = "openai/gpt-4.1-mini"

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class BookStructure(BaseModel):
    title: str = Field(description="Book title from metadata or h1 tag")
    author: str = Field(description="Author name from metadata or heading")
    has_toc: bool = Field(description="Whether the book has a table of contents")
    toc_type: str = Field(description="TOC format: 'table', 'paragraph', 'list', 'none'")
    toc_anchor_ids: list[str] = Field(
        default_factory=list,
        description="Ordered list of anchor IDs found in TOC (e.g. chap01, CHAPTER_I)"
    )
    chapter_wrapper: str = Field(
        description="How chapters are wrapped: 'div.chapter', 'h2', 'anchor_id', 'none'"
    )
    anchor_pattern: str = Field(
        description="Regex pattern matching chapter anchors (e.g. 'chap\\\\d+', 'CHAPTER_[IVX]+')"
    )
    estimated_chapter_count: int = Field(description="Expected number of chapters")
    notes: str = Field(default="", description="Any structural observations")


class ChapterData(BaseModel):
    chapter_number: int = Field(description="1-based chapter index")
    anchor_id: str = Field(default="", description="Anchor ID used to locate this chapter")
    title: str = Field(description="Chapter title as it appears in the text")
    paragraphs: list[str] = Field(description="List of paragraph texts, cleaned")
    word_count: int = Field(description="Total word count for this chapter")


class ParsedBook(BaseModel):
    title: str
    author: str
    chapters: list[ChapterData]
    total_chapters: int
    extraction_notes: str = Field(default="", description="Notes from extraction agent")


class ReviewDecision(BaseModel):
    approved: bool = Field(description="True if extraction is acceptable")
    issues_found: list[str] = Field(default_factory=list, description="List of issues found")
    final_chapter_count: int = Field(description="Final number of valid chapters")
    review_notes: str = Field(default="", description="Reviewer explanation")


# ---------------------------------------------------------------------------
# BeautifulSoup implementation functions (take file_path explicitly)
# These are NEVER called by the LLM directly — only through closure tools.
# ---------------------------------------------------------------------------

def _load_soup(file_path: str) -> BeautifulSoup:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return BeautifulSoup(f.read(), "html.parser")


def _is_boilerplate(tag) -> bool:
    for parent in tag.parents:
        if hasattr(parent, "get") and parent.get("id") in ("pg-header", "pg-footer"):
            return True
        cls = parent.get("class", []) if hasattr(parent, "get") else []
        if "pg-boilerplate" in cls or "pgheader" in cls or "pgfooter" in cls:
            return True
    return False


def _clean_paragraph(text: str) -> str:
    text = re.sub(r"\[Pg\s*\d+\]", "", text)                # [Pg 5] format
    text = re.sub(r"\{[a-z0-9]+\}", "", text, flags=re.I)   # {3}, {ix}, {xii} curly-brace page nums
    text = re.sub(r"\s+", " ", text).strip()
    return text


_PAGE_MARKER_RE = re.compile(r'^[\[{][a-z0-9\s]+[\]}]$', re.I)


def _inspect_html_structure_impl(file_path: str) -> str:
    try:
        soup = _load_soup(file_path)
        title_meta = soup.find("meta", attrs={"name": "dc.title"})
        author_meta = soup.find("meta", attrs={"name": "dc.creator"})
        title_tag = soup.find("title")
        title = (title_meta["content"] if title_meta else
                 (title_tag.get_text(strip=True) if title_tag else "UNKNOWN"))
        author = author_meta["content"] if author_meta else "UNKNOWN"

        heading_counts = {h: len(soup.find_all(h)) for h in ["h1","h2","h3","h4","h5","h6"]}
        chapter_divs = soup.find_all("div", class_="chapter")

        # Collect anchor IDs from <a> tags AND from heading elements (h1-h4 with id=)
        seen_ids: set[str] = set()
        anchors = []
        for tag in soup.find_all(["a", "h1", "h2", "h3", "h4"]):
            aid = tag.get("id") or tag.get("name")
            if aid and aid not in seen_ids and not _is_boilerplate(tag):
                seen_ids.add(aid)
                anchors.append({"id": aid, "tag": tag.name})
        anchors = anchors[:60]

        h2_texts = [h.get_text(separator=" ", strip=True)[:80] for h in soup.find_all("h2")][:15]

        return json.dumps({
            "title": title,
            "author": author,
            "heading_counts": heading_counts,
            "has_div_chapter": len(chapter_divs) > 0,
            "div_chapter_count": len(chapter_divs),
            "anchor_ids_sample": anchors,
            "h2_texts_sample": h2_texts,
        }, indent=2)
    except Exception as e:
        return f"ERROR: {e}"


def _extract_toc_section_impl(file_path: str) -> str:
    try:
        soup = _load_soup(file_path)

        toc_heading = None
        for h in soup.find_all(["h2", "h3", "h4"]):
            if re.search(r"\bcontents?\b", h.get_text(), re.I):
                toc_heading = h
                break

        if toc_heading:
            lines = [f"[TOC HEADING]: {toc_heading.get_text(strip=True)}"]
            sib = toc_heading.find_next_sibling()
            for _ in range(30):
                if sib is None:
                    break
                if sib.name in ["h1", "h2", "h3"] and sib != toc_heading:
                    break
                for lnk in sib.find_all("a", href=True):
                    lines.append(f"  href={lnk['href']}  text={lnk.get_text(strip=True)[:60]}")
                sib = sib.find_next_sibling()
            return "\n".join(lines)

        toc_p = soup.find(class_="toc")
        if toc_p:
            lines = ["[TOC class=toc found]"]
            for lnk in toc_p.find_all("a", href=True):
                lines.append(f"  href={lnk['href']}  text={lnk.get_text(strip=True)[:60]}")
            return "\n".join(lines)

        return "NO TOC FOUND"
    except Exception as e:
        return f"ERROR: {e}"


def _find_all_anchor_ids_impl(file_path: str, pattern: str) -> str:
    try:
        soup = _load_soup(file_path)
        regex = re.compile(pattern, re.IGNORECASE)
        seen: set[str] = set()
        matches = []
        # Check <a> tags first (most common in older Gutenberg), then heading elements
        for tag in soup.find_all(["a", "h1", "h2", "h3", "h4"]):
            aid = tag.get("id") or tag.get("name")
            if aid and aid not in seen and regex.fullmatch(aid) and not _is_boilerplate(tag):
                seen.add(aid)
                matches.append(aid)
        return json.dumps(matches)
    except Exception as e:
        return f"ERROR: {e}"


def _extract_chapter_text_impl(file_path: str, start_anchor: str, end_anchor: str) -> str:
    try:
        soup = _load_soup(file_path)

        def find_anchor(aid):
            # Find <a id=...> first, then fall back to ANY element with that id/name
            return (soup.find("a", id=aid) or soup.find("a", attrs={"name": aid})
                    or soup.find(id=aid) or soup.find(attrs={"name": aid}))

        start_tag = find_anchor(start_anchor)
        if not start_tag:
            return json.dumps({"error": f"start_anchor '{start_anchor}' not found",
                               "paragraphs": [], "word_count": 0, "paragraph_count": 0})

        # Find title: if start_tag IS a heading, use it; else find next heading.
        # Apply _clean_paragraph to strip page-number markers like {ix} or [Pg 5].
        # Skip headings whose cleaned text is purely a page-number marker.
        title = ""
        if start_tag.name in ["h1","h2","h3","h4","h5","h6"]:
            t = _clean_paragraph(start_tag.get_text(separator=" ", strip=True))
            if t and not _PAGE_MARKER_RE.fullmatch(t):
                title = t
        if not title:
            parent = start_tag.parent
            if parent and parent.name in ["h1","h2","h3","h4","h5","h6"]:
                t = _clean_paragraph(parent.get_text(separator=" ", strip=True))
                if t and not _PAGE_MARKER_RE.fullmatch(t):
                    title = t
        if not title:
            # Scan for title heading, stopping when we hit the end anchor (chapter boundary).
            # Check headings before their contents — if a heading *contains* the end anchor,
            # it belongs to the next chapter (stop before using it as the title).
            for nxt in start_tag.find_all_next(["a", "h1", "h2", "h3", "h4"]):
                if nxt.name == "a":
                    aid = nxt.get("id") or nxt.get("name")
                    if aid and end_anchor and aid == end_anchor:
                        break  # crossed into next chapter
                    continue
                # nxt is a heading — check if it belongs to the next chapter
                if end_anchor and end_anchor != "EOF":
                    if (nxt.get("id") == end_anchor
                            or nxt.find("a", id=end_anchor)
                            or nxt.find("a", attrs={"name": end_anchor})):
                        break
                t = _clean_paragraph(nxt.get_text(separator=" ", strip=True))
                if t and not _PAGE_MARKER_RE.fullmatch(t):
                    title = t
                    break
        # Last resort: derive title from anchor ID itself (e.g. PREFACE → Preface)
        if not title:
            title = start_anchor.replace("_", " ").title()

        end_tag = find_anchor(end_anchor) if end_anchor and end_anchor != "EOF" else None

        # Visit anchors (<a>), headings (h1-h4, which may carry IDs), and paragraphs
        paragraphs = []
        in_chapter = False
        for elem in soup.find_all(["a", "h1", "h2", "h3", "h4", "p"]):
            if elem.name != "p":
                eid = elem.get("id") or elem.get("name")
                if not in_chapter and eid == start_anchor:
                    in_chapter = True
                    continue
                if in_chapter and end_anchor and eid == end_anchor:
                    break
            elif in_chapter and not _is_boilerplate(elem):
                if elem.parent and elem.parent.name == "p":
                    continue
                text = _clean_paragraph(elem.get_text(separator=" ", strip=True))
                if text and len(text) > 10:
                    paragraphs.append(text)

        word_count = sum(len(p.split()) for p in paragraphs)
        return json.dumps({
            "title": title,
            "paragraphs": paragraphs[:500],
            "word_count": word_count,
            "paragraph_count": len(paragraphs),
        })
    except Exception as e:
        return f"ERROR: {e}"


def _get_html_snippet_impl(file_path: str, search_term: str, context_lines: int = 25) -> str:
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if search_term.lower() in line.lower():
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines)
                return f"[Lines {start+1}-{end+1}]\n" + "".join(lines[start:end])
        return f"TERM '{search_term}' NOT FOUND"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------------------------------------------------------------------
# Pydantic schemas for tool inputs (LangChain structured output for tools)
# ---------------------------------------------------------------------------

class _FindAnchorInput(BaseModel):
    pattern: str = Field(
        description=(
            "Python regex pattern to match anchor IDs in document order. "
            "Examples: 'chap\\\\d+' matches chap01..chap20, "
            "'CHAPTER_[IVX]+' matches CHAPTER_I..CHAPTER_XX, "
            "'pref\\\\d+|chap\\\\d+' matches both preface and chapters."
        )
    )


class _ExtractChapterInput(BaseModel):
    start_anchor: str = Field(
        description="The anchor ID (id or name attribute) where this chapter begins, e.g. 'chap01'"
    )
    end_anchor: str = Field(
        description="The anchor ID where this chapter ends. Use the string 'EOF' for the last chapter."
    )


class _GetSnippetInput(BaseModel):
    search_term: str = Field(
        description="A word or tag to search for in the raw HTML, e.g. 'chap01' or '<div class'"
    )


# ---------------------------------------------------------------------------
# Tool factories — file_path is CLOSED OVER, never passed by LLM
# ---------------------------------------------------------------------------

def _make_analyst_tools(file_path: str) -> list:
    """Create analysis tools with file_path baked in as a closure.
    The LLM never receives or passes file_path — it is invisible to the model."""

    @tool
    def inspect_html_structure() -> str:
        """Inspect this book's HTML: metadata (title, author), heading tag counts (h1-h6), first 60 anchor IDs, whether div.chapter exists, and h2 text samples. Call this first."""
        return _inspect_html_structure_impl(file_path)

    @tool
    def extract_toc_section() -> str:
        """Find and return the Table of Contents section with all anchor href values. Call this to discover chapter anchor IDs."""
        return _extract_toc_section_impl(file_path)

    @tool(args_schema=_FindAnchorInput)
    def find_all_anchor_ids(pattern: str) -> str:
        """Find all anchor IDs matching a Python regex pattern, returned in document order as a JSON list. Use this to verify your pattern finds the right chapters."""
        return _find_all_anchor_ids_impl(file_path, pattern)

    @tool(args_schema=_GetSnippetInput)
    def get_html_snippet(search_term: str) -> str:
        """Return 25 lines of raw HTML around the first occurrence of search_term. Use this to inspect how a specific anchor or heading is structured."""
        return _get_html_snippet_impl(file_path, search_term)

    return [inspect_html_structure, extract_toc_section, find_all_anchor_ids, get_html_snippet]


def _make_extractor_tools(file_path: str) -> list:
    """Create extraction tools with file_path baked in as a closure.
    The LLM only needs to provide anchor IDs — never the file path."""

    @tool(args_schema=_FindAnchorInput)
    def find_all_anchor_ids(pattern: str) -> str:
        """Find all anchor IDs matching a Python regex pattern in document order. Returns a JSON array of strings. Call this ONCE to get the ordered chapter list."""
        return _find_all_anchor_ids_impl(file_path, pattern)

    @tool(args_schema=_ExtractChapterInput)
    def extract_chapter_text(start_anchor: str, end_anchor: str) -> str:
        """Extract all paragraph text between two anchor IDs. Returns JSON with keys: title (str), paragraphs (list[str]), word_count (int), paragraph_count (int). Use end_anchor='EOF' for the final chapter."""
        return _extract_chapter_text_impl(file_path, start_anchor, end_anchor)

    return [find_all_anchor_ids, extract_chapter_text]


# ---------------------------------------------------------------------------
# Python fallback extractor (no LLM involved)
# ---------------------------------------------------------------------------

def _extract_toc_anchor_ids_impl(file_path: str) -> list[str]:
    """Parse TOC anchor IDs directly from HTML <a href="#..."> links.
    Finds the CONTENTS heading, then extracts all internal hrefs from the
    adjacent table/list container. Excludes page-number links (#page_NNN)."""
    soup = _load_soup(file_path)

    # Find the CONTENTS heading
    toc_heading = None
    for h in soup.find_all(["h2", "h3"]):
        if _is_boilerplate(h):
            continue
        if re.search(r'\bcontents?\b', h.get_text(strip=True), re.I):
            toc_heading = h
            break

    if not toc_heading:
        return []

    # Find the TOC container: next table, ul, ol, or div sibling
    toc_container = None
    for sibling in toc_heading.find_next_siblings():
        if sibling.name in ("table", "ul", "ol", "div"):
            toc_container = sibling
            break
        if sibling.name in ("h2", "h3", "h4"):
            break  # hit next section without finding a container

    if not toc_container:
        return []  # no recognizable TOC structure

    # Extract all internal hrefs, skipping page-number links
    anchors = []
    seen: set[str] = set()
    for a in toc_container.find_all("a", href=True):
        href = a.get("href", "")
        if not href.startswith("#"):
            continue
        anchor_id = href[1:]
        if re.match(r'^page_\d+$', anchor_id):
            continue
        if anchor_id and anchor_id not in seen:
            seen.add(anchor_id)
            anchors.append(anchor_id)

    return anchors


def _python_extract_chapters(file_path: str, structure: BookStructure) -> ParsedBook:
    """Direct BeautifulSoup extraction using anchor_pattern from Agent 1.
    Called when Agent 2 returns too few chapters or reviewer rejects."""
    if not structure.anchor_pattern or structure.anchor_pattern in ("none", ""):
        return ParsedBook(
            title=structure.title, author=structure.author,
            chapters=[], total_chapters=0,
            extraction_notes="No anchor pattern available for fallback"
        )

    raw = _find_all_anchor_ids_impl(file_path, structure.anchor_pattern)
    try:
        anchors = json.loads(raw)
    except Exception:
        anchors = []

    chapters = []
    for i, anchor_id in enumerate(anchors):
        next_anchor = anchors[i + 1] if i + 1 < len(anchors) else "EOF"
        result_raw = _extract_chapter_text_impl(file_path, anchor_id, next_anchor)
        try:
            data = json.loads(result_raw)
        except Exception:
            continue
        if data.get("paragraph_count", 0) == 0:
            continue
        chapters.append(ChapterData(
            chapter_number=i + 1,
            anchor_id=anchor_id,
            title=data.get("title") or f"Chapter {i + 1}",
            paragraphs=data.get("paragraphs", []),
            word_count=data.get("word_count", 0),
        ))

    return ParsedBook(
        title=structure.title, author=structure.author,
        chapters=chapters, total_chapters=len(chapters),
        extraction_notes=f"Python fallback: {len(chapters)} chapters via pattern '{structure.anchor_pattern}'"
    )


def _python_extract_by_div_chapters(file_path: str, title: str, author: str):
    """Extract chapters from <div class="chapter"> elements (no anchor IDs needed).
    Returns a list of ChapterData, or empty list if no chapter divs found."""
    soup = _load_soup(file_path)
    # Remove boilerplate sections first
    for section in soup.find_all("section", class_="pg-boilerplate"):
        section.decompose()
    for div in soup.find_all("div", id=["pg-header", "pg-footer"]):
        div.decompose()

    # Find divs/sections with class containing "chapter"
    chapter_elements = soup.find_all(
        ["div", "section"],
        class_=lambda c: c and "chapter" in (c if isinstance(c, str) else " ".join(c)).lower()
    )
    if not chapter_elements:
        return []

    chapters = []
    for i, elem in enumerate(chapter_elements):
        heading = elem.find(["h1", "h2", "h3", "h4"])
        ch_title = heading.get_text(separator=" ", strip=True) if heading else f"Chapter {i+1}"
        paragraphs = []
        for p in elem.find_all("p"):
            if _is_boilerplate(p):
                continue
            if p.parent and p.parent.name == "p":
                continue
            text = _clean_paragraph(p.get_text(separator=" ", strip=True))
            if text and len(text) > 10:
                paragraphs.append(text)
        if not paragraphs:
            continue
        chapters.append(ChapterData(
            chapter_number=len(chapters) + 1,
            anchor_id=f"div_{i}",
            title=ch_title,
            paragraphs=paragraphs,
            word_count=sum(len(p.split()) for p in paragraphs),
        ))
    return chapters


def _python_extract_by_heading_sections(file_path: str, title: str, author: str):
    """Split book into chapters by h2/h3 headings when no anchor IDs or chapter divs exist.
    Only used when there are 2+ meaningful content headings. Returns list of ChapterData."""
    soup = _load_soup(file_path)
    for section in soup.find_all("section", class_="pg-boilerplate"):
        section.decompose()
    for div in soup.find_all("div", id=["pg-header", "pg-footer"]):
        div.decompose()

    # Collect h2/h3 headings that look like chapter/story titles (not metadata)
    headings = []
    for h in soup.find_all(["h2", "h3"]):
        if _is_boilerplate(h):
            continue
        text = h.get_text(strip=True)
        # Skip metadata-like headings and very short/long ones
        if not text or len(text) > 120:
            continue
        # Skip standalone Roman numeral section markers (I, II, III, I., etc.)
        if re.fullmatch(r'[IVXLCDM]+\.?', text.strip(), re.I):
            continue
        # Skip very short section numbers like "1.", "2.", "Part I"
        if re.fullmatch(r'(?:part\s+)?[0-9IVXLCDM]+\.?', text.strip(), re.I) and len(text) < 10:
            continue
        skip_patterns = re.compile(r'project gutenberg|full license|license|copyright|contents?|footnotes?|bibliography|index|illustrations?|appendix', re.I)
        if skip_patterns.fullmatch(text.strip()) or (skip_patterns.search(text) and len(text) < 35):
            continue
        headings.append(h)

    if len(headings) < 2:
        return []

    chapters = []
    for i, heading in enumerate(headings):
        ch_title = heading.get_text(separator=" ", strip=True)
        next_heading = headings[i + 1] if i + 1 < len(headings) else None

        # Collect paragraphs between this heading and the next
        paragraphs = []
        for elem in heading.find_all_next(["h2", "h3", "p"]):
            if next_heading and elem is next_heading:
                break
            if elem.name in ["h2", "h3"] and elem in headings:
                break
            if elem.name == "p" and not _is_boilerplate(elem):
                if elem.parent and elem.parent.name == "p":
                    continue
                text = _clean_paragraph(elem.get_text(separator=" ", strip=True))
                if text and len(text) > 10:
                    paragraphs.append(text)

        if not paragraphs:
            continue
        chapters.append(ChapterData(
            chapter_number=len(chapters) + 1,
            anchor_id=f"h_{i}",
            title=ch_title,
            paragraphs=paragraphs,
            word_count=sum(len(p.split()) for p in paragraphs),
        ))
    return chapters


def _direct_extract_single_story(file_path: str, title: str, author: str) -> dict:
    """Fallback for books with no chapter structure — try div chapters, then heading sections, then single chapter."""
    # First try div-based chapter extraction (only if chapters have meaningful content)
    div_chapters = _python_extract_by_div_chapters(file_path, title, author)
    avg_words = sum(c.word_count for c in div_chapters) / len(div_chapters) if div_chapters else 0
    if div_chapters and avg_words >= 100:
        return {
            "title": title, "author": author,
            "chapters": [
                {"chapter_number": c.chapter_number, "anchor_id": c.anchor_id,
                 "title": c.title, "paragraphs": c.paragraphs, "word_count": c.word_count}
                for c in div_chapters
            ],
            "total_chapters": len(div_chapters),
            "metadata": {"parser": "langchain-agents-div-fallback"},
        }

    # Try heading-based section extraction (e.g., anthology books with h2 story titles)
    heading_chapters = _python_extract_by_heading_sections(file_path, title, author)
    if heading_chapters and len(heading_chapters) >= 2:
        return {
            "title": title, "author": author,
            "chapters": [
                {"chapter_number": c.chapter_number, "anchor_id": c.anchor_id,
                 "title": c.title, "paragraphs": c.paragraphs, "word_count": c.word_count}
                for c in heading_chapters
            ],
            "total_chapters": len(heading_chapters),
            "metadata": {"parser": "langchain-agents-heading-fallback"},
        }

    # Final fallback: entire book as one chapter
    soup = _load_soup(file_path)
    for section in soup.find_all("section", class_="pg-boilerplate"):
        section.decompose()
    for div in soup.find_all("div", id=["pg-header", "pg-footer"]):
        div.decompose()

    paragraphs = []
    for p in soup.find_all("p"):
        if _is_boilerplate(p):
            continue
        text = _clean_paragraph(p.get_text(separator=" ", strip=True))
        if text and len(text) > 15:
            paragraphs.append(text)

    return {
        "title": title, "author": author,
        "chapters": [{"chapter_number": 1, "anchor_id": "", "title": title,
                      "paragraphs": paragraphs,
                      "word_count": sum(len(p.split()) for p in paragraphs)}],
        "total_chapters": 1,
        "metadata": {"parser": "langchain-agents-fallback"},
    }


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
        max_tokens=8000,
    )


# ---------------------------------------------------------------------------
# Agent loop helper
# ---------------------------------------------------------------------------

def _run_agent_loop(tool_llm, messages: list, tool_map: dict,
                    max_iterations: int, verbose: bool, label: str) -> list:
    """Run agentic tool-calling loop. Returns final messages list."""
    for _ in range(max_iterations):
        response = tool_llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if not tool_fn:
                result = f"Unknown tool: {tc['name']}"
            else:
                if verbose:
                    args_preview = {k: str(v)[:50] for k, v in tc["args"].items()}
                    print(f"  [Tool] {tc['name']}({args_preview})")
                result = tool_fn.invoke(tc["args"])

            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return messages


# ---------------------------------------------------------------------------
# Agent 1: Structure Analyst
# ---------------------------------------------------------------------------

ANALYST_SYSTEM = r"""You are an expert HTML book structure analyst for Project Gutenberg books.
Use the provided tools to inspect the book, then return a structured analysis.

Steps:
1. Call inspect_html_structure to get metadata, heading counts, anchor IDs
2. Call extract_toc_section to find the table of contents and its anchor hrefs
3. From the TOC hrefs, identify the anchor ID pattern (e.g. '#chap01' → pattern 'chap\d+')
4. Call find_all_anchor_ids with the pattern to verify how many chapters exist

Rules:
- If no TOC, check h2 headings with chapter keywords as chapter markers
- If single-story book with no chapters, set anchor_pattern='none', estimated_chapter_count=1
- The anchor_pattern must be a valid Python regex (use \d+ for digits, [IVXLCDM]+ for Roman numerals)
- Roman numeral patterns MUST use [IVXLCDM]+ (all digits: I V X L C D M), never [IVX]+ alone
"""


def _run_structure_analyst(file_path: str, llm: ChatOpenAI, verbose: bool) -> BookStructure:
    tools = _make_analyst_tools(file_path)
    tool_map = {t.name: t for t in tools}
    tool_llm = llm.bind_tools(tools)
    structured_llm = llm.with_structured_output(BookStructure, method="json_schema")

    with open(file_path, encoding="utf-8", errors="replace") as _f:
        html_preview = "".join(_f.readlines()[:150])

    messages = [
        SystemMessage(content=ANALYST_SYSTEM),
        HumanMessage(content=(
            f"HTML preview (first 150 lines):\n```html\n{html_preview}\n```\n\n"
            "Now use tools to complete the structural analysis and return a BookStructure."
        )),
    ]

    if verbose:
        print("\n[Agent 1: Structure Analyst] Starting analysis...")

    messages = _run_agent_loop(tool_llm, messages, tool_map, max_iterations=8, verbose=verbose, label="Analyst")

    context = "\n\n".join(
        m.content for m in messages
        if hasattr(m, "content") and isinstance(m.content, str) and m.content
    )

    result = structured_llm.invoke([
        SystemMessage(content=ANALYST_SYSTEM),
        HumanMessage(content=f"Based on your analysis, return the BookStructure.\n\nContext:\n{context[:6000]}"),
    ])

    if verbose:
        print(f"  [Agent 1 Result] title={result.title!r}, chapters~{result.estimated_chapter_count}, pattern={result.anchor_pattern!r}")

    return result


# ---------------------------------------------------------------------------
# Agent 2: Chapter Extractor
# ---------------------------------------------------------------------------

EXTRACTOR_SYSTEM = """You are a chapter extractor for Project Gutenberg HTML books.
You have access to two tools with the book's file already loaded — you do NOT need to provide a file path.

Your task: Extract ALL chapters.

Steps:
1. Call find_all_anchor_ids with the anchor_pattern from BookStructure to get the ordered list
2. For each anchor in the list, call extract_chapter_text(start_anchor, next_anchor)
   - Use 'EOF' as end_anchor for the last chapter
3. Collect all chapters

IMPORTANT:
- Do NOT call find_all_anchor_ids more than once
- Do NOT call any other validation tools — just extract_chapter_text for each chapter
- If a chapter returns 0 paragraphs, skip it (divider section)
- Always extract ALL chapters — do NOT stop early under any circumstances
- You may call multiple extract_chapter_text tools in a single response to be efficient
"""


def _run_chapter_extractor(file_path: str, structure: BookStructure, llm: ChatOpenAI, verbose: bool) -> ParsedBook:
    """Agent 2: LLM orchestrates tool calls; Python collects results directly.

    The LLM decides which anchors to extract and in what order. We capture the
    raw JSON from each extract_chapter_text call in Python — no second LLM call
    needed to reconstruct the data (avoids truncation and reconstruction errors).
    """
    tools = _make_extractor_tools(file_path)
    tool_map = {t.name: t for t in tools}
    tool_llm = llm.bind_tools(tools)

    # Capture tool results in Python as they arrive
    captured_chapters: list[tuple[str, dict]] = []  # (start_anchor, data_dict)

    messages = [
        SystemMessage(content=EXTRACTOR_SYSTEM),
        HumanMessage(content=f"""Extract all chapters using this structure analysis:

anchor_pattern: {structure.anchor_pattern}
estimated_chapter_count: {structure.estimated_chapter_count}
title: {structure.title}

1. Call find_all_anchor_ids with pattern='{structure.anchor_pattern}'
2. For each returned anchor, call extract_chapter_text sequentially (use 'EOF' for last)
3. Extract ALL {structure.estimated_chapter_count} chapters — do not stop early"""),
    ]

    if verbose:
        print("\n[Agent 2: Chapter Extractor] Starting extraction...")

    # Pre-populate from HTML TOC if available — gives exact ordered list including
    # anchors with hyphens or non-standard patterns the regex can't find.
    # Agent 2's find_all_anchor_ids call may extend this further if the regex finds more.
    known_anchor_ids: list[str] = list(structure.toc_anchor_ids) if structure.toc_anchor_ids else []

    # Agentic loop: LLM orchestrates, Python collects extract_chapter_text results
    for _ in range(80):
        response = tool_llm.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                if verbose:
                    args_preview = {k: str(v)[:50] for k, v in tc["args"].items()}
                    print(f"  [Tool] {tc['name']}({args_preview})")
                result = tool_fn.invoke(tc["args"])

                # Merge anchor list when find_all_anchor_ids is called.
                # known_anchor_ids may already be seeded from the HTML TOC;
                # add any regex-found anchors not already present (dedup, order matters).
                if tc["name"] == "find_all_anchor_ids":
                    try:
                        regex_anchors = json.loads(result)
                        existing = set(known_anchor_ids)
                        for aid in regex_anchors:
                            if aid not in existing:
                                known_anchor_ids.append(aid)
                                existing.add(aid)
                    except Exception:
                        pass

                # Intercept chapter results before they're truncated into context
                if tc["name"] == "extract_chapter_text":
                    try:
                        data = json.loads(result)
                        if data.get("paragraph_count", 0) > 0:
                            captured_chapters.append((
                                tc["args"].get("start_anchor", ""),
                                data,
                            ))
                    except Exception:
                        pass
            else:
                result = f"Unknown tool: {tc['name']}"

            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    # Deduplicate by start_anchor (keep first occurrence, maintain order)
    seen_anchors: set[str] = set()
    deduped: list[tuple[str, dict]] = []
    for anchor_id, data in captured_chapters:
        if anchor_id not in seen_anchors:
            seen_anchors.add(anchor_id)
            deduped.append((anchor_id, data))

    # Python gap-fill: if agent missed some anchors, extract them directly
    if known_anchor_ids:
        missing = [aid for aid in known_anchor_ids if aid not in seen_anchors]
        if missing and verbose:
            print(f"  [Gap-fill] Agent missed {len(missing)}/{len(known_anchor_ids)} anchors — extracting in Python")
        for i, aid in enumerate(missing):
            # Find next anchor in the full list to use as end boundary
            full_idx = known_anchor_ids.index(aid)
            end_aid = known_anchor_ids[full_idx + 1] if full_idx + 1 < len(known_anchor_ids) else "EOF"
            raw = _extract_chapter_text_impl(file_path, aid, end_aid)
            try:
                data = json.loads(raw)
                if data.get("paragraph_count", 0) > 0:
                    deduped.append((aid, data))
                    seen_anchors.add(aid)
            except Exception:
                pass
        # Re-sort deduped to match the original anchor order
        if missing:
            order = {aid: idx for idx, aid in enumerate(known_anchor_ids)}
            deduped.sort(key=lambda x: order.get(x[0], 9999))

    # Build ParsedBook directly from captured tool results — no LLM reconstruction
    chapters = [
        ChapterData(
            chapter_number=i + 1,
            anchor_id=anchor_id,
            title=data.get("title") or f"Chapter {i + 1}",
            paragraphs=data.get("paragraphs", []),
            word_count=data.get("word_count", 0),
        )
        for i, (anchor_id, data) in enumerate(deduped)
    ]

    if verbose:
        print(f"  [Agent 2 Result] {len(chapters)} chapters captured from tool calls")

    return ParsedBook(
        title=structure.title,
        author=structure.author,
        chapters=chapters,
        total_chapters=len(chapters),
        extraction_notes=f"Agent 2: {len(chapters)} chapters via direct tool capture",
    )


# ---------------------------------------------------------------------------
# Agent 3: Quality Reviewer
# ---------------------------------------------------------------------------

REVIEWER_SYSTEM = """You are a quality control reviewer for book parsing.

Rules:
1. If extracted chapters >= 70% of estimated_chapter_count → approved=True
2. If extracted chapters < 70% of estimated_chapter_count → approved=False
3. Flag: any chapters with 0 paragraphs, Gutenberg license text in content, empty titles
4. You cannot fix extraction — just approve or reject with final_chapter_count and review_notes
"""


def _run_quality_reviewer(
    structure: BookStructure,
    parsed: ParsedBook,
    llm: ChatOpenAI,
    verbose: bool,
) -> ReviewDecision:
    structured_llm = llm.with_structured_output(ReviewDecision, method="json_schema")

    chapter_summary = [
        {
            "number": ch.chapter_number,
            "anchor_id": ch.anchor_id,
            "title": ch.title,
            "paragraph_count": len(ch.paragraphs),
            "word_count": ch.word_count,
            "first_para_preview": ch.paragraphs[0][:100] if ch.paragraphs else "[EMPTY]",
        }
        for ch in parsed.chapters
    ]

    if verbose:
        print("\n[Agent 3: Quality Reviewer] Reviewing extraction...")

    threshold = max(1, int(structure.estimated_chapter_count * 0.7))

    # Hard Python check: if count clearly meets threshold and has real content, auto-approve
    non_empty = sum(1 for c in parsed.chapters if c.word_count > 50)
    if non_empty >= threshold:
        if verbose:
            print(f"  [Agent 3 Result] AUTO-APPROVED — {non_empty}/{parsed.total_chapters} chapters with content")
        return ReviewDecision(
            approved=True,
            issues_found=[],
            final_chapter_count=parsed.total_chapters,
        )

    review_input = f"""BookStructure:
{structure.model_dump_json(indent=2)}

Extracted {parsed.total_chapters} chapters (expected ~{structure.estimated_chapter_count}, threshold={threshold}):
{json.dumps(chapter_summary, indent=2)[:5000]}

RULE: If total_chapters < {threshold}, set approved=False.
Return ReviewDecision."""

    response = structured_llm.invoke([
        SystemMessage(content=REVIEWER_SYSTEM),
        HumanMessage(content=review_input),
    ])

    # Prevent LLM from incorrectly rejecting when Python count passes threshold
    if response.final_chapter_count >= threshold and not response.approved:
        response.approved = True
        response.issues_found = []

    if verbose:
        status = "APPROVED" if response.approved else "REJECTED"
        print(f"  [Agent 3 Result] {status} — {response.final_chapter_count} chapters")
        for issue in response.issues_found:
            print(f"    Issue: {issue}")

    return response


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def parse_book_with_agents(html_file_path: str, verbose: bool = True) -> dict:
    """
    Run the 3-agent pipeline on a Project Gutenberg HTML file.
    Returns a dict compatible with the existing TTS pipeline JSON schema.
    """
    file_path = str(Path(html_file_path).resolve())

    if not Path(file_path).exists():
        raise FileNotFoundError(f"HTML file not found: {file_path}")

    if verbose:
        print(f"\n{'='*60}")
        print(f"LangChain Book Parser: {Path(file_path).name}")
        print(f"{'='*60}")

    llm_fast = _make_llm(MODEL_ANALYST)
    llm_reviewer = _make_llm(MODEL_REVIEWER)

    # --- Agent 1: Structure Analysis ---
    structure = _run_structure_analyst(file_path, llm_fast, verbose)

    # Post-process: widen incomplete Roman numeral character classes ([IVX]+ → [IVXLCDM]+)
    # This fixes books like Pride & Prejudice where LLM generates CHAPTER_[IVX]+ but
    # chapters 40+ use L (XL, LI, LXI...) which isn't in [IVX].
    if structure.anchor_pattern:
        structure.anchor_pattern = re.sub(r'\[IVX\]\+', '[IVXLCDM]+', structure.anchor_pattern)
        structure.anchor_pattern = re.sub(r'\[IX\]\+', '[IVXLCDM]+', structure.anchor_pattern)

    # Override estimated_chapter_count with the actual Python-counted anchor count — but ONLY
    # when Python finds MORE anchors than the LLM estimated (e.g. LLM saw 42 but pattern
    # matches 61). If Python finds FEWER, it means the pattern is incomplete and the
    # last-resort fallback should trigger instead (don't lower the threshold).
    if structure.anchor_pattern and structure.anchor_pattern != "none":
        try:
            actual_anchors = json.loads(_find_all_anchor_ids_impl(file_path, structure.anchor_pattern))
            if len(actual_anchors) > structure.estimated_chapter_count:
                if verbose:
                    print(f"  [Count fix] Actual anchor count={len(actual_anchors)} overrides LLM estimate={structure.estimated_chapter_count}")
                structure.estimated_chapter_count = len(actual_anchors)
        except Exception:
            pass

    # Parse the TOC anchor IDs directly from HTML links — this gives the COMPLETE ordered
    # list including anchors with hyphens/mixed patterns that the regex might miss.
    # These are seeded into Agent 2's known_anchor_ids so gap-fill covers every TOC entry.
    toc_anchors = _extract_toc_anchor_ids_impl(file_path)
    if toc_anchors:
        structure.toc_anchor_ids = toc_anchors
        if len(toc_anchors) > structure.estimated_chapter_count:
            if verbose:
                print(f"  [TOC parse] {len(toc_anchors)} anchors from HTML TOC overrides estimate={structure.estimated_chapter_count}")
            structure.estimated_chapter_count = len(toc_anchors)
        elif verbose:
            print(f"  [TOC parse] {len(toc_anchors)} anchors from HTML TOC")

    # --- Agent 2: Chapter Extraction ---
    if structure.anchor_pattern and structure.anchor_pattern != "none":
        parsed = _run_chapter_extractor(file_path, structure, llm_fast, verbose)
    else:
        # No chapters — extract as single story
        if verbose:
            print("\n[Skipping Agent 2] No anchor pattern, using single-story fallback")
        return _direct_extract_single_story(file_path, structure.title, structure.author)

    # If Agent 2 returned too few chapters, go straight to Python fallback
    threshold = max(1, int(structure.estimated_chapter_count * 0.7))
    if parsed.total_chapters < threshold:
        if verbose:
            print(f"\n[Agent 2 insufficient] Got {parsed.total_chapters}/{structure.estimated_chapter_count} chapters — using Python fallback")
        parsed = _python_extract_chapters(file_path, structure)

    # --- Agent 3: Quality Review ---
    review = _run_quality_reviewer(structure, parsed, llm_reviewer, verbose)

    # Trigger Python fallback if reviewer rejects
    if not review.approved:
        if verbose:
            print(f"\n[Reviewer rejected] Triggering Python fallback extractor")
        parsed = _python_extract_chapters(file_path, structure)

    final_chapters = parsed.chapters

    # Last resort: if still empty or below threshold, try div/heading/single-story extraction
    below_threshold = len(final_chapters) < threshold
    if not final_chapters or below_threshold:
        if verbose:
            reason = "empty" if not final_chapters else f"below threshold ({len(final_chapters)}<{threshold})"
            print(f"  [Last resort] Anchor extraction {reason} — trying structural fallback")
        fallback_result = _direct_extract_single_story(file_path, structure.title, structure.author)
        # Use fallback only if it found more chapters than current result
        if fallback_result["total_chapters"] > len(final_chapters):
            return fallback_result

    chapters_out = [
        {
            "chapter_number": ch.chapter_number,
            "anchor_id": ch.anchor_id,
            "title": ch.title,
            "paragraphs": ch.paragraphs,
            "word_count": ch.word_count,
        }
        for ch in final_chapters
    ]

    result = {
        "title": structure.title,
        "author": structure.author,
        "chapters": chapters_out,
        "total_chapters": len(chapters_out),
        "metadata": {
            "source_file": file_path,
            "parser": "langchain-agents",
            "models_used": [MODEL_ANALYST, MODEL_REVIEWER],
            "structure_notes": structure.notes,
            "review_approved": review.approved,
            "review_notes": review.review_notes,
            "issues_found": review.issues_found,
        },
    }

    if verbose:
        print(f"\n{'='*60}")
        print(f"Parse complete: {result['title']}")
        print(f"  Chapters: {result['total_chapters']}")
        total_words = sum(ch["word_count"] for ch in chapters_out)
        total_paras = sum(len(ch["paragraphs"]) for ch in chapters_out)
        print(f"  Total words: {total_words:,}")
        print(f"  Total paragraphs: {total_paras:,}")
        print(f"{'='*60}\n")

    return result


def save_langchain_parsed_book(result: dict, output_dir: str) -> Path:
    """Legacy save — writes to a flat output directory. Kept for backwards compatibility."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w\s-]", "", result["title"])[:50].strip().replace(" ", "_")
    out_file = out_dir / f"{safe_title}_langchain.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return out_file


def _save_tts_chapters_from_codex(result: dict, chapters_dir: Path) -> None:
    """Convert codex paragraphs → TTS-chunked chapter_NNN.json files (legacy schema).

    Reuses chunk_text from parse_novel_tts.py so the downstream TTS job generator
    (create_tts_audio_jobs.py) can read chapters without any changes.
    """
    from .parse_novel_tts import chunk_text

    chapters = result["chapters"]
    title = result.get("title", "Unknown")
    total_chapters = len(chapters)
    total_chunks = 0
    total_words = sum(ch.get("word_count", 0) for ch in chapters)

    chapter_records = []
    for ch in chapters:
        full_text = "\n\n".join(ch.get("paragraphs", []))
        raw_chunks = chunk_text(full_text, min_size=400, max_size=500)
        total_chunks += len(raw_chunks)
        avg_words = round(ch.get("word_count", 0) / max(len(raw_chunks), 1))
        chapter_records.append({
            "index": ch["chapter_number"],
            "chapter_id": f"chapter_{ch['chapter_number']}",
            "title": ch.get("title", f"Chapter {ch['chapter_number']}"),
            "chunks": raw_chunks,
            "total_chunks": len(raw_chunks),
            "word_count": ch.get("word_count", 0),
            "avg_words_per_chunk": avg_words,
        })

    # Add navigation links
    for i, rec in enumerate(chapter_records):
        rec["previous_chapter"] = f"chapter_{chapter_records[i-1]['index']}" if i > 0 else None
        rec["next_chapter"] = f"chapter_{chapter_records[i+1]['index']}" if i < len(chapter_records) - 1 else None

    book_meta = {
        "book_title": title,
        "total_chapters": total_chapters,
        "total_chunks": total_chunks,
        "total_words": total_words,
        "avg_words_per_chapter": round(total_words / max(total_chapters, 1)),
        "source_file": result.get("metadata", {}).get("source_file", ""),
        "chunk_settings": {"min_size": 400, "max_size": 500},
    }

    # metadata.json — book summary + chapter index
    metadata = {
        **book_meta,
        "chapters": [
            {
                "index": r["index"],
                "chapter_id": r["chapter_id"],
                "title": r["title"],
                "total_chunks": r["total_chunks"],
                "word_count": r["word_count"],
                "avg_words_per_chunk": r["avg_words_per_chunk"],
            }
            for r in chapter_records
        ],
    }
    with open(chapters_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # chapter_NNN.json — one file per chapter
    for rec in chapter_records:
        chapter_file = chapters_dir / f"chapter_{rec['index']:03d}.json"
        with open(chapter_file, "w", encoding="utf-8") as f:
            json.dump({
                "book_metadata": book_meta,
                "chapter": {
                    "index": rec["index"],
                    "chapter_id": rec["chapter_id"],
                    "title": rec["title"],
                    "chunks": rec["chunks"],
                    "total_chunks": rec["total_chunks"],
                    "word_count": rec["word_count"],
                    "avg_words_per_chunk": rec["avg_words_per_chunk"],
                    "navigation": {
                        "previous": rec["previous_chapter"],
                        "next": rec["next_chapter"],
                    },
                },
            }, f, indent=2, ensure_ascii=False)


def save_as_codex(result: dict, html_file_path: str) -> Path:
    """Save parsed book into its foundry directory as codex.json + chapters/.

    Derives book_id from the HTML file's parent directory name
    (e.g. 'pg174' from foundry/pg174/pg174-images.html).
    """
    html_path = Path(html_file_path).resolve()
    book_id = html_path.parent.name  # e.g. 'pg174'

    # Fallback: extract pg<digits> from filename if not already a pg-id directory
    if not re.match(r'^pg\d+', book_id):
        m = re.match(r'^(pg\d+)', html_path.stem)
        book_id = m.group(1) if m else html_path.stem

    book_dir = html_path.parent
    book_dir.mkdir(parents=True, exist_ok=True)

    # 1. Full codex (raw paragraphs, LangChain format)
    codex_file = book_dir / "codex.json"
    with open(codex_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # 2. TTS-ready per-chapter files in chapters/
    chapters_dir = book_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)
    _save_tts_chapters_from_codex(result, chapters_dir)

    print(f"Saved codex:    {codex_file}")
    print(f"Saved chapters: {chapters_dir}/ ({result['total_chapters']} files)")
    return codex_file


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="LangChain multi-agent parser for Project Gutenberg HTML books"
    )
    parser.add_argument("html_file", help="Path to the Gutenberg HTML file")
    parser.add_argument("--output-dir", default=None,
                        help="Legacy flat output directory (deprecated; default saves to foundry book dir)")
    parser.add_argument("--no-save", action="store_true", help="Print result to stdout, don't save")
    parser.add_argument("--quiet", action="store_true", help="Suppress agent progress output")

    args = parser.parse_args()
    verbose = not args.quiet

    result = parse_book_with_agents(args.html_file, verbose=verbose)

    if args.no_save:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.output_dir:
        # Legacy mode: flat output directory
        out_file = save_langchain_parsed_book(result, args.output_dir)
        print(f"Saved: {out_file}")
    else:
        # Default: save into foundry book directory as codex
        save_as_codex(result, args.html_file)


if __name__ == "__main__":
    main()
