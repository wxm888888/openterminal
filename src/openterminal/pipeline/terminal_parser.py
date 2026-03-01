"""
Four-step terminal parser with fail-fast semantics.

Each step calls the LLM via the global ``LLMClient`` pool.  If any step
fails (LLM error **or** JSON extraction error), a ``StepFailedError`` is
raised so that the caller can record *which* step failed and skip all
subsequent steps for that model.
"""

from __future__ import annotations

import re
import os
import json
import asyncio
from dataclasses import dataclass, field
from typing import Any

from openterminal.pipeline.llm_client import LLMClient
from openterminal.pipeline.json_utils import extract_json
from openterminal.pipeline.prompts import (
    STEP1_SYSTEM_PROMPT,
    STEP2_SYSTEM_PROMPT,
    STEP3_SYSTEM_PROMPT,
    STEP4_SYSTEM_PROMPT,
    build_step1_user_message,
)


# =====================================================================
# Data classes
# =====================================================================

@dataclass
class ModelResult:
    """Result of running the full 4-step parse with a single model."""
    model_name: str
    success: bool
    failed_step: str | None = None
    fail_reason: str | None = None
    parsed_result: dict | None = None     # final verified parse
    step_details: dict = field(default_factory=dict)  # raw per-step data


# =====================================================================
# Custom exception
# =====================================================================

class StepFailedError(Exception):
    """Raised when an individual parsing step fails irrecoverably."""

    def __init__(self, step_name: str, reason: str):
        self.step_name = step_name
        self.reason = reason
        super().__init__(f"Step {step_name} failed: {reason}")


# =====================================================================
# TerminalParser
# =====================================================================

class TerminalParser:
    """
    Stateful, single-model terminal file parser.

    Instantiate one parser per (file, model) pair, then call
    :meth:`run_all_steps` which executes steps 1-4 sequentially
    and short-circuits on failure.

    Parameters
    ----------
    llm_client : LLMClient
        The global LLM resource-pool client.
    model_name : str
        Model used for steps 1-3.
    step4_model_name : str
        Model used for step 4 (verification).
    max_retries : int
        Per-call retry budget forwarded to ``LLMClient.call``.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        model_name: str,
        step4_model_name: str | None = None,
        max_retries: int = 10,
    ):
        self.llm = llm_client
        self.model_name = model_name
        self.step4_model_name = step4_model_name or model_name
        self.max_retries = max_retries

        # populated by step 1
        self.prompt_patterns: list[str] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_all_steps(self, file_path: str) -> ModelResult:
        """
        Execute the full 4-step pipeline for *file_path*.

        Returns a :class:`ModelResult`.  On failure the result contains
        ``failed_step`` and ``fail_reason``; on success it contains
        ``parsed_result`` with the verified parse.
        """
        step_details: dict[str, Any] = {}

        try:
            # Step 1 — learn prompt patterns
            step1_data, step1_attempts = await self._step1_learn_prompts(file_path)
            step_details["step1"] = {"attempts": step1_attempts}

            # Step 2 — filter false-positive prompts
            step2_data, step2_attempts = await self._step2_filter_fake_prompts(file_path)
            step_details["step2"] = {"attempts": step2_attempts}
            confirmed_lines: set[int] = step2_data["confirmed_prompts"]

            # Step 3 — parse turns
            step3_data = await self._step3_parse_turns(file_path, confirmed_lines)
            step_details["step3"] = {"total_turns": len(step3_data.get("turns", []))}

            # Step 4 — verify & correct
            verified, step4_attempts = await self._step4_verify_turns(file_path, step3_data)
            step_details["step4"] = {"attempts": step4_attempts}

            return ModelResult(
                model_name=self.model_name,
                success=True,
                parsed_result=verified,
                step_details=step_details,
            )

        except StepFailedError as exc:
            step_details[exc.step_name] = {"error": exc.reason}
            return ModelResult(
                model_name=self.model_name,
                success=False,
                failed_step=exc.step_name,
                fail_reason=exc.reason,
                step_details=step_details,
            )

    # ------------------------------------------------------------------
    # Step 1: learn prompt patterns
    # ------------------------------------------------------------------

    async def _step1_learn_prompts(self, file_path: str) -> tuple[dict, int]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            sample_text = fh.read()

        try:
            data, attempts = await self.llm.call(
                messages=[
                    {"role": "system", "content": STEP1_SYSTEM_PROMPT},
                    {"role": "user", "content": build_step1_user_message(sample_text)},
                ],
                model=self.model_name,
                max_retries=self.max_retries,
                log_context=f"step1:{os.path.basename(file_path)}:{self.model_name}",
                parse_json=True,
            )
        except Exception as exc:
            raise StepFailedError("step1", str(exc)) from exc

        for item in data.get("patterns", []):
            pattern = item.get("regex_for_firstline", "")
            if pattern:
                cleaned = re.sub(r"\(\?<[^>]+>", "(", pattern)
                try:
                    re.compile(cleaned)
                    self.prompt_patterns.append(cleaned)
                except re.error:
                    pass

        if not self.prompt_patterns:
            self.prompt_patterns = [r"^[\$\#\%\>]\s*"]

        return data, attempts

    # ------------------------------------------------------------------
    # Step 2: filter false-positive prompts
    # ------------------------------------------------------------------

    async def _step2_filter_fake_prompts(self, file_path: str) -> tuple[dict, int]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()

        candidates = []
        for line_num, line in enumerate(lines, 1):
            line_content = line.rstrip("\n")
            for pattern in self.prompt_patterns:
                try:
                    if re.match(pattern, line_content):
                        candidates.append(
                            {
                                "line_num": line_num,
                                "content": line_content,
                                "prev_line": lines[line_num - 2].rstrip("\n") if line_num > 1 else "",
                                "next_line": lines[line_num].rstrip("\n") if line_num < len(lines) else "",
                            }
                        )
                        break
                except re.error:
                    continue

        if not candidates:
            # Fallback: treat all regex-matching lines as confirmed (no LLM call)
            confirmed = set()
            for line_num, line in enumerate(lines, 1):
                for pattern in self.prompt_patterns:
                    try:
                        if re.match(pattern, line.rstrip("\n")):
                            confirmed.add(line_num)
                            break
                    except re.error:
                        continue
            return {"confirmed_prompts": confirmed, "false_positives": []}, 0

        candidates_text = []
        for c in candidates:
            candidates_text.append(
                f"\nLine {c['line_num']}:\n"
                f"  Previous: {c['prev_line'][:100] if c['prev_line'] else '(start of file)'}\n"
                f"  [Current]: {c['content'][:100]}\n"
                f"  Next: {c['next_line'][:100] if c['next_line'] else '(end of file)'}\n"
            )

        try:
            data, attempts = await self.llm.call(
                messages=[
                    {"role": "system", "content": STEP2_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Determine which of the following candidate lines mark "
                            "the beginning of real prompts:"
                            + "".join(candidates_text)
                            + "\n\nPlease analyze line by line and provide a list of confirmed real prompt line numbers."
                        ),
                    },
                ],
                model=self.model_name,
                temperature=0.3,
                max_retries=self.max_retries,
                log_context=f"step2:{os.path.basename(file_path)}:{self.model_name}",
                parse_json=True,
            )
        except Exception as exc:
            raise StepFailedError("step2", str(exc)) from exc

        confirmed = set(data.get("confirmed_prompts", []))
        false_positives = data.get("false_positives", [])

        if not confirmed:
            # Fallback: use all candidates
            confirmed = {c["line_num"] for c in candidates}

        return {"confirmed_prompts": confirmed, "false_positives": false_positives}, attempts

    # ------------------------------------------------------------------
    # Step 3: parse turns
    # ------------------------------------------------------------------

    async def _step3_parse_turns(self, file_path: str, confirmed_line_nums: set[int]) -> dict:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()

        result: dict[str, Any] = {"initial_output": "", "turns": []}
        current_turn: dict | None = None
        turn_id = 0
        initial_lines: list[str] = []
        in_initial = True

        for line_num, line in enumerate(lines, 1):
            line = line.rstrip("\n")
            is_prompt = False
            matched_pattern = None

            if line_num in confirmed_line_nums:
                for pattern in self.prompt_patterns:
                    try:
                        match = re.match(pattern, line)
                        if match:
                            is_prompt = True
                            matched_pattern = (pattern, match)
                            break
                    except re.error:
                        continue

            if is_prompt:
                if current_turn is not None:
                    result["turns"].append(current_turn)
                in_initial = False
                turn_id += 1
                _, match = matched_pattern  # type: ignore[misc]
                prompt_str = line[: match.end()].strip()

                current_turn = {
                    "turn_id": turn_id,
                    "prompt": prompt_str,
                    "raw_lines": [line],
                    "action": {"content": ""},
                    "observation": {"content": ""},
                }
            else:
                if in_initial:
                    initial_lines.append(line)
                elif current_turn is not None:
                    current_turn["raw_lines"].append(line)

        if current_turn is not None:
            result["turns"].append(current_turn)
        result["initial_output"] = "\n".join(initial_lines)

        # LLM classify action/observation for each turn
        if result["turns"]:
            tasks = [self._llm_classify_turn(turn, file_path) for turn in result["turns"]]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Fail-fast: if ANY turn failed, raise step error
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    raise StepFailedError(
                        "step3",
                        f"Turn {i + 1} classification failed: {r}"
                    )

        return result

    async def _llm_classify_turn(self, turn: dict, file_path: str) -> None:
        """Classify a single turn's action/observation via LLM."""
        raw_lines_text = "\n".join(turn["raw_lines"])
        user_msg = (
            f"Classify the prompt, action (command), and observation (output) from these raw lines:\n\n"
            f"[Raw Lines] ({len(turn['raw_lines'])} line(s))\n{raw_lines_text}\n\n"
            f"[Prompt first line detected by regex]: {turn['prompt']}\n\n"
            f"Please extract the complete prompt (including all prompt lines if multi-line), "
            f"the action lines (command without prompt) as a list, and observation lines (output) as a list."
        )

        data, attempts = await self.llm.call(
            messages=[
                {"role": "system", "content": STEP3_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            model=self.model_name,
            temperature=0.2,
            max_retries=self.max_retries,
            log_context=f"step3:{os.path.basename(file_path)}:turn_{turn['turn_id']}:{self.model_name}",
            parse_json=True,
        )
        turn["attempts"] = attempts

        # Apply LLM result
        extracted_prompt = data.get("prompt", "").strip()
        if extracted_prompt:
            turn["prompt"] = extracted_prompt

        action_lines = data.get("action_lines", [])
        if isinstance(action_lines, list):
            turn["action"]["content"] = "\n".join(action_lines).strip()
        else:
            turn["action"]["content"] = str(action_lines).strip()

        # Try prefix-match for observation extraction
        raw_text = "\n".join(turn["raw_lines"]) if turn.get("raw_lines") else ""
        prefix = turn["prompt"] + turn["action"]["content"]
        prefix_blank = turn["prompt"] + " " + turn["action"]["content"]

        if raw_text.startswith(prefix):
            turn["observation"]["content"] = raw_text[len(prefix) :].strip()
        elif raw_text.startswith(prefix_blank):
            turn["observation"]["content"] = raw_text[len(prefix_blank) :].strip()
        else:
            obs_lines = data.get("observation_lines", [])
            if isinstance(obs_lines, list):
                turn["observation"]["content"] = "\n".join(
                    line for line in obs_lines if line.strip()
                ).strip()
            else:
                turn["observation"]["content"] = str(obs_lines).strip()

    @staticmethod
    def _heuristic_classify_turn(turn: dict) -> None:
        """Best-effort heuristic when LLM classification fails for a turn."""
        if turn["raw_lines"]:
            first_line = turn["raw_lines"][0]
            prompt = turn["prompt"]
            if first_line.startswith(prompt):
                turn["action"]["content"] = first_line[len(prompt) :].strip()
            else:
                turn["action"]["content"] = first_line.strip()
            turn["observation"]["content"] = "\n".join(
                line for line in turn["raw_lines"][1:] if line.strip()
            ).strip()

    # ------------------------------------------------------------------
    # Step 4: verify & correct turns
    # ------------------------------------------------------------------

    async def _step4_verify_turns(self, input_file: str, parsed_result: dict) -> tuple[dict, int]:
        turns = parsed_result.get("turns", [])
        initial_output = parsed_result.get("initial_output", "")

        if not turns and not initial_output:
            return parsed_result, 0

        with open(input_file, "r", encoding="utf-8", errors="ignore") as fh:
            raw_text = fh.read()

        user_message = json.dumps(
            {
                "raw_txt": raw_text,
                "parsed_json": {
                    "initial_output": initial_output,
                    "total_turns": len(turns),
                    "turns": turns,
                },
            },
            ensure_ascii=False,
        )

        try:
            data, attempts = await self.llm.call(
                messages=[
                    {"role": "system", "content": STEP4_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                model=self.step4_model_name,
                temperature=0.2,
                max_retries=self.max_retries,
                log_context=f"step4:{os.path.basename(input_file)}:{self.step4_model_name}",
                parse_json=True,
            )
        except Exception as exc:
            raise StepFailedError("step4", str(exc)) from exc

        # Apply verification corrections
        self._apply_step4_corrections(parsed_result, data)

        return parsed_result, attempts

    # ------------------------------------------------------------------
    # Step 4 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_step4_corrections(parsed_result: dict, data: dict) -> None:
        """Mutate *parsed_result* in place based on step-4 verification *data*."""
        turns = parsed_result.get("turns", [])

        # --- Missed turns in initial_output ---
        missed_turns = data.get("missed_turns_in_initial_output", [])
        if missed_turns:
            if "corrected_initial_output" in data:
                parsed_result["initial_output"] = data["corrected_initial_output"]
            for mt in reversed(missed_turns):
                new_turn = {
                    "turn_id": 0,
                    "prompt": mt.get("prompt", "").strip(),
                    "action": {"content": mt.get("action", {}).get("content", "").strip()},
                    "observation": {"content": mt.get("observation", {}).get("content", "").strip()},
                    "attempts": "step4_modified",
                }
                turns.insert(0, new_turn)
        else:
            if not data.get("initial_output_correct", True) and "corrected_initial_output" in data:
                parsed_result["initial_output"] = data["corrected_initial_output"]

        # --- Per-turn corrections ---
        verification_map = {v.get("turn_id"): v for v in data.get("turns", [])}
        splits_to_insert: list[tuple[int, list]] = []

        for i, turn in enumerate(turns):
            v = verification_map.get(turn.get("turn_id"))
            if not v:
                continue

            if v.get("should_split", False):
                split_turns = v.get("split_into_turns", [])
                if len(split_turns) >= 2:
                    splits_to_insert.append((i, split_turns))
                    continue

            if not v.get("is_correct", True):
                corrected = v.get("corrected_turn") or {}
                if corrected.get("action", {}).get("content"):
                    turns[i]["action"]["content"] = corrected["action"]["content"].strip()
                if corrected.get("observation", {}).get("content"):
                    turns[i]["observation"]["content"] = corrected["observation"]["content"].strip()
                turns[i]["attempts"] = "step4_modified"

        # Apply splits in reverse order so indices stay valid
        for idx, split_list in sorted(splits_to_insert, reverse=True):
            new_turns = []
            for st in split_list:
                new_turns.append(
                    {
                        "turn_id": 0,
                        "prompt": st.get("prompt", "").strip(),
                        "action": {"content": st.get("action", {}).get("content", "").strip()},
                        "observation": {"content": st.get("observation", {}).get("content", "").strip()},
                        "attempts": "step4_modified",
                    }
                )
            turns[idx : idx + 1] = new_turns

        # Renumber turn IDs and clean raw_lines
        for i, turn in enumerate(turns, 1):
            turn["turn_id"] = i
            turn.pop("raw_lines", None)
