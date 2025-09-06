import json
import re
from bs4 import BeautifulSoup

def clean_text(text):
    """
    Clean text by replacing newlines with spaces and multiple spaces with single space
    """
    # Replace all newlines with single space
    text = text.replace('\n', ' ')
    # Replace dots in common titles to avoid sentence splitting issues
    text = text.replace('Mr.', 'Mr')
    text = text.replace('Mrs.', 'Mrs')
    text = text.replace('Dr.', 'Dr')
    text = text.replace('St.', 'St')
    # Replace multiple spaces with single space
    text = re.sub(r'\s+', ' ', text)
    # Strip leading/trailing whitespace
    text = text.strip()
    return text

def split_into_sentences(text):
    """
    Split text into sentences, handling edge cases like dialogue ending with ."
    """
    # First clean the text
    text = clean_text(text)
    
    # Split on sentence endings but keep the punctuation with the sentence
    # This regex handles: . ! ? followed by space and capital letter or quote
    # But also handles ." !" ?" (dialogue endings)
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z"\'])|(?<=[.!?]")\s+(?=[A-Z])|(?<=[.!?]\')\s+(?=[A-Z])', text)
    
    # Clean up each sentence and filter out empty ones
    sentences = [s.strip() for s in sentences if s.strip()]
    
    return sentences

def parse_html_novel(html_file_path):
    """
    Parse HTML novel and extract chapters from div class="chapter" blocks
    Returns dict with separate chapters, chapter_sentences, and chapter_titles
    """
    # Read the HTML file
    with open(html_file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Parse with BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find all chapter divs
    chapter_divs = soup.find_all('div', class_='chapter')
    
    chapters = {}
    chapter_sentences = {}
    chapter_titles = {}
    chapter_sentences_count = {}
    
    print(f"Found {len(chapter_divs)} total chapter divs")
    
    chapter_num = 0
    for chapter_div in chapter_divs:
        # Check if chapter has h2 tag - skip if it doesn't
        h2_tag = chapter_div.find('h2')
        if not h2_tag:
            continue  # Skip empty chapters without h2
        
        chapter_num += 1
        chapter_key = f"chapter_{chapter_num}"
        
        # Process chapter with h2 tag
        if h2_tag:
            # Clean the title - remove line breaks and extra whitespace
            title = h2_tag.get_text(separator=' ', strip=True)
            # Apply cleaning to title
            title = clean_text(title)
            chapter_titles[chapter_key] = title
        else:
            chapter_titles[chapter_key] = f"Chapter {i}"
        
        # Get ONLY paragraph text from the chapter (no title)
        paragraphs = []
        
        # Get all p tags for the actual content
        for p in chapter_div.find_all('p'):
            text = p.get_text(strip=True)
            if text:
                paragraphs.append(text)
        
        # Join paragraphs with double newlines for readability
        chapter_text = '\n\n'.join(paragraphs)
        
        # If no paragraphs found, try to get text excluding h2
        if not chapter_text.strip():
            # Remove h2 tag temporarily to get remaining text
            if h2_tag:
                h2_tag.extract()  # Remove h2 from the tree
            chapter_text = chapter_div.get_text(separator='\n\n', strip=True)
        
        # Clean the chapter text
        cleaned_text = clean_text(chapter_text)
        
        # Split chapter text into sentences
        sentences = split_into_sentences(chapter_text)
        
        # Store both full text and sentences
        chapters[chapter_key] = cleaned_text
        
        # Insert chapter title as first sentence
        sentences_with_title = [chapter_titles[chapter_key]] + sentences
        chapter_sentences[chapter_key] = sentences_with_title
        chapter_sentences_count[chapter_key] = len(sentences_with_title)
    
    print(f"Processed {chapter_num} valid chapters (with h2 tags)")
    
    # If no chapters found, try to get all text
    if not chapters:
        print("No chapter divs found, extracting all text...")
        all_text = soup.get_text(separator='\n\n', strip=True)
        # Clean the text
        cleaned_text = clean_text(all_text)
        # Split all text into sentences
        all_sentences = split_into_sentences(all_text)
        chapters["chapter_1"] = cleaned_text
        chapter_titles["chapter_1"] = "Full Text"
        
        # Insert title as first sentence for fallback case too
        all_sentences_with_title = ["Full Text"] + all_sentences
        chapter_sentences["chapter_1"] = all_sentences_with_title
        chapter_sentences_count["chapter_1"] = len(all_sentences_with_title)
    
    # Return chapters, sentences, counts, and titles
    return {
        "chapters": chapters,
        "chapter_sentences": chapter_sentences,
        "chapter_sentences_count": chapter_sentences_count,
        "chapter_titles": chapter_titles
    }

def main():
    """Test function"""
    # Example usage
    html_file = r"D:\Projects\pheonix\prod\E3\E3\input\novel\pg120-images.html"  # Change this to your HTML file path
    
    try:
        result = parse_html_novel(html_file)
        chapters = result["chapters"]
        chapter_sentences = result["chapter_sentences"]
        titles = result["chapter_titles"]
        
        print(f"\nFound {len(chapters)} chapters")
        
        # Print chapter titles and info
        for key in chapters.keys():
            print(f"\n{key}:")
            print(f"Title: {titles[key]}")
            print(f"Full text length: {len(chapters[key])} characters")
            sentences = chapter_sentences[key]
            print(f"Number of sentences: {len(sentences)}")
            # Show first 3 sentences as preview
            preview = sentences[:3] if len(sentences) > 3 else sentences
            print(f"First sentences: {' '.join(preview)}...")
        
        # Save to JSON
        with open("pg_120.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\nSaved to parsed_chapters.json")
        print(f"Structure:")
        print(f"  - 'chapters' contains full cleaned text")
        print(f"  - 'chapter_sentences' contains list of sentences")
        print(f"  - 'chapter_sentences_count' contains count of sentences")
        print(f"  - 'chapter_titles' contains titles")
        
    except FileNotFoundError:
        print(f"File not found: {html_file}")
        print("Please update the html_file path in main()")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()