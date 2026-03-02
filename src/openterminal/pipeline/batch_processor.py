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
import threading
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
    max_llm_concurrency: int,
    timeout: float,
    resume_dir: str | None = None,
) -> None:
    """
    Process every ``.txt`` file in *input_dir*, write one unified JSON
    per file into *output_dir/{timestamp}/*.

    If *resume_dir* is given, reuse that directory and skip files whose
    output JSON already exists (checkpoint / resume).
    """
    # Initialize LLM client inside event loop
    llm_client = LLMClient.init(max_concurrency=max_llm_concurrency, timeout=timeout)

    if resume_dir:
        # Resume mode: reuse the given output directory
        output_dir = resume_dir
        os.makedirs(output_dir, exist_ok=True)
    else:
        # Normal mode: create timestamped subdirectory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(output_dir, timestamp)
        os.makedirs(output_dir, exist_ok=True)
    all_txt_files = sorted(glob.glob(os.path.join(input_dir, "*.txt")))

    if not all_txt_files:
        print(f"⚠️  No .txt files found in {input_dir}")
        return

    # --- Resume: filter out already-completed files ---
    skipped = 0
    txt_files = []
    for f in all_txt_files:
        file_id = os.path.splitext(os.path.basename(f))[0]
        existing_output = os.path.join(output_dir, f"{file_id}.json")
        if os.path.exists(existing_output):
            skipped += 1
        else:
            txt_files.append(f)

    if skipped:
        print(f"⏩ Resuming: skipped {skipped} already-completed file(s), "
              f"{len(txt_files)} remaining.")

    if not txt_files:
        print(f"✅ All {skipped} file(s) already processed. Nothing to do.")
        return

    # --- Banner ---
    _print_banner(input_dir, output_dir, txt_files, models, judge_model, filter_model, max_input_tokens)

    start_time = time.time()

    # Counters
    counts = {"success": 0, "filtered": 0, "too_large": 0, "failed": 0}
    completed = 0
    total = len(txt_files)
    fail_file = os.path.join(output_dir, "fail.json")

    # Initialize fail.json as empty array if starting fresh
    if not os.path.exists(fail_file):
        with open(fail_file, "w", encoding="utf-8") as fh:
            json.dump([], fh)

    # Live file stage tracking: file_id -> (stage, stage_start_time)
    file_stages: dict[str, tuple[str, float]] = {}
    STAGE_LABELS = {
        "preprocess": "[PRE]  ",
        "parse":      "[PARSE]",
        "judge":      "[JUDGE]",
    }
    prev_display_lines = 0
    display_lock = threading.Lock()

    def _fmt_time(seconds: float) -> str:
        h = int(seconds) // 3600
        m = (int(seconds) % 3600) // 60
        s = int(seconds) % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _render_display() -> None:
        nonlocal prev_display_lines

        with display_lock:
            # Clear previous display - use line-by-line clearing for thorough cleanup
            if prev_display_lines > 0:
                for _ in range(prev_display_lines):
                    sys.stdout.write("\033[A\033[2K")  # Move up and clear entire line

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
        with display_lock:
            # Clear previous display using same method as _render_display
            if prev_display_lines > 0:
                for _ in range(prev_display_lines):
                    sys.stdout.write("\033[A\033[2K")
            # Ensure msg is a single line for clean display
            single_line = msg.replace('\n', ' ').replace('\r', '')
            print(single_line)
            sys.stdout.flush()
            prev_display_lines = 0
        _render_display()

    def _append_error_to_file(error: dict) -> None:
        """Append a single error to fail.json immediately."""
        try:
            # Read existing errors
            with open(fail_file, "r", encoding="utf-8") as fh:
                errors = json.load(fh)
            # Append new error
            errors.append(error)
            # Write back
            with open(fail_file, "w", encoding="utf-8") as fh:
                json.dump(errors, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            # Fallback: if file operation fails, just log it
            print(f"⚠️  Failed to write error to fail.json: {e}")

    llm_client._log_callback = _log_callback

    # Background ticker: re-render every second for live timers
    ticker_running = True

    async def _ticker():
        while ticker_running:
            await asyncio.sleep(0.1)
            if file_stages:  # only refresh if there are active tasks
                _render_display()

    ticker_task = asyncio.create_task(_ticker())

    # Producer-consumer: fixed worker pool pulls from queue
    num_workers = max_llm_concurrency
    queue: asyncio.Queue[tuple[str, str, str] | None] = asyncio.Queue()

    # Enqueue all files (lightweight tuples, not Task objects)
    for txt_file in txt_files:
        filename = os.path.splitext(os.path.basename(txt_file))[0]
        output_file = os.path.join(output_dir, f"{filename}.json")
        queue.put_nowait((txt_file, output_file, filename))

    # Poison pills at the tail — workers exit after all files are processed
    for _ in range(num_workers):
        queue.put_nowait(None)

    async def _worker():
        while True:
            item = await queue.get()
            if item is None:
                break
            txt_file, output_file, filename = item
            try:
                result: FileResult = await _process_and_save(
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
                counts[result.status] = counts.get(result.status, 0) + 1
                if result.errors:
                    for error in result.errors:
                        _append_error_to_file(error)
            except Exception as exc:
                counts["failed"] += 1
                error_msg = str(exc).replace('\n', ' ').replace('\r', '')[:150]
                _log_callback(f"❌ [ERROR] File: {filename} | Uncaught exception: {error_msg}")
                _append_error_to_file({
                    "file": filename,
                    "step": "unknown",
                    "model": "unknown",
                    "reason": str(exc),
                    "timestamp": datetime.now().isoformat(),
                })
            nonlocal completed
            completed += 1
            _render_display()

    workers = [asyncio.create_task(_worker()) for _ in range(num_workers)]
    await asyncio.gather(*workers)

    # Stop ticker and final render
    ticker_running = False
    ticker_task.cancel()
    try:
        await ticker_task
    except asyncio.CancelledError:
        pass
    _render_display()

    elapsed = time.time() - start_time
    _print_summary(txt_files, counts, elapsed, output_dir)

    # Count total errors in fail.json
    try:
        with open(fail_file, "r", encoding="utf-8") as fh:
            error_count = len(json.load(fh))
        if error_count > 0:
            print(f"\n❌ Error details saved to: {fail_file}  ({error_count} error(s))")
    except Exception:
        pass


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


def _print_summary(txt_files, counts, elapsed, output_dir):
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
    parser.add_argument("--input-dir", type=str, default="input")
    parser.add_argument("--output-dir", type=str, default="output")
    parser.add_argument(
        "--resume-dir",
        type=str,
        default=None,
        help="Resume from a previous output directory. Files with existing "
             "output JSON will be skipped.",
    )
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

    asyncio.run(
        batch_process(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            models=args.models,
            judge_model=args.judge_model,
            filter_model=args.filter_model,
            max_input_tokens=args.max_input_tokens,
            max_retries=args.max_retries,
            max_llm_concurrency=args.max_llm_concurrency,
            timeout=args.timeout,
            resume_dir=args.resume_dir,
        )
    )


if __name__ == "__main__":
    main()
