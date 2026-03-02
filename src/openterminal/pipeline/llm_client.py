"""
Global LLM Client with resource pool and retry mechanism.

All LLM API calls go through a single shared semaphore to prevent
rate-limit storms when running multiple models concurrently.
"""

import os
import asyncio
import random
from typing import Any
from openai import AsyncOpenAI, RateLimitError, APIStatusError

from openterminal.pipeline.json_utils import extract_json


class LLMClient:
    """
    Global LLM resource pool.

    Manages a shared AsyncOpenAI client and a global asyncio.Semaphore
    so that at most `max_concurrency` LLM requests are in-flight at any
    time, regardless of which model is being called.
    """

    _instance: "LLMClient | None" = None

    def __init__(self, max_concurrency: int = 20, timeout: float = 120.0, log_callback: Any = None):
        self._client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_concurrency = max_concurrency
        self._timeout = timeout
        self._active_requests = 0
        self._log_callback = log_callback

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------
    @classmethod
    def init(cls, max_concurrency: int = 20, timeout: float = 120.0, log_callback: Any = None) -> "LLMClient":
        """Initialise (or re-initialise) the global singleton."""
        cls._instance = cls(max_concurrency=max_concurrency, timeout=timeout, log_callback=log_callback)
        return cls._instance

    @classmethod
    def get(cls) -> "LLMClient":
        """Return the global singleton; raises if not initialised."""
        if cls._instance is None:
            raise RuntimeError(
                "LLMClient has not been initialised. "
                "Call LLMClient.init(max_concurrency) first."
            )
        return cls._instance

    def _log(self, msg: str) -> None:
        if self._log_callback:
            self._log_callback(msg)
        else:
            print(msg)

    # ------------------------------------------------------------------
    # Core call with semaphore + retry
    # ------------------------------------------------------------------
    async def call(
        self,
        *,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        max_retries: int = 10,
        base_delay: float = 5.0,
        timeout: float | None = None,
        log_context: str = "",
        parse_json: bool = False,
    ) -> tuple:
        """
        Send a chat completion request with global concurrency control
        and automatic retry on transient errors. If `parse_json` is True, 
        automatically attempts to parse the response content as a JSON dictionary 
        and retries if extraction fails.

        Returns
        -------
        tuple of (ChatCompletion | dict, int)
            The response object (or parsed dict if parse_json=True) and the number of 
            attempts it took (1 means success on first try).
        """
        last_error: Exception | None = None

        # Only pass max_tokens when explicitly set by the caller
        token_kwargs: dict = {"max_tokens": max_tokens} if max_tokens is not None else {}

        for attempt in range(max_retries):
            try:
                async with self._semaphore:
                    self._active_requests += 1
                    try:
                        response = await asyncio.wait_for(
                            self._client.chat.completions.create(
                                messages=messages,
                                model=model,
                                temperature=temperature,
                                **token_kwargs,
                            ),
                            timeout=timeout if timeout is not None else self._timeout,
                        )
                        
                        if parse_json:
                            # 1. Try to extract
                            data = extract_json(response.choices[0].message.content)
                            # 2. Defend against non-dictionary types
                            if isinstance(data, list) and data and isinstance(data[0], dict):
                                data = data[0]
                            if not isinstance(data, dict):
                                raise ValueError(f"Extracted JSON is not a dictionary, but {type(data).__name__}")
                            return data, attempt + 1
                        
                        return response, attempt + 1
                    finally:
                        self._active_requests -= 1
            except asyncio.TimeoutError:
                effective_timeout = timeout if timeout is not None else self._timeout
                last_error = TimeoutError(
                    f"LLM request timeout ({effective_timeout:.0f}s), model={model}"
                )
                if attempt < max_retries - 1:
                    wait = min(base_delay * (2 ** attempt), 60) + random.uniform(0, 1)
                    ctx = f"[{log_context}] " if log_context else ""
                    self._log(
                        f"[LLMClient] {ctx}Timeout after {effective_timeout:.0f}s "
                        f"(attempt {attempt + 1}/{max_retries}), waiting {wait:.1f}s before retrying ..."
                    )
                    await asyncio.sleep(wait)
            except ValueError as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    wait = min(base_delay * (2 ** attempt), 10) + random.uniform(0, 1)
                    ctx = f"[{log_context}] " if log_context else ""
                    self._log(
                        f"[LLMClient] {ctx}JSON Parse Error "
                        f"(attempt {attempt + 1}/{max_retries}), waiting {wait:.1f}s before retrying ..."
                    )
                    await asyncio.sleep(wait)
            except RateLimitError as exc:
                last_error = exc
                wait = self._rate_limit_wait(exc, attempt, base_delay)
                if attempt < max_retries - 1:
                    ctx = f"[{log_context}] " if log_context else ""
                    self._log(
                        f"[LLMClient] {ctx}Rate limited (attempt {attempt + 1}/{max_retries}), "
                        f"waiting {wait:.1f}s ..."
                    )
                    await asyncio.sleep(wait)
            except APIStatusError as exc:
                last_error = exc
                # Retryable status codes (418 = API gateway wrapping upstream errors)
                _RETRYABLE_STATUS_CODES = {418, 500, 502, 503, 504}
                if exc.status_code in _RETRYABLE_STATUS_CODES and attempt < max_retries - 1:
                    wait = min(base_delay * (2 ** attempt), 60) + random.uniform(0, 1)
                    ctx = f"[{log_context}] " if log_context else ""
                    self._log(
                        f"[LLMClient] {ctx}Server error {exc.status_code} "
                        f"(attempt {attempt + 1}/{max_retries}), waiting {wait:.1f}s ..."
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

        # Exhausted all retries
        raise RuntimeError(
            f"Failed after {max_retries} retries: {last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _rate_limit_wait(exc: RateLimitError, attempt: int, base_delay: float) -> float:
        retry_after = None
        if hasattr(exc, "response") and exc.response is not None:
            retry_after = exc.response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except (ValueError, TypeError):
                pass
        return min(base_delay * (2 ** attempt), 120) + random.uniform(0, 1)

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @property
    def active_requests(self) -> int:
        return self._active_requests
