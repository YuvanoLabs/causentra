"""LangGraph/LangChain callback adapter that excludes inputs and outputs."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, cast

from ..adapter import AdapterEventBridge
from ..types import EventAttributes, EventExporter, JsonValue, Redactor, TraceContext

try:
    from langchain_core.callbacks import BaseCallbackHandler as _BaseCallbackHandler
except ImportError:  # pragma: no cover - dependency-free base install

    class _BaseCallbackHandler:  # type: ignore[no-redef]
        pass


@dataclass(slots=True)
class _Run:
    trace_id: str
    run_id: str
    parent_id: str
    family: str
    name: str
    started: float
    owns_trace: bool


class LangGraphCallbackHandler(_BaseCallbackHandler):  # type: ignore[misc]
    """Translate callback lifecycles; prompt, message, and output bodies are ignored."""

    def __init__(
        self,
        service_name: str,
        exporter: EventExporter,
        *,
        redactor: Redactor | None = None,
        on_error: Any = None,
        parent_context: TraceContext | None = None,
        include_metadata: bool = False,
    ) -> None:
        options: dict[str, Any] = {"parent_context": parent_context, "on_error": on_error}
        if redactor is not None:
            options["redactor"] = redactor
        self._bridge = AdapterEventBridge(service_name, exporter, **options)
        self._include_metadata = include_metadata
        self._runs: dict[str, _Run] = {}
        self._trace_names: dict[str, str] = {}
        self._lock = threading.RLock()

    def on_chain_start(
        self,
        serialized: Any,
        inputs: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Any = None,
        metadata: Any = None,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        del inputs, kwargs
        if tags and "langsmith:hidden" in tags:
            return
        self._start(
            "agent", _name(serialized, name, "graph"), run_id, parent_run_id, tags, metadata
        )

    def on_chain_end(self, outputs: Any, *, run_id: Any, **kwargs: Any) -> None:
        del outputs, kwargs
        self._end(run_id, None)

    def on_chain_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        self._end(run_id, error)

    def on_llm_start(
        self,
        serialized: Any,
        prompts: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Any = None,
        metadata: Any = None,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        del prompts, kwargs
        self._start(
            "model", _name(serialized, name, "model"), run_id, parent_run_id, tags, metadata
        )

    def on_chat_model_start(
        self,
        serialized: Any,
        messages: Any,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Any = None,
        metadata: Any = None,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        del messages, kwargs
        self._start(
            "model", _name(serialized, name, "chat-model"), run_id, parent_run_id, tags, metadata
        )

    def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> None:
        del response, kwargs
        self._end(run_id, None)

    def on_llm_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        self._end(run_id, error)

    def on_tool_start(
        self,
        serialized: Any,
        input_str: str,
        *,
        run_id: Any,
        parent_run_id: Any = None,
        tags: Any = None,
        metadata: Any = None,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        del input_str, kwargs
        self._start("tool", _name(serialized, name, "tool"), run_id, parent_run_id, tags, metadata)

    def on_tool_end(self, output: Any, *, run_id: Any, **kwargs: Any) -> None:
        del output, kwargs
        self._end(run_id, None)

    def on_tool_error(self, error: BaseException, *, run_id: Any, **kwargs: Any) -> None:
        del kwargs
        self._end(run_id, error)

    def _start(
        self, family: str, name: str, run_id: Any, parent_run_id: Any, tags: Any, metadata: Any
    ) -> None:
        run_key = str(run_id)
        parent_key = None if parent_run_id is None else str(parent_run_id)
        with self._lock:
            if run_key in self._runs:
                return
            parent = self._runs.get(parent_key or "")
            trace_id = parent.trace_id if parent else run_key
            root = f"{trace_id}:root"
            owns_trace = trace_id not in self._trace_names
            if owns_trace:
                self._trace_names[trace_id] = name
                self._bridge.emit(
                    external_trace_id=trace_id,
                    external_span_id=root,
                    event_type="trace.start",
                    name=name,
                    attributes={"framework.name": "langgraph"},
                )
            started = time.monotonic()
            self._runs[run_key] = _Run(
                trace_id, run_key, parent_key or root, family, name, started, owns_trace
            )
            attributes: EventAttributes = {
                "framework.name": "langgraph",
                "framework.operation.family": family,
            }
            if self._include_metadata:
                if isinstance(tags, list):
                    attributes["framework.tags"] = cast(
                        JsonValue, [str(item)[:256] for item in tags[:32]]
                    )
                if isinstance(metadata, dict):
                    attributes["framework.metadata.keys"] = cast(
                        JsonValue,
                        sorted(str(key)[:256] for key in metadata)[:64],
                    )
            self._bridge.emit(
                external_trace_id=trace_id,
                external_span_id=run_key,
                external_parent_span_id=parent_key or root,
                event_type=f"{family}.start",
                name=name,
                attributes=attributes,
            )

    def _end(self, run_id: Any, error: BaseException | None) -> None:
        run_key = str(run_id)
        with self._lock:
            run = self._runs.pop(run_key, None)
            if run is None:
                return
            duration = (time.monotonic() - run.started) * 1_000
            attributes: EventAttributes = {"framework.name": "langgraph"}
            if error is not None:
                attributes["error.type"] = type(error).__name__[:128]
            self._bridge.emit(
                external_trace_id=run.trace_id,
                external_span_id=run.run_id,
                external_parent_span_id=run.parent_id,
                event_type=f"{run.family}.end",
                name=run.name,
                status="error" if error else "ok",
                duration_ms=duration,
                attributes=attributes,
            )
            if run.owns_trace:
                self._bridge.emit(
                    external_trace_id=run.trace_id,
                    external_span_id=f"{run.trace_id}:root",
                    event_type="trace.end",
                    name=self._trace_names.pop(run.trace_id, run.name),
                    status="error" if error else "ok",
                    duration_ms=duration,
                    attributes={"framework.name": "langgraph"},
                )

    def flush(self, timeout: float | None = None) -> bool:
        return self._bridge.flush(timeout)

    def shutdown(self, timeout: float | None = 5.0) -> None:
        self._bridge.shutdown(timeout)


def _name(serialized: Any, declared: str | None, fallback: str) -> str:
    if declared:
        return declared[:256]
    if isinstance(serialized, dict):
        value = serialized.get("name")
        if isinstance(value, str) and value:
            return value[:256]
        identifier = serialized.get("id")
        if isinstance(identifier, list) and identifier and isinstance(identifier[-1], str):
            return identifier[-1][:256]
    return fallback
