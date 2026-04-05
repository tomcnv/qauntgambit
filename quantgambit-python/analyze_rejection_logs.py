#!/usr/bin/env python3
"""Analyze rejection logs from replay to verify all categories are captured."""

import re
import sys
from collections import Counter
from pathlib import Path


def analyze_rejection_logs(log_file: Path):
    """Analyze rejection logs to categorize rejection reasons."""
    
    if not log_file.exists():
        print(f"Error: Log file not found: {log_file}", file=sys.stderr)
        return 1
    
    # Rejection categories we're looking for (Requirements 7.1, 7.2, 7.3, 7.4)
    categories = {
        "atr_rejection": 0,
        "poc_distance_rejection": 0,
        "rotation_rejection": 0,
        "spread_rejection": 0,
        "other_rejection": 0,
    }
    
    # Patterns to match rejection reasons
    patterns = {
        "atr_rejection": [
            r"ATR ratio (too high|below expansion threshold|above expansion threshold)",
            r"atr_ratio=[\d.]+.*max_atr_ratio=[\d.]+",
            r"atr_ratio=[\d.]+.*expansion_threshold=[\d.]+",
        ],
        "poc_distance_rejection": [
            r"POC distance too small",
            r"poc_distance_pct=[\d.]+.*min_distance=[\d.]+",
        ],
        "rotation_rejection": [
            r"rotation not reversing",
            r"rotation=[\d.-]+.*min_rotation=[\d.]+",
            r"rotation=[\d.-]+.*rotation_threshold=[\d.]+",
            r"no breakout conditions met.*rotation=",
        ],
        "spread_rejection": [
            r"spread too wide",
            r"spread=[\d.]+.*max_spread=[\d.]+",
        ],
    }
    
    # Read log file and categorize rejections
    total_lines = 0
    rejection_lines = 0
    
    with log_file.open("r") as f:
        for line in f:
            total_lines += 1
            
            # Check if this is a rejection log line
            if "Rejecting" not in line:
                continue
            
            rejection_lines += 1
            
            # Try to categorize the rejection
            categorized = False
            for category, pattern_list in patterns.items():
                for pattern in pattern_list:
                    if re.search(pattern, line, re.IGNORECASE):
                        categories[category] += 1
                        categorized = True
                        break
                if categorized:
                    break
            
            if not categorized:
                categories["other_rejection"] += 1
    
    # Print results
    print("\n=== Rejection Logging Analysis ===")
    print(f"Total log lines: {total_lines}")
    print(f"Rejection log lines: {rejection_lines}")
    print()
    
    print("=== Rejection Categories (Requirements 7.1-7.4) ===")
    for category, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
        if count > 0:
            pct = (count / rejection_lines * 100) if rejection_lines > 0 else 0
            print(f"{category}: {count} ({pct:.1f}%)")
    
    # Verify all required categories are present
    print("\n=== Verification ===")
    required_categories = ["atr_rejection", "poc_distance_rejection", "rotation_rejection", "spread_rejection"]
    all_present = True
    
    for category in required_categories:
        if categories[category] > 0:
            print(f"✓ {category}: FOUND ({categories[category]} instances)")
        else:
            print(f"✗ {category}: NOT FOUND")
            all_present = False
    
    if all_present:
        print("\n✓ SUCCESS: All rejection categories are being logged")
        return 0
    else:
        print("\n✗ FAILURE: Some rejection categories are missing")
        return 1


if __name__ == "__main__":
    log_file = Path("/tmp/sample_replay.log")
    sys.exit(analyze_rejection_logs(log_file))
