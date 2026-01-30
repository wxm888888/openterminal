#!/usr/bin/env python3
"""
Unified Batch Processing for Cast Files

Supports both turn_based and event_stream extraction formats.
Automatically detects version and processes files using appropriate parser.
"""

import json
import os
import sys
import glob
import time
from typing import Dict, List, Optional

from src.parser.detect_version import detect_version


def process_single_file(cast_path: str, output_dir: Optional[str] = None,
                        format_type: str = 'both', verbose: bool = False) -> Dict:
    """
    Process a single cast file.
    
    Args:
        cast_path: Path to the cast file
        output_dir: Optional output directory (default: same as input)
        format_type: 'turn_based', 'event_stream', or 'both'
        verbose: Print detailed output
    
    Returns:
        Processing result dictionary
    """
    result = {
        'file': cast_path,
        'version': None,
        'success': {'turn_based': False, 'event_stream': False},
        'turns': 0,
        'events': 0,
        'message': '',
        'duration_ms': 0
    }
    
    start_time = time.time()
    
    # Detect version
    version, metadata = detect_version(cast_path)
    if version is None:
        result['message'] = f"Unknown format: {metadata.get('error', '')}"
        return result
    
    result['version'] = f"v{version}"
    
    # Determine output paths
    if output_dir:
        basename = os.path.basename(cast_path)
        base_output = os.path.join(output_dir, os.path.splitext(basename)[0])
    else:
        base_output = os.path.splitext(cast_path)[0]
    
    # Process turn_based format
    if format_type in ('turn_based', 'both'):
        try:
            if version == 1:
                from src.parser.extract_v1 import extract_to_turn_based_v1
                data = extract_to_turn_based_v1(cast_path, base_output + '.turn_based.json')
            elif version == 2:
                from src.parser.extract_v2 import extract_to_turn_based_v2
                data = extract_to_turn_based_v2(cast_path, base_output + '.turn_based.json', verbose)
            else:  # version == 3
                from src.parser.extract_v3 import extract_to_turn_based_v3
                data = extract_to_turn_based_v3(cast_path, base_output + '.turn_based.json')
            
            result['success']['turn_based'] = True
            result['turns'] = len(data.get('turns', []))
        except Exception as e:
            result['message'] += f"Turn-based error: {e}; "
    
    # Process event_stream format
    if format_type in ('event_stream', 'both'):
        try:
            if version == 1:
                from src.parser.event_stream_v1 import extract_to_event_stream_v1
                data = extract_to_event_stream_v1(cast_path, base_output + '.event_stream.json')
            elif version == 2:
                from src.parser.event_stream_v2 import extract_to_event_stream_v2
                data = extract_to_event_stream_v2(cast_path, base_output + '.event_stream.json')
            else:  # version == 3
                from src.parser.event_stream_v3 import extract_to_event_stream_v3
                data = extract_to_event_stream_v3(cast_path, base_output + '.event_stream.json')
            
            result['success']['event_stream'] = True
            result['events'] = len(data.get('events', []))
        except Exception as e:
            result['message'] += f"Event-stream error: {e}; "
    
    result['duration_ms'] = round((time.time() - start_time) * 1000, 2)
    
    return result


def batch_process_unified(input_dir: str, output_dir: Optional[str] = None,
                          format_type: str = 'both', report_path: Optional[str] = None,
                          verbose: bool = False) -> Dict:
    """
    Process all cast files in a directory with both formats.
    
    Args:
        input_dir: Directory containing cast files
        output_dir: Optional output directory for JSONs
        format_type: 'turn_based', 'event_stream', or 'both'
        report_path: Path to save processing report
        verbose: Print detailed output
    
    Returns:
        Processing report dictionary
    """
    # Find all cast files
    cast_files = []
    for version_dir in ['v1', 'v2', 'v3']:
        version_path = os.path.join(input_dir, version_dir)
        if os.path.isdir(version_path):
            cast_files.extend(glob.glob(os.path.join(version_path, "*.cast")))
    
    # If no version subdirs, look for cast files directly
    if not cast_files:
        cast_files = glob.glob(os.path.join(input_dir, "*.cast"))
    
    print(f"Found {len(cast_files)} cast files to process")
    print(f"Format: {format_type}")
    
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    report = {
        'summary': {
            'total': len(cast_files),
            'turn_based_success': 0,
            'event_stream_success': 0,
            'total_turns': 0,
            'total_events': 0,
            'total_duration_ms': 0
        },
        'by_version': {
            'v1': {'count': 0, 'tb_success': 0, 'es_success': 0, 'turns': 0, 'events': 0},
            'v2': {'count': 0, 'tb_success': 0, 'es_success': 0, 'turns': 0, 'events': 0},
            'v3': {'count': 0, 'tb_success': 0, 'es_success': 0, 'turns': 0, 'events': 0}
        },
        'files': []
    }
    
    for i, cast_path in enumerate(cast_files):
        result = process_single_file(cast_path, output_dir, format_type, verbose)
        report['files'].append(result)
        
        # Update summary
        report['summary']['total_duration_ms'] += result['duration_ms']
        
        if result['success']['turn_based']:
            report['summary']['turn_based_success'] += 1
            report['summary']['total_turns'] += result['turns']
        
        if result['success']['event_stream']:
            report['summary']['event_stream_success'] += 1
            report['summary']['total_events'] += result['events']
        
        # Update by version
        if result['version']:
            v = result['version']
            report['by_version'][v]['count'] += 1
            if result['success']['turn_based']:
                report['by_version'][v]['tb_success'] += 1
                report['by_version'][v]['turns'] += result['turns']
            if result['success']['event_stream']:
                report['by_version'][v]['es_success'] += 1
                report['by_version'][v]['events'] += result['events']
        
        # Progress indicator
        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(cast_files)} files...")
    
    # Print summary
    print("\n" + "=" * 60)
    print("UNIFIED BATCH PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Total files: {report['summary']['total']}")
    print(f"Turn-based success: {report['summary']['turn_based_success']}")
    print(f"Event-stream success: {report['summary']['event_stream_success']}")
    print(f"Total turns extracted: {report['summary']['total_turns']}")
    print(f"Total events extracted: {report['summary']['total_events']}")
    print(f"Total processing time: {report['summary']['total_duration_ms']:.0f}ms")
    print("\nBy version:")
    for v in ['v1', 'v2', 'v3']:
        vr = report['by_version'][v]
        if vr['count'] > 0:
            print(f"  {v}: {vr['count']} files")
            print(f"      Turn-based: {vr['tb_success']} success, {vr['turns']} turns")
            print(f"      Event-stream: {vr['es_success']} success, {vr['events']} events")
    
    if report_path:
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {report_path}")
    
    return report


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Unified batch process cast files')
    parser.add_argument('input_dir', help='Directory containing cast files')
    parser.add_argument('--output-dir', '-o', help='Output directory for JSONs')
    parser.add_argument('--format', '-f', choices=['turn_based', 'event_stream', 'both'],
                        default='both', help='Extraction format (default: both)')
    parser.add_argument('--report', '-r', default='unified_report.json', help='Report JSON path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.input_dir):
        print(f"Error: Directory not found: {args.input_dir}")
        sys.exit(1)
    
    batch_process_unified(args.input_dir, args.output_dir, args.format, args.report, args.verbose)
