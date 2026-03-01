"""
Batch processor: process all txt files concurrently.

Concurrency is controlled *solely* by the global ``LLMClient``
semaphore (no separate file-level semaphore).  All files are launched
as concurrent tasks and the LLM pool naturally throttles throughput.
"""

from __future__ import annotations

import os
import sys
import glob
import json
import time
import asyncio
import argparse
from datetime import datetime

from openterminal.pipeline.llm_client import LLMClient
from openterminal.pipeline.pipeline import process_file, FileResult


# =====================================================================
# Batch runner
# =====================================================================

async def batch_process(
    *,
    input_dir: str,
    output_dir: str,
    models: list[str],
    judge_model: str,
    filter_model: str | None,
    max_input_tokens: int | None,
    max_retries: int,
) -> None:
    """
    Process every ``.txt`` file in *input_dir*, write one unified JSON
    per file into *output_dir/{timestamp}/*.
    """
    llm_client = LLMClient.get()

    # Create timestamped subdirectory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(output_dir, timestamp)
    os.makedirs(output_dir, exist_ok=True)
    txt_files = sorted(glob.glob(os.path.join(input_dir, "*.txt")))

    if not txt_files:
        print(f"⚠️  No .txt files found in {input_dir}")
        return

    # --- Banner ---
    _print_banner(input_dir, output_dir, txt_files, models, judge_model, filter_model, max_input_tokens)

    start_time = time.time()

    # Counters
    counts = {"success": 0, "filtered": 0, "too_large": 0, "failed": 0}
    completed = 0
    total = len(txt_files)
    all_errors: list[dict] = []  # Collect all errors for fail.json

    # Live file stage tracking: file_id -> (stage, stage_start_time)
    file_stages: dict[str, tuple[str, float]] = {}
    STAGE_LABELS = {
        "preprocess": "[PRE]  ",
        "parse":      "[PARSE]",
        "judge":      "[JUDGE]",
    }
    prev_display_lines = 0

    def _fmt_time(seconds: float) -> str:
        h = int(seconds) // 3600
        m = (int(seconds) % 3600) // 60
        s = int(seconds) % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _render_display() -> None:
        nonlocal prev_display_lines

        if prev_display_lines > 0:
            sys.stdout.write(f"\033[{prev_display_lines}A\033[J")

        now = time.time()
        lines = []

        # Active tasks with per-task timers (shown first)
        active_items = [
            (fid, stage, st) for fid, (stage, st) in file_stages.items()
            if stage != "done"
        ]
        if active_items:
            lines.append("--- Active Tasks ---")
            for fid, stage, stage_start in active_items:
                label = STAGE_LABELS.get(stage, "[???]   ")
                task_elapsed = _fmt_time(now - stage_start)
                lines.append(f"  {label} {fid}  {task_elapsed}")

        # Progress bar line (at the bottom)
        elapsed = now - start_time
        pct = (completed / total * 100) if total else 100
        bar_len = 50
        filled = int(bar_len * completed / total) if total else bar_len
        bar = "#" * filled + "-" * (bar_len - filled)
        llm_active = llm_client.active_requests
        llm_max = llm_client.max_concurrency
        lines.append(
            f"Progress: {pct:5.1f}% [{bar}] {completed}/{total}  {_fmt_time(elapsed)}"
        )
        lines.append(
            f"          "
            f"SUCCESS:{counts['success']}   FAIL:{counts['failed']}   "
            f"BIG:{counts['too_large']}   SKIP:{counts['filtered']}    "
            f"LLM:{llm_active}/{llm_max}"
        )

        output = "\n".join(lines) + "\n"
        sys.stdout.write(output)
        sys.stdout.flush()
        prev_display_lines = len(lines)

    def _status_callback(file_id: str, stage: str) -> None:
        if stage == "done":
            file_stages.pop(file_id, None)
        else:
            # Only reset timer if stage actually changes
            if file_id in file_stages:
                cur_stage, _ = file_stages[file_id]
                if cur_stage == stage:
                    return  # same stage, don't reset timer
            file_stages[file_id] = (stage, time.time())
        _render_display()

    def _log_callback(msg: str) -> None:
        nonlocal prev_display_lines
        if prev_display_lines > 0:
            sys.stdout.write(f"\033[{prev_display_lines}A\033[J")
        # Ensure msg is a single line for clean display
        single_line = msg.replace('\n', ' ').replace('\r', '')
        print(single_line)
        sys.stdout.flush()
        prev_display_lines = 0
        _render_display()

    llm_client._log_callback = _log_callback

    def _on_done(fut: asyncio.Task, filename: str) -> None:
        nonlocal completed
        try:
            result: FileResult = fut.result()
            counts[result.status] = counts.get(result.status, 0) + 1
            # Collect errors from the pipeline result
            if result.errors:
                all_errors.extend(result.errors)
        except Exception as exc:
            counts["failed"] += 1
            error_msg = str(exc).replace('\n', ' ').replace('\r', '')[:150]
            _log_callback(f"❌ [ERROR] File: {filename} | Uncaught exception: {error_msg}")
            all_errors.append({
                "file": filename,
                "step": "unknown",
                "model": "unknown",
                "reason": str(exc),
                "timestamp": datetime.now().isoformat(),
            })
        completed += 1
        _render_display()

    # Background ticker: re-render every second for live timers
    ticker_running = True

    async def _ticker():
        while ticker_running:
            await asyncio.sleep(0.1)
            if file_stages:  # only refresh if there are active tasks
                _render_display()

    ticker_task = asyncio.create_task(_ticker())

    # Launch all files concurrently – the LLM pool regulates throughput
    tasks: list[asyncio.Task] = []
    for txt_file in txt_files:
        filename = os.path.splitext(os.path.basename(txt_file))[0]
        output_file = os.path.join(output_dir, f"{filename}.json")

        task = asyncio.create_task(
            _process_and_save(
                input_file=txt_file,
                output_file=output_file,
                models=models,
                judge_model=judge_model,
                filter_model=filter_model,
                max_input_tokens=max_input_tokens,
                llm_client=llm_client,
                max_retries=max_retries,
                status_callback=_status_callback,
                log_callback=_log_callback,
            )
        )
        task.add_done_callback(lambda f, fn=filename: _on_done(f, fn))
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Stop ticker and final render
    ticker_running = False
    ticker_task.cancel()
    try:
        await ticker_task
    except asyncio.CancelledError:
        pass
    _render_display()

    elapsed = time.time() - start_time
    _print_summary(txt_files, counts, elapsed, results, output_dir)

    # Write fail.json with all collected errors
    if all_errors:
        fail_file = os.path.join(output_dir, "fail.json")
        with open(fail_file, "w", encoding="utf-8") as fh:
            json.dump(all_errors, fh, ensure_ascii=False, indent=2)
        print(f"\n❌ Error details saved to: {fail_file}  ({len(all_errors)} error(s))")


async def _process_and_save(
    *,
    input_file: str,
    output_file: str,
    models: list[str],
    judge_model: str,
    filter_model: str | None,
    max_input_tokens: int | None,
    llm_client: LLMClient,
    max_retries: int,
    status_callback=None,
    log_callback=None,
) -> FileResult:
    """Run the pipeline and persist the unified result."""
    result = await process_file(
        input_file=input_file,
        models=models,
        judge_model=judge_model,
        filter_model=filter_model,
        max_input_tokens=max_input_tokens,
        llm_client=llm_client,
        max_retries=max_retries,
        status_callback=status_callback,
        log_callback=log_callback,
    )

    with open(output_file, "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2)

    return result


# =====================================================================
# Display helpers
# =====================================================================

def _print_banner(
    input_dir, output_dir, txt_files, models, judge_model, filter_model, max_input_tokens
):
    print(f"{'=' * 70}")
    print("Batch Multi-Model Terminal Parser")
    print(f"{'=' * 70}")
    print(f"Input directory   : {input_dir}")
    print(f"Output directory  : {output_dir}")
    print(f"Total files       : {len(txt_files)}")
    print(f"Models ({len(models)}):")
    for i, m in enumerate(models):
        print(f"  Model {chr(ord('A') + i)}: {m}")
    print(f"Judge model       : {judge_model}")
    print(f"Max input tokens  : {max_input_tokens or 'unlimited'}")
    print(f"Filter model      : {filter_model or 'disabled'}")
    print(f"{'=' * 70}\n")


def _print_summary(txt_files, counts, elapsed, results, output_dir):
    print(f"\n{'=' * 70}")
    print("Batch Processing Summary")
    print(f"{'=' * 70}")
    print(f"Total files  : {len(txt_files)}")
    print(f"Successful   : {counts['success']}")
    print(f"Filtered     : {counts['filtered']}")
    print(f"Too large    : {counts['too_large']}")
    print(f"Failed       : {counts['failed']}")
    avg = elapsed / len(txt_files) if txt_files else 0
    print(f"Total time   : {elapsed:.2f}s ({avg:.2f}s per file)")
    print(f"Results saved: {output_dir}/")
    print(f"{'=' * 70}")


# =====================================================================
# CLI
# =====================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch process txt files with multiple models"
    )
    parser.add_argument("--input-dir", type=str, default="data/raw/txt")
    parser.add_argument("--output-dir", type=str, default="output")
    parser.add_argument("--models", type=str, nargs="+", required=True)
    parser.add_argument("--judge-model", type=str, required=True)
    parser.add_argument("--filter-model", type=str, default=None)
    parser.add_argument("--max-input-tokens", type=int, default=100000)
    parser.add_argument("--max-retries", type=int, default=10)
    parser.add_argument(
        "--max-llm-concurrency",
        type=int,
        default=20,
        help="Global max concurrent LLM API requests (default: 20)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds for each LLM API call (default: 120)",
    )

    args = parser.parse_args()

    if len(args.models) < 2:
        print("⚠️  At least 2 models are required for comparison")
        sys.exit(1)

    # Initialise the global LLM pool
    # The log_callback will be set during batch_process when the live display starts
    LLMClient.init(max_concurrency=args.max_llm_concurrency, timeout=args.timeout)

    asyncio.run(
        batch_process(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            models=args.models,
            judge_model=args.judge_model,
            filter_model=args.filter_model,
            max_input_tokens=args.max_input_tokens,
            max_retries=args.max_retries,
        )
    )


if __name__ == "__main__":
    main()
