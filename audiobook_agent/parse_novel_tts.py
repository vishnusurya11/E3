import json
import re
import os
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Tuple


def roman_to_arabic(roman: str) -> int:
    """Convert Roman numeral to Arabic number."""
    roman_values = {
        'I': 1, 'V': 5, 'X': 10, 'L': 50,
        'C': 100, 'D': 500, 'M': 1000
    }
    
    roman = roman.upper().strip()
    if not roman:
        return 0
        
    total = 0
    prev_value = 0
    
    for char in reversed(roman):
        if char in roman_values:
            value = roman_values[char]
            if value < prev_value:
                total -= value
            else:
                total += value
            prev_value = value
        else:
            # Not a valid Roman numeral character
            return 0
    
    return total


def convert_roman_numerals_in_title(title: str) -> str:
    """Convert Roman numerals in chapter titles to Arabic numbers."""
    import re
    
    # Pattern to match Roman numerals (I, II, III, IV, V, VI, VII, VIII, IX, X, etc.)
    # Word boundaries ensure we don't match parts of words
    roman_pattern = r'\b([IVXLCDM]+)\b'
    
    def replace_roman(match):
        roman = match.group(1)
        # Check if it's a valid Roman numeral by trying to convert it
        arabic = roman_to_arabic(roman)
        if arabic > 0:
            return str(arabic)
        else:
            # If not valid, return original
            return roman
    
    # Replace Roman numerals in the title
    converted_title = re.sub(roman_pattern, replace_roman, title)
    
    # Also handle specific patterns like "ACT I" -> "ACT 1"
    patterns = [
        (r'Chapter\s+([IVXLCDM]+)', r'Chapter \1'),
        (r'Part\s+([IVXLCDM]+)', r'Part \1'),
        (r'Act\s+([IVXLCDM]+)', r'Act \1'),
        (r'Scene\s+([IVXLCDM]+)', r'Scene \1'),
        (r'Book\s+([IVXLCDM]+)', r'Book \1'),
        (r'^([IVXLCDM]+)\.', r'\1.'),  # Roman numeral at start with period
    ]
    
    for pattern, _ in patterns:
        matches = re.finditer(pattern, converted_title, re.IGNORECASE)
        for match in matches:
            roman = match.group(1)
            arabic = roman_to_arabic(roman)
            if arabic > 0:
                converted_title = converted_title.replace(match.group(0), 
                    match.group(0).replace(roman, str(arabic)))
    
    return converted_title


def replace_abbreviations(text: str) -> str:
    """Replace common abbreviations to avoid false sentence breaks."""
    abbreviations = {
        'Dr.': 'Dr',
        'Mr.': 'Mr',
        'Mrs.': 'Mrs',
        'Ms.': 'Ms',
        'St.': 'St',
        'Jr.': 'Jr',
        'Sr.': 'Sr',
        'Ph.D.': 'PhD',
        'M.D.': 'MD',
        'B.A.': 'BA',
        'M.A.': 'MA',
        'etc.': 'etc',
        'vs.': 'vs',
        'i.e.': 'ie',
        'e.g.': 'eg',
        'Inc.': 'Inc',
        'Ltd.': 'Ltd',
        'Co.': 'Co',
        'Corp.': 'Corp',
        'U.S.': 'US',
        'U.K.': 'UK',
        'E.U.': 'EU',
        'U.N.': 'UN',
        'Jan.': 'Jan',
        'Feb.': 'Feb',
        'Mar.': 'Mar',
        'Apr.': 'Apr',
        'Jun.': 'Jun',
        'Jul.': 'Jul',
        'Aug.': 'Aug',
        'Sep.': 'Sep',
        'Sept.': 'Sept',
        'Oct.': 'Oct',
        'Nov.': 'Nov',
        'Dec.': 'Dec',
        'Mon.': 'Mon',
        'Tue.': 'Tue',
        'Wed.': 'Wed',
        'Thu.': 'Thu',
        'Fri.': 'Fri',
        'Sat.': 'Sat',
        'Sun.': 'Sun',
        'No.': 'No',
        'Vol.': 'Vol',
        'Rev.': 'Rev',
        'Prof.': 'Prof',
        'Capt.': 'Capt',
        'Col.': 'Col',
        'Gen.': 'Gen',
        'Lt.': 'Lt',
        'Sgt.': 'Sgt',
    }
    
    # Replace abbreviations
    for abbr, replacement in abbreviations.items():
        text = text.replace(abbr, replacement)
    
    return text


def split_into_sentences(text: str) -> List[str]:
    """
    Split text into sentences with intelligent boundary detection.
    Handles dialogue endings and avoids breaking at abbreviations.
    """
    # First replace abbreviations
    text = replace_abbreviations(text)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    
    # Split on sentence endings
    # This regex handles:
    # - Period, exclamation, or question mark followed by space and capital letter
    # - Same but with closing quotes (." or !" or ?")
    # - Same but with closing single quotes (.' or !' or ?')
    sentences = re.split(
        r'(?<=[.!?])\s+(?=[A-Z])|'  # Normal sentence end
        r'(?<=[.!?]")\s+(?=[A-Z])|'  # Dialogue end with double quote
        r"(?<=[.!?]')\s+(?=[A-Z])",  # Dialogue end with single quote
        text
    )
    
    # Clean up and filter
    sentences = [s.strip() for s in sentences if s.strip()]
    
    return sentences


def break_long_text(text: str, max_size: int) -> List[str]:
    """
    Break text that exceeds max_size into smaller chunks.
    Tries to break at natural boundaries (commas, semicolons, conjunctions, then words).
    
    Args:
        text: Text to break down
        max_size: Maximum size for each chunk
    
    Returns:
        List of text chunks, each <= max_size
    """
    if len(text) <= max_size:
        return [text]
    
    result_chunks = []
    
    # First try to split on semicolons or commas
    # Priority: semicolon > comma > conjunction > word boundary
    split_patterns = [
        ('; ', ';'),
        (', ', ','),
        (' and ', ' and'),
        (' but ', ' but'),
        (' or ', ' or'),
        (' - ', ' -'),
        (' — ', ' —'),
    ]
    
    parts = [text]
    for separator, join_char in split_patterns:
        if separator in text and len(text) > max_size:
            new_parts = []
            for part in parts:
                if len(part) > max_size and separator in part:
                    split_items = part.split(separator)
                    current = ""
                    for i, item in enumerate(split_items):
                        # Add separator back except for last item
                        if i < len(split_items) - 1:
                            item = item + join_char
                        
                        if len(current) + len(item) + (1 if current else 0) <= max_size:
                            current = (current + " " + item).strip() if current else item
                        else:
                            if current:
                                new_parts.append(current)
                            current = item
                    if current:
                        new_parts.append(current)
                else:
                    new_parts.append(part)
            parts = new_parts
            
            # Check if all parts are now under max_size
            if all(len(p) <= max_size for p in parts):
                return parts
    
    # If still have parts exceeding max_size, split by words
    final_chunks = []
    for part in parts:
        if len(part) > max_size:
            words = part.split()
            current = ""
            for word in words:
                # Check if adding this word would exceed limit
                test_len = len(current) + (1 if current else 0) + len(word)
                if test_len <= max_size:
                    current = (current + " " + word).strip() if current else word
                else:
                    if current:
                        final_chunks.append(current)
                    # Start new chunk with this word
                    # If single word exceeds max_size, we have to split the word itself
                    if len(word) > max_size:
                        # Split very long word (rare case)
                        while len(word) > max_size:
                            final_chunks.append(word[:max_size])
                            word = word[max_size:]
                        current = word
                    else:
                        current = word
            if current:
                final_chunks.append(current)
        else:
            final_chunks.append(part)
    
    return final_chunks


def chunk_text(text: str, min_size: int = 400, max_size: int = 500) -> List[Dict]:
    """
    Break text into chunks suitable for TTS processing.
    Enforces maximum chunk size by breaking long sentences if necessary.
    
    Args:
        text: The text to chunk
        min_size: Minimum chunk size in characters
        max_size: Maximum chunk size in characters
    
    Returns:
        List of chunk dictionaries with text and metadata
    """
    # If text is already small enough, return as single chunk
    if len(text) <= max_size:
        return [{
            'chunk_id': 1,
            'text': text,
            'char_count': len(text)
        }]
    
    # Split into sentences
    sentences = split_into_sentences(text)
    
    if not sentences:
        return []
    
    # Pre-process sentences that exceed max_size
    processed_sentences = []
    for sentence in sentences:
        if len(sentence) > max_size:
            # Break down long sentence into smaller parts
            parts = break_long_text(sentence, max_size)
            processed_sentences.extend(parts)
        else:
            processed_sentences.append(sentence)
    
    # Now chunk the processed sentences
    chunks = []
    current_chunk = []
    current_size = 0
    chunk_id = 1
    
    for sentence in processed_sentences:
        sentence_size = len(sentence)
        
        # Calculate size if we add this sentence
        test_size = current_size + (1 if current_chunk else 0) + sentence_size
        
        # If adding this sentence would exceed max_size
        if test_size > max_size:
            # Save current chunk if not empty
            if current_chunk:
                chunk_text_str = ' '.join(current_chunk)
                chunks.append({
                    'chunk_id': chunk_id,
                    'text': chunk_text_str,
                    'char_count': len(chunk_text_str)
                })
                chunk_id += 1
            
            # Start new chunk with this sentence
            current_chunk = [sentence]
            current_size = sentence_size
        else:
            # Add sentence to current chunk
            current_chunk.append(sentence)
            current_size = test_size
            
            # If we're in the sweet spot, consider saving the chunk
            if min_size <= current_size <= max_size:
                # Look ahead - if next sentence would make it too big, save now
                idx = processed_sentences.index(sentence)
                if idx + 1 < len(processed_sentences):
                    next_size = len(processed_sentences[idx + 1])
                    if current_size + next_size + 1 > max_size:
                        chunk_text_str = ' '.join(current_chunk)
                        chunks.append({
                            'chunk_id': chunk_id,
                            'text': chunk_text_str,
                            'char_count': len(chunk_text_str)
                        })
                        chunk_id += 1
                        current_chunk = []
                        current_size = 0
    
    # Add any remaining text as final chunk
    if current_chunk:
        chunk_text_str = ' '.join(current_chunk)
        chunks.append({
            'chunk_id': chunk_id,
            'text': chunk_text_str,
            'char_count': len(chunk_text_str)
        })
    
    return chunks


def clean_text(text: str) -> str:
    """Clean text by normalizing whitespace and removing extra spaces."""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def count_words(text: str) -> int:
    """Count words in a text string."""
    if not text:
        return 0
    # Split on whitespace and filter out empty strings
    words = [word for word in text.split() if word.strip()]
    return len(words)


def combine_small_chunks(chunks: List[Dict], min_size: int, max_size: int) -> List[Dict]:
    """
    Combine adjacent chunks that are below min_size to meet the minimum requirement.
    Keeps the first chunk (title) separate and only combines content chunks.
    
    Args:
        chunks: List of chunk dictionaries
        min_size: Minimum chunk size in characters
        max_size: Maximum chunk size in characters
    
    Returns:
        List of combined chunks meeting min_size requirements
    """
    if not chunks:
        return chunks
    
    # Keep the first chunk (title) separate
    if len(chunks) <= 1:
        return chunks
    
    combined_chunks = [chunks[0]]  # Keep title chunk as-is
    
    # Process content chunks (skip the first title chunk)
    i = 1
    while i < len(chunks):
        current_chunk = chunks[i]
        
        # If current chunk meets min_size, add it as-is
        if current_chunk['char_count'] >= min_size:
            combined_chunks.append(current_chunk)
            i += 1
            continue
        
        # Current chunk is too small, try to combine with following chunks
        combined_text = current_chunk['text']
        combined_size = current_chunk['char_count']
        chunks_used = 1
        
        # Look ahead and combine with next chunks while staying under max_size
        while (i + chunks_used < len(chunks) and 
               combined_size < min_size):
            
            next_chunk = chunks[i + chunks_used]
            test_size = combined_size + 1 + next_chunk['char_count']  # +1 for space
            
            if test_size <= max_size:
                combined_text = combined_text + ' ' + next_chunk['text']
                combined_size = test_size
                chunks_used += 1
            else:
                # Adding next chunk would exceed max_size
                break
        
        # Create the combined chunk
        combined_chunk = {
            'chunk_id': len(combined_chunks) + 1,  # Will be renumbered later
            'text': combined_text,
            'char_count': combined_size
        }
        combined_chunks.append(combined_chunk)
        
        # Move to next unprocessed chunk
        i += chunks_used
    
    # Renumber all chunks sequentially
    for idx, chunk in enumerate(combined_chunks, 1):
        chunk['chunk_id'] = idx
    
    return combined_chunks


def extract_book_title(soup: BeautifulSoup) -> str:
    """Extract the book title from the HTML."""
    title = "Unknown Title"
    
    meta_title = soup.find('meta', {'name': 'dc.title'})
    if meta_title and meta_title.get('content'):
        title = meta_title['content']
    elif soup.title:
        title_text = soup.title.get_text()
        title_text = re.sub(r'^The Project Gutenberg e[Bb]ook of\s*', '', title_text)
        title_text = re.split(r',\s*by\s*|\s+by\s+', title_text)[0]
        if title_text:
            title = title_text
    elif soup.find('h1'):
        h1_text = soup.find('h1').get_text(strip=True)
        if h1_text and len(h1_text) < 200:
            title = h1_text
    
    return clean_text(title)


def extract_chapters_strategy_div(soup: BeautifulSoup) -> List[Dict]:
    """Strategy 1: Extract chapters from div.chapter elements."""
    chapters = []
    chapter_divs = soup.find_all('div', class_='chapter')
    chapter_index = 0
    
    for div in chapter_divs:
        title_tag = None
        for tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            title_tag = div.find(tag)
            if title_tag:
                break
        
        if not title_tag:
            continue
            
        chapter_index += 1
        title = clean_text(title_tag.get_text(separator=' ', strip=True))
        
        # Extract paragraphs
        paragraphs = []
        for p in div.find_all('p'):
            text = p.get_text(separator=' ', strip=True)
            if text:
                cleaned = clean_text(text)
                if cleaned:
                    paragraphs.append(cleaned)
        
        # If no paragraphs, check for table content (like Contents)
        if not paragraphs:
            tables = div.find_all('table')
            for table in tables:
                # Extract table text as a list of items
                table_items = []
                for row in table.find_all('tr'):
                    row_text = row.get_text(separator=' ', strip=True)
                    if row_text:
                        table_items.append(clean_text(row_text))
                
                if table_items:
                    # Join table items as a paragraph
                    table_text = '. '.join(table_items)
                    if table_text:
                        paragraphs.append(table_text)
        
        # If still no content, use the title itself as content for structural chapters
        if not paragraphs:
            # This handles title-only chapters (like "ACT I" or book titles)
            paragraphs = [f"[{title}]"]  # Mark as structural with brackets
        
        # Always include the chapter if it has a title
        if title:
            chapters.append({
                'index': chapter_index,
                'title': title,
                'paragraphs': paragraphs
            })
    
    return chapters


def extract_chapters_strategy_h2_sequential(soup: BeautifulSoup) -> List[Dict]:
    """Strategy 2: Extract chapters based on h2 tags."""
    chapters = []
    chapter_index = 0
    
    h2_tags = soup.find_all('h2')
    
    for h2 in h2_tags:
        if h2.get('id') in ['pg-header-heading', 'pg-footer-heading']:
            continue
        
        # Check for various types of anchors (not just chap\d+)
        anchor = h2.find('a', id=True)
        story_anchor = anchor and anchor.get('id') if anchor else None

        # Detect if this appears to be a story collection
        title_text = soup.find('title')
        is_story_collection = title_text and any(word in title_text.get_text().upper()
                                                for word in ['STORIES', 'TALES', 'COLLECTION'])

        # Enhanced filtering logic for H2 tags
        h2_text = h2.get_text().strip().upper()

        # Skip if it's clearly just a collection title/header (not individual story)
        if (story_anchor and story_anchor.upper() in ['TWENTY-FIVE_GHOST_STORIES', 'GHOST_STORIES']
            and not any(word in h2_text for word in ['THE ', 'A ', 'AN '])):
            continue

        # Include if it has a meaningful anchor ID (suggests individual story/chapter)
        has_meaningful_anchor = (story_anchor and
                               len(story_anchor.replace('_', ' ').strip()) > 3 and
                               story_anchor not in ['pg-header-heading', 'pg-footer-heading'])

        # Include if it matches traditional chapter patterns
        has_chapter_keywords = any(word in h2_text for word in ['CHAPTER', 'ACT', 'SCENE', 'PART', 'BOOK'])

        # Include if it starts with Roman/Arabic numerals
        has_numeric_pattern = re.match(r'^[IVX]+\.?(\s|$)|^\d+\.?(\s|$)', h2_text)

        # Include if it's a story collection and this looks like a story title
        is_story_title = (is_story_collection and
                         (h2_text.startswith('THE ') or
                          h2_text.startswith('A ') or
                          h2_text.startswith('AN ') or
                          has_meaningful_anchor))

        # Apply the filtering logic
        if not (has_meaningful_anchor or has_chapter_keywords or has_numeric_pattern or is_story_title):
            continue
        
        chapter_index += 1
        title = clean_text(h2.get_text(separator=' ', strip=True))
        
        paragraphs = []
        current = h2.find_next_sibling()
        
        while current:
            if current.name == 'h2':
                break
            
            if current.name == 'div' and 'chapter' in current.get('class', []):
                break
                
            if current.name == 'p':
                text = current.get_text(separator=' ', strip=True)
                if text:
                    cleaned = clean_text(text)
                    if cleaned:
                        paragraphs.append(cleaned)
            
            elif current.name == 'table':
                # Handle tables in h2 sequential chapters
                table_items = []
                for row in current.find_all('tr'):
                    row_text = row.get_text(separator=' ', strip=True)
                    if row_text:
                        table_items.append(clean_text(row_text))
                if table_items:
                    table_text = '. '.join(table_items)
                    if table_text:
                        paragraphs.append(table_text)
            
            elif current.name == 'div':
                for p in current.find_all('p'):
                    text = p.get_text(separator=' ', strip=True)
                    if text:
                        cleaned = clean_text(text)
                        if cleaned:
                            paragraphs.append(cleaned)
            
            current = current.find_next_sibling()
        
        # If no paragraphs found, use title as content for structural chapters
        if not paragraphs:
            paragraphs = [f"[{title}]"]
        
        # Always include if there's a title
        if title:
            chapters.append({
                'index': chapter_index,
                'title': title,
                'paragraphs': paragraphs
            })
    
    return chapters


def extract_chapters_strategy_heading_hierarchy(soup: BeautifulSoup) -> List[Dict]:
    """Strategy 3: Extract based on heading hierarchy."""
    chapters = []
    chapter_index = 0
    
    headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    
    for heading in headings:
        if heading.get('id') in ['pg-header-heading', 'pg-footer-heading']:
            continue
        
        text = heading.get_text().strip().upper()
        
        is_chapter = (
            'CHAPTER' in text or
            'ACT' in text or
            'SCENE' in text or
            'PART' in text or
            'BOOK' in text or
            'SECTION' in text or
            re.match(r'^[IVX]+\.?\s', text) or
            re.match(r'^\d+\.?\s', text)
        )
        
        if not is_chapter:
            continue
        
        chapter_index += 1
        title = clean_text(heading.get_text(separator=' ', strip=True))
        
        paragraphs = []
        current = heading.find_next_sibling()
        
        while current:
            if current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                current_level = int(current.name[1])
                heading_level = int(heading.name[1])
                if current_level <= heading_level:
                    break
            
            if current.name == 'p':
                text = current.get_text(separator=' ', strip=True)
                if text:
                    cleaned = clean_text(text)
                    if cleaned:
                        paragraphs.append(cleaned)
            
            current = current.find_next_sibling()
        
        # If no paragraphs found, use title as content for structural chapters
        if not paragraphs:
            paragraphs = [f"[{title}]"]
        
        # Always include if there's a title
        if title:
            chapters.append({
                'index': chapter_index,
                'title': title,
                'paragraphs': paragraphs
            })
    
    return chapters


def extract_chapters_strategy_anchor(soup: BeautifulSoup) -> List[Dict]:
    """
    Strategy 4: Extract chapters using anchor IDs (for pg139-style HTML).
    This handles books where chapters are marked with <a id="chap##"> anchors.
    """
    chapters = []
    chapter_index = 0
    
    # Find all chapter anchors (including prologue and CH pattern)
    # Look for both <a> tags with id and headings with id (like <h2 id="CH1">)
    anchors = soup.find_all('a', id=re.compile(r'^(chap|prol|CH|c)\d+'))
    if not anchors:
        # Also check for headings with these IDs (for pg61262 style)
        headings_with_id = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'], id=re.compile(r'^(chap|prol|CH|c)\d+'))
        anchors = headings_with_id
    
    if not anchors:
        return chapters
    
    for i, anchor in enumerate(anchors):
        chapter_index += 1
        
        # Find the chapter heading(s) that follow the anchor
        # Handle both anchor-inside-heading and heading-with-id cases
        heading = None
        title_parts = []
        
        if anchor.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            # Case: anchor IS the heading (like <h2 id="CH1">)
            heading = anchor
            heading_text = heading.get_text(separator=' ', strip=True)
            if heading_text:
                title_parts.append(clean_text(heading_text))
        else:
            # Case: anchor inside heading or separate anchor
            heading = anchor.parent
            
            # Check if anchor's parent is a heading
            if heading and heading.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                # Extract full heading text, handling <br> tags properly
                heading_text = heading.get_text(separator=' ', strip=True)
                if heading_text:
                    title_parts.append(clean_text(heading_text))
            elif heading and heading.name == 'div':
                # Case: anchor in div, look for following headings (pg139 style)
                # <div><a id="chap01"></a></div><h3>CHAPTER I</h3><h3>"Title"</h3>
                current = heading
                h3_parts = []
                search_limit = 5
                
                while current and search_limit > 0:
                    current = current.find_next_sibling()
                    search_limit -= 1
                    
                    if not current:
                        break
                    
                    # Collect consecutive h3 tags    
                    if current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        heading_text = clean_text(current.get_text(separator=' ', strip=True))
                        if heading_text:
                            h3_parts.append(heading_text)
                            # Look for one more heading after this one
                            next_sibling = current.find_next_sibling()
                            if (next_sibling and 
                                next_sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] and
                                len(h3_parts) < 2):
                                continue  # Keep looking for second heading
                            else:
                                break  # Found our headings, stop looking
                    else:
                        # Hit non-heading, stop looking
                        break
                
                if h3_parts:
                    # Combine the headings: "CHAPTER I" + "Title" -> "CHAPTER I - Title"
                    if len(h3_parts) >= 2:
                        title_parts.append(f"{h3_parts[0]} - {h3_parts[1]}")
                    else:
                        title_parts.append(h3_parts[0])
                    
                    # Set heading to the last heading found for paragraph collection
                    heading = current if current and current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] else None
            else:
                # Fallback: look for heading after anchor
                current = anchor.parent if anchor.parent else anchor
                search_limit = 5
                while current and search_limit > 0:
                    current = current.find_next_sibling()
                    search_limit -= 1
                    
                    if not current:
                        break
                        
                    if current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        heading_text = clean_text(current.get_text(separator=' ', strip=True))
                        if heading_text:
                            title_parts.append(heading_text)
                        break
        
        # Set title based on anchor ID type (prioritize specific patterns)
        anchor_id = anchor.get('id', '')
        if anchor_id.startswith('prol'):
            title = "PROLOGUE"
        elif anchor_id.startswith('CH'):
            # Handle CH pattern (e.g., CH1, CH2) - need to extract Roman numeral and chapter title
            ch_title = f"Chapter {chapter_index}"  # Temporary fallback
            
            # Try to get Roman numeral from heading and chapter title from div.chtitle
            if heading and heading.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                roman_numeral = clean_text(heading.get_text(strip=True))
                
                # Look for div.chtitle after the heading
                chtitle_div = heading.find_next_sibling('div', class_='chtitle')
                if chtitle_div:
                    chapter_name = clean_text(chtitle_div.get_text(strip=True))
                    if roman_numeral and chapter_name:
                        title = f"{roman_numeral} - {chapter_name}"
                    elif chapter_name:
                        title = chapter_name
                    elif roman_numeral:
                        title = roman_numeral
                    else:
                        title = ch_title
                elif roman_numeral:
                    title = roman_numeral
                else:
                    title = ch_title
            else:
                title = ch_title
        elif title_parts:
            # Use extracted title parts for other patterns (chap, etc.)
            title = title_parts[0]  # Use the full heading text as extracted
        else:
            # Final fallback
            title = f"Chapter {chapter_index}"
        
        # Now collect paragraphs until the next chapter anchor or end
        paragraphs = []
        next_anchor = anchors[i + 1] if i + 1 < len(anchors) else None
        
        # Find the chapter div that contains this anchor
        chapter_div = anchor.find_parent('div', class_='chapter')
        if chapter_div:
            # Check if paragraphs are inside or after the chapter div
            # First try to find paragraphs INSIDE the chapter div (pg174 style)
            inside_paragraphs = chapter_div.find_all('p')

            if inside_paragraphs:
                # pg174 style: paragraphs are INSIDE the chapter div
                for p in inside_paragraphs:
                    text = p.get_text(separator=' ', strip=True)
                    if text:
                        cleaned = clean_text(text)
                        if cleaned:
                            paragraphs.append(cleaned)
            else:
                # Tom Sawyer style: paragraphs are AFTER the chapter div
                current = chapter_div.find_next_sibling()

                while current:
                    # Stop if we hit the next chapter
                    if (current.name == 'div' and current.get('class') == ['chapter']) or \
                       (current.name in ['h1', 'h2'] and 'CHAPTER' in current.get_text().upper()):
                        break

                    # Skip image divs
                    if current.name == 'div' and current.get('class') == ['fig']:
                        current = current.find_next_sibling()
                        continue

                    # Collect paragraph content
                    if current.name == 'p':
                        text = current.get_text(separator=' ', strip=True)
                        if text:
                            cleaned = clean_text(text)
                            if cleaned:
                                paragraphs.append(cleaned)
                    elif current.name == 'div':
                        # Check for paragraphs inside divs
                        for p in current.find_all('p'):
                            text = p.get_text(separator=' ', strip=True)
                            if text:
                                cleaned = clean_text(text)
                                if cleaned:
                                    paragraphs.append(cleaned)

                    current = current.find_next_sibling()
        else:
            # Fallback: collect paragraphs after heading until next chapter
            if anchor.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                # anchor IS the heading, start from its next sibling
                current = anchor.find_next_sibling()
            elif anchor.parent and anchor.parent.name == 'div':
                # pg139 style: anchor in div, skip past the headings we found
                current = anchor.parent
                # Skip past div and any headings
                headings_to_skip = 2  # Usually CHAPTER + Title
                while current and headings_to_skip > 0:
                    current = current.find_next_sibling()
                    if current and current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                        headings_to_skip -= 1
            else:
                # anchor might be inside heading, start from parent's next sibling
                parent = anchor.parent
                print(f"    Anchor parent: {parent.name if parent else 'None'}")

                if parent and parent.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    # For pg174 style: <h2><a id="chap00"></a>THE PREFACE</h2>
                    # We need to start from the heading's next sibling
                    current = parent.find_next_sibling()
                    print(f"    Starting from heading's next sibling: {current.name if current else 'None'}")
                else:
                    # If anchor.parent is not a heading, start from anchor itself
                    current = anchor.find_next_sibling()
                    print(f"    Starting from anchor's next sibling: {current.name if current else 'None'}")

            # Debug: Track paragraph collection
            paragraph_count = 0
            elements_checked = 0
            max_elements = 100  # Safety limit

            print(f"    Starting content extraction for chapter {chapter_index}: {title}")
            print(f"    Current element after setup: {current.name if current else 'None'}")

            while current and elements_checked < max_elements:
                elements_checked += 1

                # Debug current element
                if elements_checked <= 5:  # Log first 5 elements
                    print(f"    Element {elements_checked}: {current.name}, class={current.get('class', [])}")

                # Stop if we hit the next chapter anchor
                if next_anchor:
                    # Check if current element contains the next anchor
                    if (current.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] and
                        current.find('a', id=next_anchor.get('id'))):
                        print(f"    Stopping: Found next chapter anchor in {current.name}")
                        break
                    # Also stop if current has the next anchor's ID
                    if current.get('id') == next_anchor.get('id'):
                        print(f"    Stopping: Current element has next anchor ID")
                        break

                # Stop if we hit another chapter div
                if current.name == 'div' and 'chapter' in current.get('class', []):
                    print(f"    Stopping: Found chapter div")
                    break

                # Skip div.chtitle (chapter title div) - we already processed it
                if current.name == 'div' and 'chtitle' in current.get('class', []):
                    current = current.find_next_sibling()
                    continue

                # Collect paragraphs
                if current.name == 'p':
                    text = current.get_text(separator=' ', strip=True)
                    if text:
                        cleaned = clean_text(text)
                        if cleaned:
                            paragraphs.append(cleaned)
                            paragraph_count += 1
                            if paragraph_count <= 2:  # Log first 2 paragraphs
                                print(f"    Found paragraph {paragraph_count}: {cleaned[:100]}...")
                elif current.name == 'div':
                    div_paras = current.find_all('p')
                    for p in div_paras:
                        text = p.get_text(separator=' ', strip=True)
                        if text:
                            cleaned = clean_text(text)
                            if cleaned:
                                paragraphs.append(cleaned)
                                paragraph_count += 1
                                if paragraph_count <= 2:
                                    print(f"    Found paragraph {paragraph_count} in div: {cleaned[:100]}...")

                current = current.find_next_sibling()

                if not current:
                    break
        
        # If no paragraphs found, use title as content
        if not paragraphs:
            print(f"    WARNING: No paragraphs found for chapter {chapter_index}: {title}")
            paragraphs = [f"[{title}]"]
        else:
            print(f"    Total paragraphs found: {len(paragraphs)}")

        chapters.append({
            'index': chapter_index,
            'title': title,
            'paragraphs': paragraphs
        })
    
    return chapters


def process_chapters_for_tts(chapters: List[Dict], min_chunk_size: int = 400, max_chunk_size: int = 500) -> List[Dict]:
    """
    Process chapters to create TTS-friendly chunks.
    
    Args:
        chapters: List of chapter dictionaries
        min_chunk_size: Minimum chunk size in characters
        max_chunk_size: Maximum chunk size in characters
    
    Returns:
        List of chapters with chunked paragraphs
    """
    processed_chapters = []
    
    for chapter in chapters:
        # Convert Roman numerals in chapter title
        converted_title = convert_roman_numerals_in_title(chapter['title'])
        
        chunks = []
        
        # Add the chapter title as the first chunk (standalone)
        title_chunk = {
            'chunk_id': 1,
            'text': converted_title,
            'char_count': len(converted_title)
        }
        chunks.append(title_chunk)
        
        # Process each paragraph (skip if it's just the wrapped title)
        for para in chapter['paragraphs']:
            # Skip paragraphs that are just the wrapped title
            if para == f"[{chapter['title']}]" or para == f"[{converted_title}]":
                continue
            para_chunks = chunk_text(para, min_chunk_size, max_chunk_size)
            chunks.extend(para_chunks)
        
        # Combine small chunks to meet min_size requirements
        chunks = combine_small_chunks(chunks, min_chunk_size, max_chunk_size)
        
        # Renumber chunks sequentially for the chapter
        for i, chunk in enumerate(chunks, 1):
            chunk['chunk_id'] = i
        
        # Calculate word count for this chapter
        chapter_word_count = sum(count_words(chunk['text']) for chunk in chunks)
        avg_words_per_chunk = round(chapter_word_count / len(chunks)) if chunks else 0
        
        processed_chapter = {
            'index': chapter['index'],
            'title': converted_title,  # Use converted title
            'original_title': chapter['title'],  # Keep original for reference
            'chunks': chunks,
            'total_chunks': len(chunks),
            'word_count': chapter_word_count,
            'avg_words_per_chunk': avg_words_per_chunk,
            'original_paragraph_count': len(chapter['paragraphs'])
        }
        
        # Add navigation
        processed_chapter['chapter_id'] = f"chapter_{chapter['index']}"
        
        processed_chapters.append(processed_chapter)
    
    # Add navigation links
    for i, chapter in enumerate(processed_chapters):
        chapter['previous_chapter'] = f"chapter_{processed_chapters[i-1]['index']}" if i > 0 else None
        chapter['next_chapter'] = f"chapter_{processed_chapters[i+1]['index']}" if i < len(processed_chapters) - 1 else None
    
    return processed_chapters


def parse_gutenberg_html_tts(
    file_path: str, 
    min_chunk_size: int = 400,
    max_chunk_size: int = 500,
    save_individual: bool = False,
    output_dir: str = None
) -> Dict:
    """
    Parse Project Gutenberg HTML file and create TTS-friendly chunks.
    
    Args:
        file_path: Path to the HTML file
        min_chunk_size: Minimum chunk size in characters
        max_chunk_size: Maximum chunk size in characters
        save_individual: If True, save each chapter as a separate file
        output_dir: Directory to save individual chapter files
    
    Returns:
        Dictionary with metadata and chapters containing TTS chunks.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Extract book title
    book_title = extract_book_title(soup)
    
    # Remove Project Gutenberg boilerplate
    for section in soup.find_all('section', class_='pg-boilerplate'):
        section.decompose()
    
    # Try different extraction strategies in order
    chapters = []
    strategy_used = None
    
    # Strategy 1: Try anchor-based extraction first (for pg139-style)
    chapters = extract_chapters_strategy_anchor(soup)
    if chapters and any(len(ch.get('paragraphs', [])) > 0 for ch in chapters):
        strategy_used = 'anchor'
    
    # Strategy 2: Try div-based extraction
    if not strategy_used:  # Changed from 'if not chapters'
        chapters = extract_chapters_strategy_div(soup)
        if chapters and any(len(ch.get('paragraphs', [])) > 0 for ch in chapters):
            strategy_used = 'div'

    # Strategy 3: Try h2 sequential
    if not strategy_used:  # Changed from 'if not chapters'
        chapters = extract_chapters_strategy_h2_sequential(soup)
        if chapters and any(len(ch.get('paragraphs', [])) > 0 for ch in chapters):
            strategy_used = 'h2_sequential'

    # Strategy 4: Try heading hierarchy
    if not strategy_used:  # Changed from 'if not chapters'
        chapters = extract_chapters_strategy_heading_hierarchy(soup)
        if chapters and any(len(ch.get('paragraphs', [])) > 0 for ch in chapters):
            strategy_used = 'heading_hierarchy'
    
    # Log which strategy was used
    if strategy_used:
        print(f"Using extraction strategy: {strategy_used}")
    
    # Fallback - extract all paragraphs as single chapter
    if not chapters:
        print("Warning: No chapter structure found, using fallback strategy")
        all_paragraphs = []
        for p in soup.find_all('p'):
            text = p.get_text(separator=' ', strip=True)
            if text:
                cleaned = clean_text(text)
                if cleaned and len(cleaned) > 20:
                    all_paragraphs.append(cleaned)
        
        if all_paragraphs:
            chapters = [{
                'index': 1,
                'title': book_title,
                'paragraphs': all_paragraphs
            }]
            strategy_used = 'fallback'
    
    # Process chapters for TTS
    processed_chapters = process_chapters_for_tts(chapters, min_chunk_size, max_chunk_size)
    
    # Calculate book-level word count statistics
    total_chunks = sum(ch['total_chunks'] for ch in processed_chapters)
    total_words = sum(ch['word_count'] for ch in processed_chapters)
    avg_words_per_chapter = round(total_words / len(processed_chapters)) if processed_chapters else 0
    
    # Create the result
    result = {
        'metadata': {
            'total_chapters': len(processed_chapters),
            'total_chunks': total_chunks,
            'total_words': total_words,
            'avg_words_per_chapter': avg_words_per_chapter,
            'file': Path(file_path).name,
            'book_title': book_title,
            'chunk_settings': {
                'min_size': min_chunk_size,
                'max_size': max_chunk_size
            }
        },
        'chapters': processed_chapters
    }
    
    # Save individual files if requested
    if save_individual and output_dir:
        save_individual_tts_chapters(result, output_dir)
    
    return result


def save_individual_tts_chapters(book_data: Dict, output_dir: str):
    """Save each chapter as a separate TTS-ready JSON file."""
    # Output directly to chapters folder (no extra subfolder)
    book_dir = Path(output_dir)
    book_dir.mkdir(parents=True, exist_ok=True)
    
    # Save metadata
    metadata = {
        'book_title': book_data['metadata']['book_title'],
        'total_chapters': book_data['metadata']['total_chapters'],
        'total_chunks': book_data['metadata']['total_chunks'],
        'total_words': book_data['metadata']['total_words'],
        'avg_words_per_chapter': book_data['metadata']['avg_words_per_chapter'],
        'source_file': book_data['metadata']['file'],
        'chunk_settings': book_data['metadata']['chunk_settings'],
        'chapters': [
            {
                'index': ch['index'],
                'chapter_id': ch['chapter_id'],
                'title': ch['title'],
                'total_chunks': ch['total_chunks'],
                'word_count': ch['word_count'],
                'avg_words_per_chunk': ch['avg_words_per_chunk']
            }
            for ch in book_data['chapters']
        ]
    }
    
    metadata_file = book_dir / 'metadata.json'
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    # Save each chapter
    for chapter in book_data['chapters']:
        chapter_file = book_dir / f"chapter_{chapter['index']:03d}.json"
        
        chapter_data = {
            'book_metadata': {
                'book_title': book_data['metadata']['book_title'],
                'total_chapters': book_data['metadata']['total_chapters'],
                'total_chunks': book_data['metadata']['total_chunks'],
                'total_words': book_data['metadata']['total_words'],
                'source_file': book_data['metadata']['file'],
                'chunk_settings': book_data['metadata']['chunk_settings']
            },
            'chapter': {
                'index': chapter['index'],
                'chapter_id': chapter['chapter_id'],
                'title': chapter['title'],
                'chunks': chapter['chunks'],
                'total_chunks': chapter['total_chunks'],
                'word_count': chapter['word_count'],
                'avg_words_per_chunk': chapter['avg_words_per_chunk'],
                'navigation': {
                    'previous': chapter['previous_chapter'],
                    'next': chapter['next_chapter']
                }
            }
        }
        
        with open(chapter_file, 'w', encoding='utf-8') as f:
            json.dump(chapter_data, f, indent=2, ensure_ascii=False)
    
    print(f"  Saved {len(book_data['chapters'])} TTS-ready chapter files to {book_dir}")


def parse_novel(
    input_dir: str = "input/novel",
    output_dir: str = "output", 
    input_file: str = None,
    min_chunk_size: int = 400,
    max_chunk_size: int = 500,
    save_individual: bool = True,
    verbose: bool = True
) -> Dict:
    """
    Parse HTML novels with configurable settings.
    
    Args:
        input_dir: Directory containing HTML files to process (used if input_file not provided)
        output_dir: Base directory to save processed files
        input_file: Specific HTML file to process (overrides input_dir if provided)
        min_chunk_size: Minimum chunk size in characters
        max_chunk_size: Maximum chunk size in characters
        save_individual: If True, save each chapter as separate file
        verbose: If True, print detailed progress information
    
    Returns:
        Dict with processing results and statistics
        
    Examples:
        # Process single file
        result = parse_novel(input_file="input/novel/pg1155-images.html")
        
        # Process all files in directory
        result = parse_novel(input_dir="input/novel")
        
        # Custom settings
        result = parse_novel(
            input_file="path/to/book.html",
            output_dir="custom/output",
            min_chunk_size=350,
            max_chunk_size=450
        )
    """
    output_path = Path(output_dir)
    
    # Determine processing mode and get HTML files
    if input_file:
        # Single file mode
        input_file_path = Path(input_file)
        if not input_file_path.exists():
            error_msg = f"Error: Input file {input_file_path} not found"
            if verbose:
                print(error_msg)
            return {'error': error_msg, 'success': False}
        
        if not input_file_path.suffix.lower() == '.html':
            error_msg = f"Error: Input file must be HTML (.html extension)"
            if verbose:
                print(error_msg)
            return {'error': error_msg, 'success': False}
        
        html_files = [input_file_path]
        mode = "single file"
        display_input = str(input_file_path)
    else:
        # Directory mode (existing behavior)
        input_path = Path(input_dir)
        
        if not input_path.exists():
            error_msg = f"Error: Input directory {input_path} not found"
            if verbose:
                print(error_msg)
            return {'error': error_msg, 'success': False}
        
        html_files = list(input_path.glob('*.html'))
        
        if not html_files:
            error_msg = f"No HTML files found in {input_path}"
            if verbose:
                print(error_msg)
            return {'error': error_msg, 'success': False}
        
        mode = "directory"
        display_input = str(input_path)
    
    if verbose:
        print(f"\nTTS Novel Parser")
        print(f"Mode: {mode}")
        print(f"Input: {display_input}")
        print(f"Output: {output_path}")
        print(f"Chunk settings: min={min_chunk_size}, max={max_chunk_size} characters")
        print("=" * 70)
    
    # Create output directory
    output_path.mkdir(exist_ok=True)
    
    if verbose:
        files_text = "file" if len(html_files) == 1 else "files"
        print(f"Found {len(html_files)} HTML {files_text} to process\n")
    
    # Processing results
    results = {
        'success': True,
        'total_files': len(html_files),
        'processed_files': 0,
        'failed_files': 0,
        'books': [],
        'total_chapters_all_books': 0,
        'total_chunks_all_books': 0,
        'total_words_all_books': 0,
        'settings': {
            'mode': mode,
            'input_dir': input_dir if not input_file else None,
            'input_file': input_file,
            'output_dir': str(output_path),
            'min_chunk_size': min_chunk_size,
            'max_chunk_size': max_chunk_size,
            'save_individual': save_individual
        }
    }
    
    # Process each HTML file
    for i, html_file in enumerate(html_files, 1):
        if verbose:
            print(f"[{i}/{len(html_files)}] Processing: {html_file.name}")
            print("-" * 50)
        
        try:
            if verbose:
                print(f"Analyzing HTML structure...")
            
            result = parse_gutenberg_html_tts(
                str(html_file),
                min_chunk_size=min_chunk_size,
                max_chunk_size=max_chunk_size,
                save_individual=save_individual,
                output_dir=str(output_path)
            )
            
            book_info = {
                'filename': html_file.name,
                'book_title': result['metadata']['book_title'],
                'total_chapters': result['metadata']['total_chapters'],
                'total_chunks': result['metadata']['total_chunks'],
                'total_words': result['metadata']['total_words'],
                'avg_words_per_chapter': result['metadata']['avg_words_per_chapter']
            }
            results['books'].append(book_info)
            
            # Update totals
            results['total_chapters_all_books'] += book_info['total_chapters']
            results['total_chunks_all_books'] += book_info['total_chunks']
            results['total_words_all_books'] += book_info['total_words']
            results['processed_files'] += 1
            
            if verbose:
                print(f"Successfully processed: {book_info['book_title']}")
                print(f"   Chapters: {book_info['total_chapters']}")
                print(f"   Chunks: {book_info['total_chunks']}")
                print(f"   Words: {book_info['total_words']:,}")
                print(f"   Saved to: {output_path / html_file.stem}/")
                
                # Show first chapter as preview
                if result['chapters']:
                    chapter = result['chapters'][0]
                    print(f"   First chapter: {chapter['title']}")
                    print(f"      Chunks: {chapter['total_chunks']}, Words: {chapter['word_count']}")
                print()
            
        except Exception as e:
            error_info = {
                'filename': html_file.name,
                'error': str(e)
            }
            results['failed_files'] += 1
            if verbose:
                print(f"Error processing {html_file.name}: {e}")
                import traceback
                traceback.print_exc()
                print()
    
    # Final summary
    if verbose:
        print("\n" + "=" * 70)
        print(f"Processing Complete!")
        print(f"   Successfully processed: {results['processed_files']}/{results['total_files']} files")
        if results['failed_files'] > 0:
            print(f"   Failed: {results['failed_files']} files")
        print(f"   Total books: {len(results['books'])}")
        print(f"   Total chapters: {results['total_chapters_all_books']}")
        print(f"   Total chunks: {results['total_chunks_all_books']}")
        print(f"   Total words: {results['total_words_all_books']:,}")
        print(f"   All files saved to: {output_path}/")
        print(f"\nFeatures:")
        print(f"   - Individual chapter JSON files")
        print(f"   - Complete metadata with word counts")
        print(f"   - Optimized chunks ({min_chunk_size}-{max_chunk_size} chars)")
        print(f"   - Support for all Project Gutenberg HTML formats")
    
    return results


def main():
    """CLI wrapper for parse_novel function."""
    import sys
    
    # Allow command line arguments for chunk sizes
    min_size = 400
    max_size = 500
    
    if len(sys.argv) > 2:
        try:
            min_size = int(sys.argv[1])
            max_size = int(sys.argv[2])
        except:
            print("Usage: python parse_novel_tts.py [min_chunk_size] [max_chunk_size]")
            print("Using defaults: min=400, max=500")
    
    # Call the main parse_novel function
    result = parse_novel(
        min_chunk_size=min_size,
        max_chunk_size=max_size,
        verbose=True
    )
    
    # Exit with error code if processing failed
    if not result['success']:
        sys.exit(1)


if __name__ == "__main__":
    main()