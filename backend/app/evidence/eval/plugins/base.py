"""Benchmark-plugin framework for evaluating the grounding checker.

Deliberately decoupled from the runtime: nothing in app.core or the evidence
verification path imports this package. A benchmark is a *plugin* that loads its
raw data and yields a common `EvalItem`; the runner (benchmark_eval.py) scores
items with any scorer (our grounding checker, plain NLI, an LLM judge, a stub)
and reports hallucination-detection metrics. New benchmarks = new plugins; the
runner and metrics never change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable


@dataclass
class EvalItem:
    """One (context, claim) pair with a gold faithfulness label — the common
    schema every benchmark maps into."""
    id: str
    claim: str                      # the statement/response to check
    context: list[str]              # grounding passages / source documents
    gold: bool                      # True = faithful / supported, False = hallucinated
    task: str = ""                  # qa | summarization | data2text | ...
    gold_abstain: bool = False      # True = annotated ambiguous/gray-zone (VeriGray)
    meta: dict = field(default_factory=dict)


@runtime_checkable
class BenchmarkPlugin(Protocol):
    name: str

    def load(self, data_dir: str | None = None, limit: int | None = None,
             seed: int = 0) -> list[EvalItem]:
        """Return EvalItems. `data_dir` points at the benchmark's local files
        (plugins document how to obtain them); `limit` subsamples deterministically."""
        ...


PLUGINS: dict[str, BenchmarkPlugin] = {}


def register(plugin_cls: type) -> type:
    """Class decorator: register a plugin instance under its `name`."""
    inst = plugin_cls()
    PLUGINS[inst.name] = inst
    return plugin_cls


def get_plugin(name: str) -> BenchmarkPlugin:
    if name not in PLUGINS:
        raise KeyError(f"unknown benchmark plugin {name!r}; available: {sorted(PLUGINS)}")
    return PLUGINS[name]


def available() -> list[str]:
    return sorted(PLUGINS)


# A scorer maps (claim, context_chunks) -> (predicted_faithful, confidence[, abstain]).
Scorer = Callable[[str, list[str]], tuple[bool, float]]
