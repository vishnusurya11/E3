#!/usr/bin/env python3
"""
Create ComfyUI image job configurations from generated image prompts.
Each image prompt becomes a separate YAML job file for image generation.
"""

import json
import yaml
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Default workflow template
DEFAULT_WORKFLOW_FILE = "workflows/image_qwen_image.json"


def create_image_job(
    book_id: str,
    part_number: int,
    prompt_data: Dict,
    book_metadata: Dict,
    jobs_output_dir: str,
    finished_images_dir: str,
    workflow_template: str
) -> str:
    """
    Create a single YAML job configuration for an image generation prompt.
    
    Args:
        book_id: Book identifier (e.g., 'pg98')
        part_number: Part number (1, 2, etc.)
        prompt_data: Prompt dictionary with text and metadata
        book_metadata: Book-level metadata
        jobs_output_dir: Output directory for YAML files
        finished_images_dir: Directory where finished images will be stored
        workflow_template: Path to ComfyUI workflow JSON template
    
    Returns:
        Path to created YAML file
    """
    # Create clean book ID (remove -images suffix if present)
    clean_book_id = book_id.replace('-images', '')
    
    # Generate filename: T2I_[book]_[part]_prompt[rank].yaml (matching SPEECH pattern)
    filename = f"T2I_{clean_book_id}_{part_number}_prompt{prompt_data['rank']:03d}.yaml"
    
    # Load workflow template
    workflow_file = Path(workflow_template)
    if not workflow_file.exists():
        raise FileNotFoundError(f"Workflow template not found: {workflow_template}")
    
    with open(workflow_file, 'r', encoding='utf-8') as f:
        workflow_config = json.load(f)
    
    # Create job configuration
    job_config = {
        "job_type": "T2I",
        "workflow_id": "image_qwen_image",
        "priority": 6,  # Lower priority than TTS jobs
        "inputs": {
            # Update the text prompt in node 6 (CLIPTextEncode positive)
            "6_text": prompt_data["prompt"],
            # Keep negative prompt empty (node 7)
            "7_text": "",
            # Set output filename prefix
            "60_filename_prefix": f"images/{clean_book_id}/part{part_number}/prompt{prompt_data['rank']}"
        },
        "outputs": {
            "file_path": f"{finished_images_dir}/{clean_book_id}_part{part_number}_prompt{prompt_data['rank']}.png"
        },
        "metadata": {
            "book_title": book_metadata.get("book_title", "Unknown"),
            "book_id": book_id,
            "part_number": part_number,
            "prompt_id": prompt_data["prompt_id"],
            "prompt_rank": prompt_data["rank"],
            "image_filename": prompt_data["filename"],
            "source_prompt": prompt_data["prompt"][:100] + "..." if len(prompt_data["prompt"]) > 100 else prompt_data["prompt"],
            "creator": "Image Job Generator",
            "version": "1.0",
            "created_at": datetime.now().isoformat()
        },
        "workflow": workflow_config
    }
    
    # Save YAML file with UTF-8 encoding
    os.makedirs(jobs_output_dir, exist_ok=True)
    filepath = os.path.join(jobs_output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        yaml.dump(job_config, f, default_flow_style=False, allow_unicode=True)
    
    return filepath


def process_book_image_prompts(
    book_id: str,
    metadata_file_path: str,
    jobs_output_dir: str,
    finished_images_dir: str,
    workflow_template: str = None
) -> Dict:
    """
    Process all image prompts for a book and create ComfyUI job files.
    
    Args:
        book_id: Book identifier
        metadata_file_path: Path to book metadata.json file
        jobs_output_dir: Output directory for YAML job files
        finished_images_dir: Directory where finished images will be stored
        workflow_template: Path to workflow template (optional)
    
    Returns:
        Dict with success status and job creation details
    """
    if workflow_template is None:
        workflow_template = DEFAULT_WORKFLOW_FILE
    
    print(f"\nCreating image generation jobs for book: {book_id}")
    print("=" * 60)
    
    # Read metadata file
    metadata_path = Path(metadata_file_path)
    if not metadata_path.exists():
        return {
            'success': False,
            'error': f'Metadata file not found: {metadata_file_path}'
        }
    
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    
    # Check if image prompts exist
    image_prompts = metadata.get('image_prompts', {})
    if not image_prompts:
        return {
            'success': False,
            'error': 'No image prompts found in metadata'
        }
    
    parts = image_prompts.get('parts', [])
    if not parts:
        return {
            'success': False,
            'error': 'No parts found in image prompts'
        }
    
    print(f"Book: {metadata.get('book_title', 'Unknown')}")
    print(f"Total parts: {len(parts)}")
    
    total_jobs_created = 0
    created_jobs = []
    
    # Process each part
    for part in parts:
        part_number = part['part']
        prompts = part.get('prompts', [])
        
        print(f"\nProcessing Part {part_number}: {len(prompts)} prompts")
        
        for prompt_data in prompts:
            try:
                job_file = create_image_job(
                    book_id=book_id,
                    part_number=part_number,
                    prompt_data=prompt_data,
                    book_metadata=metadata,
                    jobs_output_dir=jobs_output_dir,
                    finished_images_dir=finished_images_dir,
                    workflow_template=workflow_template
                )
                
                created_jobs.append({
                    'part': part_number,
                    'prompt_rank': prompt_data['rank'],
                    'job_file': job_file,
                    'prompt_id': prompt_data['prompt_id']
                })
                total_jobs_created += 1
                
                print(f"  ✓ Created job: {Path(job_file).name}")
                
            except Exception as e:
                print(f"  ✗ Failed to create job for prompt {prompt_data['rank']}: {e}")
                return {
                    'success': False,
                    'error': f'Failed to create job for part {part_number} prompt {prompt_data["rank"]}: {e}'
                }
    
    print(f"\n✓ Image job creation completed!")
    print(f"  Total jobs created: {total_jobs_created}")
    print(f"  Jobs saved to: {jobs_output_dir}")
    
    return {
        'success': True,
        'total_jobs_created': total_jobs_created,
        'created_jobs': created_jobs,
        'jobs_output_dir': jobs_output_dir,
        'finished_images_dir': finished_images_dir
    }


def create_image_jobs_for_book(
    book_id: str,
    base_input_dir: str = "foundry/processing",
    base_jobs_dir: str = "comfyui_jobs",  # Fixed: Use correct ComfyUI jobs directory
    base_output_dir: str = "foundry/finished",
    workflow_template: str = None,
    verbose: bool = True
) -> Dict:
    """
    High-level function to create image jobs for a book.
    
    Args:
        book_id: Book identifier
        base_input_dir: Base directory for processing files
        base_jobs_dir: Base directory for job files
        base_output_dir: Base directory for finished files
        workflow_template: Path to workflow template
        verbose: Enable verbose output
    
    Returns:
        Dict with creation results
    """
    if verbose:
        print(f"Creating image generation jobs for book: {book_id}")
    
    # Set up paths
    metadata_file = f"{base_input_dir}/{book_id}/metadata.json"
    jobs_output_dir = f"{base_jobs_dir}/processing"  # Fixed: Use ComfyUI processing directory
    finished_images_dir = f"{base_output_dir}/images/{book_id}"
    
    # Create output directories
    Path(jobs_output_dir).mkdir(parents=True, exist_ok=True)
    Path(finished_images_dir).mkdir(parents=True, exist_ok=True)
    
    if verbose:
        print(f"  Metadata source: {metadata_file}")
        print(f"  Jobs output: {jobs_output_dir}")
        print(f"  Images output: {finished_images_dir}")
    
    # Process the book
    result = process_book_image_prompts(
        book_id=book_id,
        metadata_file_path=metadata_file,
        jobs_output_dir=jobs_output_dir,
        finished_images_dir=finished_images_dir,
        workflow_template=workflow_template
    )
    
    if verbose and result['success']:
        print(f"\n✅ Image jobs created successfully for {book_id}")
        print(f"   Total jobs: {result['total_jobs_created']}")
    elif verbose:
        print(f"\n❌ Failed to create image jobs for {book_id}: {result['error']}")
    
    return result


if __name__ == "__main__":
    # Example usage
    if len(sys.argv) > 1:
        book_id = sys.argv[1]
        result = create_image_jobs_for_book(book_id)
        if not result['success']:
            sys.exit(1)
    else:
        print("Usage: python3 create_image_jobs.py <book_id>")
        sys.exit(1)