# OpenTerminal

OpenTerminal 是一个**大规模真实终端交互数据集构建工具包**，旨在从 [Asciinema](https://asciinema.org/explore/public) 平台采集终端录屏数据，并通过多模型协作 Pipeline 自动将原始终端文本解析、分割为高质量的多轮交互训练数据，用于推进 **Terminal AI Agent** 的能力边界。

## 核心特性

- **真实数据**：所有数据来源于 Asciinema 平台的真实开发任务录屏，与 Terminal Bench 任务高度一致
- **多模型协作**：多个 LLM 独立解析同一文件，由裁判模型择优选取，确保分割质量
- **4 步解析 Pipeline**：提示符学习 → 提示符验证 → 轮次划分 → 验证修正，层层保障准确性

## 流程介绍

整个 Pipeline 可分为 **预处理 → 多模型解析 → Judge 评判** 三大阶段：

```
input/*.txt → 预处理(质量过滤+Token计数) → 多模型4步解析 → Judge评判 → output/*.json
                      ↓                                             ↓
               跳过不合格/超大文件                          fail: 不适合训练的数据
```


### 一、预处理

| 步骤 | 说明 |
|------|------|
| Token 计数 | 使用 tiktoken 统计文件 token 数，超过 `max-input-tokens` 阈值的文件直接跳过 |
| LLM 质量过滤 | 将原始文本交给 `filter-model` 判断是否包含合法终端交互（排除 vim 编辑、SSH 嵌套、空文件等），同时生成任务描述 |

### 二、多模型 4 步解析

对每个通过预处理的文件，使用**多个模型独立执行**以下 4 步解析：

#### Step 1：提示符学习

将原始 txt 发给 LLM，识别文本中所有终端提示符（如 `user@host:~$`、`>>> ` 等），并为每种提示符生成正则表达式。

#### Step 2：提示符验证

用 Step 1 生成的正则逐行匹配候选提示符行，然后将每个候选行及其上下文（前后各一行）交给 LLM 二次验证，过滤掉"碰巧包含提示符文本但并非真正提示符"的行。

#### Step 3：轮次划分

根据 Step 2 确认的提示符行号，将终端内容分割为多轮交互。对每一轮分别调用 LLM，划分出 `prompt`（提示符）、`action`（用户输入）和 `observation`（终端输出）。

#### Step 4：验证修正

将原始文件和分割结果一起交给 LLM 进行验证：
- 检测是否存在内容错误或幻觉
- 检查单轮内是否包含多轮数据
- 验证 `initial_output` 是否正确
- 自动修正发现的问题

### 三、Judge 评判

将**多个模型的解析结果**和原始文本一起交给裁判模型（`judge-model`），由其：
1. **选择最佳结果**：对比各模型的分割质量，选出最准确的那个
2. **训练适用性判断**：判断该条数据是否适合用于 Terminal Agent 训练
3. 不适合训练的数据会标记 `rejection_type` 和 `rejection_reason`

### 四、基于规则的评估（可选）

在批量处理完成后，可运行 `evaluation/evaluator.py` 进行基于多数投票的二次评估：
1. **轮数筛选**：与 winner 模型轮数一致的模型数需过半
2. **相似度筛选**：各模型与 winner 每轮输入输出的平均相似度需过半超过阈值
3. **拼接还原检查**：拼接所有轮次内容与原始 txt 计算相似度，检验完整性

## 项目结构

```
openterminal/
├── run.sh                         # 批量处理运行入口
├── pyproject.toml                 # 项目配置，定义 openterminal CLI 入口
├── requirements.txt               # Python 依赖
│
├── src/
│   ├── openterminal/              # 核心包
│   │   ├── cli.py                 # CLI 入口 → batch_processor.main()
│   │   └── pipeline/              # 处理流水线
│   │       ├── batch_processor.py # 批量调度：并发处理、进度显示、结果汇总
│   │       ├── pipeline.py        # 单文件 Pipeline：预处理 → 多模型解析 → Judge
│   │       ├── terminal_parser.py # 4 步解析器（TerminalParser 类）
│   │       ├── judge.py           # 多模型裁判：选最优 + 判断训练适用性
│   │       ├── preprocess.py      # 预处理：Token 计数 + LLM 质量过滤
│   │       ├── llm_client.py      # 全局 LLM 连接池（单例 + Semaphore + 重试）
│   │       ├── json_utils.py      # 鲁棒 JSON 提取（13 种修复策略）
│   │       └── prompts.py         # 所有 LLM prompt 模板
│   │
│   └── crawler/                   # 数据爬取模块
│       ├── asciinema_crawler.py   # Asciinema 爬虫（支持重试、并发）
│       ├── gif_generator.py       # cast → gif 转换
│       └── json_exporter.py       # csv → json 导出
│
├── evaluation/                    # 评估模块
│   └── evaluator.py               # 基于规则的后评估（多数投票 + 相似度）
│
├── input/                         # 输入目录：原始 txt 文件
└── output/                        # 输出目录：处理结果
```

## 使用方法

### 1. 克隆仓库

```bash
git clone https://github.com/wxm888888/openterminal.git
cd openterminal
```

### 2. 创建环境并安装依赖

```bash
conda create -n openterminal python=3.10
conda activate openterminal
pip install -r requirements.txt
pip install -e .
```

### 3. 配置 `run.sh`

编辑 `run.sh`，填入你的 API 配置和参数：

```bash
#!/bin/bash

# API 配置
export OPENAI_API_KEY="<your API_KEY>"
export OPENAI_BASE_URL="<your BASE_URL>"

# 目录配置
OUTPUT_DIR="output"
INPUT_DIR="input"

# 模型配置（至少 2 个模型）
MODELS="model-a model-b model-c model-d"
JUDGE_MODEL="judge-model-name"
FILTER_MODEL="filter-model-name"

# 运行参数
MAX_INPUT_TOKENS=60000     # 原始 txt 文件最大 token 数
MAX_RETRIES=10             # LLM 调用最大重试次数
MAX_LLM_CONCURRENCY=50    # 全局最大并发 LLM 请求数
LLM_TIMEOUT=60             # 单次 LLM 调用超时（秒）

openterminal \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --models $MODELS \
    --judge-model "$JUDGE_MODEL" \
    --filter-model "$FILTER_MODEL" \
    --max-input-tokens $MAX_INPUT_TOKENS \
    --max-retries $MAX_RETRIES \
    --max-llm-concurrency $MAX_LLM_CONCURRENCY \
    --timeout $LLM_TIMEOUT
```

### 4. 准备输入数据

将原始终端录屏文本文件（`.txt`）放入 `input/` 目录。

### 5. 运行批量处理

```bash
bash run.sh
```

运行时会实时显示进度：
```
--- Active Tasks ---
  [PARSE] 788050  00:01:23
  [JUDGE] 787434  00:00:05
Progress: 45.2% [######################----------------------------] 18/39  00:01:05
          SUCCESS:10   FAIL:0   BIG:1   SKIP:7    LLM:12/50
```

### 6. 基于规则的评估（可选）

```bash
python evaluation/evaluator.py --batch
```

### CLI 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--input-dir` | str | `data/raw/txt` | 输入 txt 文件目录 |
| `--output-dir` | str | `output` | 输出结果目录 |
| `--models` | str[] | *必填* | 解析模型列表（至少 2 个） |
| `--judge-model` | str | *必填* | 裁判模型 |
| `--filter-model` | str | None | 质量过滤模型，不指定则跳过 LLM 过滤 |
| `--max-input-tokens` | int | 100000 | 文件最大 token 数阈值 |
| `--max-retries` | int | 10 | LLM 调用最大重试次数 |
| `--max-llm-concurrency` | int | 20 | 全局 LLM 最大并发数 |
| `--timeout` | float | 120.0 | 单次 LLM 调用超时（秒） |

> **MAX_INPUT_TOKENS 的选择**：MODELS 的输入约为 2 倍 txt token 数；JUDGE_MODEL 的输入约为 (模型数+1) 倍 txt token 数。例如 `MAX_INPUT_TOKENS=60000` 时，JUDGE 输入约 60K×5=300K，需确保 judge 模型支持。

## 结果结构

每次运行在 `output/` 下生成一个时间戳目录（如 `output/20260302_102642/`），每个输入文件对应一个 JSON 结果文件。

### 成功处理的文件

```json
{
  "input_file": "input/788050.txt",
  "status": "success",
  "preprocess": {
    "token_count": 1837,
    "max_input_tokens": 60000,
    "filter_model": "gemini-2.5-flash-nothinking",
    "qualified": true,
    "reason": "包含清晰的命令行标识和完整的输入输出对...",
    "task_description": "使用 PRSpec 工具分析 go-ethereum 中 EIP-1559 的实现..."
  },
  "models": {
    "a: model-name": {
      "success": true,
      "step_details": { "step1": {"attempts": 1}, "step2": {...}, ... },
      "parsed_result": {
        "initial_output": "",
        "turns": [
          {
            "turn_id": 1,
            "prompt": "user@host:~$",
            "action":      { "content": "ls -la" },
            "observation": { "content": "total 48\ndrwxr-xr-x ..." }
          }
        ]
      }
    },
    "b: model-name": { ... }
  },
  "judge": {
    "winner": "a: model-name",
    "reason": "Model A 的提示符识别和轮次划分最准确...",
    "confidence": 0.9,
    "suitable_for_training": true,
    "model_issues": { ... }
  },
  "final_result": {
    "task_description": "任务描述...",
    "initial_output": "...",
    "turns": [ ... ]
  },
  "errors": []
}
```

### 被过滤的文件

```json
{
  "input_file": "input/100040.txt",
  "status": "filtered",
  "preprocess": {
    "token_count": 148,
    "qualified": false,
    "reason": "文件包含不完整的交互对，缺乏连贯的多步任务流..."
  },
  "models": {},
  "judge": null,
  "final_result": null,
  "errors": []
}
```

### 处理状态说明

| status | 说明 |
|--------|------|
| `success` | 处理成功，`final_result` 包含最终分割结果 |
| `filtered` | 被质量过滤器排除（不适合训练） |
| `too_large` | 文件 token 数超过阈值 |
| `failed` | 处理过程中出错 |

### 最终输出数据格式

`final_result` 中的核心数据结构：

| 字段 | 说明 |
|------|------|
| `task_description` | LLM 生成的任务描述 |
| `initial_output` | 第一个提示符之前的终端输出 |
| `turns` | 多轮交互列表 |
| `turns[].turn_id` | 轮次编号 |
| `turns[].prompt` | 该轮的终端提示符 |
| `turns[].action.content` | 用户输入的命令 |
| `turns[].observation.content` | 终端返回的输出 |
