#!/usr/bin/env python
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DIR = os.path.join(BASE_DIR, "data", "live")
SHADOW_FEEDBACK_DIR = os.path.join(BASE_DIR, "data", "shadow_feedback")
SHADOW_MEMORY_DIR = os.path.join(BASE_DIR, "data", "shadow_memory")
SHADOW_LEARNING_DIR = os.path.join(BASE_DIR, "data", "shadow_learning")

def clean_directory_contents(dir_path):
    if not os.path.exists(dir_path):
        print(f"Directory {dir_path} does not exist, skipping.")
        return
    
    print(f"Cleaning contents of {dir_path}...")
    for item in os.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        try:
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
                print(f"  Removed directory: {item}")
            else:
                os.remove(item_path)
                print(f"  Removed file: {item}")
        except Exception as e:
            print(f"  Error removing {item}: {e}")

def main():
    print("========================================================")
    print("  EigenCapital Dashboard & Paper Trading State Reset Tool ")
    print("========================================================")
    
    force = len(sys.argv) > 1 and sys.argv[1] in ("-y", "--yes")
    
    if not force:
        print("\nWARNING: This will permanently delete:")
        print("  - All trading logs, states, and history (state.json, trade_journal, equity_history)")
        print("  - Cached prices, snapshots, and dashboard metrics")
        print("  - Shadow learning metrics, feedback loops, and shadow memories")
        print("\nMake sure the paper trading engine/monitor is NOT running before proceeding!\n")
        
        confirm = input("Are you sure you want to reset everything to a clean slate? (y/N): ").strip().lower()
        if confirm != 'y':
            print("Reset aborted.")
            sys.exit(0)
    
    # 1. Clean data/live
    clean_directory_contents(LIVE_DIR)
    
    # Re-create cache, snapshots, logs directories inside live to ensure they exist
    for sub in ["cache", "snapshots", "logs"]:
        os.makedirs(os.path.join(LIVE_DIR, sub), exist_ok=True)
        print(f"  Created empty folder: data/live/{sub}")
        
    # 2. Clean shadow learning, feedback, and memory
    clean_directory_contents(SHADOW_FEEDBACK_DIR)
    clean_directory_contents(SHADOW_MEMORY_DIR)
    clean_directory_contents(SHADOW_LEARNING_DIR)
    
    print("\n✅ Reset completed successfully! Your paper trading engine and dashboard are now at a clean slate.")

if __name__ == "__main__":
    main()
