#!/usr/bin/env python3
"""
Step 1: Rule-based trajectory filtering.

Filters trajectories based on quantitative criteria:
- similarity > threshold
- turn count > 0

Can be run independently or as part of the pipeline.
"""

import json
import glob
import os
import shutil
from typing import List, Dict, Optional
from tqdm import tqdm


def filter_trajectories(
    input_dir: str = "data/processed/interactions",
    output_dir: str = "data/filtered/high_quality",
    min_similarity: float = 0.95,
    min_turns: int = 1,
    copy_files: bool = False
) -> List[Dict]:
    """
    Filter trajectories based on quality criteria.
    
    Args:
        input_dir: Directory containing .turn_based.json files
        output_dir: Directory to copy filtered files (if copy_files=True)
        min_similarity: Minimum similarity threshold (exclusive)
        min_turns: Minimum number of turns (exclusive)
        copy_files: Whether to copy filtered files to output_dir
    
    Returns:
        List of filtered file info dictionaries
    """
    files = glob.glob(os.path.join(input_dir, "*.turn_based.json"))
    
    print(f"Scanning {len(files)} files...")
    print(f"Criteria: similarity > {min_similarity}, turns > {min_turns - 1}")
    print()
    
    filtered = []
    
    for fpath in tqdm(files, desc="Filtering", unit="file"):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            turns = data.get('turns', [])
            verification = data.get('verification', {})
            
            if len(turns) <= (min_turns - 1):
                continue
            
            sim = verification.get('similarity', 0)
            if sim <= min_similarity:
                continue
            
            filtered.append({
                'path': fpath,
                'filename': os.path.basename(fpath),
                'turns': len(turns),
                'similarity': sim,
                'perfect_match': verification.get('perfect_match', False)
            })
            
        except Exception as e:
            pass  # Silent errors during progress bar
    
    print(f"\nFiltered: {len(filtered)} / {len(files)} files")
    
    if copy_files and filtered:
        os.makedirs(output_dir, exist_ok=True)
        print(f"\nCopying to {output_dir}...")
        for item in filtered:
            dst = os.path.join(output_dir, item['filename'])
            shutil.copy2(item['path'], dst)
        print(f"Copied {len(filtered)} files")
    
    return filtered


def save_filtered_list(filtered: List[Dict], output_path: str = "data/filtered/filtered_list.json"):
    """Save the list of filtered files to a JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    summary = {
        'total': len(filtered),
        'total_turns': sum(f['turns'] for f in filtered),
        'perfect_matches': sum(1 for f in filtered if f['perfect_match']),
        'files': [f['filename'] for f in filtered]
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved to {output_path}")
    print(f"  Total: {summary['total']}, Turns: {summary['total_turns']}, Perfect: {summary['perfect_matches']}")
    
    return output_path


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Step 1: Rule-based trajectory filtering')
    parser.add_argument('--input-dir', '-i', default='data/processed/interactions')
    parser.add_argument('--output-dir', '-o', default='data/filtered/high_quality')
    parser.add_argument('--min-similarity', '-s', type=float, default=0.95)
    parser.add_argument('--min-turns', '-t', type=int, default=1)
    parser.add_argument('--copy', '-c', action='store_true')
    parser.add_argument('--save-list', '-l', default='data/filtered/rule_filtered.json')
    
    args = parser.parse_args()
    
    filtered = filter_trajectories(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        min_similarity=args.min_similarity,
        min_turns=args.min_turns,
        copy_files=args.copy
    )
    
    if args.save_list:
        save_filtered_list(filtered, args.save_list)
