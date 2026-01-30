"""
简化版增强终端解析器 - 完全基于LLM的三步流程
"""
import re
import json
from openai import OpenAI

client = OpenAI(
    api_key='sk-TiFLADXP6zKkEykXhWcK8rGGLdLmxz2WApfjQEkAOoKeFQMH',
    base_url='https://yeysai.com/v1'
)


class SimplifiedTerminalParser:
    """简化版解析器：LLM主导的三步流程"""
    
    def __init__(self):
        self.prompt_patterns = []  # LLM学习到的提示符模式
        self.error_marker = r'^\[Error:'
    
    def step1_learn_prompts(self, file_path, sample_lines=100):
        """步骤1：让LLM分析前N行，直接给出提示符正则"""
        print(f"\n[1/4] LLM分析提示符模式")
        
        # 读取前N行
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = []
            for _ in range(sample_lines):
                line = f.readline()
                if not line:
                    break
                lines.append(line.rstrip('\n'))
        
        sample_text = '\n'.join(lines)
        
        system_prompt = """你是终端提示符识别专家。

分析给定的终端输出文本，找出【所有不同的】提示符模式。

⚠️ 重要：同一个终端会话中可能存在多个提示符！
- 因为目录切换（cd命令）导致路径变化
- 因为git分支切换导致分支名变化
- 因为虚拟环境激活/退出导致环境名变化
- 因为权限变化（普通用户 $ vs root #）

提示符特征：
- 包含用户名、主机名、路径、git分支、虚拟环境等动态信息
- 以特殊符号结尾（$, #, %, >, ★, ✗ 等）
- 格式相对固定，但内容会变化
- 后面跟着用户输入的命令

生成正则时的关键要求：
1. 正则要【足够通用】，能匹配同一格式但内容不同的提示符
   例如：`user@host:/path1$` 和 `user@host:/path2$` 应该用同一个正则匹配
   正确: `^[^@]+@[^:]+:[^$]+\\$\\s+`
   错误: `^user@host:/path1\\$\\s+` （太具体，只能匹配path1）

2. 正则【只匹配提示符部分】，不要匹配后面的命令
   例如：`➜ dir git:(main) ✗ command` 应该匹配到 `✗` 后（包含可选的空格）为止

3. 正则应该以 `\\s*` 结尾（0个或多个空格），这样可以匹配空命令的提示符

4. 找出所有格式不同的提示符（即使只出现一次也要识别）

返回JSON格式：
{
  "patterns": [
    {
      "example": "示例提示符行（完整的一行，包含命令）",
      "regex": "只匹配提示符部分的通用正则（以\\\\s+结尾）",
      "description": "说明这个模式的特点"
    }
  ]
}

示例输出：
{
  "patterns": [
    {
      "example": "user@host:~/dir1$ cd /tmp",
      "regex": "^[^@]+@[^:]+:[^$]+\\\\$\\\\s*",
      "description": "标准bash提示符：用户@主机:路径$"
    },
    {
      "example": "➜  project git:(main) ✗ npm start",
      "regex": "^➜\\\\s+[^\\\\s]+\\\\s+git:\\\\([^\\\\)]+\\\\)\\\\s+✗\\\\s*",
      "description": "zsh提示符：带git分支和修改状态"
    }
  ]
}

注意：正则以 \\s* 结尾可以匹配有命令和无命令（空提示符）两种情况。"""
        
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"""分析以下终端输出，找出【所有不同格式的】提示符模式。

注意：
- 即使路径、分支名不同，但格式相同的提示符只需要一个通用正则
- 但如果格式完全不同（如 bash风格 vs zsh风格），需要分别识别
- 确保正则足够通用，能匹配动态内容（路径、分支、环境名等）

终端输出：
{sample_text}

请返回所有提示符模式的通用正则表达式。"""}
                ],
                model="gpt-5.2-2025-12-11"
            ).model_dump()
            
            result = response['choices'][0]['message']['content']
            
            # 解析JSON
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            
            data = json.loads(result)
            
            print(f"\n  【步骤1调试信息：LLM返回的提示符判断】")
            print(f"  找到 {len(data.get('patterns', []))} 个模式\n")
            
            for idx, item in enumerate(data.get('patterns', []), 1):
                print(f"  模式 {idx}:")
                print(f"    示例行: {item.get('example', 'N/A')}")
                print(f"    原始正则: {item.get('regex', 'N/A')}")
                print(f"    说明: {item.get('description', 'N/A')}")
                
                pattern = item.get('regex', '')
                if pattern:
                    # 清洗正则：去掉命名捕获组 (?<name>) → (...)
                    cleaned = re.sub(r'\(\?<[^>]+>', '(', pattern)
                    
                    # 验证正则有效性
                    try:
                        re.compile(cleaned)
                        self.prompt_patterns.append(cleaned)
                        if cleaned != pattern:
                            print(f"    清洗后: {cleaned}")
                        print(f"    ✅ 模式有效，已添加")
                    except re.error as e:
                        print(f"    ❌ 模式无效，已跳过: {e}")
                print()
            
            return len(self.prompt_patterns) > 0
        
        except Exception as e:
            print(f"  ⚠️ LLM分析失败: {e}")
            return False
    
    def step2_filter_fake_prompts(self, file_path):
        """步骤2：LLM过滤假提示符（只是恰好重复的文本）"""
        print(f"\n[2/4] LLM过滤假提示符")
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # 收集所有匹配提示符正则的行
        candidate_prompts = []
        for line_num, line in enumerate(lines, 1):
            line_content = line.rstrip('\n')
            
            # 检查是否匹配任何提示符模式
            matched = False
            for pattern in self.prompt_patterns:
                try:
                    if re.match(pattern, line_content):
                        matched = True
                        break
                except re.error:
                    continue
            
            if matched:
                candidate_prompts.append({
                    'line_num': line_num,
                    'content': line_content,
                    'prev_line': lines[line_num-2].rstrip('\n') if line_num > 1 else '',
                    'next_line': lines[line_num].rstrip('\n') if line_num < len(lines) else ''
                })
        
        print(f"  发现 {len(candidate_prompts)} 个候选提示符行")
        
        if not candidate_prompts:
            print(f"  ⚠️ 没有找到匹配的行")
            return set()
        
        # 打印候选行详情
        print(f"\n  【步骤2调试信息：候选提示符行】")
        for i, c in enumerate(candidate_prompts[:10], 1):
            print(f"    候选{i} [行{c['line_num']}]: {c['content'][:70]}...")
        if len(candidate_prompts) > 10:
            print(f"    ... 还有 {len(candidate_prompts) - 10} 个候选")
        
        # 让LLM判断哪些是真的提示符
        confirmed_line_nums = self._filter_with_llm(candidate_prompts)
        
        print(f"\n  ✓ 确认 {len(confirmed_line_nums)} 个真实提示符")
        print(f"  ✓ 过滤掉 {len(candidate_prompts) - len(confirmed_line_nums)} 个假提示符")
        
        return confirmed_line_nums
    
    def _filter_with_llm(self, candidates):
        """让LLM判断哪些候选行是真正的提示符"""
        system_prompt = """你是终端提示符验证专家。判断哪些行是真正的提示符，哪些只是恰好匹配正则的文本。

真提示符的特征：
1. 位置：通常在命令输出之后，新命令之前
2. 上下文：前一行是命令输出（或空行），后面跟着命令（或空）
3. 功能：标记新的用户输入开始

假提示符（应该过滤）：
1. 命令输出中恰好包含类似提示符的文本
   例如：echo "user@host:~$ this is just text"
2. 程序打印的日志、错误信息中的文本
3. 文件内容、代码片段中的文本

返回JSON格式：
{
  "confirmed_prompts": [真提示符的行号列表],
  "false_positives": [
    {"line_num": 假提示符的行号, "reason": "为什么判断为假"}
  ]
}

注意：如果不确定，倾向于认为是真提示符（保守策略）。"""
        
        # 构造候选列表（最多50个）
        candidates_text = []
        for c in candidates[:50]:
            candidates_text.append(f"""
行 {c['line_num']}:
  上一行: {c['prev_line'][:100] if c['prev_line'] else '(文件开头)'}
  【当前】: {c['content'][:100]}
  下一行: {c['next_line'][:100] if c['next_line'] else '(文件结尾)'}
""")
        
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"判断以下候选行哪些是真正的提示符：{''.join(candidates_text)}\n\n请逐行分析，给出确认的真提示符行号列表。"}
                ],
                model="gpt-5.2-2025-12-11",
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
            
            # 打印过滤掉的假提示符
            if false_positives:
                print(f"\n  【过滤掉的假提示符】")
                for fp in false_positives[:10]:
                    print(f"    行 {fp['line_num']}: {fp.get('reason', 'N/A')[:80]}")
            
            return confirmed
        
        except Exception as e:
            print(f"  ⚠️ LLM过滤失败: {e}")
            # 失败时返回所有候选（保守策略）
            return set(c['line_num'] for c in candidates)
    
    def step3_parse_turns(self, file_path, confirmed_line_nums):
        """步骤3：用确认的提示符行划分轮次"""
        print(f"\n[3/4] 用确认的提示符划分轮次")
        
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
            
            # 只在确认的行号上识别提示符
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
                # 保存上一轮
                if current_turn is not None:
                    result["turns"].append(current_turn)
                
                # 开始新一轮
                in_initial = False
                turn_id += 1
                
                # 提取命令（从提示符结束位置到行尾）
                pattern_str, match = matched_pattern
                command = line[match.end():].strip()
                
                current_turn = {
                    "turn_id": turn_id,
                    "raw_lines": [line],
                    "action": {
                        "content": command,
                        "raw_prompt_line": line
                    },
                    "observation": {
                        "content": "",
                        "raw_output_lines": []
                    },
                    "metadata": {
                        "has_error": False,
                        "matched_pattern": pattern_str  # 记录是哪个模式匹配的
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
                    
                    # 添加到输出行
                    if line.strip():
                        current_turn["observation"]["raw_output_lines"].append(line)
        
        # 保存最后一轮
        if current_turn is not None:
            result["turns"].append(current_turn)
        
        result["initial_output"] = '\n'.join(initial_lines)
        
        # 合并输出内容
        for turn in result["turns"]:
            turn["observation"]["content"] = '\n'.join(
                turn["observation"]["raw_output_lines"]
            )
        
        print(f"  ✓ 划分出 {len(result['turns'])} 个轮次")
        
        # 打印每个轮次的提示符匹配情况
        if result['turns']:
            print(f"\n  【步骤3调试信息：轮次提示符匹配详情】")
            
            # 统计每个模式匹配了多少轮次
            pattern_counts = {}
            for turn in result['turns']:
                pattern = turn['metadata'].get('matched_pattern', 'unknown')
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
            
            print(f"  模式使用统计：")
            for idx, (pattern, count) in enumerate(pattern_counts.items(), 1):
                print(f"    模式{idx}: {count} 个轮次")
                print(f"    正则: {pattern[:80]}{'...' if len(pattern) > 80 else ''}")
            
            print(f"\n  前5个轮次详情：")
            for turn in result['turns'][:5]:
                prompt_line = turn['action']['raw_prompt_line']
                command = turn['action']['content']
                matched_pattern = turn['metadata'].get('matched_pattern', 'unknown')
                pattern_idx = list(pattern_counts.keys()).index(matched_pattern) + 1 if matched_pattern in pattern_counts else 0
                
                print(f"  轮次 {turn['turn_id']} [模式{pattern_idx}]:")
                print(f"    原始行: {prompt_line[:70]}{'...' if len(prompt_line) > 70 else ''}")
                print(f"    提取命令: {command if command else '(空命令)'}")
            
            if len(result['turns']) > 5:
                print(f"  ... 还有 {len(result['turns']) - 5} 个轮次")
        
        return result
    
    def step4_verify_turns(self, turns):
        """步骤4：让LLM验证每个轮次的命令和输出分割"""
        print(f"\n[4/4] LLM验证每个轮次的命令/输出分割")
        
        verification_results = []
        issues_found = 0
        corrected_count = 0
        turns_to_delete = []  # 记录需要删除的轮次索引
        
        for i in range(len(turns)):
            # 只验证当前轮次（不看上下文）
            verification = self._verify_single_turn(turns[i])
            verification_results.append(verification)
            
            if not verification['is_correct']:
                issues_found += 1
                print(f"\n  【步骤4调试信息：发现问题】")
                print(f"  ⚠️ 轮次 {turns[i]['turn_id']}: {verification['issue'][:80]}...")
                
                # 检查是否应该删除此轮次
                if verification.get('should_delete', False):
                    turns_to_delete.append(i)
                    print(f"    🗑️  标记删除：轮次 {turns[i]['turn_id']} 将被删除")
                
                # 如果不删除但有修正数据，自动应用
                elif 'corrected_turn' in verification and verification['corrected_turn']:
                    corrected = verification['corrected_turn']
                    
                    # 应用修正
                    if 'action' in corrected and 'content' in corrected['action']:
                        turns[i]['action']['content'] = corrected['action']['content']
                        print(f"    ✅ 命令已修正: {corrected['action']['content'][:60]}...")
                    
                    if 'observation' in corrected and 'content' in corrected['observation']:
                        new_output = corrected['observation']['content']
                        turns[i]['observation']['content'] = new_output
                        turns[i]['observation']['raw_output_lines'] = [
                            line for line in new_output.split('\n') if line.strip()
                        ]
                        print(f"    ✅ 输出已修正（{len(turns[i]['observation']['raw_output_lines'])} 行）")
                    
                    corrected_count += 1
        
        # 删除标记的轮次（从后往前删，避免索引变化）
        deleted_count = 0
        if turns_to_delete:
            print(f"\n  【删除多余轮次】")
            for i in sorted(turns_to_delete, reverse=True):
                deleted_turn = turns.pop(i)
                deleted_count += 1
                print(f"    ✅ 已删除轮次 {deleted_turn['turn_id']} (索引 {i})")
            
            # 重新分配 turn_id
            print(f"\n  【重新分配轮次ID】")
            for i, turn in enumerate(turns, 1):
                old_id = turn['turn_id']
                turn['turn_id'] = i
                if old_id != i:
                    print(f"    轮次 {old_id} → {i}")
        
        print(f"\n  ✓ 验证完成！{len(turns) - issues_found + deleted_count}/{len(turns) + deleted_count} 轮正确")
        if corrected_count > 0:
            print(f"  ✅ 自动修正了 {corrected_count} 个轮次")
        if deleted_count > 0:
            print(f"  🗑️  删除了 {deleted_count} 个多余轮次")
        
        return verification_results
    
    def _verify_single_turn(self, turn):
        """验证单个轮次的命令和输出分割"""
        system_prompt = """你是终端轮次验证专家。给定一个轮次的原始行（raw_lines），判断命令和输出是否正确分割。

判断标准：
1. 第一行通常是：提示符 + 命令
2. 续行命令（以 \\ 结尾）应该合并到命令中，续行参数不应该被当作输出
3. 命令参数（以 -- 开头或缩进的续行）不应该被误认为是输出
4. 输出应该从第一个非命令行开始
5. 输出不应该包含下一个提示符
6. 空命令且无输出的轮次应该删除

返回JSON格式：
{
  "is_correct": true/false,
  "issue": "如果不正确，说明问题（简洁明了，一句话）",
  "should_delete": true/false,  // 如果是空命令且无输出，设为true
  "corrected_turn": {  // 如果不删除但需要修正，返回修正后的数据
    "action": {
      "content": "修正后的完整命令（包含所有续行参数，去掉反斜杠）"
    },
    "observation": {
      "content": "修正后的输出内容（只包含真正的命令输出，不包含命令参数行）"
    }
  }
}

注意：
1. 只根据给定的原始行来判断
2. 续行命令示例：第1行 "cmd \\" + 第2行 " --option" → 命令应该是 "cmd --option"
3. 输出从第一个不是命令、不是续行参数的行开始"""
        
        # 构造原始行显示
        raw_lines_text = '\n'.join([
            f"    {i+1}. {line[:150]}{'...' if len(line) > 150 else ''}" 
            for i, line in enumerate(turn['raw_lines'])
        ])
        
        # 构造当前分割结果
        current_command = turn['action']['content'] or '(空)'
        current_output = turn['observation']['content'][:300] if turn['observation']['content'] else '(空)'
        
        user_message = f"""请验证以下轮次的命令和输出分割：

【原始行】（共 {len(turn['raw_lines'])} 行）
{raw_lines_text}

【当前分割结果】
命令: {current_command}
输出: {current_output}{'...' if len(turn['observation']['content']) > 300 else ''}

请判断分割是否正确，如果不正确请给出修正。"""
        
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model="gpt-5.2-2025-12-11",
                temperature=0.3
            ).model_dump()
            
            result = response['choices'][0]['message']['content']
            
            # 解析JSON
            if '```json' in result:
                result = result.split('```json')[1].split('```')[0]
            elif '```' in result:
                result = result.split('```')[1].split('```')[0]
            
            data = json.loads(result)
            
            verification_result = {
                'turn_id': turn['turn_id'],
                'is_correct': data.get('is_correct', True),
                'issue': data.get('issue', ''),
                'suggestion': data.get('suggestion', ''),
                'should_delete': data.get('should_delete', False)
            }
            
            # 如果有修正数据，添加到返回结果中
            if 'corrected_turn' in data and data['corrected_turn']:
                verification_result['corrected_turn'] = data['corrected_turn']
            
            return verification_result
        
        except Exception as e:
            # 验证失败时默认认为正确
            return {
                'turn_id': turn['turn_id'],
                'is_correct': True,
                'issue': '',
                'suggestion': '',
                'should_delete': False
            }


def parse_terminal_file(input_file, output_file=None):
    """
    主流程：四步走
    1. LLM分析前100行，学习提示符模式
    2. LLM过滤假提示符（只是恰好重复的文本）
    3. 用确认的提示符行划分轮次
    4. LLM验证每个轮次（带上下文）
    """
    parser = SimplifiedTerminalParser()
    
    print("="*70)
    print("增强版终端解析器 - LLM四步主导模式")
    print("="*70)
    print("""
流程说明：
  [1/4] LLM分析前100行 → 学习提示符正则模式
  [2/4] LLM过滤假提示符 → 确认哪些行是真提示符
  [3/4] 用确认的提示符行 → 划分轮次
  [4/4] LLM验证每个轮次 → 自动修正错误
    """)
    
    # 步骤1：学习提示符
    success = parser.step1_learn_prompts(input_file)
    if not success or len(parser.prompt_patterns) == 0:
        print("  ⚠️ 未识别到提示符，使用默认模式")
        parser.prompt_patterns = [r'^[\$\#\%>]\s*']
    
    # 步骤2：过滤假提示符
    confirmed_line_nums = parser.step2_filter_fake_prompts(input_file)
    if not confirmed_line_nums:
        print("  ⚠️ 未确认任何提示符行，将使用所有匹配的行")
        # 如果LLM过滤失败，收集所有匹配的行
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
    
    # 步骤3：划分轮次
    parsed_data = parser.step3_parse_turns(input_file, confirmed_line_nums)
    
    # 步骤4：验证轮次
    verification_results = []
    if len(parsed_data['turns']) > 0:
        verification_results = parser.step4_verify_turns(parsed_data['turns'])
    else:
        print("\n[4/4] 跳过验证（未发现轮次）")
    
    # 构造最终结果
    final_result = {
        "file_path": input_file,
        "total_turns": len(parsed_data['turns']),
        "initial_output": parsed_data["initial_output"],
        "turns": parsed_data["turns"],
        "learned_patterns": parser.prompt_patterns,
        "confirmed_prompt_lines": sorted(list(confirmed_line_nums)),  # 新增：确认的提示符行号
        "verification_results": verification_results
    }
    
    # 保存JSON
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 结果已保存到: {output_file}")
    
    # 打印摘要
    print(f"\n{'='*70}")
    print(f"解析摘要")
    print(f"{'='*70}")
    print(f"文件: {input_file}")
    print(f"确认的提示符行: {len(confirmed_line_nums)} 行")
    print(f"总轮次: {len(parsed_data['turns'])}")
    print(f"学到的模式数: {len(parser.prompt_patterns)}")
    
    if parser.prompt_patterns:
        print(f"\n识别到的提示符模式（共{len(parser.prompt_patterns)}个）：")
        
        # 统计每个模式的使用情况
        pattern_usage = {}
        for turn in parsed_data['turns']:
            pattern = turn['metadata'].get('matched_pattern', '')
            if pattern in parser.prompt_patterns:
                pattern_usage[pattern] = pattern_usage.get(pattern, 0) + 1
        
        for i, p in enumerate(parser.prompt_patterns, 1):
            usage_count = pattern_usage.get(p, 0)
            print(f"  模式{i}: {p}")
            print(f"          使用次数: {usage_count}")
    
    # 调试信息汇总
    print(f"\n{'='*70}")
    print(f"调试信息汇总")
    print(f"{'='*70}")
    print(f"步骤1 - 学习模式: {len(parser.prompt_patterns)} 个正则模式")
    print(f"步骤2 - 过滤假提示符: {len(confirmed_line_nums)} 行确认为真提示符")
    print(f"步骤3 - 划分轮次: {len(parsed_data['turns'])} 个轮次")
    if verification_results:
        corrected = sum(1 for v in verification_results if not v['is_correct'] and not v.get('should_delete'))
        deleted = sum(1 for v in verification_results if v.get('should_delete'))
        print(f"步骤4 - 验证修正: {corrected} 个轮次被修正, {deleted} 个轮次被删除")
    
    if verification_results:
        correct = sum(1 for v in verification_results if v['is_correct'])
        print(f"\n验证结果: {correct}/{len(verification_results)} 轮次正确")
    
    return final_result


if __name__ == "__main__":
    # 默认解析 7.txt
    result = parse_terminal_file(
        input_file='data/raw/txt/759276.txt',
        output_file='data/analyzed/759276_enhanced_v2.json'
    )
    
    # 预览前3轮（显示修正后的结果）
    if result['turns']:
        print(f"\n{'='*70}")
        print("前3轮预览（修正后）")
        print(f"{'='*70}")
        for turn in result['turns'][:3]:
            # 检查该轮次是否被修正
            was_corrected = False
            for v in result.get('verification_results', []):
                if v['turn_id'] == turn['turn_id'] and not v['is_correct']:
                    was_corrected = True
                    break
            
            status = " [已修正]" if was_corrected else ""
            print(f"\n轮次 {turn['turn_id']}{status}:")
            print(f"  提示符: {turn['action']['raw_prompt_line'][:60]}...")
            print(f"  命令: {turn['action']['content'] or '(空)'}")
            print(f"  输出行数: {len(turn['observation']['raw_output_lines'])}")
            if turn['observation']['content']:
                print(f"  输出预览: {turn['observation']['content'][:80]}...")
