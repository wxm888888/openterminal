import json
import os
from openai import OpenAI
from llm_enhanced_split import one_model_parse

client = OpenAI(
    api_key='sk-TiFLADXP6zKkEykXhWcK8rGGLdLmxz2WApfjQEkAOoKeFQMH',
    base_url='https://yeysai.com/v1'
)

def clean_parse_result(result):
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
    import copy
    result = copy.deepcopy(clean_output)
    
    turns = result.get('turns', [])
    
    if not turns:
        return result
    
    # 1. 第一个 turn 的 prompt 加到 initial_output 后面
    first_prompt = turns[0].get('prompt', '')
    if first_prompt:
        current_initial = result.get('initial_output', '')
        if current_initial:
            result['initial_output'] = current_initial + '\n' + first_prompt
        else:
            result['initial_output'] = first_prompt
    
    # 2. 后续 turn 的 prompt 加到上一个 turn 的 observation 后面
    for i in range(len(turns) - 1):
        next_prompt = turns[i + 1].get('prompt', '')
        
        if next_prompt:
            # 更新 observation.content
            current_content = turns[i].get('observation', {}).get('content', '')
            if current_content:
                turns[i]['observation']['content'] = current_content + '\n' + next_prompt
            else:
                turns[i]['observation']['content'] = next_prompt
            
            # 更新 observation.raw_output_lines
            if 'raw_output_lines' in turns[i].get('observation', {}):
                turns[i]['observation']['raw_output_lines'].append(next_prompt)
            else:
                turns[i]['observation']['raw_output_lines'] = [next_prompt]
    
    return result


def judge_results(txt_file, result_a, result_b, judge_model='gpt-5.2-2025-12-11'):
    # 读取原始文本
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
  "reason": "Detailed reasoning for the judgment (explaining where and why one model outperformed the other)",
  "confidence": 0.0-1.0,
  "model_a_issues": ["List of issues for Model A"],
  "model_b_issues": ["List of issues for Model B"]
}

Notes:
- If both results contain severe errors (e.g., inaccurate turn segmentation or discrepancies relative to the raw text), return "both_incorrect".
- If both results are of equal quality and it is difficult to determine a winner, return "tie".
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
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            model=judge_model,
            temperature=0.3
        ).model_dump()
        
        result = response['choices'][0]['message']['content']
        
        # 解析JSON
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
        print(f"  ⚠️ 裁判模型判断失败: {e}")
        return {
            'winner': 'tie',
            'reason': f'Judge model failed: {e}',
            'confidence': 0.0,
            'model_a_issues': [],
            'model_b_issues': []
        }


def dual_model_parse_and_save(
    input_file, 
    output_file,
    model_a='gpt-5.2-2025-12-11',
    model_b='gpt-4o',
    judge_model='gpt-5.2-2025-12-11'
):
    print("="*70)
    print("双模型解析 + 裁判机制")
    print("="*70)
    print(f"输入文件: {input_file}")
    print(f"模型A: {model_a}")
    print(f"模型B: {model_b}")
    print(f"裁判模型: {judge_model}")
    print("="*70)
    
    # 步骤1：模型A解析
    print(f"\n{'='*70}")
    print(f"[步骤1/3] 模型A解析")
    print(f"{'='*70}")
    result_a = one_model_parse(input_file, model_a)
    clean_a = clean_parse_result(result_a)
    
    if clean_a.get('skipped'):
        print(f"  ⚠️ 模型A判断文件不适合处理: {clean_a['reason']}")
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
        
        # 保存失败记录
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✓ 失败记录已保存到: {output_file}")
        return final_result
    
    print(f"  ✓ 模型A完成：{len(clean_a['turns'])} 个轮次")
    
    # 步骤2：模型B解析
    print(f"\n{'='*70}")
    print(f"[步骤2/3] 模型B解析")
    print(f"{'='*70}")
    result_b = one_model_parse(input_file, model_b)
    clean_b = clean_parse_result(result_b)
    
    if clean_b.get('skipped'):
        print(f"  ⚠️ 模型B判断文件不适合处理: {clean_b['reason']}")
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
        
        # 保存失败记录
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        
        print(f"\n✓ 失败记录已保存到: {output_file}")
        return final_result
    
    print(f"  ✓ 模型B完成：{len(clean_b['turns'])} 个轮次")
    
    # 步骤3：裁判模型判断
    print(f"\n{'='*70}")
    print(f"[步骤3/3] 裁判模型判断")
    print(f"{'='*70}")
    judgment = judge_results(input_file, clean_a, clean_b, judge_model)
    
    print(f"  胜出: {judgment['winner']}")
    print(f"  理由: {judgment['reason'][:100]}...")
    print(f"  置信度: {judgment['confidence']:.1%}")
    
    # 根据判断选择结果
    winner = judgment['winner']
    
    if winner == 'model_a':
        final_result = {
            'success': True,
            'winner': 'model_a',
            'result': result_a,  # 使用完整结果（包含verification）
            'judgment': judgment,
            'input_file': input_file,
            'model_a': model_a,
            'model_b': model_b,
            'judge_model': judge_model
        }
        print(f"\n  ✅ 选择模型A的结果")
    
    elif winner == 'model_b':
        final_result = {
            'success': True,
            'winner': 'model_b',
            'result': result_b,  # 使用完整结果（包含verification）
            'judgment': judgment,
            'input_file': input_file,
            'model_a': model_a,
            'model_b': model_b,
            'judge_model': judge_model
        }
        print(f"\n  ✅ 选择模型B的结果")
    
    elif winner == 'both_incorrect':
        final_result = {
            'success': False,
            'winner': 'none',
            'result': None,
            'judgment': judgment,
            'input_file': input_file,
            'model_a': model_a,
            'model_b': model_b,
            'judge_model': judge_model,
            'model_a_result': clean_a,  # 保存两个结果用于debug
            'model_b_result': clean_b
        }
        print(f"\n  ❌ 两个模型的结果都不正确")
    
    else:  # tie
        # 平局时默认选择模型A
        final_result = {
            'success': True,
            'winner': 'tie_use_model_a',
            'result': result_a,
            'judgment': judgment,
            'input_file': input_file,
            'model_a': model_a,
            'model_b': model_b,
            'judge_model': judge_model
        }
        print(f"\n  ⚖️ 平局，默认使用模型A")
    
    # 保存完整结果（包含元数据）到 data/judge/ 文件夹
    # 从 output_file 提取文件名，重新构造路径
    basename = os.path.basename(output_file)  # 例如：759276_dual.json
    
    # 完整结果保存到 data/judge/
    judge_dir = 'data/judge'
    judge_output_file = os.path.join(judge_dir, basename)
    os.makedirs(judge_dir, exist_ok=True)
    
    with open(judge_output_file, 'w', encoding='utf-8') as f:
        json.dump(final_result, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*70}")
    print(f"✓ 完整结果已保存到: {judge_output_file}")
    
    # 如果成功，额外保存一个简化版（只包含 initial_output 和 turns）到 results/ 文件夹
    if final_result['success']:
        chosen_result = final_result['result']
        
        clean_output = {
            'initial_output': chosen_result.get('initial_output', ''),
            'turns': chosen_result.get('turns', [])
        }
        
        # 将提示符融入输出流中
        clean_output_with_prompts = merge_prompts_into_output(clean_output)
        
        # 简化结果保存到 results/ 文件夹，文件名去掉 _dual 后缀
        # 例如：759276_dual.json -> 759276.json
        clean_basename = basename.replace('_dual.json', '.json')
        results_dir = 'data/results'
        results_output_file = os.path.join(results_dir, clean_basename)
        os.makedirs(results_dir, exist_ok=True)
        
        with open(results_output_file, 'w', encoding='utf-8') as f:
            json.dump(clean_output_with_prompts, f, ensure_ascii=False, indent=2)
        
        print(f"✓ 简化结果已保存到: {results_output_file}（提示符已融入输出流）")
    
    print(f"{'='*70}")
    
    # 打印摘要
    if final_result['success']:
        chosen_result = final_result['result']
        print(f"\n最终结果摘要：")
        print(f"  胜出模型: {final_result['winner']}")
        print(f"  总轮次: {chosen_result.get('total_turns', 0)}")
        print(f"  学到的模式: {len(chosen_result.get('learned_patterns', []))}")
    else:
        print(f"\n处理失败：")
        print(f"  原因: {final_result['judgment']['reason']}")
        if 'model_a_result' in final_result:
            print(f"  模型A轮次: {len(final_result['model_a_result']['turns'])}")
            print(f"  模型B轮次: {len(final_result['model_b_result']['turns'])}")
    
    return final_result


if __name__ == "__main__":
    # 配置两个模型
    MODEL_A = 'claude-sonnet-4-5-20250929-thinking'
    MODEL_B = 'gpt-5.2-2025-12-11'
    JUDGE_MODEL = 'claude-opus-4-5-20251101'
    
    # 输入文件路径
    input_file = 'data/raw/txt/137.txt'
    
    # 自动从 input_file 提取文件名（不含扩展名）
    import os
    filename = os.path.splitext(os.path.basename(input_file))[0]  # '442'
    output_file = f'{filename}_dual.json'  # '442_dual.json'
    
    result = dual_model_parse_and_save(
        input_file=input_file,
        output_file=output_file,
        model_a=MODEL_A,
        model_b=MODEL_B,
        judge_model=JUDGE_MODEL
    )
    
    print(f"\n处理完成！成功: {result['success']}")
