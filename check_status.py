"""
Quick diagnostic tool to check E3 ComfyUI Agent status.
Shows what's in the database and tests ComfyUI connection.
"""

import sqlite3
import httpx
import os
import sys

def check_database(db_path='database/comfyui_agent.db'):
    """Check database contents."""
    print("\n=== DATABASE STATUS ===")
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check jobs
    cursor.execute("SELECT COUNT(*) FROM jobs")
    total = cursor.fetchone()[0]
    print(f"Total jobs: {total}")
    
    # Check by status
    cursor.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
    status_counts = cursor.fetchall()
    
    for status, count in status_counts:
        emoji = {"pending": "⏳", "processing": "🔄", "done": "✅", "failed": "❌"}.get(status, "❓")
        print(f"  {emoji} {status}: {count}")
    
    # Show all jobs
    print("\nAll jobs:")
    cursor.execute("""
        SELECT id, config_name, status, workflow_id, priority, 
               retries_attempted, retry_limit, error_trace
        FROM jobs
        ORDER BY id
    """)
    jobs = cursor.fetchall()
    
    for job in jobs:
        print(f"\nJob #{job[0]}: {job[1]}")
        print(f"  Status: {job[2]}")
        print(f"  Workflow: {job[3]}")
        print(f"  Priority: {job[4]}")
        print(f"  Retries: {job[5]}/{job[6]}")
        if job[7]:
            print(f"  Error: {job[7][:100]}...")
    
    conn.close()

def check_comfyui(url='http://127.0.0.1:8000'):
    """Test ComfyUI connection."""
    print(f"\n=== COMFYUI CONNECTION TEST ===")
    print(f"Testing: {url}")
    
    try:
        # Try system_stats endpoint
        with httpx.Client() as client:
            response = client.get(f"{url}/system_stats", timeout=2.0)
            if response.status_code == 200:
                print(f"✅ ComfyUI is running at {url}")
                stats = response.json()
                print(f"  System info: {stats.get('system', {}).get('os', 'Unknown OS')}")
                return True
            else:
                print(f"⚠️ ComfyUI responded with status {response.status_code}")
    except httpx.ConnectError:
        print(f"❌ Cannot connect to ComfyUI at {url}")
        print("  Make sure ComfyUI is running: python main.py --port 8000")
    except Exception as e:
        print(f"❌ Error connecting to ComfyUI: {e}")
    
    return False

def check_yaml_files(processing_dir='comfyui_jobs/processing'):
    """Check for YAML files in processing directory."""
    print(f"\n=== YAML FILES ===")
    
    if not os.path.exists(processing_dir):
        print(f"❌ Processing directory not found: {processing_dir}")
        return
    
    yaml_count = 0
    for root, dirs, files in os.walk(processing_dir):
        for file in files:
            if file.endswith('.yaml') or file.endswith('.yml'):
                yaml_count += 1
                rel_path = os.path.relpath(os.path.join(root, file), processing_dir)
                print(f"  📄 {rel_path}")
    
    if yaml_count == 0:
        print("  No YAML files found in processing directory")
    else:
        print(f"\nTotal: {yaml_count} YAML file(s)")

def main():
    print("E3 ComfyUI Agent - System Check")
    print("=" * 40)
    
    # Load config to get actual URLs
    try:
        import yaml
        with open('comfyui_agent/config/global_config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        comfyui_url = config['comfyui']['api_base_url']
        db_path = config['paths']['database']
    except:
        comfyui_url = 'http://127.0.0.1:8000'
        db_path = 'database/comfyui_agent.db'
    
    check_database(db_path)
    check_yaml_files()
    check_comfyui(comfyui_url)
    
    print("\n" + "=" * 40)
    print("Check complete!")

if __name__ == "__main__":
    main()