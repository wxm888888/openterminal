import json
import os
import asyncio
from openai import AsyncOpenAI
from llm_enhanced_split_async import one_model_parse_async

async_client = AsyncOpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url=os.getenv('OPENAI_BASE_URL', 'https://yeysai.com/v1')
)

def clean_parse_result(result):
    """Clean parsing result to keep only essential fields"""
    if result.get('skipped'):
        return {'skipped': True, 'reason': result.get('message', 'Unknown')}
    
    cleaned = {
        "initial_output": result.get("initial_output", ""),
        "turns": []
    }
    
    for turn in result.get("turns", []):
        cleaned_turn = {
            "turn_id": turn.get("turn_id"),
            "action": {
                "content": turn.get("action", {}).get("content", "")
            },
            "observation": {
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
            
            if 'raw_output_lines' in turns[i].get('observation', {}):
                turns[i]['observation']['raw_output_lines'].append(next_prompt)
            else:
                turns[i]['observation']['raw_output_lines'] = [next_prompt]
    
    return result


async def judge_results_async(txt_file, result_a, result_b, judge_model='gpt-5.2-2025-12-11'):
    """Async version of judge_results"""
    with open(txt_file, 'r', encoding='utf-8', errors='ignore') as f:
        txt_content = f.read()
    
    system_prompt = """You are an expert in Terminal Parsing Quality Evaluation. Given the raw terminal text and the parsing results from two different models, determine which one is more accurate.

Evaluation Criteria:
1. **Turn Segmentation Accuracy**: Whether prompt recognition is correct and turn boundaries are clearly defined.
2. **Command Extraction Accuracy**:
   - Whether multi-line commands (ending with `\`) are correctly merged.
   - Whether command arguments are complete.
   - Whether output was incorrectly identified as a command.
3. **Output Extraction Accuracy**:
   - Whether the output content is complete.
   - Whether command arguments were incorrectly identified as output.
   - Whether the next prompt was accidentally included in the output.
4. **Structural Integrity**:
   - Whether the action-observation mapping for each turn is correct.
   - Whether any turns were missed.
   - Whether any turns were hallucinated (fictionalized).

Return the result in JSON format:
{
  "winner": "model_a" | "model_b" | "both_incorrect" | "tie",
  "reason": "Detailed reasoning for the judgment",
  "confidence": 0.0-1.0,
  "model_a_issues": ["List of issues for Model A"],
  "model_b_issues": ["List of issues for Model B"]
}

Notes:
- If both results contain severe errors, return "both_incorrect".
- If both results are of equal quality, return "tie".
- Prioritize the result with more accurate turn segmentation and clearer command-output correspondence."""
    
    user_message = f"""Please compare the parsing results of the two models and determine which one is more accurate.

[Raw Terminal Text]
```
{txt_content}
```

[Model A Parsing Result]
```json
{json.dumps(result_a, indent=2, ensure_ascii=False)}
```

[Model B Parsing Result]
```json
{json.dumps(result_b, indent=2, ensure_ascii=False)}
```

Please compare the two results point-by-point and provide your judgment."""
    
    try:
        response = await async_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=judge_model,
            temperature=0.3
        )
        
        result = response.choices[0].message.content
        
        if '```json' in result:
            result = result.split('```json')[1].split('```')[0]
        elif '```' in result:
            result = result.split('```')[1].split('```')[0]
        
        data = json.loads(result)
        
        return {
            'winner': data.get('winner', 'tie'),
            'reason': data.get('reason', 'No reason provided'),
            'confidence': data.get('confidence', 0.5),
            'model_a_issues': data.get('model_a_issues', []),
            'model_b_issues': data.get('model_b_issues', [])
        }
    
    except Exception as e:
        return {
            'winner': 'tie',
            'reason': f'Judge model failed: {e}',
            'confidence': 0.0,
            'model_a_issues': [],
            'model_b_issues': []
        }


async def dual_model_parse_and_save_async(
    input_file, 
    output_file,
    model_a='gpt-5.2-2025-12-11',
    model_b='claude-opus-4-5-20251101',
    judge_model='claude-sonnet-4-5-20250929-thinking'
):
    """
    Async version: Parse with two models concurrently, then judge
    """
    # Parse with both models concurrently
    result_a_task = one_model_parse_async(input_file, model_a)
    result_b_task = one_model_parse_async(input_file, model_b)
    
    result_a, result_b = await asyncio.gather(result_a_task, result_b_task)
    
    clean_a = clean_parse_result(result_a)
    clean_b = clean_parse_result(result_b)
    
    if clean_a.get('skipped'):
        final_result = {
            'success': False,
            'winner': 'none',
            'result': None,
            'judgment': {
                'reason': f"Model A skipped file: {clean_a['reason']}",
                'confidence': 1.0
            },
            'input_file': input_file,
            'model_a': model_a,
            'model_b': model_b
        }
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        
        return final_result
    
    if clean_b.get('skipped'):
        final_result = {
            'success': False,
            'winner': 'none',
            'result': None,
            'judgment': {
                'reason': f"Model B skipped file: {clean_b['reason']}",
                'confidence': 1.0
            },
            'input_file': input_file,
            'model_a': model_a,
            'model_b': model_b
        }
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        
        return final_result
    
    # Judge results
    judgment = await judge_results_async(input_file, clean_a, clean_b, judge_model)
    
    winner = judgment['winner']
    
    if winner == 'model_a':
        chosen_result = result_a
        success = True
    elif winner == 'model_b':
        chosen_result = result_b
        success = True
    elif winner == 'tie':
        chosen_result = result_a
        success = True
    else:  # both_incorrect
        chosen_result = None
        success = False
    
    final_result = {
        'success': success,
        'winner': winner,
        'result': chosen_result,
        'judgment': {
            'reason': judgment['reason'],
            'confidence': judgment['confidence'],
            'model_a_issues': judgment['model_a_issues'],
            'model_b_issues': judgment['model_b_issues']
        },
        'input_file': input_file,
        'model_a': model_a,
        'model_b': model_b,
        'judge_model': judge_model,
        'model_a_result': clean_a,
        'model_b_result': clean_b
    }
    
    # Save complete result to data/judge/
    basename = os.path.basename(output_file)
    judge_dir = 'data/judge'
    judge_output_file = os.path.join(judge_dir, basename)
    os.makedirs(judge_dir, exist_ok=True)
    
    with open(judge_output_file, 'w', encoding='utf-8') as f:
        json.dump(final_result, f, ensure_ascii=False, indent=2)
    
    # If successful, save simplified result to data/results/
    if success and chosen_result:
        clean_output = {
            'initial_output': chosen_result.get('initial_output', ''),
            'turns': chosen_result.get('turns', [])
        }
        
        # Merge prompts into output stream
        clean_output_with_prompts = merge_prompts_into_output(clean_output)
        
        # Save simplified result to results/ folder with _dual removed
        clean_basename = basename.replace('_dual.json', '.json')
        results_dir = 'data/results'
        results_output_file = os.path.join(results_dir, clean_basename)
        os.makedirs(results_dir, exist_ok=True)
        
        with open(results_output_file, 'w', encoding='utf-8') as f:
            json.dump(clean_output_with_prompts, f, ensure_ascii=False, indent=2)
    
    return final_result


if __name__ == "__main__":
    async def main():
        MODEL_A = 'gpt-5.2-2025-12-11'
        MODEL_B = 'claude-opus-4-5-20251101'
        JUDGE_MODEL = 'claude-sonnet-4-5-20250929-thinking'
        
        input_file = 'data/test/10000.txt'
        
        filename = os.path.splitext(os.path.basename(input_file))[0]
        output_file = f'data/judge/{filename}_dual_async.json'
        
        result = await dual_model_parse_and_save_async(
            input_file=input_file,
            output_file=output_file,
            model_a=MODEL_A,
            model_b=MODEL_B,
            judge_model=JUDGE_MODEL
        )
        
        print(f"✅ Winner: {result['winner']}")
        print(f"Confidence: {result['judgment']['confidence']:.1%}")
    
    asyncio.run(main())
