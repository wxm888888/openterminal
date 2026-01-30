#!/usr/bin/env python3
"""
Step 2: LLM-based trajectory filtering.

Uses OpenAI API with async high-concurrency to evaluate trajectories.
Saves all messages, responses, and extracted true/false results.

Features:
- Incremental saving: saves every 100 processed items
- Checkpoint resume: skips already processed files on restart
- Request timeout: prevents indefinite hanging on API calls

Can be run independently or as part of the pipeline.
"""

import json
import os
import re
import asyncio
import argparse
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, asdict
from datetime import datetime

from openai import AsyncOpenAI

# Constants
DEFAULT_TIMEOUT = 600  # seconds for each API request
SAVE_INTERVAL = 20   # save results every N processed items

TRAJECTORY_EVALUATION_PROMPT = r"""Here are multi-turn action-observation pairs extracted from human-terminal interaction data. Please analyze whether this trajectory is suitable for training a LLM-based Terminal Agent.

## Input Data

### Extraction Result
```json
{json_content}
```

### Original Terminal Record
```
{txt_content}
```

## Evaluation Criteria

A trajectory suitable for Terminal Agent training **must have correct extraction results**:
- The extraction must accurately reflect the original terminal record
- Actions must be real, executable shell commands (not output or natural language)
- Observations must contain the correct execution results corresponding to each action

### The following types of trajectories are **NOT suitable** for Terminal Agent training:

#### 1. Structural extraction errors (CRITICAL - any extraction error means false)

Comparing the original terminal record txt with the extraction result, if ANY of the following errors exist, the trajectory is NOT suitable:
- Content that should be an action is incorrectly classified as observation
- Execution output is incorrectly classified as action
- Multi-line command parsing errors, causing commands to be truncated or merged incorrectly

#### 2. Low command validity rate

- Actions contain a large amount of non-command text (except for AI model-based interactions like Claude Code)
- Output content, tutorial explanations, or natural language are misidentified as commands, resulting in high noise

#### 3. Special trajectories

- Demo or animation scripts where command order, semantics, or execution relationships are incorrect after extraction (correctly extracted ones suitable for Terminal Agent learning can be kept)
- brain-* series practice or tutorial commands

#### 4. Interactive program trajectories

- Strongly interactive programs like vim, ssh, etc., that rely on real-time input or state switching

---

Please compare the original terminal record txt with the extracted result and analyze it step by step to determine whether this trajectory is suitable for training a Terminal Agent.

After completing your reasoning, provide your final answer enclosed in \boxed{{}}. Use \boxed{{true}} if the trajectory is suitable for training, or \boxed{{false}} if it is not.
"""

@dataclass
class EvaluationResult:
    """Result of a single trajectory evaluation."""
    filename: str
    messages: List[Dict]
    response: str
    result: Optional[bool]
    error: Optional[str]
    latency_ms: float
    is_timeout: bool = False


def extract_boxed_result(response: str) -> Optional[bool]:
    """Extract true/false from \\boxed{} or oxed{} in the response."""
    # Match \boxed{true/false} or oxed{true/false} (when \b is interpreted as backspace)
    # Also match $\boxed{...}$ format
    patterns = [
        r'\\boxed\{(true|false)\}',  # \boxed{...}
        r'oxed\{(true|false)\}',      # oxed{...} (when \b eaten)
    ]
    for pattern in patterns:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            return match.group(1).lower() == 'true'
    return None


def clean_turn(turn: dict) -> dict:
    """Extract only necessary fields from a turn."""
    cleaned = {}
    if 'action' in turn:
        cleaned['action'] = {
            'type': turn['action'].get('type'),
            'content': turn['action'].get('content')
        }
    if 'observation' in turn:
        cleaned['observation'] = {
            'content': turn['observation'].get('content')
        }
    return cleaned


def prepare_json_for_llm(full_data: dict) -> str:
    """Prepare simplified JSON for LLM evaluation."""
    extracted = {
        "initial_output": full_data.get("initial_output", ""),
        "turns": [clean_turn(t) for t in full_data.get("turns", [])]
    }
    return json.dumps(extracted, indent=2, ensure_ascii=False)


async def evaluate_single(
    client: AsyncOpenAI,
    filename: str,
    json_path: str,
    txt_dir: str,
    model: str,
    semaphore: asyncio.Semaphore,
    max_retries: int = 200,
    retry_delay: float = 1.0,
    timeout: float = DEFAULT_TIMEOUT
) -> EvaluationResult:
    """Evaluate a single trajectory with retry mechanism and timeout."""
    import time
    start_time = time.time()
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            full_data = json.load(f)
        
        json_content = prepare_json_for_llm(full_data)
        
        base_name = filename.replace('.turn_based.json', '')
        txt_path = os.path.join(txt_dir, f"{base_name}.txt")
        
        if os.path.exists(txt_path):
            with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
                txt_content = f.read()
        else:
            txt_content = "[txt file not found]"
        
        prompt = TRAJECTORY_EVALUATION_PROMPT.format(
            txt_content=txt_content,
            json_content=json_content
        )
        messages = [{"role": "user", "content": prompt}]
        
        # Retry loop for API calls
        last_error = None
        for attempt in range(max_retries):
            try:
                async with semaphore:
                    # Use asyncio.wait_for to enforce hard timeout
                    response = await asyncio.wait_for(
                        client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=0.6,
                            max_tokens=16384
                        ),
                        timeout=timeout
                    )
                
                response_text = response.choices[0].message.content
                result = extract_boxed_result(response_text)
                
                return EvaluationResult(
                    filename=filename,
                    messages=messages,
                    response=response_text,
                    result=result,
                    error=None,
                    latency_ms=(time.time() - start_time) * 1000,
                    is_timeout=False
                )
            
            except asyncio.TimeoutError:
                last_error = f"Request timed out after {timeout}s"
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                continue
                
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                continue
        
        # All retries failed
        return EvaluationResult(
            filename=filename,
            messages=messages,
            response="",
            result=None,
            error=f"Failed after {max_retries} retries: {str(last_error)}",
            latency_ms=(time.time() - start_time) * 1000,
            is_timeout="Request timed out" in str(last_error)
        )
        
    except Exception as e:
        return EvaluationResult(
            filename=filename,
            messages=[],
            response="",
            result=None,
            error=str(e),
            latency_ms=(time.time() - start_time) * 1000,
            is_timeout=False
        )


def load_existing_results(output_path: str) -> tuple[List[EvaluationResult], Set[str]]:
    """
    Load existing results from file for checkpoint resume.
    Returns (existing_results, processed_filenames).
    """
    if not os.path.exists(output_path):
        return [], set()
    
    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        results = []
        processed = set()
        
        for r in data.get('results', []):
            result = EvaluationResult(
                filename=r['filename'],
                messages=r['messages'],
                response=r['response'],
                result=r['result'],
                error=r['error'],
                latency_ms=r['latency_ms'],
                is_timeout=r.get('is_timeout', False)
            )
            results.append(result)
            processed.add(r['filename'])
        
        print(f"Loaded {len(results)} existing results from {output_path}")
        return results, processed
    
    except Exception as e:
        print(f"Warning: Could not load existing results: {e}")
        return [], set()


async def evaluate_batch(
    files: List[str],
    json_dir: str,
    txt_dir: str,
    model: str,
    concurrency: int,
    output_path: str,
    timeout: float = DEFAULT_TIMEOUT,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None
) -> List[EvaluationResult]:
    """
    Evaluate a batch of trajectories with high concurrency.
    
    Features:
    - Checkpoint resume: skips already processed files
    - Incremental saving: saves every SAVE_INTERVAL items
    - Request timeout: prevents indefinite hanging
    """
    
    # Load existing results for checkpoint resume
    existing_results, processed_files = load_existing_results(output_path)
    
    # Filter out already processed files
    remaining_files = [f for f in files if f not in processed_files]
    
    if len(remaining_files) < len(files):
        print(f"Skipping {len(files) - len(remaining_files)} already processed files")
    
    if not remaining_files:
        print("All files already processed!")
        return existing_results
    
    client = AsyncOpenAI(
        api_key=api_key or os.getenv("OPENAI_API_KEY"),
        base_url=base_url or os.getenv("OPENAI_BASE_URL")
    )
    
    semaphore = asyncio.Semaphore(concurrency)
    
    tasks = [
        evaluate_single(
            client, f, os.path.join(json_dir, f), txt_dir, model, semaphore,
            timeout=timeout
        )
        for f in remaining_files
    ]
    
    print(f"Evaluating {len(tasks)} files (concurrency={concurrency}, timeout={timeout}s)...")
    
    # Start with existing results
    results = list(existing_results)
    new_count = 0
    last_save_count = 0
    
    for i, coro in enumerate(asyncio.as_completed(tasks)):
        result = await coro
        results.append(result)
        new_count += 1
        
        # Progress logging
        if new_count % 10 == 0 or new_count == len(tasks):
            suitable = sum(1 for r in results if r.result is True)
            not_suitable = sum(1 for r in results if r.result is False)
            print(f"  [New: {new_count}/{len(tasks)}, Total: {len(results)}] "
                  f"Suitable: {suitable}, Not suitable: {not_suitable}")
        
        # Incremental saving every SAVE_INTERVAL new items
        if new_count - last_save_count >= SAVE_INTERVAL:
            save_results(results, output_path, silent=True)
            print(f"  [Checkpoint] Saved {len(results)} results to {output_path}")
            last_save_count = new_count
    
    return results


def save_results(results: List[EvaluationResult], output_path: str, silent: bool = False):
    """Save evaluation results."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    data = {
        'metadata': {
            'timestamp': datetime.now().isoformat(),
            'total': len(results),
            'suitable': sum(1 for r in results if r.result is True),
            'not_suitable': sum(1 for r in results if r.result is False),
            'errors': sum(1 for r in results if r.error is not None)
        },
        'results': [asdict(r) for r in results]
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    if not silent:
        m = data['metadata']
        print(f"\nSaved to {output_path}")
        print(f"  Total: {m['total']}, Suitable: {m['suitable']}, Not suitable: {m['not_suitable']}, Errors: {m['errors']}")


async def main():
    parser = argparse.ArgumentParser(description='Step 2: LLM-based trajectory filtering')
    parser.add_argument('--input', '-i', default='data/filtered/rule_filtered.json')
    parser.add_argument('--json-dir', '-j', default='data/processed/interactions')
    parser.add_argument('--txt-dir', '-t', default='data/raw/txt')
    parser.add_argument('--output', '-o', default='data/filtered/llm_filtered.json')
    parser.add_argument('--model', '-m', default='gemini-3-flash-preview')
    parser.add_argument('--concurrency', '-c', type=int, default=10)
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT,
                        help=f'Request timeout in seconds (default: {DEFAULT_TIMEOUT})')
    parser.add_argument('--limit', '-l', type=int, default=None)
    parser.add_argument('--api-key', default=None)
    parser.add_argument('--base-url', default=None)
    
    args = parser.parse_args()
    
    with open(args.input, 'r') as f:
        files = json.load(f).get('files', [])
    
    if args.limit:
        files = files[:args.limit]
    
    print(f"Loaded {len(files)} files, Model: {args.model}, Timeout: {args.timeout}s")
    
    results = await evaluate_batch(
        files=files,
        json_dir=args.json_dir,
        txt_dir=args.txt_dir,
        model=args.model,
        concurrency=args.concurrency,
        output_path=args.output,
        timeout=args.timeout,
        api_key=args.api_key,
        base_url=args.base_url
    )
    
    save_results(results, args.output)


if __name__ == "__main__":
    asyncio.run(main())
