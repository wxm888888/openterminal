"""
Centralised LLM prompt templates.

Every system / user prompt used in the pipeline lives here so they can
be reviewed, versioned, and tested in isolation.
"""


# =====================================================================
# Step 1 – Learn prompt patterns
# =====================================================================

STEP1_SYSTEM_PROMPT = r"""You are an expert in Terminal Prompt Recognition.
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
      "complete_prompt": "user@host|~/dir\n> ",
      "regex_for_firstline": "^[^@]+@[^|]+\\|[^\\n]+\\s*",
      "description": "Two-line prompt: first line user@host|path; do NOT create regex for the '>' line"
    }
  ]
}
```

Note: Ensure the regex uses double backslashes for escaping (e.g., \\s*) to remain valid within the JSON string.
IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text."""


def build_step1_user_message(sample_text: str) -> str:
    return f"""Analyze the following terminal output and identify ALL distinct prompt patterns.

Important Notes:
- Prompts with the same format but different paths/branches should share ONE generic regex.
- However, if formats are completely different (e.g., bash-style vs. zsh-style), identify them separately.
- For multi-line prompts: provide the complete prompt in complete_prompt, but regex_for_firstline should ONLY match the first line.

Terminal Output:
{sample_text}

Please return generic regex patterns for all prompt types."""


# =====================================================================
# Step 2 – Filter false-positive prompts
# =====================================================================

STEP2_SYSTEM_PROMPT = """You are an expert in Terminal Prompt Verification. Determine which lines are real prompts and which are just text that happens to match the regex pattern.

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


# =====================================================================
# Step 3 – Classify action / observation per turn
# =====================================================================

STEP3_SYSTEM_PROMPT = r"""You are an expert in Terminal Command/Output Classification.

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


# =====================================================================
# Step 4 – Verify & correct turns
# =====================================================================

STEP4_SYSTEM_PROMPT = r"""You are an expert in Terminal Turn Verification.
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


# =====================================================================
# Quality filter prompt
# =====================================================================

QUALITY_FILTER_PROMPT = r"""You are a professional Data Compliance and Quality Assurance Expert, specializing in identifying Terminal Interaction patterns within technical documentation.

Task Goal:
Please evaluate the following .txt document to determine if it contains high-quality terminal interaction records suitable for training High-Performance Terminal Agent.

Screening Criteria (Must Include):

1.Interaction Features: The document must contain clear command-line identifiers, such as $, #, C:\\>, or user@machine:~$.

2.Structural Integrity: It must include complete "Input (Command)" and "Output (Stdout/Stderr)" pairs.

3.Technical Relevance: The content should involve Linux/Unix administration, network configuration, software development environment setup, Git operations, or file system management, etc.

4.Logical Coherence: Ideally, the document should contain a multi-step instruction flow aimed at solving a specific problem, rather than scattered, out-of-context commands.

Exclusion Criteria (Discard if present):

1.Pure Code Snippets: (e.g., only Python or C++ source code without terminal execution records).

2.Pure Natural Language Descriptions: (e.g., discussing technology without showing actual command lines).

3.Irrelevant System Logs: (e.g., pure Nginx access logs without human intervention processes).

4.Full-screen editing tools (e.g., vim, vi, nano): Only the startup and exit commands are visible, while the internal editing process remains hidden.

Output Format:
Return ONLY a JSON object (wrapped in ```json code block) with the following format:
```json
{
  "qualified": true or false,
  "reason": "Brief explanation. If qualified, list the primary tools covered (e.g., find, docker, grep, etc.).",
  "task_description": "If qualified, provide a concise task description summarizing what this terminal session is doing (e.g., 'Setting up a Docker-based development environment with Nginx reverse proxy'). If unqualified, leave as empty string."
}
```

IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text."""


# =====================================================================
# Judge prompt (dynamic – depends on model count)
# =====================================================================

def build_judge_system_prompt(model_count: int) -> str:
    """Build the system prompt for the Judge, parameterised by model count."""
    model_labels = [f"model_{chr(ord('a') + i)}" for i in range(model_count)]
    winner_options = " | ".join([f'"{l}"' for l in model_labels]) + ' | "all_incorrect"'

    model_issues_fields = "\n".join(
        [
            f'  "{l}_issues": ["List of issues for {l.replace("_", " ").title()}"],'
            for l in model_labels
        ]
    )

    return f"""You are an expert in Terminal Parsing Quality Evaluation. Given the raw terminal text and the parsing results from {model_count} different models, you need to:

1. **Evaluate which parsing result is most accurate**
2. **Determine if this trajectory is suitable for training a Terminal Agent**

## Parsing Quality Evaluation Criteria:
1. **Turn Segmentation Accuracy**: Whether command recognition is correct and turn boundaries are clearly deifned.
2. **Command Extraction Accuracy**:
   - Whether multi-line commands, if any, have been fully and accurately extracted.
   - Whether command arguments are complete.
   - Whether output was incorrectly identified as a command.
   - Whether the prompt was mistakenly identified as a command.
3. **Output Extraction Accuracy**:
   - Whether the output content is complete and accurate.
   - Whether command arguments were incorrectly identified as output.
   - Whether the next prompt was accidentally included in the output.
4. **Structural Integrity**:
   - Whether the action-observation mapping for each turn is correct.
   - Whether any turns were missed.
   - Whether any turns were hallucinated (fictionalized).

## Trajectory Suitability Evaluation:

A trajectory is **NOT suitable** for Terminal Agent training if:

### 1. Original content issues (check raw terminal text):
- **Full-screen editing tools (e.g., vim, vi, nano)**: Only the startup and exit commands are visible, while the internal editing process remains hidden.
- **Tutorial/practice commands**: brain-* series, dummy examples without real execution
- **No meaningful commands**: no actual terminal operations

### 2. Parsing quality issues (check all parsing results):
- **All models have severe extraction errors**: Content misclassified, commands truncated, incorrect turn boundaries

Return the result in JSON format (wrapped in ```json code block):
```json
{{{{
  "winner": {winner_options},
  "reason": "Detailed reasoning for which parsing is best",
  "confidence": 0.0-1.0,
{model_issues_fields}
  "suitable_for_training": true | false,
  "rejection_type": "original_content_issues" | "parsing_quality_issues" (only if suitable_for_training=false),
  "rejection_reason": "Why this trajectory should not be used for training (only if suitable_for_training=false)"
}}}}
```

Notes:
- If all results contain severe errors, return "all_incorrect".
- You MUST choose exactly one winner. Even if multiple results are of similar quality, pick the one that is slightly better or has fewer issues.
- If a turn consists only of a prompt, without any input or output, it still counts as a separate turn.
- Set suitable_for_training=false if the original content or all parsing results are problematic.
- rejection_reason should clearly state whether it's due to original content issues or parsing quality issues.

IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text.
"""
