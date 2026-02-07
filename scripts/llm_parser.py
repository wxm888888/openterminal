import re
import json
import os
import time
from datetime import datetime
from pathlib import Path
from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url=os.getenv('OPENAI_BASE_URL')
)

class TerminalParser:
    def __init__(self, model_name='qwen3-8b', step4_model_name='claude-sonnet-4-20250514', save_raw_responses=True, save_json_results=True, file_id=None):
        self.prompt_patterns = []
        self.model_name = model_name
        self.step4_model_name = step4_model_name
        self.save_raw_responses = save_raw_responses
        self.save_json_results = save_json_results
        self.file_id = file_id

    def _extract_json_from_response(self, response_text):
        if not response_text or not isinstance(response_text, str):
            raise ValueError("Empty or invalid response text")

        text = response_text.strip()

        # Strategy 1: Extract from ```json code block
        if '```json' in text:
            try:
                json_content = text.split('```json')[1].split('```')[0].strip()
                return json.loads(json_content)
            except (IndexError, json.JSONDecodeError):
                pass

        # Strategy 2: Extract from generic ``` code block
        if '```' in text:
            try:
                json_content = text.split('```')[1].split('```')[0].strip()
                return json.loads(json_content)
            except (IndexError, json.JSONDecodeError):
                pass

        # Strategy 3: Try parsing the entire text as JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 4: Find JSON object using brace matching
        start_idx = text.find('{')
        if start_idx != -1:
            brace_count = 0
            end_idx = -1
            for i in range(start_idx, len(text)):
                if text[i] == '{':
                    brace_count += 1
                elif text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i
                        break
            if end_idx != -1:
                try:
                    return json.loads(text[start_idx:end_idx + 1])
                except json.JSONDecodeError:
                    pass

        # Strategy 5: Find JSON array using bracket matching
        start_idx = text.find('[')
        if start_idx != -1:
            bracket_count = 0
            end_idx = -1
            for i in range(start_idx, len(text)):
                if text[i] == '[':
                    bracket_count += 1
                elif text[i] == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        end_idx = i
                        break
            if end_idx != -1:
                try:
                    return json.loads(text[start_idx:end_idx + 1])
                except json.JSONDecodeError:
                    pass

        # Strategy 6: Try to fix common JSON issues and parse again
        # Remove trailing commas before } or ]
        fixed_text = re.sub(r',\s*([}\]])', r'\1', text)
        # Try extracting JSON object again from fixed text
        start_idx = fixed_text.find('{')
        if start_idx != -1:
            brace_count = 0
            end_idx = -1
            for i in range(start_idx, len(fixed_text)):
                if fixed_text[i] == '{':
                    brace_count += 1
                elif fixed_text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i
                        break
            if end_idx != -1:
                try:
                    return json.loads(fixed_text[start_idx:end_idx + 1])
                except json.JSONDecodeError:
                    pass

        raise ValueError(f"Failed to extract JSON from response: {text[:200]}...")

    def _save_raw_response(self, step_name, response_content, turn_id=None, request_time=None, response_time=None, inference_duration=None):
        """Save the raw response from the model to the specified directory"""
        if not self.save_raw_responses or not self.file_id:
            return

        # data/analysis/raw_response/{file_id}/{model_name}/step*
        model_name = self.step4_model_name if step_name == "step4" else self.model_name
        file_dir = Path(f"data/analysis/raw_response/{self.file_id}/{model_name}")
        file_dir.mkdir(parents=True, exist_ok=True)

        if turn_id is not None:
            filename = f"{step_name}_turn{turn_id}.json"
        else:
            filename = f"{step_name}.json"

        output_path = file_dir / filename

        data_to_save = {
            "file_id": self.file_id,
            "step": step_name,
            "turn_id": turn_id,
            "model": self.model_name if step_name != "step4" else self.step4_model_name,
            "raw_response": response_content
        }

        if request_time is not None:
            data_to_save["request_time"] = request_time
        if response_time is not None:
            data_to_save["response_time"] = response_time
        if inference_duration is not None:
            data_to_save["inference_duration"] = inference_duration

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)

    def _save_json_result(self, step_name, json_data):
        """Save the extracted JSON data from each step to the specified directory"""
        if not self.save_json_results or not self.file_id:
            return

        # data/analysis/json_results/{file_id}/{model_name}/step*
        model_name = self.step4_model_name if step_name == "step4" else self.model_name
        file_dir = Path(f"data/analysis/json_results/{self.file_id}/{model_name}")
        file_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{step_name}.json"
        output_path = file_dir / filename

        data_to_save = {
            "file_id": self.file_id,
            "step": step_name,
            "model_name": self.model_name if step_name != "step4" else self.step4_model_name,
            "data": json_data
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)

    async def step1_learn_prompts(self, file_path):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = [line.rstrip('\n') for line in f.readlines()]

        sample_text = '\n'.join(lines)
        
        system_prompt = """You are an expert in Terminal Prompt Recognition.
TASK:
- Analyze the provided terminal output text and identify all distinct prompt patterns.
- For each identified prompt, generate a generic regex for the FIRST LINE of the identified prompt.

Prompt Characteristics:
- Contains dynamic information such as username, hostname, path, git branch, or virtual environment.
- Ends with a special symbol (e.g., $, #, %, >, ★, ✗, etc.).
- Is usually followed by a user-inputted command.
- May be multi-line: Some prompts across two or more lines.

IMPORTANT: Multiple prompt types may exist within a single terminal session due to:
- Directory changes (cd command) changing the path.
- Git branch switches changing the branch name.
- Virtual environment activation/deactivation changing the environment prefix.
- Permission changes (Standard user $ vs. Root #).
- Context switching: Entering/exiting containers (Docker, LXC), remote servers (SSH), or sub-shells (mysql, python).

Key Requirements for Regex Generation:
1. Generalization: The regex must be generic enough to match the same format even when content varies.
   Example: `user@host:/path1$` and `user@host:/path2$` should be matched by the same regex.
   Correct: `^[^@]+@[^:]+:[^$]+\\$\\s*`
   Incorrect: `^user@host:/path1\\$\\s*` (Too specific; only matches path1).

2. Scope: Do not include the trailing command in the match.
   Example: For `➜ dir git:(main) ✗ command`, the match should stop after the `✗`.

3. Ending: The regex should end with `\\s*` (zero or more spaces). This ensures it matches the prompt even if no command followed it. Beginning: The regex MUST start with `^` (caret) to anchor the match at the beginning of a line.

4. If a prompt is multi-line, generate a regex that matches ONLY the first line of the prompt.
   - Do NOT generate a separate regex for the second line.

5. Exhaustiveness: Identify every uniquely formatted prompt, even if it only appears once in the text.

Return the result in JSON format (wrapped in ```json code block):
```json
{
  "patterns": [
    {
      "complete_prompt": "Complete prompt (without command)",
      "regex_for_firstline": "Generic regex matching ONLY the prompt FIRST LINE (starting with ^, ending in \\\\s*)",
      "description": "Explanation of the characteristics of this pattern"
    }
  ]
}
```

Example Output:
```json
{
  "patterns": [
    {
      "complete_prompt": "user@host:~/dir1$ ",
      "regex_for_firstline": "^[^@]+@[^:]+:[^$]+\\\\$\\\\s*",
      "description": "Standard Bash prompt: user@host:path$"
    },
    {
      "complete_prompt": "user@host|~/dir\\n> ",
      "regex_for_firstline": "^[^@]+@[^|]+\\|[^\\n]+\\s*",
      "description": "Two-line prompt: first line user@host|path; do NOT create regex for the '>' line"
    }
  ]
}
```

Note: Ensure the regex uses double backslashes for escaping (e.g., \\s*) to remain valid within the JSON string.
IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text."""
        
        try:
            request_time = datetime.now().isoformat()
            start_time = time.time()

            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"""Analyze the following terminal output and identify ALL distinct prompt patterns.

Important Notes:
- Prompts with the same format but different paths/branches should share ONE generic regex.
- However, if formats are completely different (e.g., bash-style vs. zsh-style), identify them separately.
- For multi-line prompts: provide the complete prompt in complete_prompt, but regex_for_firstline should ONLY match the first line.

Terminal Output:
{sample_text}

Please return generic regex patterns for all prompt types."""}
                ],
                model=self.model_name,
                max_tokens=64 * 1024
            )

            end_time = time.time()
            response_time = datetime.now().isoformat()
            inference_duration = end_time - start_time

            self._save_raw_response("step1", response.model_dump(),
                                   request_time=request_time,
                                   response_time=response_time,
                                   inference_duration=inference_duration)

            result = response.choices[0].message.content

            data = self._extract_json_from_response(result)

            for item in data.get('patterns', []):
                pattern = item.get('regex_for_firstline', '')
                if pattern:
                    cleaned = re.sub(r'\(\?<[^>]+>', '(', pattern)

                    try:
                        re.compile(cleaned)
                        self.prompt_patterns.append(cleaned)
                    except re.error:
                        pass

            # Save step1 extracted JSON data
            self._save_json_result("step1", data)

            return len(self.prompt_patterns) > 0

        except Exception as e:
            return False
    
    async def step2_filter_fake_prompts(self, file_path):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        candidate_prompts = []
        
        for line_num, line in enumerate(lines, 1):       
            line_content = line.rstrip('\n')
            matched = False
            matched_pattern = None
            
            for pattern in self.prompt_patterns:
                try:
                    if re.match(pattern, line_content):
                        matched = True
                        matched_pattern = pattern
                        break
                except re.error:
                    continue
            
            if matched:
                candidate_prompts.append({
                    'line_num': line_num,
                    'content': line_content,
                    'prev_line': lines[line_num-2].rstrip('\n') if line_num > 1 else '',
                    'next_line': lines[line_num].rstrip('\n') if line_num < len(lines) else '',
                })

        if not candidate_prompts:
            return set(), set()

        confirmed, false_positives = await self._filter_with_llm(candidate_prompts)

        return confirmed, false_positives
    
    async def _filter_with_llm(self, candidates):
        system_prompt = """You are an expert in Terminal Prompt Verification. Determine which lines are real prompts and which are just text that happens to match the regex pattern.

Real Prompt Characteristics:
1. Position: Usually appears after command output, before a new command.
2. Function: Marks the beginning of new user input.

False Positives (should be filtered), for example:
1. Text in command output that resembles a prompt
   Example: echo "user@host:~$ this is just text"
2. Text in program logs or error messages
3. Text in file contents or code snippets

Return JSON format (wrapped in ```json code block):
```json
{
  "confirmed_prompts": [list of line numbers for real prompts (If it's a multi-line prompt, return the line number of the first line)],
  "false_positives": [
    {"line_num": line number of false prompt, "reason": "why it's considered false"}
  ]
}
```

Note: The prompt may be multi-line. If so, only return the line number of the FIRST line of the prompt in confirmed_prompts.
IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text."""
        
        candidates_text = []
        for c in candidates:
            candidates_text.append(f"""
Line {c['line_num']}:
  Previous: {c['prev_line'][:100] if c['prev_line'] else '(start of file)'}
  [Current]: {c['content'][:100]}
  Next: {c['next_line'][:100] if c['next_line'] else '(end of file)'}
""")
        
        try:
            request_time = datetime.now().isoformat()
            start_time = time.time()

            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Determine which of the following candidate lines mark the beginning of real prompts::{''.join(candidates_text)}\n\nPlease analyze line by line and provide a list of confirmed real prompt line numbers."}
                ],
                model=self.model_name,
                temperature=0.3,
                max_tokens=64 * 1024
            )

            end_time = time.time()
            response_time = datetime.now().isoformat()
            inference_duration = end_time - start_time

            self._save_raw_response("step2", response.model_dump(),
                                   request_time=request_time,
                                   response_time=response_time,
                                   inference_duration=inference_duration)

            result = response.choices[0].message.content

            data = self._extract_json_from_response(result)

            confirmed = set(data.get('confirmed_prompts', []))
            false_positives = set(fp['line_num'] for fp in data.get('false_positives', []))

            # Save step2 extracted JSON data
            self._save_json_result("step2", data)

            return confirmed, false_positives

        except Exception:
            return set(c['line_num'] for c in candidates), set()
    
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
                            matched_pattern = (pattern, match)
                            break
                    except re.error:
                        continue
            
            if is_prompt:
                if current_turn is not None:
                    result["turns"].append(current_turn)
                
                in_initial = False
                turn_id += 1
                
                pattern_str, match = matched_pattern
                
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


        if result['turns']:
            import asyncio
            tasks = []
            for turn in result['turns']:
                tasks.append(self._llm_classify_action_observation(turn))
            await asyncio.gather(*tasks)

        step3_concatenated_data = {
            "initial_output": result["initial_output"],
            "total_turns": len(result["turns"]),
            "turns": result["turns"]
        }
        self._save_json_result("step3", step3_concatenated_data)

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
7. Extract text EXACTLY as it appears in the raw lines. Do NOT add or remove any characters (including spaces). If the raw line is ">", the prompt should end with ">" not "> ".

Common Patterns:
- Single-line prompt: "user@host:~$ command" - prompt is "user@host:~$ "
- Multi-line prompt: "user@host|~/path\\n> command" - prompt is "user@host|~/path\\n> "
- Multi-line command (e.g., with \\): Multiple lines form the command, then output follows

Return JSON format (wrapped in ```json code block):
```json
{
  "prompt": "The complete prompt (may be multi-line, use \\n for line breaks)",
  "action_lines": ["line1 of command", "line2 of command", ...],
  "observation_lines": ["line1 of output", "line2 of output", ...]
}
```

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
```json
{
  "prompt": "$ ",
  "action_lines": ["docker run \\", "--name test \\", "-p 8080:80 \\", "nginx"],
  "observation_lines": ["Unable to find image 'nginx:latest' locally"]
}
```

IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text."""

        raw_lines_text = '\n'.join([
            f"  {i+1}. {line}"
            for i, line in enumerate(turn['raw_lines'])
        ])

        user_message = f"""Classify the prompt, action (command), and observation (output) from these raw lines:

[Raw Lines] ({len(turn['raw_lines'])} line(s))
{raw_lines_text}

[Prompt first line detected by regex]: {turn['prompt']}

Please extract the complete prompt (including all prompt lines if multi-line), the action lines (command without prompt) as a list, and observation lines (output) as a list."""

        try:
            request_time = datetime.now().isoformat()
            start_time = time.time()

            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=self.model_name,
                temperature=0.2,
                max_tokens=64 * 1024
            )

            end_time = time.time()
            response_time = datetime.now().isoformat()
            inference_duration = end_time - start_time

            self._save_raw_response(
                "step3",
                response.model_dump(),
                turn_id=turn['turn_id'],
                request_time=request_time,
                response_time=response_time,
                inference_duration=inference_duration
            )

            result = response.choices[0].message.content

            data = self._extract_json_from_response(result)

            extracted_prompt = data.get('prompt', '')
            if extracted_prompt:
                turn['prompt'] = extracted_prompt

            action_lines = data.get('action_lines', [])
            if isinstance(action_lines, list):
                turn['action']['content'] = '\n'.join(action_lines)
            else:
                turn['action']['content'] = str(action_lines).strip()

            # try to extract observation from raw_lines using prompt + action as prefix
            raw_text = '\n'.join(turn['raw_lines']) if turn.get('raw_lines') else ''
            prefix = turn['prompt'] + turn['action']['content']

            if raw_text.startswith(prefix):
                turn['observation']['content'] = raw_text[len(prefix):].strip()
                turn['prefix_matched'] = True
            else:
                obs_lines = data.get('observation_lines', [])
                if isinstance(obs_lines, list):
                    turn['observation']['content'] = '\n'.join([line for line in obs_lines if line.strip()])
                else:
                    turn['observation']['content'] = str(obs_lines).strip()
                turn['prefix_matched'] = False

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
            turn['prefix_matched'] = False
    
    async def step4_verify_turns(self, input_file, parsed_result):

        turns = parsed_result.get('turns', [])
        initial_output = parsed_result.get('initial_output', '')

        if not turns and not initial_output:
            return []

        with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
            raw_text = f.read()

        system_prompt = """You are an expert in Terminal Turn Verification.
You will receive:
1) The raw terminal txt file content
2) The parsed JSON with initial_output and turns

Your task:
1. FIRST: Check if initial_output contains any missed command executions (command-output pairs that were not parsed as turns). If found, extract them as new turns AND rewrite the corrected initial_output by removing those command executions. The initial_output must contain all raw text content occurring strictly before the very first command-line prompt, which typically includes system login banners (e.g., "Welcome to Ubuntu..."), "Last login" timestamps, or environment initialization logs. Note that the initial_output can be an empty string
2. SECOND: If no missed command executions were found, check if initial_output is correctly extracted
3. THIRD: If a single turn actually contains MULTIPLE command executions (multiple prompts, commands and outputs), split it into multiple turns
4. FOURTH: For EACH turn, determine whether there are writing/segmentation mistakes in the parsed result. If correction is needed, return corrected action and observation content

Return JSON format (wrapped in ```json code block):
```json
{
  "initial_output_correct": true/false,
  "initial_output_issue": "If incorrect, describe the issue",
  "corrected_initial_output": "Corrected initial output if needed",
  "missed_turns_in_initial_output": [
    {
      "prompt": "The prompt string (may be empty string \"\" before command)",
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
```

Rules:
- Always use the raw txt as ground truth
- First check initial_output for missed command executions:
  * Check if initial_output contains any missed command executions (command-output pairs that should have been parsed as turns)
  * If found: set initial_output_correct=false, add them to missed_turns_in_initial_output array, AND provide corrected_initial_output by removing the command execution content (keep only the true initial content before any commands)
  * If no missed turns found: omit missed_turns_in_initial_output field, then proceed to check initial_output correctness
- Then check initial_output correctness :
  * If correct: set initial_output_correct=true, and omit both initial_output_issue and corrected_initial_output
  * If incorrect: set initial_output_correct=false, provide initial_output_issue describing the problem, and provide corrected_initial_output with the corrected content
- For each turn, first check if it contains multiple command executions (multiple prompts or multiple command-output pairs):
  * If yes: set should_split=true, then provide split_into_turns array with 2 or more turns, and do NOT provide corrected_turn
  * When splitting turns, the "prompt" field may be empty string "" if no prompt is detected before a command
  * If no: continue to next step
- If the turn doesn't need splitting, check if there are writing/segmentation mistakes:
  * If the turn is correct: set is_correct=true, should_split=false, and omit both corrected_turn and split_into_turns
  * If the turn has mistakes but doesn't need splitting: set is_correct=false, should_split=false, then provide corrected_turn with the corrected content, and omit split_into_turns
- The "prompt" field can be an empty string "" if there is no command-line prompt before the command (e.g., in scripts automated environments). Always check for this case when splitting turns or extracting missed turns from initial_output

IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text."""


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
            request_time = datetime.now().isoformat()
            start_time = time.time()

            response = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model=self.step4_model_name,
                temperature=0.2,
                max_tokens=64 * 1024
            )

            end_time = time.time()
            response_time = datetime.now().isoformat()
            inference_duration = end_time - start_time

            self._save_raw_response("step4", response.model_dump(),
                                   request_time=request_time,
                                   response_time=response_time,
                                   inference_duration=inference_duration)

            result = response.choices[0].message.content

            data = self._extract_json_from_response(result)

            # Save step4 extracted JSON data
            self._save_json_result("step4", data)

            missed_turns = data.get('missed_turns_in_initial_output', [])
            missed_count = len(missed_turns)
            if missed_turns:

                if 'corrected_initial_output' in data:
                    parsed_result['initial_output'] = data.get('corrected_initial_output', '')

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
                    if 'corrected_initial_output' in data:
                        parsed_result['initial_output'] = data.get('corrected_initial_output', '')

            verification_results = data.get('turns', [])

        except Exception as e:
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

        for turn in turns:
            if 'raw_lines' in turn:
                del turn['raw_lines']

        return verification_results

async def parse_terminal_file(input_file, parsed_output=None, verified_output=None, model_name='gpt-5.2-2025-12-11', step4_model_name='claude-sonnet-4-20250514', save_raw_responses=True, save_json_results=True):

    file_id = None
    if save_raw_responses or save_json_results:
        file_id = Path(input_file).stem

    parser = TerminalParser(model_name=model_name, step4_model_name=step4_model_name, save_raw_responses=save_raw_responses, save_json_results=save_json_results, file_id=file_id)
    
    success = await parser.step1_learn_prompts(input_file)
    if not success or len(parser.prompt_patterns) == 0:
        parser.prompt_patterns = [r'^[\$\#\%>]\s*']
    
    confirmed_line_nums, false_positive_nums = await parser.step2_filter_fake_prompts(input_file)
    if not confirmed_line_nums and not false_positive_nums:
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
    if len(parsed_data['turns']) > 0 or parsed_data['initial_output']:
        import copy
        turns_for_verification = copy.deepcopy(parsed_data['turns'])
        parsed_for_verification = {
            "initial_output": parsed_data["initial_output"],
            "turns": turns_for_verification
        }
        verification_results = await parser.step4_verify_turns(input_file, parsed_for_verification)
        
        verified_result = {
            "file_path": input_file,
            "total_turns": len(turns_for_verification),
            "initial_output": parsed_for_verification['initial_output'],
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

    final_result = verified_result

    return final_result

async def one_model_parse_async(input_file, model_name='qwen3-coder-30b-a3b-instruct', step4_model_name='gpt-5.2-2025-12-11', save_raw_responses=True, save_json_results=True):
    result = await parse_terminal_file(
        input_file=input_file,
        parsed_output=None,
        verified_output=None,
        model_name=model_name,
        step4_model_name=step4_model_name,
        save_raw_responses=save_raw_responses,
        save_json_results=save_json_results
    )
    return result

if __name__ == "__main__":
    import asyncio
    result = asyncio.run(parse_terminal_file(
        input_file='data/raw/txt/39675.txt',
        parsed_output='data/analyzed/39675_parsed_async.json',
        verified_output='data/analyzed/39675_verified_async.json',
        model_name='kimi-k2-instruct',
        step4_model_name='kimi-k2-instruct',
        save_raw_responses=True,
        save_json_results=True
    ))
