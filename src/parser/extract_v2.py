#!/usr/bin/env python3
"""
V2 Format Cast File Parser (Optimized)

Extracts terminal interactions from v2 format cast files.
Enhanced version with better error handling, heredoc detection, and logging.
"""

import json
import re
import sys
import os
import glob
from typing import List, Dict, Any, Optional, Tuple
import difflib


# Regex patterns
HEREDOC_START = re.compile(r"<<\s*['\"]?(\w+)['\"]?\s*$|<<\s*['\"]?(\w+)['\"]?\s*\n")
ALTERNATE_SCREEN_ENTER = re.compile(r'\x1b\[\?(1049|47)h')
ALTERNATE_SCREEN_EXIT = re.compile(r'\x1b\[\?(1049|47)l')


def parse_v2_cast(file_path: str, verbose: bool = False) -> Tuple[Dict, List[Dict]]:
    """
    Parse v2 format cast file.
    
    v2 format is NDJSON with:
    - First line: header with version:2, width, height, etc.
    - Following lines: [time, type, data] arrays with absolute timestamps
    
    Returns:
        (metadata, events) tuple
    """
    metadata = {}
    events = []
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f):
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
                    events.append({
                        'timestamp': timestamp,
                        'type': event_type,
                        'data': content
                    })
            
            except json.JSONDecodeError as e:
                if verbose:
                    print(f"  Warning: JSON decode error at line {line_num + 1}: {e}")
                continue
    
    return metadata, events


def clean_output_for_display(text: str) -> str:
    """Remove ANSI codes for cleaner display content."""
    # Remove OSC codes (Operating System Command)
    # Match \x1b] ... \x07
    text = re.sub(r'\x1b\].*?\x07', '', text, flags=re.DOTALL)
    # Match \x1b] ... \x1b\
    text = re.sub(r'\x1b\].*?\x1b\\', '', text, flags=re.DOTALL)
    
    # Remove CSI codes (Control Sequence Introducer)
    # \x1b[ ... [a-zA-Z]
    # Standard CSI pattern: ESC [ parameter_bytes intermediate_bytes final_byte
    # parameter_bytes: 0x30-0x3F (0-9;:<=>?)
    # intermediate_bytes: 0x20-0x2F (space !"#$%&'()*+,-./)
    # final_byte: 0x40-0x7E (@-~)
    text = re.sub(r'\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]', '', text)
    
    # Remove other escape sequences
    # \x1b(X - G0 character set
    text = re.sub(r'\x1b\(.', '', text)
    # \x1b)X - G1 character set (and others)
    text = re.sub(r'\x1b[\)\*+\-./].', '', text)
    
    # Remove simple Fe escape sequences
    # \x1bN, \x1bO, etc.
    # 0x40-0x5F (@- _)
    text = re.sub(r'\x1b[@-_]', '', text)
    
    # Remove basic escapes like \x1b> (keypad) \x1b=
    text = re.sub(r'\x1b[=>]', '', text)
    
    # Remove bell characters if any remain
    text = text.replace('\x07', '')
    
    # Fallback: remove any remaining escape sequences
    text = re.sub(r'\x1b[^a-zA-Z]*[a-zA-Z]', '', text)
    
    # Remove any other control characters (except \n, \t, and \x08 backspace)
    # Backspace is preserved for process_backspaces() to handle semantically
    text = re.sub(r'[\x00-\x07\x0b\x0c\x0e-\x1f\x7f]', '', text)
    
    # Convert \r\n to \n
    text = text.replace('\r\n', '\n')
    return text


def process_backspaces(text: str) -> str:
    """
    Process backspace and carriage return characters to simulate terminal editing behavior.
    
    Handles:
    - \\x08 (Backspace): Moves cursor left (overwrites on next char)
    - \\r (Carriage Return): Moves cursor to start of line
    - \\n (Newline): Starts new line
    """
    # Use a list of lines, each line is a list of characters
    lines = []
    current_line = []
    cursor = 0
    
    for char in text:
        if char == '\n':
            lines.append(''.join(current_line))
            current_line = []
            cursor = 0
        elif char == '\r':
            cursor = 0
        elif char == '\x08':  # backspace character
            cursor = max(0, cursor - 1)
        else:
            # Normal character - write at cursor position
            if cursor >= len(current_line):
                # Extend line with spaces if needed
                current_line.extend([' '] * (cursor - len(current_line)))
                current_line.append(char)
            else:
                current_line[cursor] = char
            cursor += 1
            
    lines.append(''.join(current_line))
    return '\n'.join(lines)


def clean_command_input(raw_input: str) -> str:
    """
    Clean raw command input to extract actual command text.
    
    Removes ANSI escape codes, processes backspaces, and strips
    prompt characters that may have leaked into the input.
    
    Args:
        raw_input: Raw input string from terminal events
        
    Returns:
        Cleaned command string
    """
    # First remove ANSI escape codes
    cleaned = clean_output_for_display(raw_input)
    
    # Process backspaces to get the final text
    cleaned = process_backspaces(cleaned)
    
    # Remove complete prompt patterns (comprehensive)
    # Pattern: [user@host path]$ or user@host:path$
    cleaned = re.sub(r'^\[?[^\]\n]*[@:][^\]\n]*\]?\s*[\$#%>❯]\s*', '', cleaned)
    # Pattern: path (version) % (e.g., "~ (1.9.2-p290) % ")
    cleaned = re.sub(r'^[\w\d~./-]*\s*\([^)]+\)\s*[%>❯]\s*', '', cleaned)
    # Pattern: path % or path $ (e.g., "~ % ")
    cleaned = re.sub(r'^[\w\d~./-]+\s+[\$#%>❯]\s*', '', cleaned)
    # Pattern: simple prompt ➜, $, #, %, > at start followed by spaces
    cleaned = re.sub(r'^[➜\$#%>❯]\s+', '', cleaned)
    
    # Pattern: custom tool prompts like "dagger ch-ch-ch-changes ? ❯"
    cleaned = re.sub(r'^[^\n]*\?\s*[>❯]\s*', '', cleaned)
    
    # Pattern: git branch prompts like "[user:~/path] master ±"
    cleaned = re.sub(r'^\[[^\]]+:[^\]]+\]\s*(master|main|develop|\w+)\s*[±✓✗→]\s*', '', cleaned)
    
    # Remove directory path pattern like "~ " at start
    cleaned = re.sub(r'^~\s+', '', cleaned)
    
    # Remove newlines and extra whitespace
    cleaned = cleaned.replace('\r', '').replace('\n', '').strip()
    
    return cleaned


def is_likely_output(text: str) -> bool:
    """
    Detect if text looks like program output rather than a user command.
    
    Used to filter out false positives when inferring commands from output.
    Returns True if the text is likely output, False if it might be a command.
    """
    if not text or len(text) < 2:
        return True
    
    # apt/yum/dnf download progress patterns
    # e.g., "[2 InRelease 995 B/267 kB 0%]"
    if re.match(r'^\[[^\]]*\d+\s*(B|KB|MB|GB)/\d+', text):
        return True
    
    # Progress bar with percentage
    # e.g., "[Working] ... 50%"
    if re.match(r'^\[.*\d+%\]', text):
        return True
    
    # apt status messages
    # e.g., "[Working]", "[Waiting for headers]", "[Connecting to ...]"
    if re.match(r'^\[(Working|Waiting|Connecting|Reading|Building)', text):
        return True
    
    # wget/curl download progress
    # e.g., "50% [===>    ]" or contains download speed
    if re.search(r'\d+%\s*\[=*>?\s*\]', text):
        return True
    if re.search(r'\d+\s*(B|KB|MB|GB)/s', text):
        return True
    if re.search(r'--\.-K/s|--\.-B/s|--\.-M/s', text):
        return True
    
    # Timestamp at beginning (likely log output)
    # e.g., "00:00:00.000" or "2024-01-01"
    if re.match(r'^\d{2}:\d{2}:\d{2}', text):
        return True
    if re.match(r'^\d{4}-\d{2}-\d{2}', text):
        return True
    
    # Numeric ratio patterns (likely progress)
    # e.g., "107/107 :"
    if re.match(r'^\d+/\d+\s*:', text):
        return True
    
    # Git-style prompt that leaked into command
    # e.g., "[user:~/path] master ±"
    if re.match(r'^\[[^\]]+:[^\]]+\]\s*(master|main|develop|feature|hotfix|release|\w+)\s*[±✓✗→]', text):
        return True
    
    # Starts with special output indicators
    # e.g., "Get:", "Hit:", "Ign:", "Err:" (apt output)
    if re.match(r'^(Get|Hit|Ign|Err|Fetched|Reading|Building|Unpacking|Setting up):', text):
        return True
    
    # npm/yarn warning/error patterns
    if re.match(r'^(npm|yarn)\s+(WARN|ERR|warn|error)', text, re.IGNORECASE):
        return True
    
    # === NEW PATTERNS FOR INTERACTIVE PROGRAMS ===
    
    # ASCII art patterns - lines with mostly repeated special characters
    if len(text) > 10 and re.match(r'^[#=\-_*~+|/\\<>]{5,}$', text.strip()):
        return True
    
    # ASCII art with box/border characters
    if re.match(r'^[│┌┐└┘├┤┬┴┼╭╮╯╰║═╔╗╚╝╠╣╦╩╬\s]+$', text.strip()):
        return True
    
    # Interactive program welcome/header messages
    welcome_patterns = [
        r'^Welcome to',
        r'^Copyright',
        r'^\s*version\s+\d',
        r'^This (is|program)',
        r'^Press any key',
        r'^Type .* to',
        r'^Enter .* to',
        r'ABSOLUTELY NO WARRANTY',
        r'GNU General Public License',
        r'^Congratulations',
        r'^GAME OVER',
        r'^Loading',
        r'^score:',
        r'^lives:',
        r'^rank\s+score',
    ]
    for pattern in welcome_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    
    # Menu/help text patterns
    menu_patterns = [
        r'^[a-z],\s*[A-Z].*:',  # e.g., "q,n:quit  c:show copyright"
        r'^\s*\[[A-Z]\]\s+\w',  # e.g., "[Q] Quit"
        r':\s*(start|quit|exit|continue|help|show)',  # action hints
    ]
    for pattern in menu_patterns:
        if re.search(pattern, text):
            return True
    
    # Score/status display patterns (common in games)
    if re.match(r'^(score|level|lives|time|round|stage)\s*:', text, re.IGNORECASE):
        return True
    
    # Lines starting with special prefixes that indicate output
    output_prefixes = [
        'Error:', 'Warning:', 'Info:', 'Note:', 'Hint:',
        'SUCCESS:', 'FAILED:', 'OK:', 'DONE:',
        '>>>', '...', '>>',  # REPL prompts
        '***', '---', '===',
    ]
    for prefix in output_prefixes:
        if text.strip().startswith(prefix):
            return True
    
    # Lines that are mostly special characters or whitespace (only for longer strings)
    # Short commands like '???' or ':)' should not be filtered
    if len(text.strip()) > 15:
        alpha_ratio = sum(1 for c in text if c.isalpha()) / len(text)
        if alpha_ratio < 0.15:
            return True
    
    # Very long lines are usually not commands (commands are typically short)
    if len(text.strip()) > 200:
        return True
    
    return False


def is_valid_command(text: str) -> bool:
    """
    Validate if text looks like a valid shell command.
    
    Uses a whitelist approach to filter out obvious non-commands.
    Returns True if the text appears to be a valid command.
    """
    if not text or len(text.strip()) < 1:
        return False
    
    text = text.strip()
    first_word = text.split()[0] if text.split() else ''
    
    # Common command prefixes (extensive list)
    valid_prefixes = [
        # File operations
        'ls', 'cd', 'pwd', 'cat', 'head', 'tail', 'less', 'more', 'file',
        'cp', 'mv', 'rm', 'mkdir', 'rmdir', 'touch', 'chmod', 'chown', 'chgrp',
        'ln', 'find', 'locate', 'which', 'whereis', 'stat', 'du', 'df',
        # Text processing
        'echo', 'printf', 'grep', 'egrep', 'fgrep', 'sed', 'awk', 'cut', 'sort',
        'uniq', 'wc', 'tr', 'diff', 'patch', 'tee', 'xargs',
        # Archives
        'tar', 'gzip', 'gunzip', 'zip', 'unzip', 'bzip2', 'xz', '7z',
        # Network
        'curl', 'wget', 'ssh', 'scp', 'rsync', 'ftp', 'sftp', 'nc', 'netstat',
        'ping', 'traceroute', 'dig', 'nslookup', 'host', 'ip', 'ifconfig',
        # Package managers
        'apt', 'apt-get', 'apt-cache', 'dpkg', 'yum', 'dnf', 'rpm',
        'brew', 'port', 'pacman', 'apk', 'snap', 'flatpak',
        'pip', 'pip3', 'pipx', 'conda', 'npm', 'npx', 'yarn', 'pnpm',
        'gem', 'bundle', 'cargo', 'go', 'composer', 'maven', 'gradle',
        # Version control
        'git', 'svn', 'hg', 'cvs',
        # Editors
        'vim', 'vi', 'nvim', 'nano', 'emacs', 'code', 'subl', 'atom',
        # Build tools
        'make', 'cmake', 'ninja', 'meson', 'autoconf', 'automake',
        # Containers/VMs
        'docker', 'docker-compose', 'podman', 'kubectl', 'helm', 'vagrant',
        'terraform', 'ansible', 'puppet', 'chef',
        # Programming languages
        'python', 'python3', 'python2', 'node', 'nodejs', 'deno', 'bun',
        'ruby', 'irb', 'perl', 'php', 'java', 'javac', 'scala', 'kotlin',
        'rustc', 'cargo', 'gcc', 'g++', 'clang', 'clang++',
        'ghc', 'ghci', 'stack', 'cabal', 'julia', 'R', 'Rscript',
        # System administration
        'sudo', 'su', 'passwd', 'useradd', 'userdel', 'usermod', 'groupadd',
        'systemctl', 'service', 'journalctl', 'dmesg', 'top', 'htop', 'ps',
        'kill', 'killall', 'pkill', 'pgrep', 'nice', 'renice', 'nohup',
        'crontab', 'at', 'bg', 'fg', 'jobs', 'disown', 'screen', 'tmux',
        # Shell builtins and scripts
        'source', 'export', 'alias', 'unalias', 'set', 'unset', 'env',
        'history', 'type', 'help', 'man', 'info', 'whatis', 'apropos',
        'exit', 'logout', 'clear', 'reset', 'true', 'false', 'test',
        'read', 'eval', 'exec', 'time', 'wait', 'sleep',
        # Misc common tools
        'date', 'cal', 'bc', 'expr', 'seq', 'yes', 'watch', 'timeout',
        'xdg-open', 'open', 'pbcopy', 'pbpaste', 'xclip', 'xsel',
    ]
    
    # Check if it starts with a valid command
    for prefix in valid_prefixes:
        if first_word == prefix or first_word.endswith('/' + prefix):
            return True
    
    # Allow relative/absolute paths to executables
    if first_word.startswith('./') or first_word.startswith('/'):
        return True
    
    # Allow environment variable assignments followed by commands
    if re.match(r'^[A-Z_][A-Z0-9_]*=', text):
        return True
    
    # Allow commands with leading env vars like "FOO=bar command"
    if re.match(r'^([A-Z_][A-Z0-9_]*=[^\s]*\s+)+\w+', text):
        return True
    
    # Filter out common paths that are mistakenly identified as commands
    # e.g. /dev, /dev/shm which appear in df output
    if text.startswith('/'):
        # Valid absolute path commands usually are in bin/sbin or user/bin
        # or end with .sh, .py, etc.
        if not (re.search(r'/(s?bin|usr|opt|home|tmp|var)/', text) or 
                text.endswith(('.sh', '.py', '.pl', '.rb', '.js', '.ts'))):
            # If it's just a path like /dev/sda1, filter it out
            # Unless it's explicitly structured like an executable call
            return False
            
    return False


def calculate_confidence(command: str, prompt: str = '', is_input_derived: bool = False) -> float:
    """
    Calculate confidence score for an extracted command.
    
    Args:
        command: The extracted command text
        prompt: The prompt that preceded this command
        is_input_derived: Whether the command was derived from explicit input events (Gold Standard)
        
    Returns:
        Confidence score between 0.0 and 1.0
    """
    # High confidence for input-derived commands (Gold Standard)
    if is_input_derived:
        confidence = 1.0
        # Only penalize extremely short commands or likely artifacts
        if len(command.strip()) < 1:
            confidence = 0.5
        return confidence

    # Start with base confidence for output-inferred commands
    confidence = 0.5
    

    
    # Boost for valid command patterns (bonus only, no penalty)
    # NOTE: Removed penalty for non-whitelisted commands as it was too strict
    if is_valid_command(command):
        confidence = min(1.0, confidence + 0.2)
    
    # Boost for typical prompt patterns
    if prompt:
        # Strong prompt patterns
        if re.search(r'[\w.-]+@[\w.-]+[:\s].*[\$#]', prompt):
            confidence = min(1.0, confidence + 0.1)
        # Weak prompt (just ends with $, #, etc.)
        elif re.search(r'[\$#%>]\s*$', prompt):
            confidence = min(1.0, confidence + 0.05)
    
    # Penalize suspicious patterns in command
    suspicious_patterns = [
        r'^[<>|]',  # Starts with redirect/pipe
        r'^\d+[.:]',  # Starts with numbers (likely output)
        r'^[A-Z][a-z]+:',  # Starts with capitalized word + colon (likely output)
        r'\s{10,}',  # Excessive whitespace
        r'^[\s\-=_#*]{5,}$',  # ASCII art line
    ]
    for pattern in suspicious_patterns:
        if re.search(pattern, command):
            confidence = max(0.1, confidence - 0.2)
            break
    
    # Penalize very short or very long commands
    cmd_len = len(command.strip())
    if cmd_len < 2:
        confidence = max(0.1, confidence - 0.2)
    elif cmd_len > 150:
        confidence = max(0.1, confidence - 0.15)
    
    return round(confidence, 2)


def normalize_text_for_verification(text: str) -> str:
    """Normalize text for verification comparison."""
    # Remove ANSI escape codes
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
    # Remove CR
    text = text.replace('\r', '')
    # Remove trailing spaces from each line (these often differ between sources)
    lines = text.split('\n')
    lines = [line.rstrip() for line in lines]
    text = '\n'.join(lines)
    return text.strip()


def find_ground_truth_txt(cast_path: str) -> Optional[str]:
    """Find corresponding ground truth .txt file."""
    # Check same directory
    p1 = cast_path.replace('.cast', '.txt')
    if os.path.exists(p1):
        return p1
    
    # Check sibling txt directory (data/raw/txt vs data/raw/cast)
    dirname = os.path.dirname(cast_path)
    filename = os.path.basename(cast_path).replace('.cast', '.txt')
    
    # Try assuming current dir is data/raw/cast -> look in data/raw/txt
    # OR just look in ../txt/ relative to cast file
    parent_dir = os.path.dirname(dirname)
    p2 = os.path.join(parent_dir, 'txt', filename)
    if os.path.exists(p2):
        return p2
        
    return None


def verify_extraction(initial_output: str, turns: List[Dict], txt_content: str) -> Dict[str, Any]:
    """
    Verify extracted content against ground truth text.
    
    Reconstructs the full session text from extracted turns and compares
    with the provided ground truth text.
    """
    # Reconstruct session text
    # Note: observation.content may not have trailing space, so we may need to add space
    # before action to match format like "$ command". But don't add space if previous part
    # ends with space, newline, or is empty.
    parts = [initial_output]
    for turn in turns:
        if 'action' in turn and 'content' in turn['action']:
            action_content = turn['action']['content']
            # Add space before command only if previous part doesn't end with space or newline
            if parts and parts[-1] and not parts[-1][-1] in (' ', '\n'):
                parts.append(' ')
            parts.append(action_content + '\n')
        if 'observation' in turn and 'content' in turn['observation']:
            parts.append(turn['observation']['content'])
            
    reconstructed = ''.join(parts)
    
    clean_reconstructed = normalize_text_for_verification(reconstructed)
    clean_txt = normalize_text_for_verification(txt_content)
    
    # Calculate similarity
    matcher = difflib.SequenceMatcher(None, clean_reconstructed, clean_txt)
    # Optimization for large files
    if len(clean_reconstructed) > 50000 or len(clean_txt) > 50000:
        similarity = matcher.quick_ratio()
    else:
        similarity = matcher.ratio()
        
    return {
        'verified': True,
        'perfect_match': clean_reconstructed == clean_txt,
        'similarity': round(similarity, 4),
        'perfect_match_length_check': len(clean_reconstructed) == len(clean_txt)
    }



def detect_interactive_program(input_text: str) -> Optional[str]:
    """Detect if input is launching an interactive program."""
    programs = ['vim', 'vi', 'nano', 'emacs', 'less', 'more', 'top', 'htop', 'man', 
                'ssh', 'docker', 'kubectl', 'python', 'python3', 'node', 'irb', 'psql', 'mysql']
    words = input_text.strip().split()
    if words:
        cmd = words[0]
        for prog in programs:
            if cmd == prog or cmd.endswith('/' + prog):
                return prog
    return None


def detect_heredoc(input_text: str) -> Optional[str]:
    """Detect heredoc and return the delimiter, or None."""
    match = HEREDOC_START.search(input_text)
    if match:
        return match.group(1) or match.group(2)
    return None



def extract_turns_from_v2(metadata: Dict, events: List[Dict], verbose: bool = False) -> Tuple[str, List[Dict], str]:
    """
    Extract turns from v2 events.
    
    A turn consists of:
    - action: user input (from 'i' events, or inferred from output patterns)
    - observation: terminal output (from 'o' events)
    
    Returns:
        (initial_output, turns, raw_all_output) tuple
    """
    # First, check if there are any input events
    has_input_events = any(e['type'] == 'i' for e in events)
    
    # Collect all output for raw_all_output
    raw_all_output = ''.join(e['data'] for e in events if e['type'] == 'o')
    
    if not has_input_events:
        # No input events - infer commands from output patterns like v1
        return extract_turns_from_output_v2(metadata, events, raw_all_output)
    
    # Has input events - use standard extraction
    turns = []
    current_turn = None
    turn_id = 0
    
    # Track state
    in_alternate_screen = False
    alternate_screen_program = None
    alternate_screen_keystrokes = []
    heredoc_delimiter = None
    heredoc_content = []
    pending_input = []
    accumulated_input = []
    input_start_timestamp = None
    
    # Collect initial output (before first input)
    initial_output = ''
    found_first_input = False
    
    i = 0
    while i < len(events):
        event = events[i]
        
        # Collect output before first input
        if not found_first_input and event['type'] == 'o':
            initial_output += event['data']
            i += 1
            continue
        
        if event['type'] == 'i':
            found_first_input = True
            input_data = event['data']
            timestamp = event['timestamp']
            
            if input_start_timestamp is None:
                input_start_timestamp = timestamp
            
            # Check if we're in heredoc mode
            if heredoc_delimiter:
                heredoc_content.append(input_data)
                if heredoc_delimiter + '\n' in input_data or input_data.strip() == heredoc_delimiter:
                    full_input = ''.join(pending_input) + ''.join(heredoc_content)
                    
                    if current_turn:
                        turns.append(current_turn)
                    
                    turn_id += 1
                    current_turn = {
                        'turn_id': turn_id,
                        'timestamp': input_start_timestamp,
                        'action': {
                            'type': 'heredoc',
                            'raw_input': full_input,
                            'content': clean_output_for_display(full_input).strip()
                        },
                        'observation': {
                            'raw_output': '',
                            'content': '',
                            'duration_ms': 0
                        }
                    }
                    heredoc_delimiter = None
                    heredoc_content = []
                    pending_input = []
                    accumulated_input = []
                    input_start_timestamp = None
                i += 1
                continue
            
            # Check for alternate screen (vim, etc.)
            if in_alternate_screen:
                alternate_screen_keystrokes.append(input_data)
                i += 1
                continue
            
            # Accumulate input until we see a newline/enter
            accumulated_input.append(input_data)
            
            # Check if command is complete (ends with newline)
            if '\n' in input_data or '\r' in input_data:
                full_input = ''.join(accumulated_input)
                accumulated_input = []
                
                # Check if this starts a heredoc
                delim = detect_heredoc(full_input)
                if delim:
                    heredoc_delimiter = delim
                    pending_input = [full_input]
                    i += 1
                    continue
                
                # Regular input - start a new turn
                if current_turn:
                    turns.append(current_turn)
                
                turn_id += 1
                
                prog = detect_interactive_program(full_input)
                action_type = 'interactive_program' if prog else 'command'
                
                current_turn = {
                    'turn_id': turn_id,
                    'timestamp': input_start_timestamp or timestamp,
                    'action': {
                        'type': action_type,
                        'raw_input': full_input,
                        'content': clean_command_input(full_input),
                        'confidence': calculate_confidence(clean_command_input(full_input), is_input_derived=True)
                    },
                    'observation': {
                        'raw_output': '',
                        'content': '',
                        'duration_ms': 0
                    }
                }
                
                input_start_timestamp = None
                
                if prog:
                    current_turn['action']['program'] = prog
                    alternate_screen_program = prog
        
        elif event['type'] == 'o':
            output_data = event['data']
            
            # Check for alternate screen enter/exit
            if ALTERNATE_SCREEN_ENTER.search(output_data):
                in_alternate_screen = True
            elif ALTERNATE_SCREEN_EXIT.search(output_data):
                in_alternate_screen = False
                if current_turn and alternate_screen_keystrokes:
                    current_turn['action']['keystrokes'] = alternate_screen_keystrokes
                    current_turn['observation']['alternate_screen_used'] = True
                alternate_screen_keystrokes = []
                alternate_screen_program = None
            
            # Append to current turn's observation
            if current_turn:
                current_turn['observation']['raw_output'] += output_data
                obs_end_time = event['timestamp']
                if 'timestamp' in current_turn:
                    duration = (obs_end_time - current_turn['timestamp']) * 1000
                    current_turn['observation']['duration_ms'] = round(duration, 2)
        
        elif event['type'] == 'm':
            # Episode marker
            if current_turn:
                if 'markers' not in current_turn:
                    current_turn['markers'] = []
                current_turn['markers'].append({
                    'timestamp': event['timestamp'],
                    'data': event['data']
                })
        
        elif event['type'] == 'r':
            # Resize event
            if current_turn:
                if 'resizes' not in current_turn['observation']:
                    current_turn['observation']['resizes'] = []
                current_turn['observation']['resizes'].append(event['data'])
        
        i += 1
    
    # Don't forget the last turn
    if current_turn:
        turns.append(current_turn)
    
    # Post-process: clean up observation content
    for turn in turns:
        raw_output = turn['observation']['raw_output']
        clean_content = clean_output_for_display(raw_output)
        # Apply backspace processing to observation content
        clean_content = process_backspaces(clean_content)
        
        lines = clean_content.split('\n')
        if lines and turn['action']['content']:
            cmd = turn['action']['content']
            if lines[0].strip().startswith(cmd[:min(len(cmd), 20)]):
                lines = lines[1:]
        
        # Note: Don't strip to preserve trailing spaces after prompt (e.g., "$ ")
        turn['observation']['content'] = '\n'.join(lines)
    
    return initial_output, turns, raw_all_output


def extract_turns_from_output_v2(metadata: Dict, events: List[Dict], raw_all_output: str) -> Tuple[str, List[Dict], str]:
    """
    Extract turns from v2 events by inferring commands from output patterns.
    Used when no input events are present.
    
    Returns:
        (initial_output, turns, raw_all_output) tuple
    """
    turns = []
    turn_id = 0
    
    # Clean ANSI escape codes and process backspaces before regex matching
    cleaned_output = process_backspaces(clean_output_for_display(raw_all_output))
    
    # Try to detect prompt+command patterns
    # More strict pattern: 
    # 1. Start of line (with optional chars)
    # 2. Ends with $, #, >, %, ❯, ➜, λ, or »
    # 3. For %, ensure it's not preceded by a digit (to avoid matching "0%" in df output)
    # 4. For >, ensure it's not preceded by = (to avoid matching "==>" in Vagrant output)
    prompt_command_pattern = re.compile(
        r'(^.*?(?:(?<!\d)%|(?<![\=\-])>|[\$#&❯➜λ»])\s+)([^\r\n]+)([\r\n]+)',
        re.MULTILINE
    )
    
    matches = list(prompt_command_pattern.finditer(cleaned_output))
    
    if not matches:
        # No commands detected, return empty turns with cleaned output
        return cleaned_output, [], raw_all_output
    
    initial_output = cleaned_output[:matches[0].end(1)] if matches else cleaned_output
    
    for i, match in enumerate(matches):
        prompt = match.group(1)
        command = match.group(2).strip()
        
        # Skip empty commands
        if not command:
            continue
        
        # Clean the command first
        cleaned_command = clean_command_input(command)
        
        # Skip if this looks like program output rather than a command
        if is_likely_output(cleaned_command):
            continue
        
        # NOTE: Removed is_valid_command check as it was too strict (whitelist-based)
        # The prompt pattern match and is_likely_output filter are sufficient
        # if not is_valid_command(cleaned_command):
        #     continue
        
        # Calculate confidence score (Output inferred)
        confidence = calculate_confidence(cleaned_command, prompt=prompt, is_input_derived=False)
        
        # Skip very low confidence commands
        if confidence < 0.3:
            continue
        
        turn_id += 1
        
        # Find observation: from end of this match to start of next command (so includes next prompt)
        obs_start = match.end()
        # matches[i+1].end(1) is the end of the PROMPT of the next match
        obs_end = matches[i + 1].end(1) if i + 1 < len(matches) else len(cleaned_output)
        
        observation_raw = cleaned_output[obs_start:obs_end]
        
        # Clean the observation content (apply backspace processing)
        # Note: Don't strip to preserve trailing spaces
        cleaned_observation = process_backspaces(clean_output_for_display(observation_raw))
        
        turns.append({
            'turn_id': turn_id,
            'timestamp': 0,  # Can't determine exact timestamp without input events
            'action': {
                'type': 'command',
                'raw_input': command + '\n',
                'content': cleaned_command,
                'confidence': confidence  # NEW: Add confidence score
            },
            'observation': {
                'raw_output': prompt + command + '\n' + observation_raw,
                'content': cleaned_observation,
                'duration_ms': 0
            }
        })
    
    return initial_output, turns, raw_all_output


def extract_to_turn_based_v2(file_path: str, output_path: Optional[str] = None, 
                             verbose: bool = False) -> Dict:
    """
    Main extraction function for v2 format.
    
    Args:
        file_path: Path to the v2 .cast file
        output_path: Optional output path for JSON
        verbose: Print detailed processing info
    
    Returns:
        The extracted data structure
    """
    metadata, events = parse_v2_cast(file_path, verbose)
    initial_output, turns, raw_all_output = extract_turns_from_v2(metadata, events, verbose)
    
    # Calculate statistics
    input_events = sum(1 for e in events if e['type'] == 'i')
    output_events = sum(1 for e in events if e['type'] == 'o')
    
    result = {
        'session_metadata': {
            'terminal_size': {
                'width': metadata.get('width', 80),
                'height': metadata.get('height', 24)
            },
            'shell': metadata.get('env', {}).get('SHELL', '/bin/bash'),
            'env': metadata.get('env', {}),
            'source_file': os.path.basename(file_path),
            'original_version': 2,
            'statistics': {
                'total_events': len(events),
                'input_events': input_events,
                'output_events': output_events,
                'extracted_turns': len(turns)
            }
        },
        'initial_output': initial_output,
        'raw_all_output': raw_all_output,  # Complete raw output for verification
        'turns': turns,
        'verification': {'verified': False}  # Default
    }
    
    # Perform verification if ground truth is available
    txt_path = find_ground_truth_txt(file_path)
    if txt_path:
        try:
            with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
                txt_content = f.read()
            verification = verify_extraction(initial_output, turns, txt_content)
            result['verification'] = verification
        except Exception as e:
            if verbose:
                print(f"Verification failed: {e}")
            result['verification'] = {'verified': False, 'error': str(e)}
    
    if output_path is None:
        output_path = os.path.splitext(file_path)[0] + '.turn_based.json'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"V2 extraction complete: {output_path}")
    print(f"  - Total events: {len(events)} (input: {input_events}, output: {output_events})")
    print(f"  - Extracted turns: {len(turns)}")
    
    return result


def process_directory(target_path: str, verbose: bool = False):
    """Process all v2 cast files in a directory."""
    cast_files = glob.glob(os.path.join(target_path, "*.cast"))
    print(f"Found {len(cast_files)} cast files in {target_path}")
    
    for f in cast_files:
        try:
            extract_to_turn_based_v2(f, verbose=verbose)
        except Exception as e:
            print(f"Error processing {f}: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract turns from v2 cast files')
    parser.add_argument('path', help='Cast file or directory path')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('-o', '--output', help='Output JSON path')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.path):
        print(f"Error: Path not found: {args.path}")
        sys.exit(1)
    
    if os.path.isfile(args.path):
        extract_to_turn_based_v2(args.path, args.output, args.verbose)
    else:
        process_directory(args.path, args.verbose)
