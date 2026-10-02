"""Benchmark-plugin framework: registry, loaders, metrics, runner (no data/models)."""
from __future__ import annotations

import json

from app.evidence.eval.benchmark_eval import _stub_scorer, run
from app.evidence.eval.plugins import EvalItem, available, get_plugin
from app.evidence.eval.plugins.metrics import evaluate


def test_all_four_benchmarks_registered():
    assert {"ragtruth", "tofueval", "hallumix", "verigray"} <= set(available())


def test_metrics_math():
    # gold faithful, pred faithful. halluc = positive class (not faithful).
    gold = [True, True, False, False]
    pred = [True, False, False, True]   # 1 correct faithful, 1 correct halluc
    r = evaluate(gold, pred)
    assert r.n == 4 and r.accuracy == 0.5
    # halluc: tp=1 (idx2), fp=1 (idx3 gold faithful pred halluc), fn=1 (idx1) -> P=R=F=0.5
    assert abs(r.halluc_f1 - 0.5) < 1e-9


def test_auroc_separable():
    r = evaluate([True, True, False, False], [True, True, False, False],
                 p_faithful=[0.9, 0.8, 0.2, 0.1])
    assert r.auroc == 1.0


def test_run_excludes_gray_zone_and_scores():
    items = [
        EvalItem("1", "the market grew 40 percent", ["the market grew 40 percent in 2026"], gold=True),
        EvalItem("2", "aliens built the pyramids", ["the market grew 40 percent in 2026"], gold=False),
        EvalItem("3", "ambiguous claim here", ["some context"], gold=False, gold_abstain=True),
    ]
    out = run(items, _stub_scorer())
    assert out["graded"] == 2 and out["gray_zone"] == 1
    # stub: item1 overlaps context (faithful), item2 does not (hallucinated) -> both correct
    assert out["report"].accuracy == 1.0


def test_loaders_require_data_dir():
    for name in ("ragtruth", "tofueval", "hallumix", "verigray"):
        try:
            get_plugin(name).load()
            assert False, f"{name} should require data_dir"
        except FileNotFoundError:
            pass


def test_ragtruth_parses_synthetic(tmp_path):
    (tmp_path / "source_info.jsonl").write_text(
        json.dumps({"source_id": "s1", "task_type": "QA", "source_info": "Paris is the capital of France."}) + "\n",
        encoding="utf-8")
    (tmp_path / "response.jsonl").write_text(
        json.dumps({"id": "r1", "source_id": "s1", "model": "m", "response": "Paris is the capital.", "labels": []}) + "\n"
        + json.dumps({"id": "r2", "source_id": "s1", "model": "m", "response": "Berlin is the capital.",
                      "labels": [{"start": 0}]}) + "\n",
        encoding="utf-8")
    items = {it.id: it for it in get_plugin("ragtruth").load(data_dir=str(tmp_path))}
    assert items["r1"].gold is True and items["r2"].gold is False
    assert "Paris" in items["r1"].context[0]


def test_tofueval_parses_synthetic(tmp_path):
    (tmp_path / "x.jsonl").write_text(
        json.dumps({"document": "The meeting approved the budget.", "sentence": "The budget was approved.",
                    "label": "factual"}) + "\n"
        + json.dumps({"document": "The meeting approved the budget.", "sentence": "The budget was rejected.",
                      "label": "not_factual"}) + "\n",
        encoding="utf-8")
    golds = sorted(it.gold for it in get_plugin("tofueval").load(data_dir=str(tmp_path)))
    assert golds == [False, True]
