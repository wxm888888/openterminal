import re
import json
import os
from pathlib import Path
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key='sk-vTUtgFvIecBHF9XpZvg0OVFYYexMSZGayAmtFKjWvX5PFt10',
    base_url='https://yeysai.com/v1'
)

class TerminalParser:    
    def __init__(self, model_name='qwen3-8b', step4_model_name='claude-sonnet-4-20250514'):
        self.prompt_patterns = []
        self.model_name = model_name
        self.step4_model_name = step4_model_name

    async def step1_learn_prompts(self, file_path):
        print(f"\n{'='*60}")
        print(f"[Step 1] Learning prompt patterns from: {file_path}")
        print(f"{'='*60}")

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [line.rstrip('\n') for line in f.readlines()]

        print(f"Total lines in file: {len(lines)}")
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
            response = await client.chat.completions.create(
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
            )
            
            result = response.choices[0].message.content
            
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            
            data = json.loads(result)

            print(f"\n[Step 1] LLM identified {len(data.get('patterns', []))} prompt patterns:")

            for item in data.get('patterns', []):
                pattern = item.get('regex', '')
                if pattern:
                    cleaned = re.sub(r'\(\?<[^>]+>', '(', pattern)

                    try:
                        re.compile(cleaned)
                        self.prompt_patterns.append(cleaned)
                        print(f"  ✓ Pattern: {cleaned[:80]}")
                        print(f"    Example: {item.get('example', 'N/A')[:80]}")
                    except re.error:
                        print(f"  ✗ Invalid pattern (skipped): {cleaned[:80]}")
                        pass

            print(f"\n[Step 1] Result: {len(self.prompt_patterns)} valid patterns learned")
            return len(self.prompt_patterns) > 0

        except Exception as e:
            print(f"\n[Step 1] Error: {str(e)}")
            return False
    
    async def step2_filter_fake_prompts(self, file_path):
        print(f"\n{'='*60}")
        print(f"[Step 2] Filtering fake prompts")
        print(f"{'='*60}")

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        candidate_prompts = []
        matched_line_nums = set()
        
        for line_num, line in enumerate(lines, 1):
            if line_num in matched_line_nums:
                continue
                
            line_content = line.rstrip('\n')
            
            matched = False
            matched_pattern = None
            matched_lines = 1
            
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
                matched_line_nums.add(line_num)
                
                candidate_prompts.append({
                    'line_num': line_num,
                    'content': line_content,
                    'prev_line': lines[line_num-2].rstrip('\n') if line_num > 1 else '',
                    'next_line': lines[line_num].rstrip('\n') if line_num < len(lines) else '',
                    'is_multiline': False,
                    'num_lines': 1
                })

        if not candidate_prompts:
            print(f"\n[Step 2] No candidate prompts found by regex matching")
            return set()

        print(f"\n[Step 2] Found {len(candidate_prompts)} candidate prompts by regex")
        print(f"[Step 2] Sending to LLM for verification...")

        confirmed_line_nums = await self._filter_with_llm(candidate_prompts)

        print(f"\n[Step 2] Result: {len(confirmed_line_nums)} confirmed real prompts")
        print(f"[Step 2] Confirmed line numbers: {sorted(list(confirmed_line_nums))[:10]}{'...' if len(confirmed_line_nums) > 10 else ''}")

        return confirmed_line_nums
    
    async def _filter_with_llm(self, candidates):
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
        
        candidates_text = []
        for c in candidates:
            candidates_text.append(f"""
Line {c['line_num']}:
  Previous: {c['prev_line'][:100] if c['prev_line'] else '(start of file)'}
  [Current]: {c['content'][:100]}
  Next: {c['next_line'][:100] if c['next_line'] else '(end of file)'}
""")
        
        try:
            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Determine which of the following candidate lines are real prompts:{''.join(candidates_text)}\n\nPlease analyze line by line and provide a list of confirmed real prompt line numbers."}
                ],
                model=self.model_name,
                temperature=0.3
            )
            
            result = response.choices[0].message.content
            
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            
            data = json.loads(result)
            
            confirmed = set(data.get('confirmed_prompts', []))
            
            return confirmed
        
        except Exception:
            return set(c['line_num'] for c in candidates)
    
    async def step3_parse_turns(self, file_path, confirmed_line_nums):
        print(f"\n{'='*60}")
        print(f"[Step 3] Parsing turns from confirmed prompts")
        print(f"{'='*60}")

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
        
        for line_num, line in enumerate(lines, 1):
            line = line.rstrip('\n')
            
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
                if current_turn is not None:
                    result["turns"].append(current_turn)
                
                in_initial = False
                turn_id += 1
                
                pattern_str, match, _ = matched_pattern
                
                prompt_str = line[:match.end()]
                
                current_turn = {
                    "turn_id": turn_id,
                    "prompt": prompt_str,
                    "raw_lines": [line],
                    "action": {
                        "content": ""
                    },
                    "observation": {
                        "content": ""
                    },
                }
            else:
                if in_initial:
                    initial_lines.append(line)
                elif current_turn is not None:
                    current_turn["raw_lines"].append(line)
                            
        if current_turn is not None:
            result["turns"].append(current_turn)
        
        result["initial_output"] = '\n'.join(initial_lines)

        print(f"\n[Step 3] Parsed {len(result['turns'])} turns")
        print(f"[Step 3] Initial output: {len(initial_lines)} lines")

        if result['turns']:
            print(f"[Step 3] Classifying actions and observations with LLM...")
            import asyncio
            tasks = []
            for turn in result['turns']:
                tasks.append(self._llm_classify_action_observation(turn))
            await asyncio.gather(*tasks)

            print(f"[Step 3] Turn classification completed")
            for i, turn in enumerate(result['turns'][:3], 1):
                print(f"  Turn {i}: action={len(turn['action']['content'])} chars, obs={len(turn['observation']['content'])} chars")
            if len(result['turns']) > 3:
                print(f"  ... and {len(result['turns']) - 3} more turns")

        # 删除仅用于内部处理的 raw_lines 字段
        for turn in result['turns']:
            if 'raw_lines' in turn:
                del turn['raw_lines']

        return result

    async def _llm_classify_action_observation(self, turn):
        system_prompt = """You are an expert in Terminal Command/Output Classification.

Given the raw lines of a terminal turn, classify which part is the prompt, which part is the user's command (action), and which part is the command's output (observation).

Key Principles:
1. The prompt may be single-line or multi-line (e.g., two-line prompts like "user@host|~/path\\n> ")
2. After the prompt comes the command (may be on the same line as the last prompt line, or on separate lines)
3. Multi-line commands use continuation (e.g., lines ending with \\) - these should ALL be part of the action
4. Command parameters/arguments that span multiple lines are part of the action
5. Everything after the complete command is the observation (output)
6. The prompt itself is NOT part of the action content

Common Patterns:
- Single-line prompt: "user@host:~$ command" - prompt is "user@host:~$"
- Multi-line prompt: "user@host|~/path\\n> command" - prompt is "user@host|~/path\\n>"
- Multi-line command (e.g., with \\): Multiple lines form the command, then output follows
- Here-doc (<<EOF): Everything until EOF is part of the command input
- Interactive commands: May have interleaved input/output

Return JSON format:
{
  "prompt": "The complete prompt (may be multi-line, use \\n for line breaks)",
  "action_lines": ["line1 of command", "line2 of command", ...],
  "observation_lines": ["line1 of output", "line2 of output", ...]
}

Example 1 - Single line prompt:
Raw lines:
  user@host:~$ ls -la
  total 8
  drwxr-xr-x 2 user user 4096 Jan 1 00:00 .

Result:
{
  "prompt": "user@host:~$ ",
  "action_lines": ["ls -la"],
  "observation_lines": ["total 8", "drwxr-xr-x 2 user user 4096 Jan 1 00:00 ."]
}

Example 2 - Multi-line prompt:
Raw lines:
  user@host|~/documents
  > ls -la
  total 8
  drwxr-xr-x 2 user user 4096 Jan 1 00:00 .

Result:
{
  "prompt": "user@host|~/documents\\n> ",
  "action_lines": ["ls -la"],
  "observation_lines": ["total 8", "drwxr-xr-x 2 user user 4096 Jan 1 00:00 ."]
}

Example 3 - Multi-line command:
Raw lines:
  $ docker run \\
    --name test \\
    -p 8080:80 \\
    nginx
  Unable to find image 'nginx:latest' locally。

Result:
{
  "prompt": "$ ",
  "action_lines": ["docker run \\", "--name test \\", "-p 8080:80 \\", "nginx"],
  "observation_lines": ["Unable to find image 'nginx:latest' locally"]
}"""

        raw_lines_text = '\n'.join([
            f"  {i+1}. {line}"
            for i, line in enumerate(turn['raw_lines'])
        ])

        user_message = f"""Classify the prompt, action (command), and observation (output) from these raw lines:

[Raw Lines] ({len(turn['raw_lines'])} line(s))
{raw_lines_text}

[Initial prompt detected by regex]: {turn['prompt']}

Please extract the complete prompt (including all prompt lines if multi-line), the action lines (command without prompt) as a list, and observation lines (output) as a list."""

        try:
            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=self.model_name,
                temperature=0.2
            )

            result = response.choices[0].message.content

            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]

            data = json.loads(result)

            extracted_prompt = data.get('prompt', '').strip()
            if extracted_prompt:
                turn['prompt'] = extracted_prompt

            action_lines = data.get('action_lines', [])
            if isinstance(action_lines, list):
                turn['action']['content'] = '\n'.join(action_lines)
            else:
                turn['action']['content'] = str(action_lines).strip()

            obs_lines = data.get('observation_lines', [])
            if isinstance(obs_lines, list):
                turn['observation']['content'] = '\n'.join([line for line in obs_lines if line.strip()])
            else:
                turn['observation']['content'] = str(obs_lines).strip()

        except Exception:
            if turn['raw_lines']:
                first_line = turn['raw_lines'][0]
                prompt = turn['prompt']
                if first_line.startswith(prompt):
                    turn['action']['content'] = first_line[len(prompt):].strip()
                else:
                    turn['action']['content'] = first_line.strip()

                turn['observation']['content'] = '\n'.join([
                    line for line in turn['raw_lines'][1:] if line.strip()
                ])
    
    async def step4_verify_turns(self, input_file, parsed_result):
        print(f"\n{'='*60}")
        print(f"[Step 4] Verifying turns with LLM")
        print(f"{'='*60}")

        turns = parsed_result.get('turns', [])
        if not turns:
            print(f"[Step 4] No turns to verify")
            return []

        print(f"[Step 4] Verifying {len(turns)} turns...")

        with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
            raw_text = f.read()

        initial_output = parsed_result.get('initial_output', '')

        system_prompt = """You are an expert in Terminal Turn Verification.
You will receive:
1) The raw terminal txt file content
2) The parsed JSON with initial_output and turns

Your task:
1. FIRST: Check if initial_output contains any missed command executions (command-output pairs that were not parsed as turns). If found, extract them as new turns AND rewrite the corrected initial_output by removing those command executions. The initial_output must contain all raw text content occurring strictly before the very first command-line prompt, which typically includes system login banners (e.g., "Welcome to Ubuntu..."), "Last login" timestamps, or environment initialization logs. Note that the initial_output can be an empty string
2. SECOND: If no missed command executions were found, check if initial_output is correctly extracted
3. THIRD: For EACH turn, determine whether there are writing/segmentation mistakes in the parsed result. If correction is needed, return corrected action and observation content
4. FOURTH: If a single turn actually contains MULTIPLE command executions (multiple prompts, commands and outputs), split it into multiple turns

Return JSON format:
{
  "initial_output_correct": true/false,
  "initial_output_issue": "If incorrect, describe the issue",
  "corrected_initial_output": "Corrected initial output if needed",
  "missed_turns_in_initial_output": [
    {
      "prompt": "The prompt string (may be empty string \"\" if no prompt detected)",
      "action": { "content": "The command content" },
      "observation": { "content": "The command output" }
    },
    ...
  ],
  "turns": [
    {
      "turn_id": 1,
      "is_correct": true/false,
      "issue": "If incorrect, describe the issue (concise, one sentence)",
      "should_split": true/false,
      "split_into_turns": [
        {
          "prompt": "The actual prompt string detected in first turn (e.g., user@host:~$ or empty string \"\")",
          "action": { "content": "The specific command content for this split" },
          "observation": { "content": "The specific command output for this split" }
        },
        {
          "prompt": "The actual prompt string detected in second turn (e.g., user@host:~$ or empty string \"\")",
          "action": { "content": "The specific command content for this split" },
          "observation": { "content": "The specific command output for this split" }
        },
        ...
      ],
      "corrected_turn": {
        "action": { "content": "Corrected command (merged, no prompt)" },
        "observation": { "content": "Corrected output only" }
      }
    },
    ...
  ]
}

Rules:
- Always use the raw txt as ground truth
- First check initial_output for missed command executions:
  * Check if initial_output contains any missed command executions (command-output pairs that should have been parsed as turns)
  * If found: set initial_output_correct=false, add them to missed_turns_in_initial_output array, AND provide corrected_initial_output by removing the command execution content (keep only the true initial content before any commands)
  * If no missed turns found: omit missed_turns_in_initial_output field, then proceed to check initial_output correctness
- Then check initial_output correctness (only if no missed turns were found):
  * If correct: set initial_output_correct=true, and omit both initial_output_issue and corrected_initial_output
  * If incorrect: set initial_output_correct=false, provide initial_output_issue describing the problem, and provide corrected_initial_output with the corrected content
- For each turn, first check if it contains multiple command executions (multiple prompts or multiple command-output pairs):
  * If yes: set should_split=true, then provide split_into_turns array with 2+ turns, and do NOT provide corrected_turn
  * When splitting turns, the "prompt" field may be empty string "" if no prompt is detected before a command
  * If no: continue to next step
- If the turn doesn't need splitting, check if there are writing/segmentation mistakes:
  * If the turn is correct: set is_correct=true, should_split=false, and omit both corrected_turn and split_into_turns
  * If the turn has mistakes but doesn't need splitting: set is_correct=false, should_split=false, then provide corrected_turn with the corrected content, and omit split_into_turns
- The "prompt" field can be an empty string "" if there is no command-line prompt before the command (e.g., in scripts or automated environments). Always check for this case when splitting turns or extracting missed turns from initial_output"""
  

        user_message = json.dumps({
            "raw_txt": raw_text,
            "parsed_json": {
                "initial_output": initial_output,
                "total_turns": len(turns),
                "turns": turns
            }
        }, ensure_ascii=False)

        missed_count = 0

        try:
            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=self.step4_model_name,
                temperature=0.2
            )

            result = response.choices[0].message.content

            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]

            data = json.loads(result)

            missed_turns = data.get('missed_turns_in_initial_output', [])
            missed_count = len(missed_turns)
            if missed_turns:
                print(f"[Step 4] ✓ Found {len(missed_turns)} missed turns in initial_output")

                corrected_initial = data.get('corrected_initial_output', '')
                if corrected_initial:
                    parsed_result['initial_output'] = corrected_initial
                    print(f"[Step 4] ✓ Initial output corrected (removed command executions)")

                for mt in reversed(missed_turns):
                    new_turn = {
                        "turn_id": 0,  # Placeholder, will be renumbered at the end
                        "prompt": mt.get('prompt', ''),
                        "action": {
                            "content": mt.get('action', {}).get('content', '')
                        },
                        "observation": {
                            "content": mt.get('observation', {}).get('content', '')
                        }
                    }
                    turns.insert(0, new_turn)
            else:
                if not data.get('initial_output_correct', True):
                    corrected_initial = data.get('corrected_initial_output', '')
                    if corrected_initial:
                        parsed_result['initial_output'] = corrected_initial
                        print(f"[Step 4] ✓ Initial output corrected")
                else:
                    print(f"[Step 4] ✓ Initial output is correct")

            verification_results = data.get('turns', [])

        except Exception as e:
            print(f"[Step 4] Error during verification: {str(e)}")
            verification_results = [
                {
                    'turn_id': t.get('turn_id'),
                    'is_correct': True,
                    'issue': '',
                    'should_split': False
                } for t in turns
            ]

        turns_to_insert = []

        verification_map = {v.get('turn_id'): v for v in verification_results}

        correct_count = 0
        split_count = 0
        corrected_count = 0

        for i in range(len(turns)):
            v = verification_map.get(turns[i].get('turn_id'))
            if not v:
                continue

            if v.get('should_split', False):
                split_turns = v.get('split_into_turns', [])
                if len(split_turns) >= 2:
                    turns_to_insert.append((i, split_turns))
                    split_count += 1
                    continue

            if not v.get('is_correct', True):
                corrected = v.get('corrected_turn') or {}
                if corrected and 'action' in corrected and 'content' in corrected['action']:
                    turns[i]['action']['content'] = corrected['action']['content']

                if corrected and 'observation' in corrected and 'content' in corrected['observation']:
                    new_output = corrected['observation']['content']
                    turns[i]['observation']['content'] = new_output

                corrected_count += 1
            else:
                correct_count += 1

        print(f"\n[Step 4] Verification summary:")
        print(f"  - Correct turns: {correct_count}")
        print(f"  - Corrected turns: {corrected_count}")
        print(f"  - Turns to split: {split_count}")
        if missed_count > 0:
            print(f"  - Missed turns found in initial_output: {missed_count}")

        for insert_idx, split_turns in sorted(turns_to_insert, reverse=True):
            new_turns = []
            for st in split_turns:
                new_turn = {
                    "turn_id": 0,
                    "prompt": st.get('prompt', ''),
                    "action": {
                        "content": st.get('action', {}).get('content', '')
                    },
                    "observation": {
                        "content": st.get('observation', {}).get('content', '')
                    }
                }
                new_turns.append(new_turn)

            turns[insert_idx:insert_idx+1] = new_turns

        for i, turn in enumerate(turns, 1):
            turn['turn_id'] = i

        print(f"[Step 4] Final result: {len(turns)} turns after processing")

        return verification_results
    
async def parse_terminal_file(input_file, parsed_output=None, verified_output=None, model_name='gpt-5.2-2025-12-11', step4_model_name='claude-sonnet-4-20250514'):
    print(f"\n{'#'*60}")
    print(f"# Terminal File Parsing Started")
    print(f"# Input: {input_file}")
    print(f"# Model: {model_name}")
    print(f"# Step4 Model: {step4_model_name}")
    print(f"{'#'*60}")

    parser = TerminalParser(model_name=model_name, step4_model_name=step4_model_name)
    
    success = await parser.step1_learn_prompts(input_file)
    if not success or len(parser.prompt_patterns) == 0:
        parser.prompt_patterns = [r'^[\$\#\%>]\s*']
    
    confirmed_line_nums = await parser.step2_filter_fake_prompts(input_file)
    if not confirmed_line_nums:
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
    
    parsed_data = await parser.step3_parse_turns(input_file, confirmed_line_nums)
    
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
        print(f"\n[Output] Parsed result saved to: {parsed_output}")

    verification_results = []
    if len(parsed_data['turns']) > 0:
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
        verification_results = await parser.step4_verify_turns(input_file, parsed_for_verification)
        
        verified_result = {
            "file_path": input_file,
            "total_turns": len(turns_for_verification),
            "initial_output": parsed_data["initial_output"],
            "turns": turns_for_verification,
            "learned_patterns": parser.prompt_patterns,
            "confirmed_prompt_lines": sorted(list(confirmed_line_nums)),
            "verification_results": verification_results
        }
        
        if verified_output:
            with open(verified_output, 'w', encoding='utf-8') as f:
                json.dump(verified_result, f, ensure_ascii=False, indent=2)
            print(f"[Output] Verified result saved to: {verified_output}")
    else:
        verified_result = parsed_result

    final_result = verified_result if len(parsed_data['turns']) > 0 else parsed_result

    print(f"\n{'#'*60}")
    print(f"# Parsing Complete!")
    print(f"# Total turns: {final_result.get('total_turns', 0)}")
    print(f"{'#'*60}\n")

    return final_result

async def one_model_parse_async(input_file, model_name='gpt-5.2-2025-12-11', step4_model_name=None):
    # 如果没有指定 step4_model_name，则使用与 model_name 相同的模型
    if step4_model_name is None:
        step4_model_name = model_name
    
    result = await parse_terminal_file(
        input_file=input_file,
        parsed_output=None,
        verified_output=None,
        model_name=model_name,
        step4_model_name=step4_model_name
    )
    return result

if __name__ == "__main__":
    import asyncio
    result = asyncio.run(parse_terminal_file(
        input_file='data/raw/txt/100024.txt',
        parsed_output='data/analyzed/100024_parsed_async.json',
        verified_output='data/analyzed/100024_verified_async.json',
        model_name='gemini-1.5-flash',
        step4_model_name='gemini-1.5-flash'
    ))
