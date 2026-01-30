import re
import json
from openai import OpenAI

client = OpenAI(
    api_key='sk-TiFLADXP6zKkEykXhWcK8rGGLdLmxz2WApfjQEkAOoKeFQMH',
    base_url='https://yeysai.com/v1'
)


class TerminalParser:
    """精确的终端输出解析器，逐行分析并识别每一轮交互"""
    
    def __init__(self):
        # 常见的提示符模式
        self.prompt_patterns = [
            r'^[^@]+@[^:]+:[^\$\#\%]+[\$\#\%★]\s*',  # user@host:path$ 格式（添加★符号）
            r'^[^\s]+\([^\)]+\)\s*\([^\)]*\)\s*%\s*',  # zsh格式: path(env) (git) %
            r'^\[[^\]]+\]\s*[\$\#\%]\s*',  # [context]$ 格式
            r'^[\$\#\%>]\s*',  # 简单的 $, #, %, > 提示符
        ]
        
        # 特殊标记识别（用于排除，不是提示符）
        self.special_markers = [
            r'^\s*↪',  # 时间戳标记
            r'^\s*↩',  # 时间戳标记
            r'^\[PX\]',  # 特殊标记行
            r'^\[CR\]',
            r'^\[MB\]',
            r'^\[PL\]',
        ]
        self.error_marker = r'^\[Error:'  # 错误标记
        
    def is_prompt_line(self, line):
        """判断是否为提示符行（包含用户输入的命令）"""
        # 检查特殊标记行，这些不是提示符
        for marker in self.special_markers:
            if re.match(marker, line):
                return False
            
        # 检查是否匹配提示符模式
        for pattern in self.prompt_patterns:
            if re.match(pattern, line):
                return True
        return False
    
    def extract_command_from_prompt(self, line):
        """从提示符行中提取命令"""
        # 尝试各种提示符模式，提取命令部分
        for pattern in self.prompt_patterns:
            match = re.match(pattern, line)
            if match:
                # 提示符后的内容就是命令
                command = line[match.end():].strip()
                return command
        return line.strip()
    
    def parse_file_line_by_line(self, file_path):
        """
        逐行解析终端文件，精确识别每一轮的输入和输出
        
        返回格式：
        {
            "initial_output": "初始内容",
            "turns": [
                {
                    "turn_id": 1,
                    "raw_lines": [...],  # 这一轮的原始行
                    "action": {"content": "用户命令"},
                    "observation": {"content": "命令输出"}
                },
                ...
            ]
        }
        """
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
        
        i = 0
        while i < len(lines):
            line = lines[i].rstrip('\n')
            
            # 检查是否是提示符行（新一轮开始）
            if self.is_prompt_line(line):
                # 如果有未完成的轮次，先保存
                if current_turn is not None:
                    result["turns"].append(current_turn)
                
                # 开始新的一轮
                in_initial = False
                turn_id += 1
                command = self.extract_command_from_prompt(line)
                
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
                        "has_error": False
                    }
                }
            else:
                # 不是提示符行
                if in_initial:
                    # 还在初始阶段（第一个命令之前）
                    initial_lines.append(line)
                elif current_turn is not None:
                    # 属于当前轮次的输出
                    current_turn["raw_lines"].append(line)
                    
                    # 检查错误标记
                    if re.match(self.error_marker, line):
                        current_turn["metadata"]["has_error"] = True
                    
                    # 所有非空行都加入输出（包括时间戳）
                    if line.strip():
                        current_turn["observation"]["raw_output_lines"].append(line)
            
            i += 1
        
        # 保存最后一轮
        if current_turn is not None:
            result["turns"].append(current_turn)
        
        # 设置初始输出
        result["initial_output"] = '\n'.join(initial_lines)
        
        # 整理每一轮的输出内容
        for turn in result["turns"]:
            turn["observation"]["content"] = '\n'.join(
                turn["observation"]["raw_output_lines"]
            )
        
        return result
    
    def analyze_turn_with_llm(self, turn_data):
        """使用大模型分析单个轮次的交互"""
        system_prompt = """你是一个专业的终端交互分析助手。我会给你一轮终端交互的详细信息，包括：
- 用户输入的命令
- 命令的输出结果
- 相关的元数据（时间戳、错误标记等）

请分析这一轮交互，并返回JSON格式的结构化数据：
{
  "turn_id": 轮次ID,
  "action": {
    "content": "规范化的用户命令",
    "command_type": "命令类型（如：文件操作、系统命令、编程语言等）"
  },
  "observation": {
    "content": "清理后的输出内容",
    "status": "成功/失败/警告",
    "summary": "输出内容的简要说明"
  },
  "analysis": {
    "purpose": "用户执行此命令的目的",
    "result": "命令执行的结果",
    "key_info": "关键信息提取"
  }
}"""
        
        user_message = f"""请分析以下终端交互轮次：

轮次ID: {turn_data['turn_id']}

用户输入命令:
{turn_data['action']['content']}

原始提示符行:
{turn_data['action']['raw_prompt_line']}

命令输出:
{turn_data['observation']['content']}

元数据:
- 是否有错误: {turn_data['metadata']['has_error']}

完整原始内容:
{chr(10).join(turn_data['raw_lines'])}
"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        response = client.chat.completions.create(
            messages=messages,
            model="gpt-5.2-2025-12-11"
        ).model_dump()
        
        return response['choices'][0]['message']['content']


def analyze_terminal_file(file_path, output_path=None):
    """
    完整的终端文件分析流程
    
    Args:
        file_path: 输入的终端文件路径
        output_path: 输出JSON文件路径（可选）
    """
    parser = TerminalParser()
    
    print(f"[1/3] 正在解析文件: {file_path}")
    parsed_data = parser.parse_file_line_by_line(file_path)
    
    print(f"[2/3] 发现 {len(parsed_data['turns'])} 轮交互")
    print(f"      初始内容: {len(parsed_data['initial_output'])} 字符")
    
    # 逐轮分析
    print(f"[3/3] 开始逐轮分析（将调用大模型 {len(parsed_data['turns'])} 次）")
    
    analyzed_turns = []
    for i, turn in enumerate(parsed_data['turns'], 1):
        print(f"      分析第 {i}/{len(parsed_data['turns'])} 轮: {turn['action']['content'][:50]}...")
        
        try:
            analysis_result = parser.analyze_turn_with_llm(turn)
            analyzed_turns.append({
                "turn_id": turn["turn_id"],
                "original_data": turn,
                "llm_analysis": analysis_result
            })
        except Exception as e:
            print(f"      ⚠️  第 {i} 轮分析失败: {e}")
            analyzed_turns.append({
                "turn_id": turn["turn_id"],
                "original_data": turn,
                "llm_analysis": None,
                "error": str(e)
            })
    
    final_result = {
        "file_path": file_path,
        "initial_output": parsed_data["initial_output"],
        "total_turns": len(parsed_data["turns"]),
        "analyzed_turns": analyzed_turns
    }
    
    # 保存结果
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 分析完成！结果已保存到: {output_path}")
    
    return final_result


# 使用示例
if __name__ == "__main__":
    input_file = 'data/raw/txt/7.txt'
    output_file = 'data/analyzed/7_analyzed.json'
    
    result = analyze_terminal_file(input_file, output_file)
    
    # 打印摘要
    print("\n" + "="*60)
    print("分析摘要:")
    print("="*60)
    print(f"总轮次: {result['total_turns']}")
    for turn in result['analyzed_turns'][:3]:  # 只显示前3轮
        print(f"\n轮次 {turn['turn_id']}:")
        print(f"  命令: {turn['original_data']['action']['content']}")
        print(f"  输出行数: {len(turn['original_data']['observation']['raw_output_lines'])}")
        if turn['llm_analysis']:
            print(f"  分析结果: {turn['llm_analysis'][:100]}...")
