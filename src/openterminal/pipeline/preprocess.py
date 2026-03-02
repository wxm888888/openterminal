"""
Pre-processing: token counting and LLM-based quality filtering.
"""

from __future__ import annotations

from dataclasses import dataclass
import tiktoken
import os

from openterminal.pipeline.llm_client import LLMClient
from openterminal.pipeline.json_utils import extract_json
from openterminal.pipeline.prompts import QUALITY_FILTER_PROMPT


@dataclass
class QualityResult:
    qualified: bool
    reason: str
    task_description: str


def count_file_tokens(file_path: str, encoding: str = "cl100k_base") -> int:
    """Count the number of tokens in *file_path* using tiktoken."""
    enc = tiktoken.get_encoding(encoding)
    with open(file_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    return len(enc.encode(content))


async def check_file_quality(
    file_path: str,
    *,
    model_name: str,
    llm_client: LLMClient,
    max_retries: int = 10,
) -> QualityResult:
    """
    Use *model_name* to decide whether *file_path* contains legitimate
    terminal interaction data worth parsing.
    """
    with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
        content = fh.read()

    # Early exit for empty files to avoid LLM API 500 errors
    if not content.strip():
        return QualityResult(
            qualified=False,
            reason="File is empty or contains only whitespace",
            task_description="",
        )

    try:
        response, _attempts = await llm_client.call(
            messages=[
                {"role": "system", "content": QUALITY_FILTER_PROMPT},
                {"role": "user", "content": content},
            ],
            model=model_name,
            temperature=0.2,
            max_tokens=64000,
            max_retries=max_retries,
            log_context=f"quality_filter:{os.path.basename(file_path)}:{model_name}",
        )
        data = extract_json(response.choices[0].message.content)
        return QualityResult(
            qualified=data.get("qualified", False),
            reason=data.get("reason", ""),
            task_description=data.get("task_description", ""),
        )
    except Exception as exc:
        # On error, default to qualified to avoid false filtering
        return QualityResult(
            qualified=True,
            reason=f"Filter error: {exc}",
            task_description="",
        )
