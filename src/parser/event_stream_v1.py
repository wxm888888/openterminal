#!/usr/bin/env python3
"""
V1 Format Event Stream Extraction

Extracts raw event stream from v1 format cast files (standard JSON with stdout array).
Preserves all events with timestamps for maximum fidelity.
"""

import json
import sys
import os
from typing import Dict, List, Optional, Tuple


def parse_v1_to_events(file_path: str) -> Tuple[Dict, List[Dict]]:
    """
    Parse v1 format cast file to normalized event list.
    
    v1 format is a standard JSON object with:
    - metadata fields (width, height, duration, etc.)
    - stdout array containing [delay, data] pairs
    
    Returns:
        (metadata, events) tuple where events have absolute timestamps
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    metadata = {
        'version': 1,
        'width': data.get('width', 80),
        'height': data.get('height', 24),
        'duration': data.get('duration', 0),
        'command': data.get('command', ''),
        'title': data.get('title', ''),
        'env': data.get('env', {})
    }
    
    # Convert relative delays to absolute timestamps
    events = []
    current_time = 0.0
    
    for frame in data.get('stdout', []):
        if isinstance(frame, list) and len(frame) >= 2:
            delay, content = frame[0], frame[1]
            current_time += delay
            events.append({
                't': round(current_time, 6),
                'type': 'output',  # v1 only has output events
                'data': content
            })
    
    return metadata, events


def extract_to_event_stream_v1(file_path: str, output_path: Optional[str] = None) -> Dict:
    """
    Extract v1 cast file to event stream format.
    
    Args:
        file_path: Path to the v1 .cast file
        output_path: Optional output path for JSON
    
    Returns:
        The extracted data structure
    """
    metadata, events = parse_v1_to_events(file_path)
    
    # Calculate statistics
    output_count = len(events)  # v1 only has output events
    
    if events:
        total_duration = events[-1]['t']
    else:
        total_duration = metadata.get('duration', 0)
    
    result = {
        'metadata': {
            'version': 1,
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
            'input_events': 0,  # v1 has no input events
            'output_events': output_count,
            'marker_events': 0,
            'total_duration_seconds': round(total_duration, 2)
        },
        'events': events
    }
    
    if output_path is None:
        output_path = os.path.splitext(file_path)[0] + '.event_stream.json'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"V1 event stream extraction complete: {output_path}")
    print(f"  - Total events: {len(events)} (output only)")
    print(f"  - Duration: {total_duration:.2f}s")
    
    return result


def process_directory(target_path: str):
    """Process all v1 cast files in a directory."""
    for entry in os.scandir(target_path):
        if entry.is_file() and entry.name.endswith('.cast'):
            try:
                extract_to_event_stream_v1(entry.path)
            except Exception as e:
                print(f"Error processing {entry.path}: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_v1_event_stream.py <cast_file_or_directory>")
        sys.exit(1)
    
    target_path = sys.argv[1]
    
    if not os.path.exists(target_path):
        print(f"Error: Path not found: {target_path}")
        sys.exit(1)
    
    if os.path.isfile(target_path):
        extract_to_event_stream_v1(target_path)
    else:
        process_directory(target_path)
