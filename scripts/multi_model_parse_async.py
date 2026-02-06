import json
import os
import asyncio
from pathlib import Path
from openai import AsyncOpenAI
from llm_enhanced_split_async import one_model_parse_async, TerminalParser

client = AsyncOpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url=os.getenv('OPENAI_BASE_URL')
)

def clean_parse_result(result):
    """Clean parsing result to keep only essential fields"""
    cleaned = {
        "initial_output": result.get("initial_output", ""),
        "turns": []
    }

    for turn in result.get("turns", []):
        cleaned_turn = {
            "turn_id": turn.get("turn_id"),
            "prompt": turn.get("prompt", ""),
            "input": {
                "content": turn.get("action", {}).get("content", "")
            },
            "output": {
                "content": turn.get("observation", {}).get("content", "")
            }
        }
        cleaned["turns"].append(cleaned_turn)

    return cleaned

def merge_prompts_into_output(clean_output):
    """Merge prompts into output stream"""
    import copy
    result = copy.deepcopy(clean_output)

    turns = result.get('turns', [])

    if not turns:
        return result

    # 1. Add first turn's prompt to initial_output
    first_prompt = turns[0].get('prompt', '')
    if first_prompt:
        current_initial = result.get('initial_output', '')
        if current_initial:
            result['initial_output'] = current_initial + '\n' + first_prompt
        else:
            result['initial_output'] = first_prompt

    # 2. Add subsequent turn's prompt to previous turn's observation
    for i in range(len(turns) - 1):
        next_prompt = turns[i + 1].get('prompt', '')

        if next_prompt:
            current_content = turns[i].get('observation', {}).get('content', '')
            if current_content:
                turns[i]['observation']['content'] = current_content + '\n' + next_prompt
            else:
                turns[i]['observation']['content'] = next_prompt

    return result

def build_judge_system_prompt(model_count):
    """Build system prompt for judging N models"""
    model_labels = [f"model_{chr(ord('a') + i)}" for i in range(model_count)]
    winner_options = ' | '.join([f'"{label}"' for label in model_labels]) + ' | "all_incorrect"'

    model_issues_fields = '\n'.join([f'  "{label}_issues": ["List of issues for {label.replace("_", " ").title()}"],' for label in model_labels])

    system_prompt = f"""You are an expert in Terminal Parsing Quality Evaluation. Given the raw terminal text and the parsing results from {model_count} different models, you need to:

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
- **Interactive programs**: vim, ssh, nano, emacs, tmux, screen, etc. that rely on real-time input or state switching
- **Tutorial/practice commands**: brain-* series, dummy examples without real execution
- **No meaningful commands**: no actual terminal operations

### 2. Parsing quality issues (check all parsing results):
- **All models have severe extraction errors**: Content misclassified, commands truncated, incorrect turn boundaries

Return the result in JSON format (wrapped in ```json code block):
```json
{{
  "winner": {winner_options},
  "reason": "Detailed reasoning for which parsing is best",
  "confidence": 0.0-1.0,
{model_issues_fields}
  "suitable_for_training": true | false,
  "rejection_type": "original_content_issues" | "parsing_quality_issues" (only if suitable_for_training=false),
  "rejection_reason": "Why this trajectory should not be used for training (only if suitable_for_training=false)"
}}
```

Notes:
- If all results contain severe errors, return "all_incorrect".
- You MUST choose exactly one winner. Even if multiple results are of similar quality, pick the one that is slightly better or has fewer issues.
- If a turn consists only of a prompt, without any input or output, it still counts as a separate turn.
- Set suitable_for_training=false if the original content or all parsing results are problematic.
- rejection_reason should clearly state whether it's due to original content issues or parsing quality issues.

IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text.
"""

    return system_prompt


def build_judge_user_message(txt_content, model_results):
    """Build user message for judging N models"""
    model_sections = []
    for i, (_, result) in enumerate(model_results.items()):
        label = f"Model {chr(ord('a') + i)}"
        model_sections.append(f"""[{label} Parsing Result]
```json
{json.dumps(result, indent=2, ensure_ascii=False)}
```""")

    models_text = '\n\n'.join(model_sections)

    user_message = f"""Please evaluate the parsing results and determine:
1. Which model's parsing is most accurate
2. Whether this trajectory is suitable for training a Terminal Agent

[Raw Terminal Text]
```
{txt_content}
```

{models_text}

First, check the raw terminal text for content issues (vim, ssh, demo scripts, etc.).
Then, compare all parsing results and evaluate their quality.
Finally, provide your complete judgment in JSON format."""

    return user_message


async def judge_results_async(txt_file, model_results, judge_model='gpt-5.2-2025-12-11', save_raw_response=True, file_id=None):
    """Async version of judge_results with trajectory suitability evaluation for N models"""
    from datetime import datetime

    with open(txt_file, 'r', encoding='utf-8', errors='ignore') as f:
        txt_content = f.read()

    model_count = len(model_results)
    system_prompt = build_judge_system_prompt(model_count)
    user_message = build_judge_user_message(txt_content, model_results)

    # Build expected issue fields
    model_labels = [f"model_{chr(ord('a') + i)}" for i in range(model_count)]

    try:
        request_time = datetime.now().isoformat()
        start_time = datetime.now().timestamp()

        response = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=judge_model,
            temperature=0.3
        )

        end_time = datetime.now().timestamp()
        response_time = datetime.now().isoformat()
        inference_duration = end_time - start_time

        result = response.choices[0].message.content

        # Save raw response
        if save_raw_response and file_id:
            raw_response_dir = Path(f"data/analysis/raw_response/{file_id}")
            raw_response_dir.mkdir(parents=True, exist_ok=True)

            raw_data = {
                "file_id": file_id,
                "step": "judge",
                "model": judge_model,
                "raw_response": response.model_dump(),
                "request_time": request_time,
                "response_time": response_time,
                "inference_duration": inference_duration
            }

            with open(raw_response_dir / "judge.json", 'w', encoding='utf-8') as f:
                json.dump(raw_data, f, ensure_ascii=False, indent=2)

        # Use TerminalParser's robust JSON extraction method
        parser = TerminalParser()
        data = parser._extract_json_from_response(result)

        # Save json result
        if save_raw_response and file_id:
            json_results_dir = Path(f"data/analysis/json_results/{file_id}")
            json_results_dir.mkdir(parents=True, exist_ok=True)

            json_data = {
                "file_id": file_id,
                "step": "judge",
                "model": judge_model,
                "data": data
            }

            with open(json_results_dir / "judge.json", 'w', encoding='utf-8') as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)

        model_issues = {}
        for label in model_labels:
            model_issues[f'{label}_issues'] = data.get(f'{label}_issues', [])

        return {
            'winner': data.get('winner', 'model_a'),
            'reason': data.get('reason', 'No reason provided'),
            'confidence': data.get('confidence', 0.5),
            'model_issues': model_issues,
            'suitable_for_training': data.get('suitable_for_training', True),
            'rejection_type': data.get('rejection_type', ''),
            'rejection_reason': data.get('rejection_reason', '')
        }

    except Exception as e:
        model_issues = {f'{label}_issues': [] for label in model_labels}
        return {
            'winner': 'all_incorrect',
            'reason': f'Judge model failed: {e}',
            'confidence': 0.0,
            'model_issues': model_issues,
            'suitable_for_training': False,
            'rejection_type': 'Judge model failed',
            'rejection_reason': f'Judge model error: {e}'
        }


async def multi_model_parse_and_save_async(
    input_file,
    output_file,
    models,
    judge_model='claude-sonnet-4-5-20250929-thinking',
    save_raw_response=True
):
    """
    Async version: Parse with multiple models concurrently, then judge

    Args:
        input_file: Path to input txt file
        output_file: Path to output json file
        models: List of model names to use for parsing
        judge_model: Model to use for judging results
        save_raw_response: Whether to save raw model responses
    """
    if len(models) < 2:
        raise ValueError("At least 2 models are required for comparison")

    file_id = Path(input_file).stem if save_raw_response else None

    tasks = [one_model_parse_async(input_file=input_file, model_name=model, step4_model_name=model) for model in models]
    results = await asyncio.gather(*tasks)

    model_labels = [f"model_{chr(ord('a') + i)}" for i in range(len(models))]
    raw_results = dict(zip(model_labels, results))
    clean_results = {label: clean_parse_result(result) for label, result in raw_results.items()}

    label_to_model = dict(zip(model_labels, models))

    # Judge the results
    judgment = await judge_results_async(
        txt_file=input_file,
        model_results=clean_results,
        judge_model=judge_model,
        save_raw_response=save_raw_response,
        file_id=file_id
    )

    winner = judgment['winner']
    suitable_for_training = judgment.get('suitable_for_training', True)

    if winner in model_labels:
        chosen_result = raw_results[winner]
        success = suitable_for_training  
    else:
        chosen_result = None
        success = False

    # Build final result
    final_result = {
        'success': success,
        'winner': winner,
        'winner_model': label_to_model.get(winner, winner) if winner in model_labels else winner,
        'result': chosen_result,
        'judgment': {
            'reason': judgment['reason'],
            'confidence': judgment['confidence'],
            'model_issues': judgment['model_issues'],
            'suitable_for_training': suitable_for_training,
            'rejection_type': judgment.get('rejection_type'),
            'rejection_reason': judgment['rejection_reason']
        },
        'input_file': input_file,
        'models': {label: model for label, model in zip(model_labels, models)},
        'judge_model': judge_model,
        'all_results': {label: clean_results[label] for label in model_labels}
    }

    basename = os.path.basename(output_file)
    judge_dir = 'data/judge'
    judge_output_file = os.path.join(judge_dir, basename)
    os.makedirs(judge_dir, exist_ok=True)

    with open(judge_output_file, 'w', encoding='utf-8') as f:
        json.dump(final_result, f, ensure_ascii=False, indent=2)

    if not suitable_for_training:
        rejection_type = judgment.get('rejection_type') or 'empty'
        fail_dir = f'data/fail_LLM/{rejection_type}'
        fail_basename = basename.replace('_multi.json', '.json')
        fail_output_file = os.path.join(fail_dir, fail_basename)
        os.makedirs(fail_dir, exist_ok=True)

        fail_data = {
            'input_file': input_file,
            'rejection_type': judgment.get('rejection_type'),
            'rejection_reason': judgment['rejection_reason'],
            'winner': winner,
            'confidence': judgment['confidence'],
            'model_issues': judgment['model_issues'],
            'judgment_detail': judgment['reason']
        }

        with open(fail_output_file, 'w', encoding='utf-8') as f:
            json.dump(fail_data, f, ensure_ascii=False, indent=2)

    elif success:
        clean_output = {
            'initial_output': chosen_result.get('initial_output', ''),
            'turns': chosen_result.get('turns', [])
        }

        clean_output_with_prompts = merge_prompts_into_output(clean_output)

        clean_basename = basename.replace('_multi.json', '.json')
        results_dir = 'data/results_LLM'
        results_output_file = os.path.join(results_dir, clean_basename)
        os.makedirs(results_dir, exist_ok=True)

        with open(results_output_file, 'w', encoding='utf-8') as f:
            json.dump(clean_output_with_prompts, f, ensure_ascii=False, indent=2)

    return final_result


if __name__ == "__main__":
    async def main():
        MODELS = [
            'kimi-k2-instruct',
            'gemini-3-flash-preview-nothinking',
        ]
        JUDGE_MODEL = 'kimi-k2-instruct'

        input_file = 'data/raw/txt/39675.txt'

        filename = os.path.splitext(os.path.basename(input_file))[0]
        output_file = f'data/judge/{filename}_multi.json'

        result = await multi_model_parse_and_save_async(
            input_file=input_file,
            output_file=output_file,
            models=MODELS,
            judge_model=JUDGE_MODEL,
            save_raw_response=True
        )

        print(f"Winner: {result['winner']} ({result.get('winner_model', '')})")
        print(f"Confidence: {result['judgment']['confidence']:.1%}")
        print(f"Suitable for training: {result['judgment']['suitable_for_training']}")

    asyncio.run(main())
