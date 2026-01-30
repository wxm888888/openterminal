#!/usr/bin/env python3
"""
V2 Format Event Stream Extraction

Extracts raw event stream from v2 format cast files (NDJSON with absolute timestamps).
Preserves all events with timestamps for maximum fidelity.
"""

import json
import sys
import os
from typing import Dict, List, Optional, Tuple


def parse_v2_to_events(file_path: str) -> Tuple[Dict, List[Dict]]:
    """
    Parse v2 format cast file to normalized event list.
    
    v2 format is NDJSON with:
    - First line: header with version:2, width, height, etc.
    - Following lines: [time, type, data] arrays with absolute timestamps
    
    Returns:
        (metadata, events) tuple
    """
    metadata = {}
    events = []
    
    # Event type mapping
    type_map = {
        'i': 'input',
        'o': 'output',
        'm': 'marker',
        'r': 'resize'
    }
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                data = json.loads(line)
                
                if isinstance(data, dict):
                    # Header line
                    metadata = {
                        'version': data.get('version', 2),
                        'width': data.get('width', 80),
                        'height': data.get('height', 24),
                        'timestamp': data.get('timestamp'),
                        'duration': data.get('duration'),
                        'idle_time_limit': data.get('idle_time_limit'),
                        'command': data.get('command', ''),
                        'title': data.get('title', ''),
                        'env': data.get('env', {}),
                        'theme': data.get('theme', {})
                    }
                
                elif isinstance(data, list) and len(data) >= 3:
                    timestamp, event_type, content = data[0], data[1], data[2]
                    normalized_type = type_map.get(event_type, event_type)
                    
                    events.append({
                        't': round(timestamp, 6),
                        'type': normalized_type,
                        'data': content
                    })
            
            except json.JSONDecodeError:
                continue
    
    return metadata, events


def extract_to_event_stream_v2(file_path: str, output_path: Optional[str] = None) -> Dict:
    """
    Extract v2 cast file to event stream format.
    
    Args:
        file_path: Path to the v2 .cast file
        output_path: Optional output path for JSON
    
    Returns:
        The extracted data structure
    """
    metadata, events = parse_v2_to_events(file_path)
    
    # Calculate statistics
    input_count = sum(1 for e in events if e['type'] == 'input')
    output_count = sum(1 for e in events if e['type'] == 'output')
    marker_count = sum(1 for e in events if e['type'] == 'marker')
    resize_count = sum(1 for e in events if e['type'] == 'resize')
    
    if events:
        total_duration = events[-1]['t'] - events[0]['t']
    else:
        total_duration = metadata.get('duration', 0) or 0
    
    result = {
        'metadata': {
            'version': 2,
            'width': metadata.get('width', 80),
            'height': metadata.get('height', 24),
            'shell': metadata.get('env', {}).get('SHELL', '/bin/bash'),
            'command': metadata.get('command', ''),
            'title': metadata.get('title', ''),
            'env': metadata.get('env', {}),
            'source_file': os.path.basename(file_path)
        },
        'statistics': {
            'total_events': len(events),
            'input_events': input_count,
            'output_events': output_count,
            'marker_events': marker_count,
            'resize_events': resize_count,
            'total_duration_seconds': round(total_duration, 2)
        },
        'events': events
    }
    
    if output_path is None:
        output_path = os.path.splitext(file_path)[0] + '.event_stream.json'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"V2 event stream extraction complete: {output_path}")
    print(f"  - Total events: {len(events)} (input: {input_count}, output: {output_count})")
    print(f"  - Duration: {total_duration:.2f}s")
    
    return result


def process_directory(target_path: str):
    """Process all v2 cast files in a directory."""
    for entry in os.scandir(target_path):
        if entry.is_file() and entry.name.endswith('.cast'):
            try:
                extract_to_event_stream_v2(entry.path)
            except Exception as e:
                print(f"Error processing {entry.path}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_v2_event_stream.py <cast_file_or_directory>")
        sys.exit(1)
    
    target_path = sys.argv[1]
    
    if not os.path.exists(target_path):
        print(f"Error: Path not found: {target_path}")
        sys.exit(1)
    
    if os.path.isfile(target_path):
        extract_to_event_stream_v2(target_path)
    else:
        process_directory(target_path)
