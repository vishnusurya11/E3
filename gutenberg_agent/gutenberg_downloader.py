#!/usr/bin/env python3
"""
Project Gutenberg Book Downloader

This script downloads specific books from Project Gutenberg by their ID,
respecting the site's robot access policies and rate limiting.

Usage:
    python gutenberg_downloader.py <book_id> [options]

Examples:
    # Download book ID 1342 (Pride and Prejudice) in text format
    python gutenberg_downloader.py 1342
    
    # Download in EPUB format
    python gutenberg_downloader.py 1342 --format epub
    
    # Download to specific directory
    python gutenberg_downloader.py 1342 --output-dir ./downloads
    
    # Download with custom filename
    python gutenberg_downloader.py 1342 --filename "pride_and_prejudice.txt"
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from tqdm import tqdm
from bs4 import BeautifulSoup


class GutenbergDownloader:
    """Downloads books from Project Gutenberg mirrors."""
    
    # Primary Project Gutenberg mirrors
    MIRRORS = [
        "https://www.gutenberg.org",
        "https://gutenberg.pglaf.org",
        "https://mirror.csclub.uwaterloo.ca/gutenberg"
    ]
    
    # Preferred format order (most readable to least)
    FORMAT_PRIORITY = [
        "text/html",
        "application/epub+zip",
        "text/plain; charset=utf-8",
        "text/plain",
        "application/pdf",
        "application/x-mobipocket-ebook"
    ]
    
    # Format extensions mapping
    FORMAT_EXTENSIONS = {
        "text/plain": ".txt",
        "text/plain; charset=utf-8": ".txt",
        "application/epub+zip": ".epub",
        "text/html": ".html",
        "application/pdf": ".pdf",
        "application/x-mobipocket-ebook": ".mobi",
        "application/zip": ".zip"
    }
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Gutenberg-Downloader/1.0 (Educational Use; Respects robot.txt)'
        })
        
    def get_book_metadata(self, book_id: int) -> Optional[Dict]:
        """Fetch book metadata from Gutendx API with fallback."""
        # Try Gutendx API first
        url = f"https://gutendx.com/books/{book_id}"
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Gutendx API unavailable: {e}")
            print("Falling back to direct Project Gutenberg access")
            return self._scrape_book_metadata(book_id)
    
    def _create_minimal_metadata(self, book_id: int) -> Dict:
        """Create minimal metadata when API is unavailable."""
        # Common Project Gutenberg URL patterns
        base_url = "https://www.gutenberg.org/files"
        formats = {}
        
        # Try common format URLs (HTML first since it's preferred)
        possible_formats = [
            ("text/html", f"{base_url}/{book_id}/{book_id}-h/{book_id}-h.htm"),
            ("text/html", f"{base_url}/{book_id}/{book_id}-h.zip"),
            ("application/epub+zip", f"{base_url}/{book_id}/{book_id}.epub"),
            ("text/plain; charset=utf-8", f"{base_url}/{book_id}/{book_id}-0.txt"),
            ("text/plain", f"{base_url}/{book_id}/{book_id}.txt"),
        ]
        
        # Test which formats are actually available
        for format_type, url in possible_formats:
            try:
                response = self.session.head(url, timeout=10)
                if response.status_code == 200:
                    formats[format_type] = url
            except:
                continue
        
        return {
            "id": book_id,
            "title": f"Project Gutenberg Book #{book_id}",
            "formats": formats
        }
    
    def _scrape_book_metadata(self, book_id: int) -> Optional[Dict]:
        """Scrape real metadata from Project Gutenberg book page."""
        import re
        
        for mirror in self.MIRRORS:
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
                    authors.append({'name': author_text})
                
                # Get available formats with enhanced detection
                formats = self._get_enhanced_book_formats(book_id, mirror)
                
                book_metadata = {
                    "id": book_id,
                    "title": title,
                    "authors": authors,
                    "formats": formats
                }
                
                print(f"Successfully scraped metadata for: {title}")
                return book_metadata
                
            except Exception as e:
                print(f"Error scraping {mirror}/ebooks/{book_id}: {e}")
                continue
        
        # Fallback to minimal metadata if scraping fails
        return self._create_minimal_metadata(book_id)
    
    def _get_enhanced_book_formats(self, book_id: int, mirror: str) -> Dict[str, str]:
        """Get available download formats for a book with enhanced detection."""
        formats = {}
        
        # Enhanced format patterns prioritizing HTML
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
    
    def get_available_formats(self, book_id: int) -> Dict[str, str]:
        """Get available download formats for a book."""
        metadata = self.get_book_metadata(book_id)
        if not metadata:
            return {}
        
        formats = metadata.get("formats", {})
        print(f"Available formats for '{metadata.get('title', 'Unknown')}':")
        for format_type, url in formats.items():
            print(f"  - {format_type}: {url}")
        
        return formats
    
    def select_best_format(self, formats: Dict[str, str], preferred_format: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """
        Select the best format to download.
        
        Args:
            formats: Dictionary of format -> URL
            preferred_format: User's preferred format (e.g., 'txt', 'epub', 'pdf')
            
        Returns:
            Tuple of (format_type, download_url) or None
        """
        if not formats:
            return None
        
        # If user specified a format, try to match it
        if preferred_format:
            preferred_format = preferred_format.lower()
            for format_type, url in formats.items():
                if preferred_format in format_type.lower():
                    return format_type, url
            
            print(f"Warning: Preferred format '{preferred_format}' not found")
        
        # Use priority order
        for priority_format in self.FORMAT_PRIORITY:
            if priority_format in formats:
                return priority_format, formats[priority_format]
        
        # Fallback to first available format
        format_type, url = next(iter(formats.items()))
        return format_type, url
    
    def generate_filename(self, book_metadata: Dict, format_type: str, custom_filename: Optional[str] = None) -> str:
        """Generate a filename for the downloaded book."""
        if custom_filename:
            return custom_filename
        
        title = book_metadata.get("title", "Unknown_Title")
        book_id = book_metadata.get("id", "unknown")
        
        # Clean title for filename
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_title = safe_title.replace(' ', '_')[:50]  # Limit length
        
        # Get appropriate extension
        extension = self.FORMAT_EXTENSIONS.get(format_type, ".txt")
        
        return f"pg{book_id}_{safe_title}{extension}"
    
    def download_book(self, 
                     book_id: int, 
                     output_dir: str = ".", 
                     preferred_format: Optional[str] = None,
                     custom_filename: Optional[str] = None) -> Optional[str]:
        """
        Download a book by its Project Gutenberg ID.
        
        Args:
            book_id: Project Gutenberg book ID
            output_dir: Directory to save the book
            preferred_format: Preferred format (txt, epub, pdf, etc.)
            custom_filename: Custom filename for the downloaded book
            
        Returns:
            Path to downloaded file or None if failed
        """
        print(f"Fetching information for book ID: {book_id}")
        
        # Get book metadata and formats
        metadata = self.get_book_metadata(book_id)
        if not metadata:
            print(f"Could not find book with ID: {book_id}")
            return None
        
        formats = metadata.get("formats", {})
        if not formats:
            print(f"No download formats available for book {book_id}")
            return None
        
        # Select format to download
        format_info = self.select_best_format(formats, preferred_format)
        if not format_info:
            print("No suitable format found")
            return None
        
        format_type, download_url = format_info
        print(f"Selected format: {format_type}")
        print(f"Download URL: {download_url}")
        
        # Generate filename
        filename = self.generate_filename(metadata, format_type, custom_filename)
        filepath = Path(output_dir) / filename
        
        # Create output directory if it doesn't exist
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Download the file
        return self._download_file(download_url, filepath, metadata)
    
    def _download_file(self, url: str, filepath: Path, metadata: Dict) -> Optional[str]:
        """Download file with progress bar and error handling."""
        try:
            print(f"Downloading '{metadata.get('title', 'Unknown')}' to {filepath}")
            
            # Rate limiting - respect the 2-second delay mentioned in robot policy
            time.sleep(2)
            
            response = self.session.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            
            with open(filepath, 'wb') as f, tqdm(
                desc=filepath.name,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
            ) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))
            
            print(f"Successfully downloaded: {filepath}")
            print(f"File size: {filepath.stat().st_size:,} bytes")
            
            return str(filepath)
            
        except requests.exceptions.RequestException as e:
            print(f"Error downloading {url}: {e}")
            # Clean up partial file
            if filepath.exists():
                filepath.unlink()
            return None
        except IOError as e:
            print(f"Error writing file {filepath}: {e}")
            return None
    
    def list_formats(self, book_id: int):
        """List all available formats for a book."""
        print(f"Checking available formats for book ID: {book_id}")
        formats = self.get_available_formats(book_id)
        
        if not formats:
            print("No formats available or book not found")
            return
        
        print(f"\nAvailable formats:")
        for i, (format_type, url) in enumerate(formats.items(), 1):
            extension = self.FORMAT_EXTENSIONS.get(format_type, "")
            print(f"{i:2d}. {format_type}{extension}")
    
    def download_multiple_formats(self, book_id: int, output_dir: str = ".") -> List[str]:
        """Download all available formats for a book."""
        metadata = self.get_book_metadata(book_id)
        if not metadata:
            return []
        
        formats = metadata.get("formats", {})
        downloaded_files = []
        
        print(f"Downloading all formats for '{metadata.get('title', 'Unknown')}'")
        
        for format_type, url in formats.items():
            filename = self.generate_filename(metadata, format_type)
            filepath = Path(output_dir) / filename
            
            result = self._download_file(url, filepath, metadata)
            if result:
                downloaded_files.append(result)
            
            # Rate limiting between downloads
            time.sleep(2)
        
        return downloaded_files


def download_book_to_foundry(book_id: int) -> bool:
    """
    Download book to foundry structure (foundry/pg{book_id}/pg{book_id}-images.html).

    Args:
        book_id: Project Gutenberg book ID

    Returns:
        bool: True if download successful, False otherwise
    """
    try:
        downloader = GutenbergDownloader()

        # Create book-specific directory in foundry
        book_dir = f"foundry/pg{book_id}"
        os.makedirs(book_dir, exist_ok=True)

        # Download with specific filename format (prefer HTML)
        filename = f"pg{book_id}-images.html"
        result = downloader.download_book(
            book_id=book_id,
            output_dir=book_dir,
            preferred_format="html",  # Prefer HTML for audiobook processing
            custom_filename=filename
        )

        if result:
            print(f"Successfully downloaded pg{book_id} to {result}")
            return True
        else:
            print(f"Failed to download pg{book_id}")
            return False

    except Exception as e:
        print(f"Error downloading pg{book_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download books from Project Gutenberg",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "book_id", 
        type=int, 
        help="Project Gutenberg book ID to download"
    )
    parser.add_argument(
        "--format", 
        help="Preferred format (txt, epub, pdf, html, mobi)"
    )
    parser.add_argument(
        "--output-dir", 
        default=".",
        help="Directory to save downloaded books (default: current directory)"
    )
    parser.add_argument(
        "--filename", 
        help="Custom filename for downloaded book"
    )
    parser.add_argument(
        "--list-formats", 
        action="store_true",
        help="List available formats without downloading"
    )
    parser.add_argument(
        "--all-formats", 
        action="store_true",
        help="Download all available formats"
    )
    
    args = parser.parse_args()
    
    downloader = GutenbergDownloader()
    
    try:
        if args.list_formats:
            # Just list available formats
            downloader.list_formats(args.book_id)
            return 0
        
        if args.all_formats:
            # Download all formats
            files = downloader.download_multiple_formats(args.book_id, args.output_dir)
            if files:
                print(f"\nSuccessfully downloaded {len(files)} files:")
                for file in files:
                    print(f"  - {file}")
                return 0
            else:
                print("No files were downloaded")
                return 1
        else:
            # Download single format
            result = downloader.download_book(
                args.book_id, 
                args.output_dir, 
                args.format,
                args.filename
            )
            
            if result:
                print(f"\nDownload completed successfully: {result}")
                return 0
            else:
                print("Download failed")
                return 1
                
    except KeyboardInterrupt:
        print("\nDownload cancelled by user")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())