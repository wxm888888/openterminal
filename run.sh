#!/bin/bash

# API Configuration
export OPENAI_API_KEY=""
export OPENAI_BASE_URL=""

# Configuration
INPUT_DIR="data/test"
OUTPUT_DIR="data/judge"

MODELS="kimi-k2-instruct gemini-2.5-flash-nothinking qwen3-8b"
JUDGE_MODEL="gemini-2.5-flash-nothinking"
FILTER_MODEL="gemini-2.5-flash-nothinking"

MAX_CONCURRENT=5
MAX_INPUT_TOKENS=60000
MAX_RETRIES=10
MAX_LLM_CONCURRENCY=20

python scripts/batch_processor.py \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --models $MODELS \
    --judge-model "$JUDGE_MODEL" \
    --filter-model "$FILTER_MODEL" \
    --max-concurrent $MAX_CONCURRENT \
    --max-input-tokens $MAX_INPUT_TOKENS \
    --max-retries $MAX_RETRIES \
    --max-llm-concurrency $MAX_LLM_CONCURRENCY
