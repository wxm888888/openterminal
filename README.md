## OpenTerminal

OpenTerminal 是一个大规模、真实世界、多样化的终端 (terminal / shell) 交互数据集，旨在推进 AI Terminal Agent 的能力边界。


### Motivation

https://asciinema.org/explore/public 

- 真实性：
  - 完全来源于实际开发任务
  - 这些 Trajectory 与 Terminal Bench 的任务高度一致，Asciinema本身就是 Terminal Bench 的数采平台
- 大规模：80,254 条终端交互数据，Asciinema 有发布门槛，数据质量有天然保障
  - 每条数据包含 metadata、纯文本（txt）、cast 轨迹、gif 可视化（可支持 VL 模型的 Terminal 理解任务）
- 稀缺性：
  - 包含完整交互的 Agent 数据相对稀少，尤其 Coding 相关场景大多是 Text-Code Pair
- 两方面的监督信号，可以实现 Self-Play 训练


### Todo List

- [ ] 数据爬取
- [ ] 交互轨迹抽取
- [ ] 数据过滤与人工标注
  - 数据质量评估
  - 任务类型（AI、CS、Game 等）、难度、属性标注
  - 人工修正
- [ ] 编写任务描述（Description）与 Step-Level Reasoning -> SFT Trajectory Construction
- [ ] 构建 Release Set 与 Training Set



### Case

- Linux MCP: https://asciinema.org/a/758139 
- AI Agent as Tool: https://asciinema.org/a/758325 
- Terminal Tetris: https://asciinema.org/a/709161 
- Git Branch Tracking: https://asciinema.org/a/759143 
- Docker Run Docker: https://asciinema.org/a/24707 

### Project Structure

```
OpenTerminal/
├── data/
│   ├── raw/                    # 原始数据
│   │   ├── cast/               # .cast 录屏文件
│   │   ├── txt/                # .txt 文本内容
│   │   ├── html/               # .html 页面备份
│   │   └── gif/                # .gif 可视化文件
│   ├── all_data.json           # 元数据索引
│   ├── processed/              # 提取后的数据
│   ├── filtered/               # 过滤后的数据
│   ├── judge/                  # Judge 模型评估结果
│   ├── results_LLM/            # Judge 认为正确的分割结果
│   └── fail_LLM/               # Judge 认为不适合训练的轨迹
├── src/
│   ├── crawler/                # 数据爬取与转换
│   │   ├── asciinema_crawler.py    # 主爬虫 (支持重试、并发控制)
│   │   ├── gif_generator.py        # GIF 生成器 (cast→gif)
│   │   └── json_exporter.py        # JSON 导出器 (csv→json)
│   ├── parser/                 # Cast 解析 (v1/v2/v3)
│   ├── validator/              # 数据验证
│   │   ├── event_stream_verifier.py
│   │   └── extraction_verifier.py
│   ├── filter/                 # 数据过滤流程
│   │   ├── 1_rule_filter.py    # 规则过滤
│   │   ├── 2_llm_filter.py     # LLM 过滤
│   │   └── 3_export.py         # 导出结果
│   └── utils/                  # 工具函数
│       ├── file_utils.py
│       └── http_utils.py
├── scripts/                    # 脚本工具
│   ├── llm_parser.py           # LLM 解析器核心逻辑
│   ├── multi_llm_parser.py     # 多模型异步解析
│   └── batch_processor.py      # 批量多模型解析
├── tests/                      # 测试工具
│   ├── test_crawl_files.py     # 爬虫数据文件验证
│   ├── test_api_connection.py  # API 连接测试
│   └── debug_llm_parser.py     # LLM 解析器调试
├── evaluation/                 # 评估工具
│   └── evaluator.py
├── run.sh                      # 批量处理运行入口
└── requirements.txt
```

### 分割流程

#### 一、单文件处理流程

**1. 提示符提取**

提示符是终端输入前的提示文本，比如（单行多行都有可能）：

```
root@zest1:~# exit    ！！！"root@zest1:~#"是提示符
chb@conventiont|~    
> lxc list
```

首先，将原始txt文件发给LLM，让其识别出文本中所有的提示符有哪些，并生成对应regex（正则表达式，只对提示符第一行的内容生成，只匹配行首）；随后使用regex逐行匹配哪些行可能是提示符所在行，即新一轮交互的开始，记录这些行。

代码实现：`scripts/llm_parser.py`

```python
async def step1_learn_prompts(self, file_path):
    ...
```

**2. 提示符验证**

为防止正则表达式提取到的行并非提示符所在行，而只是恰巧包含提示符信息。在本步骤中，将step1提取到的所有候选行和每个候选行的上一行和下一行打包发给LLM，让它判断这些行是否真是提示符所在行，返回真实提示符所在行的行号。

代码实现：`scripts/llm_parser.py`

```python
async def step2_filter_fake_prompts(self, file_path):
    # 正则匹配
    ...

async def _filter_with_llm(self, candidates):
    # LLM过滤
    ...
```

**3. 划分每一轮的提示符，输入和输出**

通过step2获得的提示符所在行号，可以将终端交互内容分成多轮输入-输出对。在本步骤中，将每一轮的终端内容传给LLM（多次请求），让它返回分割好的提示符，输入和输出。

代码实现：`scripts/llm_parser.py`

```python
async def step3_parse_turns(self, file_path, confirmed_line_nums):
    # 划分轮次
    ...

async def _llm_classify_action_observation(self, turn):
    # LLM划分提示符，输入和输出
    ...
```

**4. 验证/检查**

对于模型分割好的多轮交互结果，将原始txt文件和分割结果传给LLM，让其验证每一轮中是否存在内容错误、幻觉，并解析LLM的输出以修改分割结果。

检查每一轮分割内部是否包含多轮数据，如果包含多轮数据，LLM再次分割。可处理之前提示符没找全的问题，有机会解决无提示符的问题。同时检查当前 `initial_output` 里是否存在未检测出来的轮次，`initial_output` 是否正确。

代码实现：`scripts/llm_parser.py`

```python
async def step4_verify_turns(self, input_file, parsed_result):
    ...
```

#### 二、JUDGE

**1. LLM Judge**

首先，分别使用多个模型处理单个文件；将原始txt文件和多个模型的分割结果传给裁判模型，让其判断哪个模型分割的最准确。在judge过程中不运行模型修改分割结果，只能挑选。

同时在JUDGE时同时过滤掉不适合用来训练Terminal Agent的数据：
- 原始txt文本不适合用来进行训练（包含vim等）
- 所有模型的划分结果都很差

代码实现：`scripts/llm_parser.py`

```python
async def judge_results_async(txt_file, model_results, judge_model='gpt-5.2-2025-12-11', save_raw_response=True, file_id=None):
    # LLM调用
    ...

async def multi_model_parse_and_save_async(
    input_file,
    output_file,
    models,
    judge_model='claude-sonnet-4-5-20250929-thinking',
    save_raw_response=True
):
    # 处理并保存文件
    ...
```

#### 三、基于规则的评估

基于多数投票的评估，输入文件夹是 `data/judge`：

1. 根据LLM Judge的评估结果，如果判断为"不适合用来训练"，则放弃该文件。
2. **轮数筛选**：根据多个模型的分割结果，如果和winner模型轮数相同的模型小于等于半数，则放弃该文件。
3. **每轮相似度筛选**：先计算每个模型和winner模型每轮输入输出相似度的平均值，如果平均相似度大于阈值的模型数量小于等于半数，则放弃该文件。
4. 拼接每一轮的内容，和原始txt文件计算相似度，如果大于阈值，保留文件。

代码实现：`evaluation/evaluator.py`

---

### 代码使用

**1. 克隆仓库**

```bash
git clone https://github.com/wxm888888/openterminal.git 
cd OpenTerminal
```

**2. 创建虚拟环境**

```bash
conda create -n openterminal python=3.10
conda activate openterminal
```

**3. 安装依赖**

```bash
pip install -r requirements.txt
pip install -e .
```

**4. 配置批量处理脚本**

打开 `scripts/run.sh` 文件：

```bash
#!/bin/bash

cd "$(dirname "$0")/.."

# API Configuration
export OPENAI_API_KEY="<your API_KEY>"
export OPENAI_BASE_URL="<your BASE_URL>"

# Configuration
INPUT_DIR="data/test"
OUTPUT_DIR="data/judge"
MODELS="kimi-k2-instruct gemini-2.5-flash-nothinking gpt-4.1-mini-2025-04-14"    # 使用模型列表，数量至少为2
JUDGE_MODEL="gemini-2.5-flash-nothinking"
MAX_CONCURRENT=5    # 任务并发度
MAX_INPUT_TOKENS=60000    # 原始txt文件最大token数

python scripts/batch_processor.py \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --models $MODELS \
    --judge-model "$JUDGE_MODEL" \
    --max-concurrent $MAX_CONCURRENT \
    --max-input-tokens $MAX_INPUT_TOKENS
```

**5. 运行批量处理**

```bash
bash scripts/run.sh
```

**6. 基于规则的代码评估**

```bash
python evaluation/evaluator.py --batch
```

**7. 结果解析**

```
OpenTerminal/
├── data/
│   ├── raw/
│   │   ├── cast/          # 原始 .cast 文件
│   │   └── txt/           # 原始文本文件
│   ├── analysis/          # LLM 交互信息
│   │   ├── json_results/        # LLM返回的json
│   │   └── raw_response/        # LLM的原始返回
│   ├── judge/             # Judge 模型评估结果和所有模型的分割结果
│   ├── results_LLM/       # Judge 认为正确的分割结果
│   ├── fail_LLM/          # Judge 认为不适合训练的轨迹
│   │   ├── original_content_issues/  # 原始文本不适合
│   │   └── parsing_errors/           # 模型解析错误
│   └── too_large/         # 超过token阈值的文件
└── evaluation/            # 基于规则的评估
    └── result/            # 评估结果
```

### 注意

> [!IMPORTANT]
> **MAX_TOKENS 的选择**：MODELS最多的输入略大于2倍的txt的token数；JUDGE_MODEL的输入约（模型数+1）倍的txt的token数。MAX_TOKENS=60000的计算：gpt的输入上限为128K，MODELS最多的输入略大于2倍的txt的token数，60K×2<128K。。
