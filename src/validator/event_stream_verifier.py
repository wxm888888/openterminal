#!/usr/bin/env python3
"""
Event Stream Extraction Verification

Verifies extracted event stream JSON data against original cast files.
Supports v1, v2, v3 cast formats.
"""

import json
import re
import sys
import os
import glob
from typing import List, Dict, Any, Optional, Tuple

# Import version detector
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detect_version import detect_version


def reconstruct_output_from_cast_v1(cast_path: str) -> Tuple[str, Dict]:
    """Reconstruct raw output from v1 cast file."""
    with open(cast_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    output_parts = []
    total_time = 0.0
    
    for frame in data.get('stdout', []):
        if isinstance(frame, list) and len(frame) >= 2:
            total_time += frame[0]
            output_parts.append(frame[1])
    
    return ''.join(output_parts), {
        'frames': len(data.get('stdout', [])),
        'duration': total_time
    }


def reconstruct_output_from_cast_v2(cast_path: str) -> Tuple[str, Dict]:
    """Reconstruct raw output from v2 cast file."""
    output_parts = []
    event_count = 0
    input_count = 0
    last_time = 0
    
    with open(cast_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                if isinstance(data, list) and len(data) >= 3:
                    last_time = data[0]
                    if data[1] == 'o':
                        output_parts.append(data[2])
                        event_count += 1
                    elif data[1] == 'i':
                        input_count += 1
            except json.JSONDecodeError:
                continue
    
    return ''.join(output_parts), {
        'output_events': event_count,
        'input_events': input_count,
        'duration': last_time
    }


def reconstruct_output_from_cast_v3(cast_path: str) -> Tuple[str, Dict]:
    """Reconstruct raw output from v3 cast file."""
    output_parts = []
    current_time = 0.0
    event_count = 0
    input_count = 0
    
    with open(cast_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                data = json.loads(line)
                if isinstance(data, list) and len(data) >= 3:
                    current_time += data[0]
                    if data[1] == 'o':
                        output_parts.append(data[2])
                        event_count += 1
                    elif data[1] == 'i':
                        input_count += 1
            except json.JSONDecodeError:
                continue
    
    return ''.join(output_parts), {
        'output_events': event_count,
        'input_events': input_count,
        'duration': current_time
    }


def reconstruct_output_from_json(json_path: str) -> Tuple[str, Dict]:
    """Reconstruct raw output from extracted event stream JSON."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    events = data.get('events', [])
    output_parts = []
    input_count = 0
    output_count = 0
    
    for event in events:
        if event.get('type') == 'output':
            output_parts.append(event.get('data', ''))
            output_count += 1
        elif event.get('type') == 'input':
            input_count += 1
    
    duration = events[-1]['t'] if events else 0
    
    return ''.join(output_parts), {
        'output_events': output_count,
        'input_events': input_count,
        'total_events': len(events),
        'duration': duration
    }


def verify_single_file(cast_path: str, json_path: Optional[str] = None,
                       verbose: bool = False) -> Dict:
    """
    Verify event stream extraction for a single cast file.
    
    Returns:
        Verification result dictionary
    """
    result = {
        'file': cast_path,
        'version': None,
        'verification': {
            'success': False,
            'output_match': False,
            'event_count_match': False,
            'message': ''
        },
        'statistics': {
            'cast_events': 0,
            'json_events': 0,
            'cast_duration': 0,
            'json_duration': 0
        }
    }
    
    # Detect version
    version, metadata = detect_version(cast_path)
    if version is None:
        result['verification']['message'] = f"Unknown format: {metadata.get('error', '')}"
        return result
    
    result['version'] = f"v{version}"
    
    # Find JSON file if not specified
    if json_path is None:
        json_path = os.path.splitext(cast_path)[0] + '.event_stream.json'
    
    if not os.path.exists(json_path):
        result['verification']['message'] = f"JSON file not found: {json_path}"
        return result
    
    # Reconstruct from cast
    try:
        if version == 1:
            cast_output, cast_info = reconstruct_output_from_cast_v1(cast_path)
        elif version == 2:
            cast_output, cast_info = reconstruct_output_from_cast_v2(cast_path)
        else:  # version == 3
            cast_output, cast_info = reconstruct_output_from_cast_v3(cast_path)
    except Exception as e:
        result['verification']['message'] = f"Error reading cast: {e}"
        return result
    
    # Reconstruct from JSON
    try:
        json_output, json_info = reconstruct_output_from_json(json_path)
    except Exception as e:
        result['verification']['message'] = f"Error reading JSON: {e}"
        return result
    
    # Compare outputs
    result['verification']['output_match'] = (cast_output == json_output)
    
    # Compare event counts (for output events)
    cast_output_events = cast_info.get('output_events', cast_info.get('frames', 0))
    json_output_events = json_info.get('output_events', 0)
    result['verification']['event_count_match'] = (cast_output_events == json_output_events)
    
    # Overall success
    result['verification']['success'] = (
        result['verification']['output_match'] and 
        result['verification']['event_count_match']
    )
    
    # Statistics
    result['statistics']['cast_events'] = cast_output_events
    result['statistics']['json_events'] = json_output_events
    result['statistics']['cast_duration'] = round(cast_info.get('duration', 0), 2)
    result['statistics']['json_duration'] = round(json_info.get('duration', 0), 2)
    
    if not result['verification']['success']:
        if not result['verification']['output_match']:
            result['verification']['message'] = f"Output mismatch: cast {len(cast_output)} chars, json {len(json_output)} chars"
        elif not result['verification']['event_count_match']:
            result['verification']['message'] = f"Event count mismatch: cast {cast_output_events}, json {json_output_events}"
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"File: {os.path.basename(cast_path)}")
        print(f"Version: v{version}")
        print(f"Verification: {result['verification']}")
        print(f"Statistics: {result['statistics']}")
    
    return result


def verify_directory(target_dir: str, output_report: Optional[str] = None,
                     cast_dir: Optional[str] = None, verbose: bool = False) -> Dict:
    """Verify all extracted event stream files in a directory."""
    
    json_files = glob.glob(os.path.join(target_dir, "**", "*.event_stream.json"), recursive=True)
    
    results = {
        'summary': {
            'total': 0,
            'pass': 0,
            'fail': 0
        },
        'by_version': {
            'v1': {'pass': 0, 'fail': 0},
            'v2': {'pass': 0, 'fail': 0},
            'v3': {'pass': 0, 'fail': 0}
        },
        'details': []
    }
    
    print(f"Verifying {len(json_files)} event stream files...")
    
    for json_path in json_files:
        # Determine cast path
        if cast_dir:
            basename = os.path.basename(json_path).replace('.event_stream.json', '.cast')
            # Check root
            cast_path = os.path.join(cast_dir, basename)
            if not os.path.exists(cast_path):
                # Check version subdirs
                for v in ['v1', 'v2', 'v3']:
                    possible = os.path.join(cast_dir, v, basename)
                    if os.path.exists(possible):
                        cast_path = possible
                        break
        else:
            cast_path = json_path.replace('.event_stream.json', '.cast')
        
        if not os.path.exists(cast_path):
            print(f"  [SKIP] Cast file not found: {cast_path}")
            continue
        
        result = verify_single_file(cast_path, json_path, verbose)
        results['details'].append(result)
        results['summary']['total'] += 1
        
        # Update summary
        if result['verification']['success']:
            results['summary']['pass'] += 1
            if result['version']:
                results['by_version'][result['version']]['pass'] += 1
        else:
            results['summary']['fail'] += 1
            if result['version']:
                results['by_version'][result['version']]['fail'] += 1
        
        # Print progress
        status = '[PASS]' if result['verification']['success'] else '[FAIL]'
        print(f"  {status} {os.path.basename(cast_path)} ({result['version']})")
    
    # Print summary
    print("\n" + "=" * 60)
    print("EVENT STREAM VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total files: {results['summary']['total']}")
    print(f"Pass: {results['summary']['pass']}, Fail: {results['summary']['fail']}")
    print(f"By version:")
    for v in ['v1', 'v2', 'v3']:
        vr = results['by_version'][v]
        if vr['pass'] + vr['fail'] > 0:
            print(f"  {v}: {vr['pass']} pass, {vr['fail']} fail")
    
    if output_report:
        with open(output_report, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        print(f"\nReport saved to: {output_report}")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify event stream extraction')
    parser.add_argument('path', help='Cast file or directory with extracted JSONs')
    parser.add_argument('--output', '-o', help='Output report JSON path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.path):
        print(f"Error: Path not found: {args.path}")
        sys.exit(1)
    
    if os.path.isfile(args.path):
        if args.path.endswith('.cast'):
            result = verify_single_file(args.path, None, args.verbose)
        else:
            # Assume it's a JSON file
            cast_path = args.path.replace('.event_stream.json', '.cast')
            result = verify_single_file(cast_path, args.path, args.verbose)
        
        print(json.dumps(result, indent=2))
    else:
        # For directory mode, we might want to support --cast-dir arg in main script too, 
        # but for now we're mostly concerned with library usage.
        # Adding support just in case:
        parser.add_argument('--cast-dir', help='Directory containing original cast files')
        # Re-parse to get the new arg if added
        args, _ = parser.parse_known_args()
        
        verify_directory(args.path, args.output, args.cast_dir, args.verbose)
