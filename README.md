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
│   ├── raw/cast/          # 原始 .cast 文件
│   └── processed/interactions/  # 提取后的 JSON
├── src/
│   ├── crawler/           # 数据爬取
│   ├── parser/            # Cast 解析 (v1/v2/v3)
│   ├── converter/         # 格式转换 (cast→gif, csv→json)
│   ├── validator/         # 数据验证
│   └── utils/             # 工具函数
└── scripts/
    └── process_data.py    # 入口脚本
```

### Quick Start

```bash
# 安装项目
pip install -e .

# 处理所有 cast 文件（支持断点续传）
python scripts/process_data.py

# 指定格式（turn_based / event_stream / both）
python scripts/process_data.py --format both

# 限制处理数量（用于测试）
python scripts/process_data.py --limit 100

# 只运行验证
python scripts/process_data.py --verify-only
```

**处理流程**: `data/raw/cast/*.cast` → 版本检测 → 解析提取 → `data/processed/interactions/*.json` → 验证



### Data Source

- https://www.kaggle.com/datasets/jessysisca/asciinema-public-terminal-recordings
- https://huggingface.co/datasets/James4Ever0/asciinema_terminal_recordings
  - Shell: https://huggingface.co/datasets/bigcode/the-stack-v2/viewer/Shell
