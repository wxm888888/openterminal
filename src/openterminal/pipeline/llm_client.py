"""
Global LLM Client with resource pool and priority-based retry mechanism.

All LLM API calls go through a priority queue where retry requests
are prioritized over new requests to maximize throughput.
"""

import os
import asyncio
import random
from typing import Any
from dataclasses import dataclass
from openai import AsyncOpenAI, RateLimitError, APIStatusError

from openterminal.pipeline.json_utils import extract_json


@dataclass
class LLMRequest:
    """Represents a single LLM API request with retry context."""
    messages: list[dict]
    model: str
    temperature: float
    max_tokens: int | None
    attempt: int
    max_retries: int
    base_delay: float
    timeout: float
    log_context: str
    parse_json: bool
    future: asyncio.Future
    request_id: int


class LLMClient:
    """
    Global LLM resource pool with priority queue.

    Manages a shared AsyncOpenAI client and a priority queue where
    retry requests are prioritized over new requests.
    """

    _instance: "LLMClient | None" = None

    def __init__(self, max_concurrency: int = 20, timeout: float = 120.0, log_callback: Any = None):
        self._client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self._max_concurrency = max_concurrency
        self._timeout = timeout
        self._active_requests = 0
        self._log_callback = log_callback

        # Priority queue: (priority, counter, request)
        # priority: 0 = retry (high), 1 = new request (normal)
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._counter = 0  # Ensures FIFO for same priority
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._request_id_counter = 0

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------
    @classmethod
    def init(cls, max_concurrency: int = 20, timeout: float = 120.0, log_callback: Any = None) -> "LLMClient":
        """Initialise (or re-initialise) the global singleton."""
        instance = cls(max_concurrency=max_concurrency, timeout=timeout, log_callback=log_callback)
        instance._start_workers()
        cls._instance = instance
        return instance

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

    def _start_workers(self) -> None:
        """Start worker tasks to process the request queue."""
        self._running = True
        for _ in range(self._max_concurrency):
            worker = asyncio.create_task(self._worker())
            self._workers.append(worker)

    async def _stop_workers(self) -> None:
        """Stop all worker tasks."""
        self._running = False
        # Put sentinel values to wake up workers
        for _ in range(len(self._workers)):
            await self._queue.put((999, 999999, None))
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    # ------------------------------------------------------------------
    # Worker to process requests from queue
    # ------------------------------------------------------------------
    async def _worker(self) -> None:
        """Worker that processes LLM requests from the priority queue."""
        while self._running:
            try:
                priority, _, request = await asyncio.wait_for(
                    self._queue.get(), timeout=0.1
                )
            except asyncio.TimeoutError:
                continue

            # Sentinel value to exit
            if request is None:
                self._queue.task_done()
                break

            await self._execute_request(request)
            self._queue.task_done()

    async def _execute_request(self, request: LLMRequest) -> None:
        """Execute a single LLM request and handle retry logic."""
        # Different models use different parameter names for token limits
        max_tokens = request.max_tokens

        # Claude models require max_tokens; default to 64000 and cap at 64000
        if 'claude' in request.model.lower():
            max_tokens = min(max_tokens or 64000, 64000)

        if max_tokens is not None:

            if request.model.startswith('gpt'):
                # OpenAI GPT models use max_completion_tokens
                token_kwargs: dict = {"max_completion_tokens": max_tokens}
            else:
                # Other models (Claude, Gemini, etc.) use max_tokens
                token_kwargs: dict = {"max_tokens": max_tokens}
        else:
            token_kwargs: dict = {}

        try:
            self._active_requests += 1
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    messages=request.messages,
                    model=request.model,
                    temperature=request.temperature,
                    **token_kwargs,
                ),
                timeout=request.timeout,
            )

            if request.parse_json:
                # Try to extract JSON
                data = extract_json(response.choices[0].message.content)
                # Defend against non-dictionary types
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    data = data[0]
                if not isinstance(data, dict):
                    raise ValueError(f"Extracted JSON is not a dictionary, but {type(data).__name__}")
                request.future.set_result((data, request.attempt))
            else:
                request.future.set_result((response, request.attempt))

        except asyncio.TimeoutError:
            await self._handle_retry(
                request,
                TimeoutError(f"LLM request timeout ({request.timeout:.0f}s), model={request.model}"),
                f"Timeout after {request.timeout:.0f}s"
            )
        except ValueError as exc:
            await self._handle_retry(request, exc, "JSON Parse Error")
        except RateLimitError as exc:
            await self._handle_retry(request, exc, "Rate limited")
        except APIStatusError as exc:
            _RETRYABLE_STATUS_CODES = {418, 500, 502, 503, 504}
            if exc.status_code in _RETRYABLE_STATUS_CODES:
                await self._handle_retry(request, exc, f"Server error {exc.status_code}")
            else:
                request.future.set_exception(exc)
        except Exception as exc:
            request.future.set_exception(exc)
        finally:
            self._active_requests -= 1

    async def _handle_retry(self, request: LLMRequest, error: Exception, error_msg: str) -> None:
        """Handle retry logic for failed requests."""
        if request.attempt >= request.max_retries:
            # Exhausted all retries
            exc = RuntimeError(f"Failed after {request.max_retries} retries: {error}")
            request.future.set_exception(exc)
            return

        # Calculate wait time - unified 1s + random jitter for all error types
        wait = 1.0 + random.uniform(0, 1)

        # Log retry
        ctx = f"[{request.log_context}] " if request.log_context else ""
        self._log(
            f"[LLMClient] {ctx}{error_msg} "
            f"(attempt {request.attempt}/{request.max_retries}), "
            f"will retry with priority in {wait:.1f}s ..."
        )

        # Schedule retry with high priority after delay
        asyncio.create_task(self._schedule_retry(request, wait))

    async def _schedule_retry(self, request: LLMRequest, delay: float) -> None:
        """Schedule a retry request after a delay."""
        await asyncio.sleep(delay)
        # Increment attempt counter
        request.attempt += 1
        # Re-enqueue with high priority (0)
        self._counter += 1
        await self._queue.put((0, self._counter, request))

    # ------------------------------------------------------------------
    # Public API
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
        Send a chat completion request with priority-based retry.

        Retry requests are prioritized over new requests in the queue.

        Returns
        -------
        tuple of (ChatCompletion | dict, int)
            The response object (or parsed dict if parse_json=True) and the number of
            attempts it took (1 means success on first try).
        """
        future: asyncio.Future = asyncio.Future()
        self._request_id_counter += 1

        request = LLMRequest(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            attempt=1,
            max_retries=max_retries,
            base_delay=base_delay,
            timeout=timeout if timeout is not None else self._timeout,
            log_context=log_context,
            parse_json=parse_json,
            future=future,
            request_id=self._request_id_counter,
        )

        # Enqueue with normal priority (1)
        self._counter += 1
        await self._queue.put((1, self._counter, request))

        # Wait for result
        return await future

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
