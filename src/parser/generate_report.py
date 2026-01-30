#!/usr/bin/env python3
"""
Generate Analysis Report for Cast File Processing

Analyzes processing results and generates a comprehensive report.
"""

import json
import os
import sys
import glob
from typing import Dict, List, Optional
from datetime import datetime


def analyze_extracted_data(json_path: str) -> Dict:
    """Analyze a single extracted JSON file."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    turns = data.get('turns', [])
    
    analysis = {
        'file': os.path.basename(json_path),
        'version': data.get('session_metadata', {}).get('original_version', 'unknown'),
        'total_turns': len(turns),
        'empty_actions': 0,
        'empty_observations': 0,
        'heredoc_turns': 0,
        'interactive_turns': 0,
        'command_turns': 0,
        'avg_observation_length': 0
    }
    
    total_obs_length = 0
    
    for turn in turns:
        action = turn.get('action', {})
        observation = turn.get('observation', {})
        
        action_content = action.get('content', '')
        obs_content = observation.get('content', '')
        
        if not action_content.strip():
            analysis['empty_actions'] += 1
        if not obs_content.strip():
            analysis['empty_observations'] += 1
        
        action_type = action.get('type', 'command')
        if action_type == 'heredoc':
            analysis['heredoc_turns'] += 1
        elif action_type == 'interactive_program':
            analysis['interactive_turns'] += 1
        else:
            analysis['command_turns'] += 1
        
        total_obs_length += len(obs_content)
    
    if len(turns) > 0:
        analysis['avg_observation_length'] = round(total_obs_length / len(turns), 2)
    
    return analysis


def generate_report(samples_dir: str, output_path: Optional[str] = None) -> Dict:
    """
    Generate comprehensive analysis report.
    
    Args:
        samples_dir: Directory containing processed samples
        output_path: Path to save the report
    
    Returns:
        Report dictionary
    """
    report = {
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_files': 0,
            'total_turns': 0,
            'files_with_turns': 0,
            'files_without_turns': 0,
            'total_empty_actions': 0,
            'total_empty_observations': 0
        },
        'by_version': {
            'v1': {'files': 0, 'turns': 0, 'avg_turns': 0},
            'v2': {'files': 0, 'turns': 0, 'avg_turns': 0},
            'v3': {'files': 0, 'turns': 0, 'avg_turns': 0}
        },
        'action_types': {
            'command': 0,
            'heredoc': 0,
            'interactive_program': 0
        },
        'files': []
    }
    
    # Find all extracted JSON files
    json_files = []
    for version_dir in ['v1', 'v2', 'v3']:
        version_path = os.path.join(samples_dir, version_dir)
        if os.path.isdir(version_path):
            json_files.extend(glob.glob(os.path.join(version_path, "*.turn_based.json")))
    
    if not json_files:
        json_files = glob.glob(os.path.join(samples_dir, "*.turn_based.json"))
    
    print(f"Analyzing {len(json_files)} extracted files...")
    
    for json_path in json_files:
        try:
            analysis = analyze_extracted_data(json_path)
            report['files'].append(analysis)
            
            # Update summary
            report['summary']['total_files'] += 1
            report['summary']['total_turns'] += analysis['total_turns']
            report['summary']['total_empty_actions'] += analysis['empty_actions']
            report['summary']['total_empty_observations'] += analysis['empty_observations']
            
            if analysis['total_turns'] > 0:
                report['summary']['files_with_turns'] += 1
            else:
                report['summary']['files_without_turns'] += 1
            
            # Update by version
            v = f"v{analysis['version']}"
            if v in report['by_version']:
                report['by_version'][v]['files'] += 1
                report['by_version'][v]['turns'] += analysis['total_turns']
            
            # Update action types
            report['action_types']['command'] += analysis['command_turns']
            report['action_types']['heredoc'] += analysis['heredoc_turns']
            report['action_types']['interactive_program'] += analysis['interactive_turns']
            
        except Exception as e:
            print(f"  Error analyzing {json_path}: {e}")
    
    # Calculate averages
    for v in ['v1', 'v2', 'v3']:
        vr = report['by_version'][v]
        if vr['files'] > 0:
            vr['avg_turns'] = round(vr['turns'] / vr['files'], 2)
    
    # Print report
    print("\n" + "=" * 60)
    print("ANALYSIS REPORT")
    print("=" * 60)
    print(f"\nGenerated at: {report['generated_at']}")
    print(f"\nSummary:")
    print(f"  Total files analyzed: {report['summary']['total_files']}")
    print(f"  Files with turns: {report['summary']['files_with_turns']}")
    print(f"  Files without turns: {report['summary']['files_without_turns']}")
    print(f"  Total turns extracted: {report['summary']['total_turns']}")
    print(f"  Empty actions: {report['summary']['total_empty_actions']}")
    print(f"  Empty observations: {report['summary']['total_empty_observations']}")
    
    print(f"\nBy Version:")
    for v in ['v1', 'v2', 'v3']:
        vr = report['by_version'][v]
        if vr['files'] > 0:
            print(f"  {v}: {vr['files']} files, {vr['turns']} turns, avg {vr['avg_turns']} turns/file")
    
    print(f"\nAction Types:")
    print(f"  Commands: {report['action_types']['command']}")
    print(f"  Heredocs: {report['action_types']['heredoc']}")
    print(f"  Interactive programs: {report['action_types']['interactive_program']}")
    
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {output_path}")
    
    return report


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate analysis report')
    parser.add_argument('samples_dir', nargs='?', default='samples', help='Directory with processed samples')
    parser.add_argument('--output', '-o', default='analysis_report.json', help='Output report path')
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.samples_dir):
        print(f"Error: Directory not found: {args.samples_dir}")
        sys.exit(1)
    
    generate_report(args.samples_dir, args.output)
