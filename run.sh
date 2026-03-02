#!/bin/bash

# API Configuration
export OPENAI_API_KEY=""
export OPENAI_BASE_URL=""
OUTPUT_DIR="output"
INPUT_DIR="input"

#如果需要上次继续跑，填写output/上次时间戳；否则设置为空
RESUME_DIR=""

MODELS="gemini-2.5-flash-nothinking kimi-k2-instruct gemini-2.5-flash-nothinking kimi-k2-instruct gemini-2.5-flash-nothinking kimi-k2-instruct"
JUDGE_MODEL="gemini-2.5-flash-nothinking"
FILTER_MODEL="gemini-2.5-flash-nothinking"

MAX_INPUT_TOKENS=60000
MAX_RETRIES=10
MAX_LLM_CONCURRENCY=30
LLM_TIMEOUT=120

RESUME_FLAG=""
if [ -n "$RESUME_DIR" ]; then
    RESUME_FLAG="--resume-dir $RESUME_DIR"
fi

openterminal \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    $RESUME_FLAG \
    --models $MODELS \
    --judge-model "$JUDGE_MODEL" \
    --filter-model "$FILTER_MODEL" \
    --max-input-tokens $MAX_INPUT_TOKENS \
    --max-retries $MAX_RETRIES \
    --max-llm-concurrency $MAX_LLM_CONCURRENCY \
    --timeout $LLM_TIMEOUT
