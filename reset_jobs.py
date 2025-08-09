"""
Quick utility to reset jobs in the database.
Run this to clear failed jobs and allow them to be reprocessed.
"""

import sqlite3
import sys

def reset_failed_jobs(db_path='database/comfyui_agent.db'):
    """Reset all failed jobs to pending status."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Show current jobs
    cursor.execute("SELECT id, config_name, status, retries_attempted, retry_limit FROM jobs")
    jobs = cursor.fetchall()
    
    print("Current jobs in database:")
    print("-" * 80)
    for job in jobs:
        print(f"ID: {job[0]}, File: {job[1]}, Status: {job[2]}, Retries: {job[3]}/{job[4]}")
    print("-" * 80)
    
    # Reset failed jobs
    cursor.execute("""
        UPDATE jobs 
        SET status='pending', 
            retries_attempted=0,
            start_time=NULL,
            end_time=NULL,
            error_trace=NULL,
            worker_id=NULL,
            lease_expires_at=NULL
        WHERE status='failed'
    """)
    
    rows_updated = cursor.rowcount
    conn.commit()
    
    if rows_updated > 0:
        print(f"\n✅ Reset {rows_updated} failed job(s) to pending status")
    else:
        print("\n✅ No failed jobs to reset")
    
    # Show updated status
    cursor.execute("SELECT id, config_name, status FROM jobs WHERE status='pending'")
    pending = cursor.fetchall()
    
    if pending:
        print("\nJobs ready to process:")
        for job in pending:
            print(f"  - ID {job[0]}: {job[1]}")
    
    conn.close()

def clear_all_jobs(db_path='database/comfyui_agent.db'):
    """Clear all jobs from database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM jobs")
    rows_deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"✅ Cleared {rows_deleted} job(s) from database")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--clear-all":
        clear_all_jobs()
    else:
        reset_failed_jobs()
        print("\nTip: Use 'python reset_jobs.py --clear-all' to remove all jobs")