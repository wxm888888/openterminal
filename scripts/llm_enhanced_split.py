import re
import json
from openai import OpenAI

client = OpenAI(
    api_key='sk-TiFLADXP6zKkEykXhWcK8rGGLdLmxz2WApfjQEkAOoKeFQMH',
    base_url='https://yeysai.com/v1'
)

class TerminalParser:    
    def __init__(self, model_name='gpt-5.2-2025-12-11', step4_model_name='claude-opus-4-5-20251101'):
        self.prompt_patterns = []
        self.error_marker = r'^\[Error:'
        self.model_name = model_name
        self.step4_model_name = step4_model_name

    def step1_learn_prompts(self, file_path):
        print(f"\n[1/4] LLM Analysis Prompt Pattern")
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [line.rstrip('\n') for line in f.readlines()]
        
        sample_text = '\n'.join(lines)
        
        system_prompt = """You are an expert in Terminal Prompt Recognition.

Analyze the provided terminal output text and identify all distinct prompt patterns.

⚠️ IMPORTANT: Multiple prompt types may exist within a single terminal session due to:
- Directory changes (cd command) changing the path.
- Git branch switches changing the branch name.
- Virtual environment activation/deactivation changing the environment prefix.
- Permission changes (Standard user $ vs. Root #).

Prompt Characteristics:
- Contains dynamic information such as username, hostname, path, git branch, or virtual environment.
- Ends with a special symbol (e.g., $, #, %, >, ★, ✗, etc.).
- Follows a consistent format even if the specific content changes.
- Is immediately followed by a user-inputted command.

Key Requirements for Regex Generation:
1. Generalization: The regex must be generic enough to match the same format even when content varies.
   Example: `user@host:/path1$` and `user@host:/path2$` should be matched by the same regex.
   Correct: `^[^@]+@[^:]+:[^$]+\\$\\s*`
   Incorrect: `^user@host:/path1\\$\\s*` (Too specific; only matches path1).

2. Scope: The regex must only match the prompt portion's FIRST LINE. Do not include the trailing command in the match.
   Example: For `➜ dir git:(main) ✗ command`, the match should stop after the `✗` (including any trailing whitespace).

3. Ending: The regex should end with `\\s*` (zero or more spaces). This ensures it matches the prompt even if no command followed it.

4. IMPORTANT: If a prompt is multi-line, generate a regex that matches ONLY the first line of the prompt.
   - Do NOT generate a separate regex for the second line.
   - The second line should be treated as part of the command input, not a prompt.

5. Exhaustiveness: Identify every uniquely formatted prompt, even if it only appears once in the text.

Return the result in JSON format:
{
  "patterns": [
    {
      "example": "Full example line including the command",
      "regex": "Generic regex matching ONLY the prompt FIRST LINE (ending in \\\\s*)",
      "description": "Explanation of the characteristics of this pattern"
    }
  ]
}

Example Output:
{
  "patterns": [
    {
      "example": "user@host:~/dir1$ cd /tmp",
      "regex": "^[^@]+@[^:]+:[^$]+\\\\$\\\\s*",
      "description": "Standard Bash prompt: user@host:path$"
    },
    {
      "example": "user@host|~/dir\\n> ls",
      "regex": "^[^@]+@[^|]+\\|[^\\n]+\\s*",
      "description": "Two-line prompt: first line user@host|path; do NOT create regex for the '>' line"
    }
  ]
}

Note: Ensure the regex uses double backslashes for escaping (e.g., \\s*) to remain valid within the JSON string."""
        
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"""Analyze the following terminal output and identify ALL distinct prompt patterns.

Important Notes:
- Prompts with the same format but different paths/branches should share ONE generic regex.
- However, if formats are completely different (e.g., bash-style vs. zsh-style), identify them separately.
- Ensure the regex is generic enough to match dynamic content (paths, branches, environment names, etc.).

Terminal Output:
{sample_text}

Please return generic regex patterns for all prompt types."""}
                ],
                model=self.model_name
            ).model_dump()
            
            result = response['choices'][0]['message']['content']
            
            # 解析JSON
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            
            data = json.loads(result)
            
            print(f"\n  [Step 1 Debug Info: LLM Prompt Pattern Recognition]")
            print(f"  Found {len(data.get('patterns', []))} pattern(s)\n")
            
            for idx, item in enumerate(data.get('patterns', []), 1):
                print(f"  Pattern {idx}:")
                print(f"    Example Line: {item.get('example', 'N/A')}")
                print(f"    Original Regex: {item.get('regex', 'N/A')}")
                print(f"    Description: {item.get('description', 'N/A')}")
                
                pattern = item.get('regex', '')
                if pattern:
                    # 清洗正则：去掉命名捕获组 (?<name>) → (...)
                    cleaned = re.sub(r'\(\?<[^>]+>', '(', pattern)
                    
                    # 验证正则有效性
                    try:
                        re.compile(cleaned)
                        self.prompt_patterns.append(cleaned)
                        if cleaned != pattern:
                            print(f"    Cleaned: {cleaned}")
                        print(f"    ✅ Pattern valid, added")
                    except re.error as e:
                        print(f"    ❌ Pattern invalid, skipped: {e}")
                print()
            
            return len(self.prompt_patterns) > 0
        
        except Exception as e:
            print(f"  ⚠️ LLM analysis failed: {e}")
            return False
    
    def step2_filter_fake_prompts(self, file_path):
        """Step 2: LLM filters false positive prompts (text that just happens to match the pattern)"""
        print(f"\n[2/4] LLM Filtering False Positive Prompts")
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # 收集所有匹配提示符正则的行（逐行匹配）
        candidate_prompts = []
        matched_line_nums = set()  # 避免重复添加
        
        for line_num, line in enumerate(lines, 1):
            if line_num in matched_line_nums:
                print(f"    [Debug] Line {line_num} already matched, skipping: {line.rstrip()[:50]}")
                continue
                
            line_content = line.rstrip('\n')
            print(f"    [Debug] Checking line {line_num}: {line_content[:50]}")
            
            # 检查是否匹配任何提示符模式
            matched = False
            matched_pattern = None
            matched_lines = 1  # 逐行匹配
            
            for pattern in self.prompt_patterns:
                try:
                    if re.match(pattern, line_content):
                        matched = True
                        matched_pattern = pattern
                        matched_lines = 1
                        break
                except re.error:
                    continue
            
            if matched:
                print(f"    [Debug] ✅ Matched {matched_lines} line(s) starting from line {line_num}")
                print(f"    [Debug] Pattern: {matched_pattern[:50]}...")
                
                # 标记当前行
                matched_line_nums.add(line_num)
                print(f"    [Debug] Marked line {line_num} as matched")
                
                candidate_prompts.append({
                    'line_num': line_num,
                    'content': line_content,
                    'prev_line': lines[line_num-2].rstrip('\n') if line_num > 1 else '',
                    'next_line': lines[line_num].rstrip('\n') if line_num < len(lines) else '',
                    'is_multiline': False,
                    'num_lines': 1
                })
        
        print(f"  Found {len(candidate_prompts)} candidate prompt line(s)")
        
        if not candidate_prompts:
            print(f"  ⚠️ No matching lines found")
            return set()
        
        # Print candidate details
        print(f"\n  [Step 2 Debug Info: Candidate Prompt Lines]")
        for i, c in enumerate(candidate_prompts[:10], 1):
            print(f"    Candidate {i} [Line {c['line_num']}]: {c['content'][:70]}...")
        if len(candidate_prompts) > 10:
            print(f"    ... and {len(candidate_prompts) - 10} more candidate(s)")
        
        # Let LLM determine which are real prompts
        confirmed_line_nums = self._filter_with_llm(candidate_prompts)
        
        print(f"\n  ✓ Confirmed {len(confirmed_line_nums)} real prompt(s)")
        print(f"  ✓ Filtered out {len(candidate_prompts) - len(confirmed_line_nums)} false positive(s)")
        
        return confirmed_line_nums
    
    def _filter_with_llm(self, candidates):
        """Let LLM determine which candidate lines are real prompts"""
        system_prompt = """You are an expert in Terminal Prompt Verification. Determine which lines are real prompts and which are just text that happens to match the regex pattern.

Real Prompt Characteristics:
1. Position: Usually appears after command output, before a new command.
2. Context: Previous line is command output (or blank), followed by a command (or blank).
3. Function: Marks the beginning of new user input.

False Positives (should be filtered):
1. Text in command output that resembles a prompt
   Example: echo "user@host:~$ this is just text"
2. Text in program logs or error messages
3. Text in file contents or code snippets

Return JSON format:
{
  "confirmed_prompts": [list of line numbers for real prompts],
  "false_positives": [
    {"line_num": line number of false prompt, "reason": "why it's considered false"}
  ]
}

Note: If uncertain, lean towards considering it a real prompt (conservative strategy)."""
        
        # Build candidate list (max 50)
        candidates_text = []
        for c in candidates:
            candidates_text.append(f"""
Line {c['line_num']}:
  Previous: {c['prev_line'][:100] if c['prev_line'] else '(start of file)'}
  [Current]: {c['content'][:100]}
  Next: {c['next_line'][:100] if c['next_line'] else '(end of file)'}
""")
        
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Determine which of the following candidate lines are real prompts:{''.join(candidates_text)}\n\nPlease analyze line by line and provide a list of confirmed real prompt line numbers."}
                ],
                model=self.model_name,
                temperature=0.3
            ).model_dump()
            
            result = response['choices'][0]['message']['content']
            
            # 解析JSON
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            
            data = json.loads(result)
            
            confirmed = set(data.get('confirmed_prompts', []))
            false_positives = data.get('false_positives', [])
            
            # Print filtered false positives
            if false_positives:
                print(f"\n  [Filtered False Positives]")
                for fp in false_positives[:10]:
                    print(f"    Line {fp['line_num']}: {fp.get('reason', 'N/A')[:80]}")
            
            return confirmed
        
        except Exception as e:
            print(f"  ⚠️ LLM filtering failed: {e}")
            # On failure, return all candidates (conservative strategy)
            return set(c['line_num'] for c in candidates)
    
    def step3_parse_turns(self, file_path, confirmed_line_nums):
        """Step 3: Segment turns using confirmed prompt lines and LLM to distinguish action/observation"""
        print(f"\n[3/4] Segmenting Turns Using Confirmed Prompts + LLM Action/Observation Classification")
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        result = {
            "initial_output": "",
            "turns": []
        }
        
        current_turn = None
        turn_id = 0
        initial_lines = []
        in_initial = True
        
        # 第一遍：根据提示符分割轮次，收集每轮的 raw_lines
        for line_num, line in enumerate(lines, 1):
            line = line.rstrip('\n')
            
            # 只在确认的行号上识别提示符
            is_prompt = False
            matched_pattern = None
            
            if line_num in confirmed_line_nums:
                for pattern in self.prompt_patterns:
                    try:
                        match = re.match(pattern, line)
                        if match:
                            is_prompt = True
                            matched_pattern = (pattern, match, 1)
                            break
                    except re.error:
                        continue
            
            if is_prompt:
                # 保存上一轮
                if current_turn is not None:
                    result["turns"].append(current_turn)
                
                # 开始新一轮
                in_initial = False
                turn_id += 1
                
                pattern_str, match, _ = matched_pattern
                
                # 提取 prompt 字符串（仅第一行）
                prompt_str = line[:match.end()]
                
                current_turn = {
                    "turn_id": turn_id,
                    "prompt": prompt_str,
                    "raw_lines": [line],
                    "action": {
                        "content": "",  # 由 LLM 填充
                        "raw_prompt_line": line
                    },
                    "observation": {
                        "content": "",
                        "raw_output_lines": []
                    },
                    "metadata": {
                        "has_error": False,
                        "matched_pattern": pattern_str
                    }
                }
            else:
                # 非提示符行
                if in_initial:
                    initial_lines.append(line)
                elif current_turn is not None:
                    current_turn["raw_lines"].append(line)
                    
                    # 检查错误标记
                    if re.match(self.error_marker, line):
                        current_turn["metadata"]["has_error"] = True
        
        # 保存最后一轮
        if current_turn is not None:
            result["turns"].append(current_turn)
        
        result["initial_output"] = '\n'.join(initial_lines)
        
        print(f"  ✓ Segmented into {len(result['turns'])} turn(s)")
        
        # 第二遍：使用 LLM 区分每轮的 action 和 observation
        if result['turns']:
            print(f"\n  [Using LLM to classify action/observation for each turn]")
            for i, turn in enumerate(result['turns']):
                print(f"    Processing turn {turn['turn_id']}/{len(result['turns'])}...", end=' ')
                self._llm_classify_action_observation(turn)
                print(f"Done")
        
        # Print prompt matching details for each turn
        if result['turns']:
            print(f"\n  [Step 3 Debug Info: Turn Prompt Matching Details]")
            
            # Count how many turns each pattern matched
            pattern_counts = {}
            for turn in result['turns']:
                pattern = turn['metadata'].get('matched_pattern', 'unknown')
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
            
            print(f"  Pattern Usage Statistics:")
            for idx, (pattern, count) in enumerate(pattern_counts.items(), 1):
                print(f"    Pattern {idx}: {count} turn(s)")
                print(f"    Regex: {pattern[:80]}{'...' if len(pattern) > 80 else ''}")
            
            print(f"\n  First 5 Turn Details:")
            for turn in result['turns'][:5]:
                prompt = turn.get('prompt', '')
                command = turn['action']['content']
                matched_pattern = turn['metadata'].get('matched_pattern', 'unknown')
                pattern_idx = list(pattern_counts.keys()).index(matched_pattern) + 1 if matched_pattern in pattern_counts else 0
                
                print(f"  Turn {turn['turn_id']} [Pattern {pattern_idx}]:")
                print(f"    Prompt: {prompt}")
                print(f"    Command: {command if command else '(empty)'}")
                print(f"    Output lines: {len(turn['observation']['raw_output_lines'])}")
            
            if len(result['turns']) > 5:
                print(f"  ... and {len(result['turns']) - 5} more turn(s)")
        
        return result
    
    def _llm_classify_action_observation(self, turn):
        """Use LLM to classify action (command) and observation (output) from raw_lines"""
        system_prompt = """You are an expert in Terminal Command/Output Classification.

Given the raw lines of a terminal turn, classify which part is the user's command (action) and which part is the command's output (observation).

Key Principles:
1. The first line usually contains: prompt + command
2. Multi-line commands use continuation (lines ending with \\) - these should ALL be part of the action
3. Command parameters/arguments that span multiple lines are part of the action
4. Everything after the complete command is the observation (output)
5. The prompt itself is NOT part of the action content

Common Patterns:
- Single-line command: Line 1 has prompt + command, Lines 2+ are output
- Multi-line command with \\: Multiple lines form the command, then output follows
- Here-doc (<<EOF): Everything until EOF is part of the command input
- Interactive commands: May have interleaved input/output

Return JSON format:
{
  "action_content": "The complete command (without prompt, backslashes removed, multi-line merged with spaces)",
  "observation_lines": ["line1 of output", "line2 of output", ...]
}

Example 1 - Single line:
Raw lines:
  user@host:~$ ls -la
  total 8
  drwxr-xr-x 2 user user 4096 Jan 1 00:00 .

Result:
{
  "action_content": "ls -la",
  "observation_lines": ["total 8", "drwxr-xr-x 2 user user 4096 Jan 1 00:00 ."]
}

Example 2 - Multi-line command:
Raw lines:
  $ docker run \\
    --name test \\
    -p 8080:80 \\
    nginx
  Unable to find image 'nginx:latest' locally

Result:
{
  "action_content": "docker run --name test -p 8080:80 nginx",
  "observation_lines": ["Unable to find image 'nginx:latest' locally"]
}"""
        
        # Build raw lines display
        raw_lines_text = '\n'.join([
            f"  {i+1}. {line}" 
            for i, line in enumerate(turn['raw_lines'])
        ])
        
        user_message = f"""Classify the action (command) and observation (output) from these raw lines:

[Raw Lines] ({len(turn['raw_lines'])} line(s))
{raw_lines_text}

[Prompt detected]: {turn['prompt']}

Please return the action content (command without prompt) and observation lines (output)."""
        
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=self.model_name,
                temperature=0.2
            ).model_dump()
            
            result = response['choices'][0]['message']['content']
            
            # 解析JSON
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            
            data = json.loads(result)
            
            # 填充 action
            turn['action']['content'] = data.get('action_content', '').strip()
            
            # 填充 observation
            obs_lines = data.get('observation_lines', [])
            if isinstance(obs_lines, list):
                turn['observation']['raw_output_lines'] = [line for line in obs_lines if line.strip()]
                turn['observation']['content'] = '\n'.join(turn['observation']['raw_output_lines'])
            else:
                # 如果返回的是字符串
                turn['observation']['content'] = str(obs_lines).strip()
                turn['observation']['raw_output_lines'] = [
                    line for line in turn['observation']['content'].split('\n') if line.strip()
                ]
        
        except Exception as e:
            # LLM 失败时，使用简单的回退逻辑
            print(f"(LLM failed: {e}, using fallback)")
            
            # 回退逻辑：第一行提示符后面是命令，其余是输出
            if turn['raw_lines']:
                first_line = turn['raw_lines'][0]
                prompt = turn['prompt']
                if first_line.startswith(prompt):
                    turn['action']['content'] = first_line[len(prompt):].strip()
                else:
                    turn['action']['content'] = first_line.strip()
                
                # 其余行作为输出
                turn['observation']['raw_output_lines'] = [
                    line for line in turn['raw_lines'][1:] if line.strip()
                ]
                turn['observation']['content'] = '\n'.join(turn['observation']['raw_output_lines'])
    
    def step4_verify_turns(self, input_file, parsed_result):
        """Step 4: LLM verifies each turn using raw txt + parsed json"""
        print(f"\n[4/4] LLM Verifying Turns Using Raw TXT + Parsed JSON")
        
        turns = parsed_result.get('turns', [])
        if not turns:
            print("  ⚠️ No turns to verify")
            return []
        
        with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
            raw_text = f.read()
        
        system_prompt = """You are an expert in Terminal Turn Verification.
You will receive:
1) The raw terminal txt file content
2) The parsed JSON turns produced by a model

Your task:
- For EACH turn, determine whether there are writing/segmentation mistakes in the parsed result
- Determine whether the turn is empty (no command and no output)
- Decide whether the turn should be deleted
- If correction is needed and the turn should NOT be deleted, return corrected action and observation content

Return JSON format:
{
  "turns": [
    {
      "turn_id": 1,
      "is_correct": true/false,
      "issue": "If incorrect, describe the issue (concise, one sentence)",
      "is_empty": true/false,
      "should_delete": true/false,
      "corrected_turn": {
        "action": { "content": "Corrected command (merged, no prompt)" },
        "observation": { "content": "Corrected output only" }
      }
    }
  ]
}

Rules:
- Use the raw txt as ground truth.
- If uncertain, prefer keeping the turn (should_delete=false).
- If BOTH action content and observation content are empty, you MUST set is_empty=true and should_delete=true.
- If is_empty=true, set should_delete=true unless there is a strong reason to keep it.
- If is_correct=true, omit corrected_turn or leave it empty."""
        
        user_message = json.dumps({
            "raw_txt": raw_text,
            "parsed_json": {
                "file_path": parsed_result.get('file_path', input_file),
                "total_turns": len(turns),
                "turns": turns
            }
        }, ensure_ascii=False)
        
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=self.step4_model_name,
                temperature=0.2
            ).model_dump()
            
            result = response['choices'][0]['message']['content']
            
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            
            data = json.loads(result)
            verification_results = data.get('turns', [])
        
        except Exception as e:
            print(f"  ⚠️ LLM verification failed: {e}")
            # Fallback: mark all turns as correct, do not delete
            verification_results = [
                {
                    'turn_id': t.get('turn_id'),
                    'is_correct': True,
                    'issue': '',
                    'is_empty': False,
                    'should_delete': False
                } for t in turns
            ]
        
        # Apply corrections and deletions
        issues_found = 0
        corrected_count = 0
        turns_to_delete = []
        
        verification_map = {v.get('turn_id'): v for v in verification_results}
        
        for i in range(len(turns)):
            v = verification_map.get(turns[i].get('turn_id'))
            if not v:
                continue
            
            if not v.get('is_correct', True):
                issues_found += 1
                print(f"\n  [Step 4 Debug Info: Issue Found]")
                print(f"  ⚠️ Turn {turns[i]['turn_id']}: {v.get('issue', '')[:80]}...")
                
                if v.get('should_delete', False):
                    turns_to_delete.append(i)
                    print(f"    🗑️  Marked for deletion: Turn {turns[i]['turn_id']} will be removed")
                else:
                    corrected = v.get('corrected_turn', {})
                    if 'action' in corrected and 'content' in corrected['action']:
                        turns[i]['action']['content'] = corrected['action']['content']
                        print(f"    ✅ Command corrected: {corrected['action']['content'][:60]}...")
                    
                    if 'observation' in corrected and 'content' in corrected['observation']:
                        new_output = corrected['observation']['content']
                        turns[i]['observation']['content'] = new_output
                        turns[i]['observation']['raw_output_lines'] = [
                            line for line in new_output.split('\n') if line.strip()
                        ]
                        print(f"    ✅ Output corrected ({len(turns[i]['observation']['raw_output_lines'])} line(s))")
                    
                    if corrected:
                        corrected_count += 1
        
        deleted_count = 0
        if turns_to_delete:
            print(f"\n  [Deleting Redundant Turns]")
            for i in sorted(turns_to_delete, reverse=True):
                deleted_turn = turns.pop(i)
                deleted_count += 1
                print(f"    ✅ Deleted Turn {deleted_turn['turn_id']} (index {i})")
            
            print(f"\n  [Reassigning Turn IDs]")
            for i, turn in enumerate(turns, 1):
                old_id = turn['turn_id']
                turn['turn_id'] = i
                if old_id != i:
                    print(f"    Turn {old_id} → {i}")
        
        print(f"\n  ✓ Verification complete! {len(turns) - issues_found + deleted_count}/{len(turns) + deleted_count} turn(s) correct")
        if corrected_count > 0:
            print(f"  ✅ Auto-corrected {corrected_count} turn(s)")
        if deleted_count > 0:
            print(f"  🗑️  Deleted {deleted_count} redundant turn(s)")
        
        return verification_results
    
def parse_terminal_file(input_file, parsed_output=None, verified_output=None, model_name='gpt-5.2-2025-12-11', step4_model_name='claude-opus-4-5-20251101'):
    """
    Main workflow: 4-step process, saving both parsed and verified JSON separately
    1. LLM analyzes first 100 lines, learns prompt patterns
    2. LLM filters false positive prompts (text that just happens to match)
    3. Segment turns using confirmed prompt lines → save to parsed_output
    4. LLM verifies each turn and corrects → save to verified_output
    """
    parser = TerminalParser(model_name=model_name, step4_model_name=step4_model_name)
    
    print("="*70)
    print("Enhanced Terminal Parser - LLM 4-Step Process")
    print("="*70)
    print("""
Workflow:
  [1/4] LLM analyzes first 100 lines → Learn prompt regex patterns
  [2/4] LLM filters false positives → Confirm which lines are real prompts
  [3/4] Use confirmed prompt lines → Segment turns
  [4/4] LLM verifies each turn → Auto-correct errors
    """)
    
    # Step 1: Learn prompts
    success = parser.step1_learn_prompts(input_file)
    if not success or len(parser.prompt_patterns) == 0:
        print("  ⚠️ No prompts identified, using default patterns")
        parser.prompt_patterns = [r'^[\$\#\%>]\s*']
    
    # Step 2: Filter false positives
    confirmed_line_nums = parser.step2_filter_fake_prompts(input_file)
    if not confirmed_line_nums:
        print("  ⚠️ No prompt lines confirmed, will use all matched lines")
        # If LLM filtering fails, collect all matched lines
        with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        confirmed_line_nums = set()
        for line_num, line in enumerate(lines, 1):
            for pattern in parser.prompt_patterns:
                try:
                    if re.match(pattern, line.rstrip('\n')):
                        confirmed_line_nums.add(line_num)
                        break
                except re.error:
                    continue
    
    # Step 3: Segment turns
    parsed_data = parser.step3_parse_turns(input_file, confirmed_line_nums)
    
    # Save Step 3 raw parsing result
    parsed_result = {
        "file_path": input_file,
        "total_turns": len(parsed_data['turns']),
        "initial_output": parsed_data["initial_output"],
        "turns": parsed_data["turns"],
        "learned_patterns": parser.prompt_patterns,
        "confirmed_prompt_lines": sorted(list(confirmed_line_nums))
    }
    
    if parsed_output:
        with open(parsed_output, 'w', encoding='utf-8') as f:
            json.dump(parsed_result, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Raw parsing result saved to: {parsed_output}")
    
    # Step 4: Verify turns (will modify parsed_data['turns'])
    verification_results = []
    if len(parsed_data['turns']) > 0:
        # Deep copy for verification and correction
        import copy
        turns_for_verification = copy.deepcopy(parsed_data['turns'])
        parsed_for_verification = {
            "file_path": input_file,
            "total_turns": len(turns_for_verification),
            "initial_output": parsed_data["initial_output"],
            "turns": turns_for_verification,
            "learned_patterns": parser.prompt_patterns,
            "confirmed_prompt_lines": sorted(list(confirmed_line_nums))
        }
        verification_results = parser.step4_verify_turns(input_file, parsed_for_verification)
        
        # Save verified and corrected result
        verified_result = {
            "file_path": input_file,
            "total_turns": len(turns_for_verification),
            "initial_output": parsed_data["initial_output"],
            "turns": turns_for_verification,  # 使用修正后的轮次
            "learned_patterns": parser.prompt_patterns,
            "confirmed_prompt_lines": sorted(list(confirmed_line_nums)),
            "verification_results": verification_results
        }
        
        if verified_output:
            with open(verified_output, 'w', encoding='utf-8') as f:
                json.dump(verified_result, f, ensure_ascii=False, indent=2)
            print(f"✓ Verified and corrected result saved to: {verified_output}")
    else:
        print("\n[4/4] Verification skipped (no turns found)")
        verified_result = parsed_result  # If no turns, verified result equals parsed result
    
    # Return verified result for display
    final_result = verified_result if len(parsed_data['turns']) > 0 else parsed_result
    
    # Print summary
    print(f"\n{'='*70}")
    print(f"Parsing Summary")
    print(f"{'='*70}")
    print(f"File: {input_file}")
    print(f"Confirmed prompt lines: {len(confirmed_line_nums)} line(s)")
    print(f"Raw parsed turns: {len(parsed_result['turns'])}")
    print(f"Verified turns: {len(final_result['turns'])}")
    print(f"Learned patterns: {len(parser.prompt_patterns)}")
    
    if parser.prompt_patterns:
        print(f"\nIdentified Prompt Patterns ({len(parser.prompt_patterns)} total):")
        
        # Count usage of each pattern
        pattern_usage = {}
        for turn in final_result['turns']:
            pattern = turn['metadata'].get('matched_pattern', '')
            if pattern in parser.prompt_patterns:
                pattern_usage[pattern] = pattern_usage.get(pattern, 0) + 1
        
        for i, p in enumerate(parser.prompt_patterns, 1):
            usage_count = pattern_usage.get(p, 0)
            print(f"  Pattern {i}: {p}")
            print(f"              Usage count: {usage_count}")
    
    # Debug info summary
    print(f"\n{'='*70}")
    print(f"Debug Information Summary")
    print(f"{'='*70}")
    print(f"Step 1 - Learn patterns: {len(parser.prompt_patterns)} regex pattern(s)")
    print(f"Step 2 - Filter false positives: {len(confirmed_line_nums)} line(s) confirmed as real prompts")
    print(f"Step 3 - Segment turns: {len(parsed_result['turns'])} turn(s) → saved to {parsed_output}")
    if verification_results:
        corrected = sum(1 for v in verification_results if not v['is_correct'] and not v.get('should_delete'))
        deleted = sum(1 for v in verification_results if v.get('should_delete'))
        print(f"Step 4 - Verify & correct: {corrected} turn(s) corrected, {deleted} turn(s) deleted → saved to {verified_output}")
    
    if verification_results:
        correct = sum(1 for v in verification_results if v['is_correct'])
        print(f"\nVerification result: {correct}/{len(verification_results)} turn(s) correct")
    
    return final_result

def one_model_parse(input_file, model_name='gpt-5.2-2025-12-11'):
    result = parse_terminal_file(
        input_file=input_file,
        parsed_output=None,      # 不保存原始解析结果
        verified_output=None,     # 不保存验证结果
        model_name=model_name
    )
    return result

if __name__ == "__main__":
    # Default: parse 3.txt, save both raw and verified results separately
    result = parse_terminal_file(
        input_file='data/raw/txt/100053.txt',
        parsed_output='data/analyzed/100053_parsed.json',      # Raw parsing result
        verified_output='data/analyzed/100053_verified.json',  # Verified and corrected result
        model_name='gpt-5.2-2025-12-11'
    )