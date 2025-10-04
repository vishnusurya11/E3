#!/usr/bin/env python3
"""
Project Gutenberg Bulk Catalog Downloader

This script downloads the complete Project Gutenberg catalog (~76,000 books)
from the official RDF archive and parses all metadata into a single JSON file.

Usage:
    uv run python gutenberg_bulk_downloader.py

Features:
- Downloads official RDF archive (rdf-files.tar.bz2)
- Extracts and parses 76,000+ individual RDF files
- Extracts complete metadata (titles, authors, genres, formats)
- Outputs single consolidated JSON file
- Progress tracking and error handling
- Weekly updates (Project Gutenberg updates daily)

Output:
- gutenberg_complete_catalog.json (all books metadata)
- gutenberg_catalog_summary.txt (statistics)
"""

import argparse
import json
import os
import sys
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

import requests
from tqdm import tqdm


class GutenbergBulkDownloader:
    """Downloads and parses complete Project Gutenberg catalog."""
    
    # Official Project Gutenberg RDF archive URL
    RDF_ARCHIVE_URL = "https://www.gutenberg.org/cache/epub/feeds/rdf-files.tar.bz2"
    
    # XML namespaces used in Project Gutenberg RDF files
    NAMESPACES = {
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'pgterms': 'http://www.gutenberg.org/2009/pgterms/',
        'dcterms': 'http://purl.org/dc/terms/',
        'marcrel': 'http://id.loc.gov/vocabulary/relators/',
        'dcam': 'http://purl.org/dc/dcam/',
    }
    
    def __init__(self, output_dir: str = "."):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Gutenberg-Bulk-Downloader/1.0 (Educational Use)'
        })
        
        # Statistics
        self.stats = {
            'total_files': 0,
            'parsed_books': 0,
            'failed_parses': 0,
            'start_time': None,
            'end_time': None
        }
    
    def download_catalog(self) -> bool:
        """Download the complete RDF archive from Project Gutenberg."""
        archive_path = self.output_dir / "rdf-files.tar.bz2"
        
        print(f"Downloading Project Gutenberg RDF archive...")
        print(f"URL: {self.RDF_ARCHIVE_URL}")
        print(f"Destination: {archive_path}")
        
        try:
            response = self.session.get(self.RDF_ARCHIVE_URL, stream=True, timeout=60)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            
            with open(archive_path, 'wb') as f, tqdm(
                desc="Downloading",
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
            ) as pbar:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))
            
            print(f"Download completed: {archive_path}")
            print(f"File size: {archive_path.stat().st_size:,} bytes")
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"Error downloading archive: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error during download: {e}")
            return False
    
    def extract_archive(self) -> Optional[Path]:
        """Extract the RDF archive to a temporary directory."""
        archive_path = self.output_dir / "rdf-files.tar.bz2"
        
        if not archive_path.exists():
            print(f"Archive not found: {archive_path}")
            return None
        
        print("Extracting RDF archive...")
        
        try:
            # Create temporary directory for extraction
            temp_dir = Path(tempfile.mkdtemp(prefix="gutenberg_rdf_"))
            
            with tarfile.open(archive_path, 'r:bz2') as tar:
                # Get list of members for progress tracking
                members = tar.getmembers()
                self.stats['total_files'] = len(members)
                
                print(f"Extracting {len(members):,} files...")
                
                with tqdm(total=len(members), desc="Extracting") as pbar:
                    for member in members:
                        tar.extract(member, temp_dir)
                        pbar.update(1)
            
            print(f"Extraction completed to: {temp_dir}")
            return temp_dir
            
        except Exception as e:
            print(f"Error extracting archive: {e}")
            return None
    
    def parse_rdf_file(self, rdf_path: Path) -> Optional[Dict[str, Any]]:
        """Parse a single RDF file to extract book metadata."""
        try:
            tree = ET.parse(rdf_path)
            root = tree.getroot()
            
            # Find the ebook element
            ebook = root.find('.//pgterms:ebook', self.NAMESPACES)
            if ebook is None:
                return None
            
            # Extract book ID from rdf:about attribute
            about = ebook.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about', '')
            book_id = None
            if about:
                # Extract ID from URL like "ebooks/12345"
                parts = about.split('/')
                if len(parts) >= 2 and parts[-1].isdigit():
                    book_id = int(parts[-1])
            
            if not book_id:
                return None
            
            # Initialize book metadata with ALL fields
            book_data = {
                'id': book_id,
                'title': '',
                'authors': [],
                'languages': [],
                'subjects': [],
                'bookshelves': [],
                'download_count': 0,
                'formats': {},
                'copyright': False,
                # Date fields
                'issued_date': None,        # dcterms:issued (publication date)
                'created_date': None,       # dcterms:created
                'modified_date': None,      # dcterms:modified
                'publication_year': None,   # Extracted from issued_date
                # Additional metadata
                'description': None,        # dcterms:description
                'alternative_title': None,  # dcterms:alternative
                'extent': None,            # dcterms:extent (file size info)
                'type': None,              # dcterms:type
                'medium': None,            # dcterms:medium
                'hasFormat': [],           # dcterms:hasFormat (related formats)
                'isFormatOf': None,        # dcterms:isFormatOf (original work)
                'publisher': None,         # dcterms:publisher
                'license': None,           # dcterms:license
                'tableOfContents': None    # dcterms:tableOfContents
            }
            
            # Extract title
            title_elem = ebook.find('.//dcterms:title', self.NAMESPACES)
            if title_elem is not None and title_elem.text:
                book_data['title'] = title_elem.text.strip()
            
            # Extract authors
            for creator in ebook.findall('.//dcterms:creator', self.NAMESPACES):
                agent = creator.find('.//pgterms:agent', self.NAMESPACES)
                if agent is not None:
                    name_elem = agent.find('.//pgterms:name', self.NAMESPACES)
                    if name_elem is not None and name_elem.text:
                        # Extract birth/death years if available
                        birth_year = death_year = None
                        
                        birth_elem = agent.find('.//pgterms:birthdate', self.NAMESPACES)
                        death_elem = agent.find('.//pgterms:deathdate', self.NAMESPACES)
                        
                        if birth_elem is not None and birth_elem.text:
                            try:
                                birth_year = int(birth_elem.text)
                            except ValueError:
                                pass
                                
                        if death_elem is not None and death_elem.text:
                            try:
                                death_year = int(death_elem.text)
                            except ValueError:
                                pass
                        
                        book_data['authors'].append({
                            'name': name_elem.text.strip(),
                            'birth_year': birth_year,
                            'death_year': death_year
                        })
            
            # Extract languages
            for language in ebook.findall('.//dcterms:language', self.NAMESPACES):
                value = language.find('.//rdf:value', self.NAMESPACES)
                if value is not None and value.text:
                    book_data['languages'].append(value.text.strip())
            
            # Extract subjects
            for subject in ebook.findall('.//dcterms:subject', self.NAMESPACES):
                value = subject.find('.//rdf:value', self.NAMESPACES)
                if value is not None and value.text:
                    subject_text = value.text.strip()
                    if subject_text and subject_text not in book_data['subjects']:
                        book_data['subjects'].append(subject_text)
            
            # Extract bookshelves
            for bookshelf in ebook.findall('.//pgterms:bookshelf', self.NAMESPACES):
                value = bookshelf.find('.//rdf:value', self.NAMESPACES)
                if value is not None and value.text:
                    shelf_text = value.text.strip()
                    if shelf_text and shelf_text not in book_data['bookshelves']:
                        book_data['bookshelves'].append(shelf_text)
            
            # Extract download count
            downloads = ebook.find('.//pgterms:downloads', self.NAMESPACES)
            if downloads is not None and downloads.text:
                try:
                    book_data['download_count'] = int(downloads.text)
                except ValueError:
                    pass
            
            # Extract file formats
            for file_elem in ebook.findall('.//pgterms:file', self.NAMESPACES):
                file_about = file_elem.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about', '')
                if file_about:
                    # Extract format
                    format_elem = file_elem.find('.//dcterms:format', self.NAMESPACES)
                    if format_elem is not None:
                        format_value = format_elem.find('.//rdf:value', self.NAMESPACES)
                        if format_value is not None and format_value.text:
                            format_type = format_value.text.strip()
                            book_data['formats'][format_type] = file_about
            
            # Extract copyright status (default to public domain)
            rights = ebook.find('.//dcterms:rights', self.NAMESPACES)
            if rights is not None and rights.text:
                copyright_text = rights.text.lower()
                book_data['copyright'] = 'copyright' in copyright_text

            # Extract ALL date fields
            # Publication date (dcterms:issued)
            issued = ebook.find('.//dcterms:issued', self.NAMESPACES)
            if issued is not None and issued.text:
                book_data['issued_date'] = issued.text.strip()
                # Extract publication year
                try:
                    year_text = issued.text.strip()
                    if len(year_text) >= 4 and year_text[:4].isdigit():
                        book_data['publication_year'] = int(year_text[:4])
                except (ValueError, AttributeError):
                    pass

            # Creation date (dcterms:created)
            created = ebook.find('.//dcterms:created', self.NAMESPACES)
            if created is not None and created.text:
                book_data['created_date'] = created.text.strip()

            # Modified date (dcterms:modified)
            modified = ebook.find('.//dcterms:modified', self.NAMESPACES)
            if modified is not None and modified.text:
                book_data['modified_date'] = modified.text.strip()

            # Description (dcterms:description)
            description = ebook.find('.//dcterms:description', self.NAMESPACES)
            if description is not None and description.text:
                book_data['description'] = description.text.strip()

            # Alternative title (dcterms:alternative)
            alternative = ebook.find('.//dcterms:alternative', self.NAMESPACES)
            if alternative is not None and alternative.text:
                book_data['alternative_title'] = alternative.text.strip()

            # Extent (dcterms:extent - file size/length info)
            extent = ebook.find('.//dcterms:extent', self.NAMESPACES)
            if extent is not None and extent.text:
                book_data['extent'] = extent.text.strip()

            # Type (dcterms:type)
            type_elem = ebook.find('.//dcterms:type', self.NAMESPACES)
            if type_elem is not None:
                type_value = type_elem.find('.//rdf:value', self.NAMESPACES)
                if type_value is not None and type_value.text:
                    book_data['type'] = type_value.text.strip()

            # Medium (dcterms:medium)
            medium = ebook.find('.//dcterms:medium', self.NAMESPACES)
            if medium is not None and medium.text:
                book_data['medium'] = medium.text.strip()

            # Publisher (dcterms:publisher)
            publisher = ebook.find('.//dcterms:publisher', self.NAMESPACES)
            if publisher is not None and publisher.text:
                book_data['publisher'] = publisher.text.strip()

            # License (dcterms:license)
            license_elem = ebook.find('.//dcterms:license', self.NAMESPACES)
            if license_elem is not None:
                license_about = license_elem.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource', '')
                if license_about:
                    book_data['license'] = license_about

            # Table of Contents (dcterms:tableOfContents)
            toc = ebook.find('.//dcterms:tableOfContents', self.NAMESPACES)
            if toc is not None and toc.text:
                book_data['tableOfContents'] = toc.text.strip()

            # Has Format (dcterms:hasFormat - related formats)
            for has_format in ebook.findall('.//dcterms:hasFormat', self.NAMESPACES):
                format_about = has_format.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource', '')
                if format_about:
                    book_data['hasFormat'].append(format_about)

            # Is Format Of (dcterms:isFormatOf - original work reference)
            is_format_of = ebook.find('.//dcterms:isFormatOf', self.NAMESPACES)
            if is_format_of is not None:
                original_about = is_format_of.get('{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource', '')
                if original_about:
                    book_data['isFormatOf'] = original_about

            return book_data
            
        except ET.ParseError as e:
            print(f"XML parse error in {rdf_path}: {e}")
            return None
        except Exception as e:
            print(f"Error parsing {rdf_path}: {e}")
            return None
    
    def parse_all_rdf_files(self, rdf_dir: Path) -> List[Dict[str, Any]]:
        """Parse all RDF files in the extracted directory."""
        print("Parsing RDF files...")
        
        # Find all .rdf files
        rdf_files = list(rdf_dir.rglob("*.rdf"))
        print(f"Found {len(rdf_files):,} RDF files")
        
        books = []
        
        with tqdm(total=len(rdf_files), desc="Parsing RDF files") as pbar:
            for rdf_file in rdf_files:
                book_data = self.parse_rdf_file(rdf_file)
                if book_data:
                    books.append(book_data)
                    self.stats['parsed_books'] += 1
                else:
                    self.stats['failed_parses'] += 1
                
                pbar.update(1)
        
        print(f"Successfully parsed {self.stats['parsed_books']:,} books")
        print(f"Failed to parse {self.stats['failed_parses']:,} files")
        
        # Sort books by ID
        books.sort(key=lambda x: x['id'])
        
        return books
    
    def save_catalog(self, books: List[Dict[str, Any]], filename: str = "gutenberg_complete_catalog.json"):
        """Save the complete catalog to JSON file."""
        output_path = self.output_dir / filename
        
        print(f"Saving catalog to {output_path}")
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(books, f, indent=2, ensure_ascii=False)
            
            print(f"Catalog saved: {output_path}")
            print(f"File size: {output_path.stat().st_size:,} bytes")
            print(f"Total books: {len(books):,}")
            
        except Exception as e:
            print(f"Error saving catalog: {e}")
    
    def save_summary(self, books: List[Dict[str, Any]]):
        """Save a summary of the catalog statistics."""
        summary_path = self.output_dir / "gutenberg_catalog_summary.txt"
        
        # Calculate statistics
        total_books = len(books)
        languages = set()
        subjects = set()
        bookshelves = set()
        total_downloads = 0
        format_counts = {}
        
        for book in books:
            languages.update(book.get('languages', []))
            subjects.update(book.get('subjects', []))
            bookshelves.update(book.get('bookshelves', []))
            total_downloads += book.get('download_count', 0)
            
            for format_type in book.get('formats', {}).keys():
                format_counts[format_type] = format_counts.get(format_type, 0) + 1
        
        # Create summary
        summary = f"""Project Gutenberg Catalog Summary
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

CATALOG STATISTICS:
==================
Total Books: {total_books:,}
Total Downloads: {total_downloads:,}
Unique Languages: {len(languages):,}
Unique Subjects: {len(subjects):,}
Unique Bookshelves: {len(bookshelves):,}

PROCESSING STATISTICS:
=====================
Total RDF Files: {self.stats['total_files']:,}
Successfully Parsed: {self.stats['parsed_books']:,}
Failed to Parse: {self.stats['failed_parses']:,}
Success Rate: {(self.stats['parsed_books'] / max(self.stats['total_files'], 1)) * 100:.1f}%

TIMING:
=======
Start Time: {self.stats['start_time']}
End Time: {self.stats['end_time']}
Duration: {self.stats['end_time'] - self.stats['start_time'] if self.stats['end_time'] and self.stats['start_time'] else 'Unknown'}

TOP LANGUAGES:
==============
"""
        
        # Add language distribution
        language_counts = {}
        for book in books:
            for lang in book.get('languages', []):
                language_counts[lang] = language_counts.get(lang, 0) + 1
        
        for lang, count in sorted(language_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            summary += f"{lang}: {count:,} books\n"
        
        summary += f"\nTOP FORMATS:\n============\n"
        for format_type, count in sorted(format_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            summary += f"{format_type}: {count:,} books\n"
        
        # Save summary
        try:
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(summary)
            print(f"Summary saved: {summary_path}")
        except Exception as e:
            print(f"Error saving summary: {e}")
    
    def cleanup_temp_files(self, temp_dir: Path):
        """Clean up temporary extracted files."""
        if temp_dir and temp_dir.exists():
            print("Cleaning up temporary files...")
            try:
                import shutil
                shutil.rmtree(temp_dir)
                print("Cleanup completed")
            except Exception as e:
                print(f"Error during cleanup: {e}")
    
    def run_complete_download(self, cleanup: bool = True):
        """Run the complete download and parsing process."""
        print("=" * 60)
        print("Project Gutenberg Complete Catalog Download")
        print("=" * 60)
        
        self.stats['start_time'] = datetime.now()
        temp_dir = None
        
        try:
            # Step 1: Download archive
            if not self.download_catalog():
                return False
            
            # Step 2: Extract archive
            temp_dir = self.extract_archive()
            if not temp_dir:
                return False
            
            # Step 3: Parse all RDF files
            books = self.parse_all_rdf_files(temp_dir)
            
            if not books:
                print("No books found in archive!")
                return False
            
            # Step 4: Save results
            self.save_catalog(books)
            
            # Step 5: Generate summary
            self.save_summary(books)
            
            self.stats['end_time'] = datetime.now()
            
            print("\n" + "=" * 60)
            print("DOWNLOAD COMPLETED SUCCESSFULLY!")
            print("=" * 60)
            print(f"Total books processed: {len(books):,}")
            print(f"Output file: gutenberg_complete_catalog.json")
            print(f"Summary file: gutenberg_catalog_summary.txt")
            print(f"Duration: {self.stats['end_time'] - self.stats['start_time']}")
            
            return True
            
        except KeyboardInterrupt:
            print("\nDownload cancelled by user")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False
        finally:
            if cleanup and temp_dir:
                self.cleanup_temp_files(temp_dir)


def run_bulk_download_as_function(output_dir: str = "temp_gutenberg", cleanup: bool = True) -> bool:
    """
    Run the bulk download process as a callable function (for gutenberg_cli.py).

    Args:
        output_dir: Directory to save downloaded files
        cleanup: Whether to clean up temporary files

    Returns:
        bool: True if download and parsing completed successfully
    """
    try:
        downloader = GutenbergBulkDownloader(output_dir)
        success = downloader.run_complete_download(cleanup=cleanup)
        return success
    except Exception as e:
        print(f"Error in bulk download function: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download complete Project Gutenberg catalog",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--output-dir",
        default=".",
        help="Output directory for downloaded files (default: current directory)"
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep temporary extracted files (for debugging)"
    )

    args = parser.parse_args()

    downloader = GutenbergBulkDownloader(args.output_dir)

    success = downloader.run_complete_download(cleanup=not args.no_cleanup)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())