#!/usr/bin/env python3
"""
Project Gutenberg Metadata Fetcher

This script fetches metadata for all books available on Project Gutenberg
using the Gutendx API and saves the data locally for analysis.

Usage:
    python gutenberg_metadata.py [options]

Examples:
    # Fetch all books
    python gutenberg_metadata.py
    
    # Fetch only English books
    python gutenberg_metadata.py --languages en
    
    # Fetch books with specific topic
    python gutenberg_metadata.py --topic "science fiction"
    
    # Save to specific file
    python gutenberg_metadata.py --output my_books.json
"""

import argparse
import json
import csv
import time
import sys
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlencode, urljoin

import requests
from tqdm import tqdm
from bs4 import BeautifulSoup


class GutenbergMetadataFetcher:
    """Fetches metadata from Project Gutenberg via Gutendx API with fallbacks."""
    
    # Fallback data sources
    GUTENBERG_MIRRORS = [
        "https://www.gutenberg.org",
        "https://gutenberg.pglaf.org",
        "https://mirror.csclub.uwaterloo.ca/gutenberg"
    ]
    
    def __init__(self, base_url: str = "https://gutendx.com", cache_dir: str = ".gutenberg_cache"):
        self.base_url = base_url
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Gutenberg-Metadata-Fetcher/1.0 (Educational Use)'
        })
        
    def get_books(self, 
                  languages: Optional[List[str]] = None,
                  topic: Optional[str] = None,
                  search: Optional[str] = None,
                  copyright: Optional[str] = None,
                  author_year_start: Optional[int] = None,
                  author_year_end: Optional[int] = None,
                  sort: str = "popular",
                  max_books: int = 100) -> List[Dict[str, Any]]:
        """
        Fetch books metadata with optional filtering.
        
        Args:
            languages: List of language codes (e.g., ['en', 'fr'])
            topic: Search term for topics/subjects
            search: Search term for titles and authors
            copyright: Copyright status ('true' or 'false')
            author_year_start: Start year for author birth/death
            author_year_end: End year for author birth/death
            sort: Sort order ('popular', 'ascending', 'descending')
            
        Returns:
            List of book metadata dictionaries
        """
        all_books = []
        url = f"{self.base_url}/books"
        
        # Build query parameters
        params = {"sort": sort}
        if languages:
            params["languages"] = ",".join(languages)
        if topic:
            params["topic"] = topic
        if search:
            params["search"] = search
        if copyright:
            params["copyright"] = copyright
        if author_year_start:
            params["author_year_start"] = author_year_start
        if author_year_end:
            params["author_year_end"] = author_year_end
            
        print(f"Fetching books with parameters: {params}")
        
        # Try Gutendx API first
        response = self._make_request(url, params)
        if not response:
            print("Gutendx API unavailable, falling back to alternative sources...")
            return self._fallback_get_books(languages, topic, search, copyright, 
                                          author_year_start, author_year_end, sort, max_books=max_books)
            
        data = response.json()
        total_count = data.get("count", 0)
        all_books.extend(data.get("results", []))
        
        print(f"Found {total_count} books total")
        
        # Progress bar for remaining pages
        with tqdm(total=total_count, initial=len(all_books), desc="Fetching books") as pbar:
            next_url = data.get("next")
            
            while next_url:
                response = self._make_request(next_url)
                if not response:
                    break
                    
                data = response.json()
                new_books = data.get("results", [])
                all_books.extend(new_books)
                pbar.update(len(new_books))
                
                next_url = data.get("next")
                
                # Rate limiting - be respectful to the API
                time.sleep(0.5)
                
        return all_books
    
    def get_book_by_id(self, book_id: int) -> Optional[Dict[str, Any]]:
        """Fetch metadata for a specific book by ID."""
        url = f"{self.base_url}/books/{book_id}"
        response = self._make_request(url)
        
        if response and response.status_code == 200:
            return response.json()
        
        # Fallback to direct Project Gutenberg access
        print(f"API unavailable, trying direct access for book {book_id}")
        return self._get_book_from_gutenberg(book_id)
    
    def _make_request(self, url: str, params: Optional[Dict] = None) -> Optional[requests.Response]:
        """Make HTTP request with error handling."""
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            print(f"Error making request to {url}: {e}")
            return None
    
    def _fallback_get_books(self, languages=None, topic=None, search=None, 
                           copyright=None, author_year_start=None, author_year_end=None, 
                           sort="popular", max_books=100) -> List[Dict[str, Any]]:
        """Fallback method to get books when API is unavailable."""
        print("Using fallback methods to discover books...")
        
        # Try different fallback strategies
        books = []
        
        # Strategy 1: Use cached data if available
        cached_books = self._load_cached_books()
        if cached_books:
            print(f"Found {len(cached_books)} books in cache")
            books.extend(cached_books)
        
        # Strategy 2: Try to discover books by ID range
        if not books:
            print("No cache found, discovering books by ID scanning...")
            books = self._discover_books_by_id_range(max_books=max_books)
        
        # Apply filters to the discovered books
        if books:
            books = self._apply_filters(books, languages, topic, search, 
                                      copyright, author_year_start, author_year_end)
        
        return books
    
    def _get_book_from_gutenberg(self, book_id: int) -> Optional[Dict[str, Any]]:
        """Get book metadata directly from Project Gutenberg."""
        # Check cache first
        cached_book = self._load_cached_book(book_id)
        if cached_book:
            return cached_book
        
        # Try to scrape real metadata from the book page
        book_metadata = self._scrape_book_metadata(book_id)
        if book_metadata:
            self._cache_book(book_metadata)
            return book_metadata
                
        return None
    
    def _scrape_book_metadata(self, book_id: int) -> Optional[Dict[str, Any]]:
        """Scrape real metadata from Project Gutenberg book page."""
        for mirror in self.GUTENBERG_MIRRORS:
            try:
                # Try to get the book's main page
                book_url = f"{mirror}/ebooks/{book_id}"
                response = self.session.get(book_url, timeout=15)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract title
                title_elem = soup.find('h1', {'itemprop': 'name'}) or soup.find('h1')
                title = title_elem.get_text(strip=True) if title_elem else f"Book #{book_id}"
                
                # Extract authors
                authors = []
                author_links = soup.find_all('a', {'itemprop': 'creator'})
                for author_link in author_links:
                    author_text = author_link.get_text(strip=True)
                    # Try to parse birth/death years
                    birth_year = death_year = None
                    if '(' in author_text and ')' in author_text:
                        match = re.search(r'\((\d{4})-(\d{4})\)', author_text)
                        if match:
                            birth_year, death_year = int(match.group(1)), int(match.group(2))
                            author_name = author_text.split('(')[0].strip()
                        else:
                            author_name = author_text
                    else:
                        author_name = author_text
                    
                    authors.append({
                        'name': author_name,
                        'birth_year': birth_year,
                        'death_year': death_year
                    })
                
                # Extract language
                languages = []
                lang_elem = soup.find('tr', string=re.compile('Language'))
                if lang_elem:
                    lang_row = lang_elem.find_next('td')
                    if lang_row:
                        lang_text = lang_row.get_text(strip=True)
                        if 'English' in lang_text:
                            languages.append('en')
                        # Add more language mappings as needed
                
                if not languages:
                    languages = ['en']  # Default
                
                # Extract subjects/genres - look for links to /ebooks/subject/
                subjects = []
                subject_links = soup.find_all('a', href=re.compile(r'/ebooks/subject/\d+'))
                for link in subject_links:
                    subject_text = link.get_text(strip=True)
                    if subject_text and subject_text not in subjects:
                        subjects.append(subject_text)
                
                # Extract bookshelves - look for links to /ebooks/bookshelf/
                bookshelves = []
                bookshelf_links = soup.find_all('a', href=re.compile(r'/ebooks/bookshelf/\d+'))
                for link in bookshelf_links:
                    shelf_text = link.get_text(strip=True)
                    # Clean up "In " prefix if present
                    if shelf_text.startswith('In '):
                        shelf_text = shelf_text[3:]
                    # Clean up "Category: " prefix if present  
                    if shelf_text.startswith('Category: '):
                        shelf_text = shelf_text[10:]
                    if shelf_text and shelf_text not in bookshelves:
                        bookshelves.append(shelf_text)
                
                # Extract download count
                download_count = 0
                downloads_elem = soup.find('td', string=re.compile('downloads'))
                if downloads_elem:
                    downloads_text = downloads_elem.get_text()
                    match = re.search(r'(\d+)', downloads_text.replace(',', ''))
                    if match:
                        download_count = int(match.group(1))
                
                # Get available formats
                formats = self._get_book_formats(book_id, mirror)
                
                book_metadata = {
                    "id": book_id,
                    "title": title,
                    "authors": authors,
                    "languages": languages,
                    "subjects": subjects,
                    "bookshelves": bookshelves,
                    "download_count": download_count,
                    "formats": formats,
                    "copyright": False  # Project Gutenberg books are public domain
                }
                
                print(f"Successfully scraped metadata for: {title}")
                return book_metadata
                
            except requests.exceptions.RequestException as e:
                print(f"Error scraping {mirror}/ebooks/{book_id}: {e}")
                continue
            except Exception as e:
                print(f"Error parsing metadata for book {book_id}: {e}")
                continue
        
        return None
    
    def _get_book_formats(self, book_id: int, mirror: str) -> Dict[str, str]:
        """Get available download formats for a book."""
        formats = {}
        
        # Common format patterns for Project Gutenberg
        format_patterns = [
            ("text/html", f"{mirror}/files/{book_id}/{book_id}-h/{book_id}-h.htm"),
            ("text/html", f"{mirror}/files/{book_id}/{book_id}-h.zip"),
            ("application/epub+zip", f"{mirror}/files/{book_id}/{book_id}.epub"),
            ("text/plain; charset=utf-8", f"{mirror}/files/{book_id}/{book_id}-0.txt"),
            ("text/plain", f"{mirror}/files/{book_id}/{book_id}.txt"),
            ("application/pdf", f"{mirror}/files/{book_id}/{book_id}.pdf"),
        ]
        
        for format_type, url in format_patterns:
            try:
                response = self.session.head(url, timeout=5)
                if response.status_code == 200:
                    formats[format_type] = url
            except:
                continue
        
        return formats
    
    def _discover_books_by_id_range(self, start_id: int = 1, max_books: int = 100) -> List[Dict[str, Any]]:
        """Discover books by testing ID ranges."""
        discovered_books = []
        current_id = start_id
        consecutive_failures = 0
        max_consecutive_failures = 10
        
        print(f"Scanning for available books (max {max_books})...")
        
        with tqdm(total=max_books, desc="Discovering books") as pbar:
            while len(discovered_books) < max_books and consecutive_failures < max_consecutive_failures:
                book = self._get_book_from_gutenberg(current_id)
                
                if book:
                    discovered_books.append(book)
                    consecutive_failures = 0
                    pbar.update(1)
                else:
                    consecutive_failures += 1
                
                current_id += 1
                time.sleep(0.5)  # Rate limiting
                
        print(f"Discovered {len(discovered_books)} books")
        return discovered_books
    
    def _apply_filters(self, books: List[Dict[str, Any]], languages=None, topic=None, 
                      search=None, copyright=None, author_year_start=None, 
                      author_year_end=None) -> List[Dict[str, Any]]:
        """Apply filters to the book list."""
        filtered_books = books
        
        if languages:
            filtered_books = [
                book for book in filtered_books 
                if any(lang in book.get('languages', []) for lang in languages)
            ]
        
        if search:
            search_lower = search.lower()
            filtered_books = [
                book for book in filtered_books
                if search_lower in book.get('title', '').lower() or
                   any(search_lower in author.get('name', '').lower() 
                       for author in book.get('authors', []))
            ]
        
        if topic:
            topic_lower = topic.lower()
            filtered_books = [
                book for book in filtered_books
                if any(topic_lower in subject.lower() 
                       for subject in book.get('subjects', [])) or
                   any(topic_lower in shelf.lower() 
                       for shelf in book.get('bookshelves', []))
            ]
        
        return filtered_books
    
    def _load_cached_books(self) -> List[Dict[str, Any]]:
        """Load books from cache."""
        cache_file = self.cache_dir / "books_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (IOError, json.JSONDecodeError):
                pass
        return []
    
    def _load_cached_book(self, book_id: int) -> Optional[Dict[str, Any]]:
        """Load specific book from cache."""
        cache_file = self.cache_dir / f"book_{book_id}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (IOError, json.JSONDecodeError):
                pass
        return None
    
    def _cache_book(self, book: Dict[str, Any]):
        """Cache a book's metadata."""
        book_id = book.get('id')
        if book_id:
            cache_file = self.cache_dir / f"book_{book_id}.json"
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(book, f, indent=2, ensure_ascii=False)
            except IOError:
                pass  # Fail silently for caching
    
    def save_to_json(self, books: List[Dict[str, Any]], filename: str = "gutenberg_books.json"):
        """Save books metadata to JSON file."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(books, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(books)} books to {filename}")
        except IOError as e:
            print(f"Error saving to JSON: {e}")
    
    def save_to_csv(self, books: List[Dict[str, Any]], filename: str = "gutenberg_books.csv"):
        """Save books metadata to CSV file."""
        if not books:
            print("No books to save")
            return
            
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Header
                writer.writerow([
                    'id', 'title', 'authors', 'languages', 'subjects', 
                    'bookshelves', 'download_count', 'formats', 'copyright'
                ])
                
                # Data rows
                for book in books:
                    authors = '; '.join([
                        f"{author.get('name', '')} ({author.get('birth_year', '')}-{author.get('death_year', '')})"
                        for author in book.get('authors', [])
                    ])
                    
                    languages = '; '.join(book.get('languages', []))
                    subjects = '; '.join(book.get('subjects', []))
                    bookshelves = '; '.join(book.get('bookshelves', []))
                    formats = '; '.join(book.get('formats', {}).keys())
                    
                    writer.writerow([
                        book.get('id', ''),
                        book.get('title', ''),
                        authors,
                        languages,
                        subjects,
                        bookshelves,
                        book.get('download_count', ''),
                        formats,
                        book.get('copyright', '')
                    ])
                    
            print(f"Saved {len(books)} books to {filename}")
        except IOError as e:
            print(f"Error saving to CSV: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch metadata for Project Gutenberg books",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--languages", 
        nargs="+", 
        help="Filter by language codes (e.g., en fr de)"
    )
    parser.add_argument(
        "--topic", 
        help="Search for books with specific topic/subject"
    )
    parser.add_argument(
        "--search", 
        help="Search book titles and authors"
    )
    parser.add_argument(
        "--copyright", 
        choices=["true", "false"],
        help="Filter by copyright status"
    )
    parser.add_argument(
        "--author-year-start", 
        type=int,
        help="Filter by author birth/death year (start)"
    )
    parser.add_argument(
        "--author-year-end", 
        type=int,
        help="Filter by author birth/death year (end)"
    )
    parser.add_argument(
        "--sort", 
        choices=["popular", "ascending", "descending"],
        default="popular",
        help="Sort order for results"
    )
    parser.add_argument(
        "--output", 
        default="gutenberg_books",
        help="Output filename (without extension)"
    )
    parser.add_argument(
        "--format", 
        choices=["json", "csv", "both"],
        default="both",
        help="Output format"
    )
    parser.add_argument(
        "--book-id", 
        type=int,
        help="Fetch metadata for specific book ID only"
    )
    parser.add_argument(
        "--offline", 
        action="store_true",
        help="Use only cached data (no network requests)"
    )
    parser.add_argument(
        "--max-books", 
        type=int,
        default=100,
        help="Maximum number of books to discover in fallback mode (default: 100)"
    )
    
    args = parser.parse_args()
    
    fetcher = GutenbergMetadataFetcher()
    
    try:
        if args.offline:
            print("Running in offline mode - using cached data only")
            if args.book_id:
                book = fetcher._load_cached_book(args.book_id)
                books = [book] if book else []
            else:
                books = fetcher._load_cached_books()
                if books:
                    books = fetcher._apply_filters(books, args.languages, args.topic, 
                                                 args.search, args.copyright, 
                                                 args.author_year_start, args.author_year_end)
        elif args.book_id:
            # Fetch single book
            print(f"Fetching metadata for book ID: {args.book_id}")
            book = fetcher.get_book_by_id(args.book_id)
            if book:
                books = [book]
                print(f"Found book: {book.get('title', 'Unknown Title')}")
            else:
                print(f"Book with ID {args.book_id} not found")
                return 1
        else:
            # Fetch multiple books with filters
            books = fetcher.get_books(
                languages=args.languages,
                topic=args.topic,
                search=args.search,
                copyright=args.copyright,
                author_year_start=args.author_year_start,
                author_year_end=args.author_year_end,
                sort=args.sort,
                max_books=args.max_books
            )
        
        if not books:
            print("No books found with the specified criteria")
            return 1
        
        # Save results
        if args.format in ["json", "both"]:
            fetcher.save_to_json(books, f"{args.output}.json")
        
        if args.format in ["csv", "both"]:
            fetcher.save_to_csv(books, f"{args.output}.csv")
        
        print(f"\nSummary:")
        print(f"Total books fetched: {len(books)}")
        if books:
            languages = set()
            for book in books:
                languages.update(book.get('languages', []))
            print(f"Languages found: {', '.join(sorted(languages))}")
            
        return 0
        
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())