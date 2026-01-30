# 终端文件精细化解析器使用说明

## 📁 文件结构

```
OpenTerminal/
├── scripts/
│   ├── terminal_parser.py    # 独立解析器（不需要OpenAI）
│   ├── llm.py                # 完整版（包含LLM分析）
│   └── test_parser.py        # 测试脚本（不调用LLM）
├── data/
│   ├── raw/txt/              # 原始终端文件
│   └── analyzed/             # 输出的分析结果
└── README_PARSER.md          # 本文档
```

## 🎯 核心改进

### 原代码的问题
- 一次性读取整个文件发送给大模型
- 分割不够精确，依赖大模型自己解析
- 对于大文件效率低下

### 新代码的优势
1. **逐行精确解析**：使用正则表达式识别提示符，准确分割每一轮交互
2. **支持多种提示符格式**：
   - `user@host:path$` 格式
   - `path(env) (git) %` zsh格式
   - 带时间戳的特殊格式（`↪`, `↩`, `★`）
3. **结构化输出**：每一轮包含完整的元数据（原始行、时间戳、错误标记等）
4. **分离设计**：解析器可独立运行，不依赖大模型

## 🧪 测试步骤

### 第1步：测试解析器（不调用LLM）

```bash
cd /home/test/test1714/wxh/OpenTerminal

# 测试单个文件
python3 scripts/test_parser.py data/raw/txt/7016.txt

# 或直接使用解析器
python3 scripts/terminal_parser.py data/raw/txt/7016.txt
```

这会输出：
- 识别到的总轮次数
- 每一轮的详细信息（提示符、命令、输出）
- 保存解析结果到 `data/analyzed/` 目录

### 第2步：检查解析结果

查看生成的JSON文件：
```bash
cat data/analyzed/7016_parsed.json | python3 -m json.tool | head -100
```

### 第3步：使用完整的LLM分析（需要安装openai）

```bash
# 首先安装依赖（如果pip3可用）
pip3 install openai

# 然后运行完整分析
python3 scripts/llm.py
```

## 📊 解析结果格式

### 解析器输出（terminal_parser.py）

```json
{
  "initial_output": "第一条命令前的内容",
  "turns": [
    {
      "turn_id": 1,
      "raw_lines": ["完整的原始行数组"],
      "action": {
        "content": "提取的命令",
        "raw_prompt_line": "原始提示符行"
      },
      "observation": {
        "content": "命令输出内容",
        "raw_output_lines": ["输出行数组"]
      },
      "metadata": {
        "has_error": false,
        "timestamps": ["时间戳数组"]
      }
    }
  ]
}
```

### LLM分析输出（llm.py）

```json
{
  "file_path": "文件路径",
  "total_turns": 19,
  "analyzed_turns": [
    {
      "turn_id": 1,
      "original_data": {...},
      "llm_analysis": "大模型的分析结果（JSON格式）"
    }
  ]
}
```

## 🔧 自定义使用

### 单独使用解析器

```python
from terminal_parser import TerminalParser

parser = TerminalParser()
result = parser.parse_file_line_by_line('data/raw/txt/your_file.txt')

print(f"发现 {len(result['turns'])} 轮交互")
for turn in result['turns']:
    print(f"命令: {turn['action']['content']}")
    print(f"输出: {turn['observation']['content'][:100]}")
```

### 使用LLM分析单个轮次

```python
from llm import TerminalParser

parser = TerminalParser()
parsed = parser.parse_file_line_by_line('data/raw/txt/7016.txt')

# 只分析第一轮
first_turn = parsed['turns'][0]
analysis = parser.analyze_turn_with_llm(first_turn)
print(analysis)
```

### 批量处理多个文件

```python
import os
from llm import analyze_terminal_file

txt_dir = 'data/raw/txt/'
for filename in os.listdir(txt_dir):
    if filename.endswith('.txt'):
        input_path = os.path.join(txt_dir, filename)
        output_path = f'data/analyzed/{filename.replace(".txt", "_analyzed.json")}'
        
        print(f"处理: {filename}")
        analyze_terminal_file(input_path, output_path)
```

## 🎨 提示符识别模式

代码支持的提示符格式：

1. **标准格式**：`glyph@rem:~/paths★ mkdir package`
2. **ZSH格式**：`code/ascii.io (1.9.2-p318@asciiio) (master*?) %`
3. **简单格式**：`$ command`, `# command`, `% command`
4. **特殊标记**：
   - `↪` 命令开始时间戳
   - `↩` 命令执行完成
   - `★` 命令回显
   - `[Error: N]` 错误标记

## 🐛 验证分割准确性

验证解析是否准确的检查点：

1. **轮次数量**：是否与实际命令数匹配
2. **命令提取**：提示符后的命令是否完整
3. **输出分割**：每轮的输出是否正确归属
4. **边界识别**：相邻两轮是否有遗漏或重叠

运行测试查看详细信息：
```bash
python3 scripts/test_parser.py data/raw/txt/7016.txt 2>&1 | less
```

## 💡 如果遇到问题

### 提示符未识别
在 `terminal_parser.py` 中添加新的正则模式：
```python
self.prompt_patterns = [
    r'^your_custom_pattern',  # 添加你的模式
    ...
]
```

### 输出分割不准确
检查是否有特殊的输出格式需要特殊处理，可以在 `parse_file_line_by_line` 方法中添加自定义逻辑。

## 📝 验证建议

1. 先用 `test_parser.py` 查看解析结果
2. 手动对比原始txt文件，确认分割准确
3. 如果分割准确，再使用 `llm.py` 进行LLM分析
4. 对于超大文件，建议先测试前几轮是否正确

---

**注意**：`llm.py` 中包含你的API密钥，请妥善保管，不要上传到公开仓库！
