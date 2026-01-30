import re
import json
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key='sk-TiFLADXP6zKkEykXhWcK8rGGLdLmxz2WApfjQEkAOoKeFQMH',
    base_url='https://yeysai.com/v1'
)

class TerminalParser:    
    def __init__(self, model_name='gpt-5.2-2025-12-11', step4_model_name='claude-opus-4-5-20251101'):
        self.prompt_patterns = []
        self.error_marker = r'^\[Error:'
        self.model_name = model_name
        self.step4_model_name = step4_model_name

    async def step1_learn_prompts(self, file_path):
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
            
            for item in data.get('patterns', []):
                pattern = item.get('regex', '')
                if pattern:
                    cleaned = re.sub(r'\(\?<[^>]+>', '(', pattern)
                    
                    try:
                        re.compile(cleaned)
                        self.prompt_patterns.append(cleaned)
                    except re.error:
                        pass
            
            return len(self.prompt_patterns) > 0
        
        except Exception:
            return False
    
    async def step2_filter_fake_prompts(self, file_path):
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
            return set()
        
        confirmed_line_nums = await self._filter_with_llm(candidate_prompts)
        
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
                        "content": "",
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
                if in_initial:
                    initial_lines.append(line)
                elif current_turn is not None:
                    current_turn["raw_lines"].append(line)
                    
                    if re.match(self.error_marker, line):
                        current_turn["metadata"]["has_error"] = True
        
        if current_turn is not None:
            result["turns"].append(current_turn)
        
        result["initial_output"] = '\n'.join(initial_lines)
        
        if result['turns']:
            import asyncio
            tasks = []
            for turn in result['turns']:
                tasks.append(self._llm_classify_action_observation(turn))
            await asyncio.gather(*tasks)
        
        return result
    
    async def _llm_classify_action_observation(self, turn):
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
            
            turn['action']['content'] = data.get('action_content', '').strip()
            
            obs_lines = data.get('observation_lines', [])
            if isinstance(obs_lines, list):
                turn['observation']['raw_output_lines'] = [line for line in obs_lines if line.strip()]
                turn['observation']['content'] = '\n'.join(turn['observation']['raw_output_lines'])
            else:
                turn['observation']['content'] = str(obs_lines).strip()
                turn['observation']['raw_output_lines'] = [
                    line for line in turn['observation']['content'].split('\n') if line.strip()
                ]
        
        except Exception:
            if turn['raw_lines']:
                first_line = turn['raw_lines'][0]
                prompt = turn['prompt']
                if first_line.startswith(prompt):
                    turn['action']['content'] = first_line[len(prompt):].strip()
                else:
                    turn['action']['content'] = first_line.strip()
                
                turn['observation']['raw_output_lines'] = [
                    line for line in turn['raw_lines'][1:] if line.strip()
                ]
                turn['observation']['content'] = '\n'.join(turn['observation']['raw_output_lines'])
    
    async def step4_verify_turns(self, input_file, parsed_result):
        turns = parsed_result.get('turns', [])
        if not turns:
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
            verification_results = data.get('turns', [])
        
        except Exception:
            verification_results = [
                {
                    'turn_id': t.get('turn_id'),
                    'is_correct': True,
                    'issue': '',
                    'is_empty': False,
                    'should_delete': False
                } for t in turns
            ]
        
        turns_to_delete = []
        
        verification_map = {v.get('turn_id'): v for v in verification_results}
        
        for i in range(len(turns)):
            v = verification_map.get(turns[i].get('turn_id'))
            if not v:
                continue
            
            if not v.get('is_correct', True):
                if v.get('should_delete', False):
                    turns_to_delete.append(i)
                else:
                    corrected = v.get('corrected_turn', {})
                    if 'action' in corrected and 'content' in corrected['action']:
                        turns[i]['action']['content'] = corrected['action']['content']
                    
                    if 'observation' in corrected and 'content' in corrected['observation']:
                        new_output = corrected['observation']['content']
                        turns[i]['observation']['content'] = new_output
                        turns[i]['observation']['raw_output_lines'] = [
                            line for line in new_output.split('\n') if line.strip()
                        ]
        
        if turns_to_delete:
            for i in sorted(turns_to_delete, reverse=True):
                turns.pop(i)
            
            for i, turn in enumerate(turns, 1):
                turn['turn_id'] = i
        
        return verification_results
    
async def parse_terminal_file(input_file, parsed_output=None, verified_output=None, model_name='gpt-5.2-2025-12-11', step4_model_name='claude-opus-4-5-20251101'):
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
    else:
        verified_result = parsed_result
    
    final_result = verified_result if len(parsed_data['turns']) > 0 else parsed_result
    
    return final_result

async def one_model_parse_async(input_file, model_name='gpt-5.2-2025-12-11'):
    result = await parse_terminal_file(
        input_file=input_file,
        parsed_output=None,
        verified_output=None,
        model_name=model_name
    )
    return result

if __name__ == "__main__":
    import asyncio
    result = asyncio.run(parse_terminal_file(
        input_file='data/raw/txt/100035.txt',
        parsed_output='data/analyzed/100035_parsed_async.json',
        verified_output='data/analyzed/100035_verified_async.json',
        model_name='claude-sonnet-4-20250514'
    ))
