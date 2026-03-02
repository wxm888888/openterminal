#!/bin/bash

# API Configuration
export OPENAI_API_KEY=""
export OPENAI_BASE_URL=""
OUTPUT_DIR="output"
INPUT_DIR="input"

MODELS="gemini-2.5-flash-nothinking kimi-k2-instruct gemini-2.5-flash-nothinking kimi-k2-instruct gemini-2.5-flash-nothinking kimi-k2-instruct gemini-2.5-flash-nothinking kimi-k2-instruct"
JUDGE_MODEL="gemini-2.5-flash-nothinking"
FILTER_MODEL="gemini-2.5-flash-nothinking"

MAX_INPUT_TOKENS=60000
MAX_RETRIES=10
MAX_LLM_CONCURRENCY=50
LLM_TIMEOUT=60

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
