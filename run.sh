#!/bin/bash

# API Configuration
export OPENAI_API_KEY=""
export OPENAI_BASE_URL=""

# Configuration
INPUT_DIR="data/test"
OUTPUT_DIR="data/judge"
MODELS="kimi-k2-instruct gemini-3-flash-preview claude-3-5-haiku-20241022"
JUDGE_MODEL="gemini-3-flash-preview"
FILTER_MODEL="gemini-3-flash-preview"
MAX_CONCURRENT=5
MAX_INPUT_TOKENS=60000

python scripts/batch_processor.py \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --models $MODELS \
    --judge-model "$JUDGE_MODEL" \
    --filter-model "$FILTER_MODEL" \
    --max-concurrent $MAX_CONCURRENT \
    --max-input-tokens $MAX_INPUT_TOKENS
