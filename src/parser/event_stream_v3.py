#!/usr/bin/env python3
"""
V3 Format Event Stream Extraction

Extracts raw event stream from v3 format cast files (NDJSON with relative timestamps).
Preserves all events with timestamps for maximum fidelity.
"""

import json
import sys
import os
from typing import Dict, List, Optional, Tuple


def parse_v3_to_events(file_path: str) -> Tuple[Dict, List[Dict]]:
    """
    Parse v3 format cast file to normalized event list.
    
    v3 format is NDJSON with:
    - First line: header with version:3, term object, etc.
    - Following lines: [interval, type, data] arrays with relative timestamps
    
    Returns:
        (metadata, events) tuple where events have absolute timestamps
    """
    metadata = {}
    events = []
    current_time = 0.0
    
    # Event type mapping
    type_map = {
        'i': 'input',
        'o': 'output',
        'm': 'marker',
        'r': 'resize',
        'x': 'exit'  # v3 specific
    }
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            if isinstance(data, dict):
                # Header line
                term = data.get('term', {})
                metadata = {
                    'version': 3,
                    'width': term.get('cols', 80),
                    'height': term.get('rows', 24),
                    'term_type': term.get('type', ''),
                    'term_version': term.get('version', ''),
                    'theme': term.get('theme', {}),
                    'timestamp': data.get('timestamp'),
                    'env': data.get('env', {}),
                    'idle_time_limit': data.get('idle_time_limit'),
                    'command': data.get('command', ''),
                    'title': data.get('title', '')
                }
            
            elif isinstance(data, list) and len(data) >= 3:
                # Event line: [interval, type, data]
                interval, event_type, content = data[0], data[1], data[2]
                
                # v3 uses relative timestamps (intervals)
                current_time += interval
                normalized_type = type_map.get(event_type, event_type)
                
                events.append({
                    't': round(current_time, 6),
                    'type': normalized_type,
                    'data': content
                })
    
    return metadata, events


def extract_to_event_stream_v3(file_path: str, output_path: Optional[str] = None) -> Dict:
    """
    Extract v3 cast file to event stream format.
    
    Args:
        file_path: Path to the v3 .cast file
        output_path: Optional output path for JSON
    
    Returns:
        The extracted data structure
    """
    metadata, events = parse_v3_to_events(file_path)
    
    # Calculate statistics
    input_count = sum(1 for e in events if e['type'] == 'input')
    output_count = sum(1 for e in events if e['type'] == 'output')
    marker_count = sum(1 for e in events if e['type'] == 'marker')
    resize_count = sum(1 for e in events if e['type'] == 'resize')
    exit_count = sum(1 for e in events if e['type'] == 'exit')
    
    if events:
        total_duration = events[-1]['t']
    else:
        total_duration = 0
    
    result = {
        'metadata': {
            'version': 3,
            'width': metadata.get('width', 80),
            'height': metadata.get('height', 24),
            'shell': metadata.get('env', {}).get('SHELL', '/bin/bash'),
            'command': metadata.get('command', ''),
            'title': metadata.get('title', ''),
            'env': metadata.get('env', {}),
            'term_info': {
                'type': metadata.get('term_type', ''),
                'version': metadata.get('term_version', ''),
                'theme': metadata.get('theme', {})
            },
            'source_file': os.path.basename(file_path)
        },
        'statistics': {
            'total_events': len(events),
            'input_events': input_count,
            'output_events': output_count,
            'marker_events': marker_count,
            'resize_events': resize_count,
            'exit_events': exit_count,
            'total_duration_seconds': round(total_duration, 2)
        },
        'events': events
    }
    
    if output_path is None:
        output_path = os.path.splitext(file_path)[0] + '.event_stream.json'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"V3 event stream extraction complete: {output_path}")
    print(f"  - Total events: {len(events)} (input: {input_count}, output: {output_count})")
    print(f"  - Duration: {total_duration:.2f}s")
    
    return result


def process_directory(target_path: str):
    """Process all v3 cast files in a directory."""
    for entry in os.scandir(target_path):
        if entry.is_file() and entry.name.endswith('.cast'):
            try:
                extract_to_event_stream_v3(entry.path)
            except Exception as e:
                print(f"Error processing {entry.path}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_v3_event_stream.py <cast_file_or_directory>")
        sys.exit(1)
    
    target_path = sys.argv[1]
    
    if not os.path.exists(target_path):
        print(f"Error: Path not found: {target_path}")
        sys.exit(1)
    
    if os.path.isfile(target_path):
        extract_to_event_stream_v3(target_path)
    else:
        process_directory(target_path)
