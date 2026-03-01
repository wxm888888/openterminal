"""
Single-file processing pipeline.

Orchestrates: preprocess → multi-model parse → judge → unified output.
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from datetime import datetime

from openterminal.pipeline.llm_client import LLMClient
from openterminal.pipeline.preprocess import count_file_tokens, check_file_quality, QualityResult
from openterminal.pipeline.terminal_parser import TerminalParser, ModelResult
from openterminal.pipeline.judge import (
    judge_results,
    clean_parse_result,
    merge_prompts_into_output,
    JudgmentResult,
)


# =====================================================================
# Unified result
# =====================================================================

@dataclass
class FileResult:
    """
    Everything about one input file's processing — serialised to a single
    JSON in ``output/``.
    """

    input_file: str
    status: str  # "success" | "filtered" | "too_large" | "failed"

    # Preprocess info
    preprocess: dict = field(default_factory=dict)

    # Per-model parse results
    models: dict[str, dict] = field(default_factory=dict)

    # Judge result (only if judge ran)
    judge: dict | None = None

    # Final cleaned result (only on success)
    final_result: dict | None = None

    # Collected errors for fail.json
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# =====================================================================
# Pipeline
# =====================================================================

async def process_file(
    *,
    input_file: str,
    models: list[str],
    judge_model: str,
    filter_model: str | None,
    max_input_tokens: int | None,
    llm_client: LLMClient,
    max_retries: int = 10,
    status_callback: Any = None,
    log_callback: Any = None,
) -> FileResult:
    """
    Full processing pipeline for a single input txt file.

    Parameters
    ----------
    status_callback : callable, optional
        ``callback(file_id, stage)`` called when the pipeline moves
        between stages.  *stage* is one of ``"preprocess"``,
        ``"parse"``, ``"judge"``, ``"done"``.
    """

    import os
    file_id = os.path.splitext(os.path.basename(input_file))[0]

    def _report(stage: str) -> None:
        if status_callback is not None:
            status_callback(file_id, stage)

    def _log_error(step: str, model: str, reason: str) -> None:
        # Truncate reason to single line for clean terminal output
        short_reason = reason.replace('\n', ' ').replace('\r', '')[:150]
        msg = f"❌ [ERROR] File: {file_id} | Step: {step} | Model: {model} | {short_reason}"
        if log_callback is not None:
            log_callback(msg)
        else:
            print(msg)
        # Collect full error details for fail.json
        result.errors.append({
            "file": file_id,
            "step": step,
            "model": model,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        })

    result = FileResult(input_file=input_file, status="failed")
    task_description = ""

    # ------------------------------------------------------------------
    # 1. Token count
    # ------------------------------------------------------------------
    _report("preprocess")
    if max_input_tokens is not None:
        token_count = count_file_tokens(input_file)
        result.preprocess["token_count"] = token_count
        result.preprocess["max_input_tokens"] = max_input_tokens

        if token_count > max_input_tokens:
            result.status = "too_large"
            _report("done")
            return result

    # ------------------------------------------------------------------
    # 2. Quality filter
    # ------------------------------------------------------------------
    if filter_model is not None:
        qr: QualityResult = await check_file_quality(
            input_file,
            model_name=filter_model,
            llm_client=llm_client,
            max_retries=max_retries,
        )
        result.preprocess["filter_model"] = filter_model
        result.preprocess["qualified"] = qr.qualified
        result.preprocess["reason"] = qr.reason
        result.preprocess["task_description"] = qr.task_description
        task_description = qr.task_description

        if not qr.qualified:
            result.status = "filtered"
            _report("done")
            return result

    # ------------------------------------------------------------------
    # 3. Multi-model parse (all concurrent, LLM pool controls throttle)
    # ------------------------------------------------------------------
    _report("parse")
    model_tasks = []
    for model_name in models:
        parser = TerminalParser(
            llm_client=llm_client,
            model_name=model_name,
            step4_model_name=model_name,
            max_retries=max_retries,
        )
        model_tasks.append(parser.run_all_steps(input_file))

    model_results: list[ModelResult] = await asyncio.gather(*model_tasks)

    # Build letter labels for each model slot: a, b, c, ...
    model_labels = [chr(ord('a') + i) for i in range(len(models))]

    # Record per-model outcome using labels as keys
    for label, model_name, mr in zip(model_labels, models, model_results):
        key = f"{label}: {model_name}"
        result.models[key] = {
            "success": mr.success,
            "failed_step": mr.failed_step,
            "fail_reason": mr.fail_reason,
            "step_details": mr.step_details,
            "parsed_result": _strip_raw_lines(mr.parsed_result) if mr.parsed_result else None,
        }
        # Print error details for failed models
        if not mr.success and mr.failed_step:
            _log_error(mr.failed_step, model_name, mr.fail_reason or "unknown error")

    # ------------------------------------------------------------------
    # 4. Judge
    # ------------------------------------------------------------------
    successful_indices = [i for i, mr in enumerate(model_results) if mr.success]

    if not successful_indices:
        result.status = "failed"
        _report("done")
        return result

    # Build label mapping for judge: model_a, model_b, ... (only successful ones)
    label_map: dict[str, str] = {}   # judge_label -> display key
    clean_map: dict[str, dict] = {}  # judge_label -> cleaned result
    raw_map: dict[str, dict] = {}    # judge_label -> raw result

    for j, idx in enumerate(successful_indices):
        judge_label = f"model_{chr(ord('a') + j)}"
        display_key = f"{model_labels[idx]}: {models[idx]}"
        label_map[judge_label] = display_key
        clean_map[judge_label] = clean_parse_result(model_results[idx].parsed_result)  # type: ignore
        raw_map[judge_label] = model_results[idx].parsed_result  # type: ignore

    _report("judge")
    judgment: JudgmentResult = await judge_results(
        txt_file=input_file,
        model_results=clean_map,
        judge_model=judge_model,
        llm_client=llm_client,
        max_retries=max_retries,
    )

    # Map judge's internal labels (model_a, model_b...) back to display keys
    winner_display = label_map.get(judgment.winner, judgment.winner)

    # Remap model_issues keys: model_a_issues -> "b: gemini..." 
    remapped_issues: dict[str, list] = {}
    for judge_label, display_key in label_map.items():
        issue_key = f"{judge_label}_issues"
        remapped_issues[display_key] = judgment.model_issues.get(issue_key, [])

    # Build judge_label_map so readers know what judge's model_a/b/c referred to
    judge_label_mapping = {jl: dk for jl, dk in label_map.items()}

    result.judge = {
        "winner": winner_display,
        "judge_label_map": judge_label_mapping,
        "reason": judgment.reason,
        "confidence": judgment.confidence,
        "suitable_for_training": judgment.suitable_for_training,
        "rejection_type": judgment.rejection_type,
        "rejection_reason": judgment.rejection_reason,
        "model_issues": remapped_issues,
    }

    # Print error if judge failed
    if judgment.rejection_type == "judge_failed":
        _log_error("judge", judge_model, judgment.rejection_reason or "unknown error")

    # ------------------------------------------------------------------
    # 5. Final result
    # ------------------------------------------------------------------
    if judgment.suitable_for_training and judgment.winner in label_map:
        chosen_raw = raw_map[judgment.winner]
        clean_output = {
            "task_description": task_description,
            "initial_output": chosen_raw.get("initial_output", ""),
            "turns": chosen_raw.get("turns", []),
        }
        result.final_result = merge_prompts_into_output(clean_output)
        result.status = "success"
    else:
        result.status = "failed"

    _report("done")
    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _strip_raw_lines(parsed: dict | None) -> dict | None:
    """Remove bulky ``raw_lines`` from turns before serialisation."""
    if parsed is None:
        return None
    out = copy.deepcopy(parsed)
    for turn in out.get("turns", []):
        turn.pop("raw_lines", None)
    return out
