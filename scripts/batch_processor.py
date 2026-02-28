import os
import glob
import time
import json
import asyncio
import tiktoken
from tqdm import tqdm
from openai import AsyncOpenAI
from llm_parser import TerminalParser, llm_call_with_retry, init_llm_semaphore
from multi_llm_parser import multi_model_parse_and_save_async

client = AsyncOpenAI(
    api_key=os.getenv('OPENAI_API_KEY'),
    base_url=os.getenv('OPENAI_BASE_URL')
)

# Reuse TerminalParser's JSON extraction
_json_extractor = TerminalParser()


async def check_file_quality(file_path, model_name='qwen3-8b', max_retries=10):
    """Use LLM to check if a txt file contains qualified terminal interaction records."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    system_prompt = """You are a professional Data Compliance and Quality Assurance Expert, specializing in identifying Terminal Interaction patterns within technical documentation.

Task Goal:
Please evaluate the following .txt document to determine if it contains high-quality terminal interaction records suitable for training High-Performance Terminal Agent.

Screening Criteria (Must Include):

1.Interaction Features: The document must contain clear command-line identifiers, such as $, #, C:\\>, or user@machine:~$.

2.Structural Integrity: It must include complete "Input (Command)" and "Output (Stdout/Stderr)" pairs.

3.Technical Relevance: The content should involve Linux/Unix administration, network configuration, software development environment setup, Git operations, or file system management, etc.

4.Logical Coherence: Ideally, the document should contain a multi-step instruction flow aimed at solving a specific problem, rather than scattered, out-of-context commands.

Exclusion Criteria (Discard if present):

1.Pure Code Snippets: (e.g., only Python or C++ source code without terminal execution records).

2.Pure Natural Language Descriptions: (e.g., discussing technology without showing actual command lines).

3.Irrelevant System Logs: (e.g., pure Nginx access logs without human intervention processes).

4.Full-screen editing tools (e.g., vim, vi, nano): Only the startup and exit commands are visible, while the internal editing process remains hidden.

Output Format:
Return ONLY a JSON object (wrapped in ```json code block) with the following format:
```json
{
  "qualified": true or false,
  "reason": "Brief explanation. If qualified, list the primary tools covered (e.g., find, docker, grep, etc.).",
  "task_description": "If qualified, provide a concise task description summarizing what this terminal session is doing (e.g., 'Setting up a Docker-based development environment with Nginx reverse proxy'). If unqualified, leave as empty string."
}
```

IMPORTANT: Return ONLY the JSON wrapped in ```json code block, without any additional explanation or text."""

    try:
        response = await llm_call_with_retry(
            max_retries=max_retries,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ],
            model=model_name,
            temperature=0.2,
            max_tokens=1024
        )
        result = response.choices[0].message.content
        data = _json_extractor._extract_json_from_response(result)
        qualified = data.get('qualified', False)
        reason = data.get('reason', '')
        task_description = data.get('task_description', '')
        return qualified, reason, task_description
    except Exception as e:
        # On error, default to qualified to avoid false filtering
        return True, f"Filter error: {str(e)}", ""

def count_file_tokens(file_path, encoding='cl100k_base'):
    """Count tokens in a file using tiktoken"""
    enc = tiktoken.get_encoding(encoding)
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return len(enc.encode(content))

async def process_single_file_async(input_file, output_dir, models, judge_model, file_index, total_files, max_input_tokens=None, filter_model=None, max_retries=10):
    """Async version: Process a single file with multiple models"""
    filename = os.path.splitext(os.path.basename(input_file))[0]
    output_file = os.path.join(output_dir, f'{filename}_multi.json')

    # Check token count before processing
    if max_input_tokens is not None:
        token_count = count_file_tokens(input_file)
        if token_count > max_input_tokens:
            too_large_dir = 'data/too_large'
            os.makedirs(too_large_dir, exist_ok=True)
            too_large_file = os.path.join(too_large_dir, f'{filename}.json')
            with open(too_large_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'input_file': input_file,
                    'token_count': token_count,
                    'max_input_tokens': max_input_tokens
                }, f, ensure_ascii=False, indent=2)

            return ('too_large', filename, token_count)

    # LLM quality filter
    if filter_model is not None:
        qualified, reason, task_description = await check_file_quality(input_file, model_name=filter_model, max_retries=max_retries)
        if not qualified:
            filtered_dir = 'data/preprocess/filtered'
            os.makedirs(filtered_dir, exist_ok=True)
            filtered_file = os.path.join(filtered_dir, f'{filename}.json')
            with open(filtered_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'input_file': input_file,
                    'filter_model': filter_model,
                    'qualified': False,
                    'reason': reason
                }, f, ensure_ascii=False, indent=2)
            return ('filtered', filename, reason)
        else:
            # Save task description for qualified files
            task_desc_dir = 'data/preprocess/qualified'
            os.makedirs(task_desc_dir, exist_ok=True)
            task_desc_file = os.path.join(task_desc_dir, f'{filename}.json')
            with open(task_desc_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'input_file': input_file,
                    'filter_model': filter_model,
                    'qualified': True,
                    'reason': reason,
                    'task_description': task_description
                }, f, ensure_ascii=False, indent=2)

    try:
        result = await multi_model_parse_and_save_async(
            input_file=input_file,
            output_file=output_file,
            models=models,
            judge_model=judge_model,
            task_description=task_description if filter_model is not None else '',
            max_retries=max_retries
        )

        if result.get('success', False):
            return ('success', filename, None)
        else:
            reason = result.get('judgment', {}).get('reason', 'Unknown')
            return ('skipped', filename, reason)

    except Exception as e:
        error_msg = str(e)

        failed_dir = 'data/error'
        os.makedirs(failed_dir, exist_ok=True)
        failed_file = os.path.join(failed_dir, f'{filename}.json')
        with open(failed_file, 'w', encoding='utf-8') as f:
            json.dump({
                'input_file': input_file,
                'error': error_msg
            }, f, ensure_ascii=False, indent=2)

        return ('failed', filename, error_msg)


async def batch_process_txt_files_async(
    input_dir='data/raw/txt',
    output_dir='data/judge',
    models=None,
    judge_model=None,
    max_concurrent=5,
    max_input_tokens=100000,
    filter_model=None,
    max_retries=10
):
    """
    Async batch processing: Process all txt files with multiple models and controlled concurrency

    Args:
        input_dir: Input txt file directory
        output_dir: Output JSON file directory
        models: List of model names to use for parsing
        judge_model: Judge model name
        max_concurrent: Maximum concurrent file processing (default 5)
        max_input_tokens: Maximum input token count per file (default 100000), None to disable
        filter_model: Model name for LLM quality filter (default None to disable)
    """
    if models is None:
        models = ['gpt-3.5-turbo', 'gemini-3-flash-preview-nothinking', 'claude-3-5-haiku-20241022']

    if len(models) < 2:
        print("⚠️ At least 2 models are required for comparison")
        return

    os.makedirs(output_dir, exist_ok=True)

    txt_pattern = os.path.join(input_dir, '*.txt')
    txt_files = sorted(glob.glob(txt_pattern))

    if not txt_files:
        print(f"⚠️ No .txt files found in {input_dir}")
        return

    print(f"{'='*70}")
    print(f"Async Batch Multi Model Parsing")
    print(f"{'='*70}")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Total files: {len(txt_files)}")
    print(f"Models ({len(models)}):")
    for i, model in enumerate(models):
        print(f"  Model {chr(ord('A') + i)}: {model}")
    print(f"Judge Model: {judge_model}")
    print(f"Max concurrent: {max_concurrent}")
    print(f"Max input tokens: {max_input_tokens if max_input_tokens else 'unlimited'}")
    print(f"Filter model: {filter_model if filter_model else 'disabled'}")
    print(f"{'='*70}\n")

    start_time = time.time()

    success_count = 0
    failed_count = 0
    skipped_count = 0
    too_large_count = 0
    filtered_count = 0
    failed_files = []
    skipped_files = []
    too_large_files = []
    filtered_files = []

    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    # Print legend for progress bar symbols
    print("Progress symbols: ✓ Success  ✗ Failed  ⊘ Skipped(judge rejected)  ⊕ Too large(token limit)  ⊖ Filtered\n")

    # Create progress bar
    pbar = tqdm(total=len(txt_files), desc="Processing", unit="file",
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}')

    def update_progress(status, filename):
        nonlocal success_count, failed_count, skipped_count, too_large_count, filtered_count
        if status == 'success':
            success_count += 1
        elif status == 'skipped':
            skipped_count += 1
        elif status == 'failed':
            failed_count += 1
        elif status == 'too_large':
            too_large_count += 1
        elif status == 'filtered':
            filtered_count += 1

        pbar.set_postfix_str(f"✓ {success_count}  ✗ {failed_count}  ⊘ {skipped_count}  ⊕ {too_large_count}  ⊖ {filtered_count}")
        pbar.update(1)

    async def process_with_semaphore(input_file, index):
        async with semaphore:
            result = await process_single_file_async(
                input_file,
                output_dir,
                models,
                judge_model,
                index,
                len(txt_files),
                max_input_tokens,
                filter_model,
                max_retries
            )
            update_progress(result[0], result[1])
            return result

    # Process all files concurrently with limited concurrency
    tasks = [
        process_with_semaphore(input_file, i)
        for i, input_file in enumerate(txt_files, 1)
    ]

    results = await asyncio.gather(*tasks)
    pbar.close()

    # Collect statistics (for detailed info)
    for status, filename, extra_info in results:
        if status == 'skipped':
            skipped_files.append((filename, extra_info))
        elif status == 'failed':
            failed_files.append((filename, extra_info))
        elif status == 'too_large':
            too_large_files.append((filename, extra_info))
        elif status == 'filtered':
            filtered_files.append((filename, extra_info))

    elapsed_time = time.time() - start_time

    # Print summary
    print(f"\n{'='*70}")
    print(f"Batch Processing Summary")
    print(f"{'='*70}")
    print(f"Total files: {len(txt_files)}")
    print(f"Successful: {success_count}")
    print(f"Too large: {too_large_count}")
    print(f"Filtered: {filtered_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Failed: {failed_count}")
    print(f"Total time: {elapsed_time:.2f}s ({elapsed_time/len(txt_files):.2f}s per file)")

    if too_large_files:
        print(f"\nToo large files:")
        for filename, token_count in too_large_files[:5]:
            print(f"  - {filename}.txt: {token_count} tokens")
        if len(too_large_files) > 5:
            print(f"  ... and {len(too_large_files) - 5} more")

    if filtered_files:
        print(f"\nFiltered files (unqualified):")
        for filename, reason in filtered_files[:5]:
            print(f"  - {filename}.txt: {reason[:60]}...")
        if len(filtered_files) > 5:
            print(f"  ... and {len(filtered_files) - 5} more")

    if skipped_files:
        print(f"\nSkipped files:")
        for filename, reason in skipped_files[:5]:
            print(f"  - {filename}.txt: {reason[:60]}...")
        if len(skipped_files) > 5:
            print(f"  ... and {len(skipped_files) - 5} more")

    if failed_files:
        print(f"\nFailed files:")
        for filename, error in failed_files[:5]:
            print(f"  - {filename}.txt: {error[:60]}...")
        if len(failed_files) > 5:
            print(f"  ... and {len(failed_files) - 5} more")

    print(f"{'='*70}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Batch process txt files with multiple models')
    parser.add_argument('--input-dir', type=str, default='data/raw/txt', help='Input directory')
    parser.add_argument('--output-dir', type=str, default='data/judge', help='Output directory')
    parser.add_argument('--models', type=str, nargs='+', required=True, help='List of models to use')
    parser.add_argument('--judge-model', type=str, default='claude-3-5-haiku-20241022', help='Judge model')
    parser.add_argument('--max-concurrent', type=int, default=5, help='Max concurrent tasks')
    parser.add_argument('--max-input-tokens', type=int, default=100000, help='Max input tokens per file')
    parser.add_argument('--filter-model', type=str, default=None, help='Model name for LLM quality filter (disabled if not set)')
    parser.add_argument('--max-retries', type=int, default=10, help='Max LLM retry attempts on rate limit or server error (default: 10)')
    parser.add_argument('--max-llm-concurrency', type=int, default=20, help='Max concurrent LLM API requests globally (default: 20)')

    args = parser.parse_args()

    async def main():
        # Limit concurrent LLM requests globally to avoid rate-limit storms
        init_llm_semaphore(args.max_llm_concurrency)
        await batch_process_txt_files_async(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            models=args.models,
            judge_model=args.judge_model,
            max_concurrent=args.max_concurrent,
            max_input_tokens=args.max_input_tokens,
            filter_model=args.filter_model,
            max_retries=args.max_retries
        )

    asyncio.run(main())
