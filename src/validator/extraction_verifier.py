#!/usr/bin/env python3
"""
Multi-Version Cast Extraction Verification

Verifies extracted JSON data against original cast files and txt screenshots.
Supports v1, v2, v3 cast formats.
"""

import json
import re
import sys
import os
import glob
from typing import List, Dict, Any, Optional, Tuple

from src.parser.detect_version import detect_version


def clean_ansi(text: str) -> str:
    """Remove all ANSI escape codes."""
    # Remove CSI sequences
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)
    # Remove OSC sequences
    text = re.sub(r'\x1b\][0-9]+;.*?\x07', '', text)
    # Remove private modes
    text = re.sub(r'\x1b\[\?[0-9]+[hl]', '', text)
    # Remove other escape sequences
    text = re.sub(r'\x1b[=>]', '', text)
    text = re.sub(r'\x1b[78]', '', text)
    text = re.sub(r'\x1bc', '', text)
    return text


def extract_commands_from_txt(txt_content: str) -> List[str]:
    """Extract commands from txt file (content after shell prompts)."""
    commands = []
    # Clean ANSI codes first
    cleaned = clean_ansi(txt_content)
    # Match lines with shell prompts followed by commands
    prompt_pattern = re.compile(r'[\$#>%]\s+(.+?)(?:\s*$)', re.MULTILINE)
    for match in prompt_pattern.finditer(cleaned):
        cmd = match.group(1).strip()
        # Filter out empty commands and prompt-only lines
        if cmd and not re.match(r'^[\$#>%\s]*$', cmd):
            commands.append(cmd)
    return commands


def extract_commands_from_json(json_path: str) -> Tuple[List[str], int]:
    """
    Extract commands from JSON turns.
    
    Returns:
        (commands, total_turns) - 命令列表和总回合数
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    commands = []
    turns = data.get('turns', [])
    
    for turn in turns:
        cmd = turn.get('action', {}).get('content', '').strip()
        # Extract actual command if it includes prompt
        if '%' in cmd:
            cmd = cmd.split('%')[-1].strip()
        elif '$' in cmd:
            cmd = cmd.split('$')[-1].strip()
        
        if cmd:
            commands.append(cmd)
    
    return commands, len(turns)


def compare_command_lists(json_cmds: List[str], txt_cmds: List[str]) -> Dict:
    """
    Compare extracted commands from JSON with commands from txt.
    
    Returns:
        Dictionary with match statistics
    """
    if not txt_cmds:
        return {
            'match_ratio': 1.0 if not json_cmds else 0.0,
            'json_count': len(json_cmds),
            'txt_count': 0,
            'matched': 0,
            'status': 'no_txt_commands'
        }
    
    if not json_cmds:
        return {
            'match_ratio': 0.0,
            'json_count': 0,
            'txt_count': len(txt_cmds),
            'matched': 0,
            'status': 'no_json_commands'
        }
    
    # Simple substring matching
    matched = 0
    for txt_cmd in txt_cmds:
        for json_cmd in json_cmds:
            # Check if either contains the other (handles prompt prefix issues)
            if txt_cmd in json_cmd or json_cmd in txt_cmd:
                matched += 1
                break
    
    match_ratio = matched / len(txt_cmds) if txt_cmds else 0.0
    
    return {
        'match_ratio': round(match_ratio, 4),
        'json_count': len(json_cmds),
        'txt_count': len(txt_cmds),
        'matched': matched,
        'status': 'pass' if match_ratio >= 0.8 else 'fail'
    }


def simulate_terminal(text: str, width: int = 80, height: int = 24) -> str:
    """
    Execute terminal simulation and return the final screen content.
    Simplified version that handles basic cases.
    """
    lines = [[]]
    cursor_x = 0
    cursor_y = 0
    viewport_top = 0
    
    # Bound limits to prevent extreme memory usage
    max_lines = 10000
    max_width = max(width, 200)
    
    def ensure_line(y):
        if y < 0:
            return
        while len(lines) <= y and len(lines) < max_lines:
            lines.append([])
    
    def ensure_col(y, x):
        if y < 0 or x < 0 or y >= max_lines or x >= max_width:
            return
        ensure_line(y)
        if y < len(lines):
            while len(lines[y]) <= x and len(lines[y]) < max_width:
                lines[y].append(' ')
    
    def safe_set_char(y, x, char):
        if y < 0 or x < 0 or y >= max_lines or x >= max_width:
            return
        ensure_col(y, x)
        if y < len(lines) and x < len(lines[y]):
            lines[y][x] = char
    
    i = 0
    n = len(text)
    
    try:
        while i < n:
            char = text[i]
            
            if char == '\x1b':  # ESC
                if i + 1 < n and text[i+1] == '[':
                    j = i + 2
                    while j < n and not ('@' <= text[j] <= '~'):
                        j += 1
                    if j < n:
                        cmd = text[j]
                        params = text[i+2:j]
                        
                        if cmd in ('H', 'f'):  # Cursor position
                            parts = params.split(';')
                            try:
                                row = int(parts[0]) if parts[0].isdigit() else 1
                                col = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                            except (ValueError, IndexError):
                                row, col = 1, 1
                            cursor_y = viewport_top + row - 1
                            cursor_x = max(0, col - 1)
                        elif cmd == 'J':  # Erase display
                            try:
                                mode = int(params) if params.isdigit() else 0
                            except ValueError:
                                mode = 0
                            if mode in (2, 3):
                                viewport_top = len(lines)
                                cursor_y = viewport_top
                                cursor_x = 0
                        elif cmd == 'K':  # Erase line
                            if 0 <= cursor_y < len(lines):
                                lines[cursor_y] = lines[cursor_y][:max(0, cursor_x)]
                        elif cmd == 'A':  # Cursor up
                            try:
                                n_lines_move = int(params) if params.isdigit() else 1
                            except ValueError:
                                n_lines_move = 1
                            cursor_y = max(viewport_top, cursor_y - n_lines_move)
                        elif cmd == 'B':  # Cursor down
                            try:
                                n_lines_move = int(params) if params.isdigit() else 1
                            except ValueError:
                                n_lines_move = 1
                            cursor_y += n_lines_move
                            ensure_line(cursor_y)
                        elif cmd == 'C':  # Cursor forward
                            try:
                                n_cols = int(params) if params.isdigit() else 1
                            except ValueError:
                                n_cols = 1
                            cursor_x = min(cursor_x + n_cols, max_width - 1)
                        elif cmd == 'D':  # Cursor back
                            try:
                                n_cols = int(params) if params.isdigit() else 1
                            except ValueError:
                                n_cols = 1
                            cursor_x = max(0, cursor_x - n_cols)
                        
                        i = j + 1
                        continue
                
                elif i + 1 < n and text[i+1] == ']':  # OSC
                    # Scan until \x07 (BEL) or \x1b\ (ST)
                    j = i + 2
                    while j < n:
                        if text[j] == '\x07':
                            i = j + 1
                            break
                        if text[j] == '\x1b' and j+1 < n and text[j+1] == '\\':
                            i = j + 2
                            break
                        j += 1
                    else:
                        i = n
                    continue
                
                i += 1
                continue
            
            if char == '\r':
                cursor_x = 0
            elif char == '\n':
                cursor_y += 1
                cursor_x = 0
                if cursor_y >= viewport_top + height:
                    viewport_top += 1
                ensure_line(cursor_y)
            elif char == '\b':
                cursor_x = max(0, cursor_x - 1)
            elif char == '\t':
                n_spaces = 8 - (cursor_x % 8)
                for _ in range(n_spaces):
                    if cursor_x >= width:
                        cursor_x = 0
                        cursor_y += 1
                        if cursor_y >= viewport_top + height:
                            viewport_top += 1
                        ensure_line(cursor_y)
                    safe_set_char(cursor_y, cursor_x, ' ')
                    cursor_x += 1
            elif char >= ' ':  # Printable characters only
                if cursor_x >= width:
                    cursor_x = 0
                    cursor_y += 1
                    if cursor_y >= viewport_top + height:
                        viewport_top += 1
                    ensure_line(cursor_y)
                
                safe_set_char(cursor_y, cursor_x, char)
                cursor_x += 1
            
            i += 1
    except Exception:
        pass  # Gracefully handle any simulation errors
    
    return '\n'.join(''.join(line).rstrip() for line in lines[viewport_top:])


def reconstruct_from_cast_v1(cast_path: str) -> Tuple[str, Dict]:
    """Reconstruct terminal output from v1 cast file."""
    with open(cast_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    output_parts = []
    for frame in data.get('stdout', []):
        if isinstance(frame, list) and len(frame) >= 2:
            output_parts.append(frame[1])
    
    raw_output = ''.join(output_parts)
    width = data.get('width', 80)
    height = data.get('height', 24)
    
    simulated = simulate_terminal(raw_output, width, height)
    
    return simulated, {'width': width, 'height': height, 'frames': len(data.get('stdout', []))}


def reconstruct_from_cast_v2(cast_path: str) -> Tuple[str, Dict]:
    """Reconstruct terminal output from v2 cast file."""
    output_parts = []
    width = 80
    height = 24
    event_count = 0
    
    with open(cast_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                if isinstance(data, dict):
                    width = data.get('width', width)
                    height = data.get('height', height)
                elif isinstance(data, list) and len(data) >= 3 and data[1] == 'o':
                    output_parts.append(data[2])
                    event_count += 1
            except json.JSONDecodeError:
                continue
    
    raw_output = ''.join(output_parts)
    simulated = simulate_terminal(raw_output, width, height)
    
    return simulated, {'width': width, 'height': height, 'output_events': event_count}


def reconstruct_from_cast_v3(cast_path: str) -> Tuple[str, Dict]:
    """Reconstruct terminal output from v3 cast file."""
    output_parts = []
    width = 80
    height = 24
    event_count = 0
    
    with open(cast_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    term = data.get('term', {})
                    width = term.get('cols', width)
                    height = term.get('rows', height)
                elif isinstance(data, list) and len(data) >= 3 and data[1] == 'o':
                    output_parts.append(data[2])
                    event_count += 1
            except json.JSONDecodeError:
                continue
    
    raw_output = ''.join(output_parts)
    simulated = simulate_terminal(raw_output, width, height)
    
    return simulated, {'width': width, 'height': height, 'output_events': event_count}


def reconstruct_from_json(json_path: str) -> Tuple[str, Dict]:
    """Reconstruct terminal output from extracted JSON."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    width = data.get('session_metadata', {}).get('terminal_size', {}).get('width', 80)
    height = data.get('session_metadata', {}).get('terminal_size', {}).get('height', 24)
    
    # For v1 format, use raw_all_output if available (complete raw data)
    if 'raw_all_output' in data:
        raw_output = data['raw_all_output']
        simulated = simulate_terminal(raw_output, width, height)
        return simulated, {
            'width': width,
            'height': height,
            'turns': len(data.get('turns', [])),
            'used_raw_all_output': True
        }
    
    # For v2/v3, reconstruct from initial_output + turns
    output_parts = []
    
    # Include initial output
    if 'initial_output' in data:
        output_parts.append(data['initial_output'])
    
    # Include all turn observations
    for turn in data.get('turns', []):
        raw_output = turn.get('observation', {}).get('raw_output', '')
        output_parts.append(raw_output)
    
    raw_output = ''.join(output_parts)
    simulated = simulate_terminal(raw_output, width, height)
    
    return simulated, {
        'width': width,
        'height': height,
        'turns': len(data.get('turns', []))
    }


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    lines = [line.rstrip() for line in text.strip().split('\n')]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts (0-1)."""
    lines1 = set(text1.split('\n'))
    lines2 = set(text2.split('\n'))
    
    if not lines1 and not lines2:
        return 1.0
    
    intersection = lines1 & lines2
    union = lines1 | lines2
    
    return len(intersection) / len(union) if union else 1.0


def find_txt_file(cast_path: str, txt_dir: str) -> Optional[str]:
    """Find corresponding txt file for a cast file."""
    # Extract ID from cast filename
    basename = os.path.basename(cast_path)
    cast_id = os.path.splitext(basename)[0]
    
    txt_path = os.path.join(txt_dir, f"{cast_id}.txt")
    if os.path.exists(txt_path):
        return txt_path
    
    return None


def verify_single_file(cast_path: str, json_path: Optional[str] = None,
                       txt_dir: Optional[str] = None, verbose: bool = False) -> Dict:
    """
    Verify extraction for a single cast file.
    
    Args:
        cast_path: Path to original cast file
        json_path: Path to extracted JSON (auto-detect if None)
        txt_dir: Directory containing txt screenshots
        verbose: Print detailed output
    
    Returns:
        Verification result dictionary
    """
    result = {
        'file': cast_path,
        'version': None,
        'cast_verification': {
            'success': False,
            'match_type': None,
            'message': ''
        },
        'txt_verification': {
            'success': None,
            'similarity': None,
            'message': ''
        },
        'turns_verification': {
            'success': None,
            'commands_extracted': 0,
            'commands_in_txt': 0,
            'match_ratio': None,
            'message': ''
        },
        'data_quality': {
            'total_turns': 0,
            'empty_actions': 0,
            'empty_observations': 0
        },
        'warnings': []
    }
    
    # Detect version
    version, metadata = detect_version(cast_path)
    if version is None:
        result['cast_verification']['message'] = f"Unknown format: {metadata.get('error', '')}"
        return result
    
    result['version'] = f"v{version}"
    
    # Find JSON file if not specified
    if json_path is None:
        json_path = os.path.splitext(cast_path)[0] + '.turn_based.json'
    
    if not os.path.exists(json_path):
        result['cast_verification']['message'] = f"JSON file not found: {json_path}"
        return result
    
    # Reconstruct from cast
    try:
        if version == 1:
            cast_simulated, cast_info = reconstruct_from_cast_v1(cast_path)
        elif version == 2:
            cast_simulated, cast_info = reconstruct_from_cast_v2(cast_path)
        else:  # version == 3
            cast_simulated, cast_info = reconstruct_from_cast_v3(cast_path)
    except Exception as e:
        result['cast_verification']['message'] = f"Error reconstructing from cast: {e}"
        return result
    
    # Reconstruct from JSON
    try:
        json_simulated, json_info = reconstruct_from_json(json_path)
    except Exception as e:
        result['cast_verification']['message'] = f"Error reconstructing from JSON: {e}"
        return result
    
    # Compare cast vs JSON reconstruction
    norm_cast = normalize_text(cast_simulated)
    norm_json = normalize_text(json_simulated)
    
    if norm_cast == norm_json:
        result['cast_verification']['success'] = True
        result['cast_verification']['match_type'] = 'exact'
    elif norm_json.startswith(norm_cast) or norm_cast.startswith(norm_json):
        result['cast_verification']['success'] = True
        result['cast_verification']['match_type'] = 'prefix'
    else:
        similarity = calculate_similarity(norm_cast, norm_json)
        if similarity >= 0.9:
            result['cast_verification']['success'] = True
            result['cast_verification']['match_type'] = f'similar ({similarity:.2f})'
        else:
            result['cast_verification']['success'] = False
            result['cast_verification']['match_type'] = f'mismatch ({similarity:.2f})'
            result['cast_verification']['message'] = f"Cast: {len(norm_cast)} chars, JSON: {len(norm_json)} chars"
    
    # Extract commands from JSON for turns verification
    json_commands, total_turns = extract_commands_from_json(json_path)
    result['turns_verification']['commands_extracted'] = len(json_commands)
    
    # Load JSON data for quality check
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    # Check for zero turns warning
    has_output = bool(json_data.get('raw_all_output', '').strip())
    if total_turns == 0 and has_output:
        result['warnings'].append('Zero turns extracted but output exists - possible extraction failure')
    
    # TXT verification with command matching
    if txt_dir:
        txt_path = find_txt_file(cast_path, txt_dir)
        if txt_path:
            try:
                with open(txt_path, 'r', encoding='utf-8') as f:
                    txt_content = f.read()
                
                norm_txt = normalize_text(clean_ansi(txt_content))
                
                # Compare with cast simulation (original behavior)
                similarity = calculate_similarity(norm_cast, norm_txt)
                result['txt_verification']['similarity'] = round(similarity, 4)
                result['txt_verification']['success'] = similarity >= 0.8
                
                if not result['txt_verification']['success']:
                    result['txt_verification']['message'] = f"Low similarity with txt screenshot"
                
                # NEW: Compare extracted commands with txt commands
                txt_commands = extract_commands_from_txt(txt_content)
                result['turns_verification']['commands_in_txt'] = len(txt_commands)
                
                if txt_commands:
                    cmd_comparison = compare_command_lists(json_commands, txt_commands)
                    result['turns_verification']['match_ratio'] = cmd_comparison['match_ratio']
                    result['turns_verification']['success'] = cmd_comparison['status'] == 'pass'
                    
                    if not result['turns_verification']['success']:
                        result['turns_verification']['message'] = (
                            f"Command mismatch: extracted {len(json_commands)}, "
                            f"txt has {len(txt_commands)}, matched {cmd_comparison['matched']}"
                        )
                        if len(json_commands) == 0 and len(txt_commands) > 0:
                            result['warnings'].append(
                                f"Failed to extract {len(txt_commands)} commands found in txt"
                            )
                else:
                    result['turns_verification']['message'] = "No commands found in txt file"
                    
            except Exception as e:
                result['txt_verification']['message'] = f"Error reading txt: {e}"
        else:
            result['txt_verification']['message'] = "No matching txt file found"
    
    # Data quality check
    turns = json_data.get('turns', [])
    result['data_quality']['total_turns'] = len(turns)
    
    for turn in turns:
        action_content = turn.get('action', {}).get('content', '')
        obs_content = turn.get('observation', {}).get('content', '')
        
        if not action_content.strip():
            result['data_quality']['empty_actions'] += 1
        if not obs_content.strip():
            result['data_quality']['empty_observations'] += 1
    
    if verbose:
        print(f"\n{'='*60}")
        print(f"File: {os.path.basename(cast_path)}")
        print(f"Version: v{version}")
        print(f"Cast verification: {result['cast_verification']}")
        print(f"TXT verification: {result['txt_verification']}")
        print(f"Turns verification: {result['turns_verification']}")
        print(f"Data quality: {result['data_quality']}")
        if result['warnings']:
            print(f"Warnings: {result['warnings']}")
    
    return result


def verify_directory(target_dir: str, txt_dir: Optional[str] = None,
                     output_report: Optional[str] = None, cast_dir: Optional[str] = None,
                     verbose: bool = False) -> Dict:
    """
    Verify all extracted files in a directory.
    
    Args:
        target_dir: Directory containing extracted JSONs
        txt_dir: Optional directory containing txt screenshots
        output_report: Optional path to save report
        cast_dir: Optional directory containing original cast files
        verbose: Print detailed output
    """
    
    json_files = glob.glob(os.path.join(target_dir, "**", "*.turn_based.json"), recursive=True)
    
    results = {
        'summary': {
            'total': 0,
            'cast_pass': 0,
            'cast_fail': 0,
            'txt_pass': 0,
            'txt_fail': 0,
            'txt_na': 0
        },
        'by_version': {
            'v1': {'pass': 0, 'fail': 0},
            'v2': {'pass': 0, 'fail': 0},
            'v3': {'pass': 0, 'fail': 0}
        },
        'details': []
    }
    
    print(f"Verifying {len(json_files)} extracted files...")
    
    for json_path in json_files:
        # Determine cast path
        if cast_dir:
            basename = os.path.basename(json_path).replace('.turn_based.json', '.cast')
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
            cast_path = json_path.replace('.turn_based.json', '.cast')
        
        if not os.path.exists(cast_path):
            print(f"  [SKIP] Cast file not found: {cast_path}")
            continue
        
        result = verify_single_file(cast_path, json_path, txt_dir, verbose)
        results['details'].append(result)
        results['summary']['total'] += 1
        
        # Update summary
        if result['cast_verification']['success']:
            results['summary']['cast_pass'] += 1
            if result['version']:
                results['by_version'][result['version']]['pass'] += 1
        else:
            results['summary']['cast_fail'] += 1
            if result['version']:
                results['by_version'][result['version']]['fail'] += 1
        
        if result['txt_verification']['success'] is True:
            results['summary']['txt_pass'] += 1
        elif result['txt_verification']['success'] is False:
            results['summary']['txt_fail'] += 1
        else:
            results['summary']['txt_na'] += 1
        
        # Print progress
        status = '[PASS]' if result['cast_verification']['success'] else '[FAIL]'
        print(f"  {status} {os.path.basename(cast_path)} ({result['version']})")
    
    # Print summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Total files: {results['summary']['total']}")
    print(f"Cast verification: {results['summary']['cast_pass']} pass, {results['summary']['cast_fail']} fail")
    print(f"TXT verification: {results['summary']['txt_pass']} pass, {results['summary']['txt_fail']} fail, {results['summary']['txt_na']} N/A")
    print(f"By version:")
    for v in ['v1', 'v2', 'v3']:
        vr = results['by_version'][v]
        print(f"  {v}: {vr['pass']} pass, {vr['fail']} fail")
    
    if output_report:
        with open(output_report, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        print(f"\nReport saved to: {output_report}")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Verify cast extraction')
    parser.add_argument('path', help='Cast file or directory with extracted JSONs')
    parser.add_argument('--txt-dir', default='../txt', help='Directory containing txt screenshots')
    parser.add_argument('--output', '-o', help='Output report JSON path')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.path):
        print(f"Error: Path not found: {args.path}")
        sys.exit(1)
    
    txt_dir = os.path.abspath(args.txt_dir) if args.txt_dir and os.path.isdir(args.txt_dir) else None
    
    if os.path.isfile(args.path):
        if args.path.endswith('.cast'):
            result = verify_single_file(args.path, None, txt_dir, args.verbose)
        else:
            # Assume it's a JSON file
            # If explicit file given, we assume cast is alongside it unless we implement more complex logic here
            cast_path = args.path.replace('.turn_based.json', '.cast')
            result = verify_single_file(cast_path, args.path, txt_dir, args.verbose)
        
        print(json.dumps(result, indent=2))
    else:
        # For directory mode, we might want to support --cast-dir arg in main script too, 
        # but for now we're mostly concerned with library usage.
        # Adding support just in case:
        parser.add_argument('--cast-dir', help='Directory containing original cast files')
        # Re-parse to get the new arg if added
        args, _ = parser.parse_known_args()
        
        verify_directory(args.path, txt_dir, args.output, args.cast_dir, args.verbose)
