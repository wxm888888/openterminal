# Terminal 解析 Pipeline 使用指南

## LLM 处理数据 Pipeline

我们使用 **双模型并行 + 评判模型** 的方式来解析终端交互数据，确保最高质量的输出：

```
原始终端文本 (data/test/*.txt)
           ↓
    ┌──────┴──────┐
    ↓             ↓
 Model A       Model B
    ↓             ↓
 结果 A         结果 B
    └──────┬──────┘
           ↓
      Judge Model
           ↓
    选择最佳结果
           ↓
    ┌──────┴──────┐
    ↓             ↓
完整结果        简化结果
(data/judge/)  (data/results/)
```

## Pipeline 详细流程

### 1. 并行解析阶段
- 同时使用两个大语言模型解析同一个终端文本文件（先通过LLM识别提示符并分割轮次，再调用LLM分割输入与输出，最后使用LLM检查分割是否正确 llm_enhanced_split_async.py实现）
- 提取交互轮次（turns）、命令（action）、输出（observation）
- 识别多行命令、命令参数、输出内容等

### 2. 评判阶段
使用第三个模型作为评判者，对比两个模型的解析结果。（dual_model_parse_async.py实现）

**评判标准：**
- ✅ **轮次分割准确性**：prompt 识别是否正确，轮次边界是否清晰
- ✅ **命令提取准确性**：
  - 多行命令（以 `\` 结尾）是否正确合并
  - 命令参数是否完整
  - 是否将输出误识别为命令
- ✅ **输出提取准确性**：
  - 输出内容是否完整
  - 是否将命令参数误识别为输出
  - 是否意外包含下一个 prompt
- ✅ **结构完整性**：
  - 每个 turn 的 action-observation 映射是否正确
  - 是否有遗漏的轮次
  - 是否有幻觉（虚构）的轮次

### 3. 结果保存阶段
- **完整结果**（包含评判信息、两个模型的输出）→ `data/judge/`
- **简化结果**（只保留胜出模型的输出）→ `data/results/`

## 运行命令

```bash
# 进入项目目录
cd OpenTerminal

# 运行双模型异步解析
python scripts/dual_model_parse_async.py
```

## 结果存储位置

解析完成后，结果会保存在两个位置：

### 1. `data/judge/` - 完整评判结果

**特点：**
- 包含两个模型的完整解析结果
- 包含评判模型的决策依据、置信度、问题分析
- 文件命名：`{filename}_dual_async.json`

**适用场景：**
- 质量分析和对比
- 模型性能评估
- 调试和优化

**格式示例：**
```json
{
  "success": true,
  "winner": "model_a",
  "result": { 
    "initial_output": "...",
    "turns": [...]
  },
  "judgment": {
    "reason": "Model A 在命令分割和输出提取方面更准确...",
    "confidence": 0.85,
    "model_a_issues": [],
    "model_b_issues": ["在第3轮将输出误识别为命令"]
  },
  "input_file": "data/test/10000.txt",
  "model_a": "gpt-5.2-2025-12-11",
  "model_b": "claude-opus-4-5-20251101",
  "judge_model": "claude-sonnet-4-5-20250929-thinking",
  "model_a_result": { /* Model A 完整结果 */ },
  "model_b_result": { /* Model B 完整结果 */ }
}
```

### 2. `data/results/` - 简化最终结果

**特点：**
- 只包含胜出模型的输出
- 已将 prompt 合并到输出流中
- 文件命名：`{filename}.json`（不含 `_dual` 后缀）

**适用场景：**
- 下游任务使用
- 模型训练数据
- 数据分析

**格式示例：**
```json
{
  "initial_output": "Welcome to Ubuntu 20.04 LTS\nuser@machine:~$ ",
  "turns": [
    {
      "turn_id": 1,
      "action": {
        "content": "ls -la"
      },
      "observation": {
        "content": "total 48\ndrwxr-xr-x 6 user user 4096 Jan 30 10:00 .\ndrwxr-xr-x 3 root root 4096 Jan 29 15:30 ..\nuser@machine:~$ "
      }
    },
    {
      "turn_id": 2,
      "action": {
        "content": "cd projects && ls"
      },
      "observation": {
        "content": "project1/  project2/  README.md\nuser@machine:~/projects$ "
      }
    }
  ]
}
```

## 配置说明

在 `scripts/dual_model_parse_async.py` 中可以配置使用的模型：

```python
# 主要配置参数
MODEL_A = 'gpt-5.2-2025-12-11'           # 第一个解析模型
MODEL_B = 'claude-opus-4-5-20251101'      # 第二个解析模型
JUDGE_MODEL = 'claude-sonnet-4-5-20250929-thinking'  # 评判模型

# 输入输出路径
input_file = 'data/test/10000.txt'        # 待解析的终端文本
output_file = 'data/judge/{filename}_dual_async.json'  # 输出路径
```

## 输出字段说明

### 简化结果字段

| 字段 | 说明 |
|------|------|
| `initial_output` | 第一个命令执行前的初始终端输出（通常包含欢迎信息和第一个 prompt）|
| `turns` | 交互轮次数组 |
| `turns[].turn_id` | 轮次编号（从 1 开始）|
| `turns[].action.content` | 用户执行的命令 |
| `turns[].observation.content` | 命令的输出 + 下一个 prompt |

### 完整结果额外字段

| 字段 | 说明 |
|------|------|
| `success` | 是否成功解析（true/false）|
| `winner` | 胜出的模型（"model_a" / "model_b" / "tie" / "both_incorrect"）|
| `judgment.reason` | 评判理由 |
| `judgment.confidence` | 置信度（0.0-1.0）|
| `judgment.model_a_issues` | Model A 的问题列表 |
| `judgment.model_b_issues` | Model B 的问题列表 |
| `model_a_result` | Model A 的完整解析结果 |
| `model_b_result` | Model B 的完整解析结果 |

## 批量处理

如果需要批量处理多个文件，可以使用 `batch_dual_parse_async.py`：

```bash
python scripts/batch_dual_parse_async.py
```

这个脚本会自动处理 `data/test/` 目录下的所有 `.txt` 文件。