#!/usr/bin/env python3
"""
Cast File Random Sampling

Randomly samples cast files from each version category (v1, v2, v3)
and copies them to the samples directory for testing.
"""

import os
import sys
import shutil
import random
from typing import Dict, List

# Add current directory to path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detect_version import detect_version


def scan_all_files(cast_dir: str, limit: int = None) -> Dict[str, List[str]]:
    """
    Scan all cast files and categorize by version.
    
    Args:
        cast_dir: Directory containing cast files
        limit: Maximum total files to scan (for faster testing)
    
    Returns:
        Dictionary with 'v1', 'v2', 'v3', 'unknown' keys
    """
    results = {'v1': [], 'v2': [], 'v3': [], 'unknown': []}
    count = 0
    
    print(f"Scanning cast files in {cast_dir}...")
    
    for entry in os.scandir(cast_dir):
        if entry.is_file() and entry.name.endswith('.cast'):
            version, _ = detect_version(entry.path)
            
            if version == 1:
                results['v1'].append(entry.path)
            elif version == 2:
                results['v2'].append(entry.path)
            elif version == 3:
                results['v3'].append(entry.path)
            else:
                results['unknown'].append(entry.path)
            
            count += 1
            if count % 1000 == 0:
                print(f"  Scanned {count} files...")
            
            if limit and count >= limit:
                break
    
    print(f"Scan complete: {count} total files")
    print(f"  v1: {len(results['v1'])}, v2: {len(results['v2'])}, v3: {len(results['v3'])}, unknown: {len(results['unknown'])}")
    
    return results


def sample_files(files: List[str], n: int, seed: int = 42) -> List[str]:
    """
    Randomly sample n files from a list.
    
    Args:
        files: List of file paths
        n: Number of files to sample
        seed: Random seed for reproducibility
    
    Returns:
        List of sampled file paths
    """
    random.seed(seed)
    
    if len(files) <= n:
        return files
    
    return random.sample(files, n)


def copy_samples(file_paths: List[str], dest_dir: str, version_label: str):
    """
    Copy sampled files to destination directory.
    
    Args:
        file_paths: List of source file paths
        dest_dir: Destination directory
        version_label: Version label for subdirectory (v1, v2, v3)
    """
    target_dir = os.path.join(dest_dir, version_label)
    os.makedirs(target_dir, exist_ok=True)
    
    for src in file_paths:
        filename = os.path.basename(src)
        dst = os.path.join(target_dir, filename)
        shutil.copy2(src, dst)
    
    print(f"Copied {len(file_paths)} files to {target_dir}")


def create_manifest(results: Dict[str, List[str]], output_path: str):
    """
    Create a manifest file listing all sampled files.
    """
    import json
    
    manifest = {
        'v1': [os.path.basename(f) for f in results.get('v1', [])],
        'v2': [os.path.basename(f) for f in results.get('v2', [])],
        'v3': [os.path.basename(f) for f in results.get('v3', [])],
        'statistics': {
            'v1_count': len(results.get('v1', [])),
            'v2_count': len(results.get('v2', [])),
            'v3_count': len(results.get('v3', [])),
        }
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"Manifest saved to {output_path}")


def main(cast_dir: str, output_dir: str, n_per_version: int = 50, 
         scan_limit: int = None, seed: int = 42):
    """
    Main sampling function.
    
    Args:
        cast_dir: Source directory with cast files
        output_dir: Destination directory for samples
        n_per_version: Number of files to sample per version
        scan_limit: Limit total files to scan (None for all)
        seed: Random seed
    """
    # Scan and categorize files
    categorized = scan_all_files(cast_dir, scan_limit)
    
    # Sample files
    sampled = {
        'v1': sample_files(categorized['v1'], n_per_version, seed),
        'v2': sample_files(categorized['v2'], n_per_version, seed),
        'v3': sample_files(categorized['v3'], n_per_version, seed),
    }
    
    print(f"\nSampled files:")
    print(f"  v1: {len(sampled['v1'])} (of {len(categorized['v1'])} available)")
    print(f"  v2: {len(sampled['v2'])} (of {len(categorized['v2'])} available)")
    print(f"  v3: {len(sampled['v3'])} (of {len(categorized['v3'])} available)")
    
    # Create output directories and copy files
    samples_dir = os.path.join(output_dir, 'samples')
    os.makedirs(samples_dir, exist_ok=True)
    
    for version in ['v1', 'v2', 'v3']:
        if sampled[version]:
            copy_samples(sampled[version], samples_dir, version)
    
    # Create manifest
    create_manifest(sampled, os.path.join(samples_dir, 'manifest.json'))
    
    print(f"\nSampling complete! Files saved to {samples_dir}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Sample cast files by version')
    parser.add_argument('--cast-dir', default='../cast', help='Source cast directory')
    parser.add_argument('--output-dir', default='.', help='Output directory')
    parser.add_argument('--n', type=int, default=50, help='Files per version')
    parser.add_argument('--scan-limit', type=int, help='Limit files to scan')
    parser.add_argument('--seed', type=int, default=42, help='Random seed')
    
    args = parser.parse_args()
    
    cast_dir = os.path.abspath(args.cast_dir)
    output_dir = os.path.abspath(args.output_dir)
    
    if not os.path.isdir(cast_dir):
        print(f"Error: Cast directory not found: {cast_dir}")
        sys.exit(1)
    
    main(cast_dir, output_dir, args.n, args.scan_limit, args.seed)
