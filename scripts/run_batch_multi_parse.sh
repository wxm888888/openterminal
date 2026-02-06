#!/bin/bash

cd "$(dirname "$0")/.."

# API Configuration
export OPENAI_API_KEY=""
export OPENAI_BASE_URL=""

# Configuration
INPUT_DIR="data/test"
OUTPUT_DIR="data/judge"
MODELS="kimi-k2-instruct gemini-2.5-flash-nothinking gpt-4.1-mini-2025-04-14"
JUDGE_MODEL="gemini-2.5-flash-nothinking"
MAX_CONCURRENT=5
MAX_TOKENS=60000

python scripts/batch_multi_parse_async.py \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --models $MODELS \
    --judge-model "$JUDGE_MODEL" \
    --max-concurrent $MAX_CONCURRENT \
    --max-tokens $MAX_TOKENS
