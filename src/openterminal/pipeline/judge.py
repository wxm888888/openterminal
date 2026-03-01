"""
Multi-model judge: compare parsing results and evaluate trajectory quality.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
import os

from openterminal.pipeline.llm_client import LLMClient
from openterminal.pipeline.json_utils import extract_json
from openterminal.pipeline.prompts import build_judge_system_prompt


# =====================================================================
# Data classes
# =====================================================================

@dataclass
class JudgmentResult:
    winner: str                         # e.g. "model_a" or "all_incorrect"
    winner_model: str                   # human-readable model name
    reason: str
    confidence: float
    model_issues: dict[str, list[str]]
    suitable_for_training: bool
    rejection_type: str = ""
    rejection_reason: str = ""


# =====================================================================
# Helpers
# =====================================================================

def clean_parse_result(result: dict) -> dict:
    """Strip a raw parse to the essential fields (for judge input)."""
    cleaned: dict[str, Any] = {
        "initial_output": result.get("initial_output", ""),
        "turns": [],
    }
    for turn in result.get("turns", []):
        cleaned["turns"].append(
            {
                "turn_id": turn.get("turn_id"),
                "prompt": turn.get("prompt", ""),
                "input": {"content": turn.get("action", {}).get("content", "")},
                "output": {"content": turn.get("observation", {}).get("content", "")},
            }
        )
    return cleaned


def merge_prompts_into_output(clean_output: dict) -> dict:
    """Merge each prompt into the preceding turn's observation stream."""
    import copy

    result = copy.deepcopy(clean_output)
    turns = result.get("turns", [])
    if not turns:
        return result

    first_prompt = turns[0].get("prompt", "")
    if first_prompt:
        cur = result.get("initial_output", "")
        result["initial_output"] = (cur + "\n" + first_prompt) if cur else first_prompt

    for i in range(len(turns) - 1):
        next_prompt = turns[i + 1].get("prompt", "")
        if next_prompt:
            cur = turns[i].get("observation", {}).get("content", "")
            turns[i]["observation"]["content"] = (cur + "\n" + next_prompt) if cur else next_prompt

    return result


# =====================================================================
# Judge
# =====================================================================

async def judge_results(
    *,
    txt_file: str,
    model_results: dict[str, dict],
    judge_model: str,
    llm_client: LLMClient,
    max_retries: int = 10,
) -> JudgmentResult:
    """
    Ask *judge_model* to pick the best parse and assess training suitability.

    Parameters
    ----------
    txt_file : str
        Path to the original txt file.
    model_results : dict[str, dict]
        ``{"model_a": cleaned_result, "model_b": ...}``
    judge_model : str
        Which model to use for judging.
    llm_client : LLMClient
        The global LLM pool.
    max_retries : int
        Retry budget.

    Returns
    -------
    JudgmentResult
    """
    with open(txt_file, "r", encoding="utf-8", errors="ignore") as fh:
        txt_content = fh.read()

    model_count = len(model_results)
    system_prompt = build_judge_system_prompt(model_count)
    user_message = _build_user_message(txt_content, model_results)

    model_labels = list(model_results.keys())

    try:
        response, _attempts = await llm_client.call(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            model=judge_model,
            temperature=0.3,
            max_retries=max_retries,
            log_context=f"judge:{os.path.basename(txt_file)}:{judge_model}",
        )
        data = extract_json(response.choices[0].message.content)
    except Exception as exc:
        issues = {f"{label}_issues": [] for label in model_labels}
        return JudgmentResult(
            winner="all_incorrect",
            winner_model="all_incorrect",
            reason=f"Judge model failed: {exc}",
            confidence=0.0,
            model_issues=issues,
            suitable_for_training=False,
            rejection_type="judge_failed",
            rejection_reason=f"Judge model error: {exc}",
        )

    issues = {}
    for label in model_labels:
        issues[f"{label}_issues"] = data.get(f"{label}_issues", [])

    return JudgmentResult(
        winner=data.get("winner", "model_a"),
        winner_model=data.get("winner", "model_a"),   # caller maps label→name
        reason=data.get("reason", "No reason provided"),
        confidence=data.get("confidence", 0.5),
        model_issues=issues,
        suitable_for_training=data.get("suitable_for_training", True),
        rejection_type=data.get("rejection_type", ""),
        rejection_reason=data.get("rejection_reason", ""),
    )


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _build_user_message(txt_content: str, model_results: dict[str, dict]) -> str:
    sections = []
    for i, (_, result) in enumerate(model_results.items()):
        label = f"Model {chr(ord('a') + i)}"
        sections.append(
            f"[{label} Parsing Result]\n```json\n"
            + json.dumps(result, indent=2, ensure_ascii=False)
            + "\n```"
        )

    return (
        "Please evaluate the parsing results and determine:\n"
        "1. Which model's parsing is most accurate\n"
        "2. Whether this trajectory is suitable for training a Terminal Agent\n\n"
        f"[Raw Terminal Text]\n```\n{txt_content}\n```\n\n"
        + "\n\n".join(sections)
        + "\n\nFirst, check the raw terminal text for content issues "
        "(vim, ssh, demo scripts, etc.).\n"
        "Then, compare all parsing results and evaluate their quality.\n"
        "Finally, provide your complete judgment in JSON format."
    )
