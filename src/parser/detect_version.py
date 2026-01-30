#!/usr/bin/env python3
"""
Cast File Version Detection

Detects the version of asciinema cast files:
- v1: Standard JSON with stdout array
- v2: NDJSON with absolute timestamps
- v3: NDJSON with relative timestamps and term object
"""

import json
import os
import sys
from typing import Optional, Tuple, Dict


def detect_version(file_path: str) -> Tuple[Optional[int], Dict]:
    """
    Detect the version of a cast file.
    
    Args:
        file_path: Path to the cast file
        
    Returns:
        (version, metadata) tuple where version is 1, 2, 3 or None if unknown
    """
    metadata = {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
            if not content.strip():
                return None, {'error': 'Empty file'}
            
            # Try parsing as standard JSON first (v1 format)
            try:
                data = json.loads(content)
                if isinstance(data, dict) and 'stdout' in data:
                    # v1 format: standard JSON with stdout array
                    metadata = {
                        'width': data.get('width', 80),
                        'height': data.get('height', 24),
                        'duration': data.get('duration', 0),
                        'command': data.get('command', ''),
                        'title': data.get('title', ''),
                        'env': data.get('env', {}),
                        'stdout_count': len(data.get('stdout', []))
                    }
                    return 1, metadata
            except json.JSONDecodeError:
                pass  # Not standard JSON, try NDJSON
            
            # Try NDJSON format (v2/v3)
            first_line = content.split('\n')[0].strip()
            if not first_line:
                return None, {'error': 'Empty first line'}
            
            try:
                data = json.loads(first_line)
            except json.JSONDecodeError:
                return None, {'error': 'Invalid JSON in first line'}
            
            if not isinstance(data, dict):
                return None, {'error': 'First line is not a JSON object'}
            
            # Check version field
            version = data.get('version')
            
            if version == 2:
                metadata = {
                    'width': data.get('width', 80),
                    'height': data.get('height', 24),
                    'timestamp': data.get('timestamp'),
                    'duration': data.get('duration'),
                    'env': data.get('env', {})
                }
                return 2, metadata
            
            elif version == 3:
                term = data.get('term', {})
                metadata = {
                    'width': term.get('cols', 80),
                    'height': term.get('rows', 24),
                    'term_type': term.get('type', ''),
                    'term_version': term.get('version', ''),
                    'theme': term.get('theme', {}),
                    'timestamp': data.get('timestamp'),
                    'env': data.get('env', {})
                }
                return 3, metadata
            
            # No version field but looks like v2 header (older v2 files)
            if 'width' in data and 'height' in data:
                # Check second line to confirm NDJSON format
                lines = content.split('\n')
                if len(lines) > 1:
                    second_line = lines[1].strip()
                    if second_line:
                        try:
                            event = json.loads(second_line)
                            if isinstance(event, list) and len(event) >= 3:
                                metadata = {
                                    'width': data.get('width', 80),
                                    'height': data.get('height', 24),
                                    'env': data.get('env', {})
                                }
                                return 2, metadata
                        except json.JSONDecodeError:
                            pass
    
    except Exception as e:
        return None, {'error': str(e)}
    
    return None, {'error': 'Unknown format'}


def detect_version_batch(file_paths: list) -> Dict[str, list]:
    """
    Detect versions for multiple files.
    
    Returns:
        Dictionary with keys 'v1', 'v2', 'v3', 'unknown' containing file paths
    """
    results = {'v1': [], 'v2': [], 'v3': [], 'unknown': []}
    
    for path in file_paths:
        version, _ = detect_version(path)
        if version == 1:
            results['v1'].append(path)
        elif version == 2:
            results['v2'].append(path)
        elif version == 3:
            results['v3'].append(path)
        else:
            results['unknown'].append(path)
    
    return results


def scan_directory(directory: str, limit: int = None) -> Dict[str, list]:
    """
    Scan a directory for cast files and detect their versions.
    
    Args:
        directory: Path to directory containing cast files
        limit: Maximum number of files to scan (None for all)
    
    Returns:
        Dictionary with version statistics
    """
    cast_files = []
    
    for entry in os.scandir(directory):
        if entry.is_file() and entry.name.endswith('.cast'):
            cast_files.append(entry.path)
            if limit and len(cast_files) >= limit:
                break
    
    return detect_version_batch(cast_files)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Detect cast file version')
    parser.add_argument('path', help='Cast file or directory path')
    parser.add_argument('--limit', type=int, help='Limit files to scan in directory mode')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed info')
    
    args = parser.parse_args()
    
    if os.path.isfile(args.path):
        version, metadata = detect_version(args.path)
        if version:
            print(f"Version: v{version}")
            if args.verbose:
                print(f"Metadata: {json.dumps(metadata, indent=2)}")
        else:
            print(f"Unknown format: {metadata.get('error', 'Unknown error')}")
    
    elif os.path.isdir(args.path):
        results = scan_directory(args.path, args.limit)
        print(f"Version statistics:")
        print(f"  v1: {len(results['v1'])} files")
        print(f"  v2: {len(results['v2'])} files")
        print(f"  v3: {len(results['v3'])} files")
        print(f"  unknown: {len(results['unknown'])} files")
        
        if args.verbose and results['unknown']:
            print(f"\nUnknown files: {results['unknown'][:10]}")
    else:
        print(f"Error: Path not found: {args.path}")
        sys.exit(1)
