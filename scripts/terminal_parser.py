"""
终端输出解析器 - 独立模块，不依赖OpenAI
"""
import re
import json


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


if __name__ == "__main__":
    import sys
    
    # 简单测试
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = 'data/raw/txt/7016.txt'
    
    parser = TerminalParser()
    result = parser.parse_file_line_by_line(file_path)
    
    print(f"解析完成: 发现 {len(result['turns'])} 轮交互")
    for i, turn in enumerate(result['turns'][:3], 1):
        print(f"{i}. {turn['action']['content']}")
