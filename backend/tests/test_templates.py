"""Template catalog (OR-34)."""
from __future__ import annotations

import json

import pytest

from app.templates.registry import (
    Template,
    TemplateRegistry,
    _derive_inputs,
    _load_pipeline,
    load_templates,
    template_registry,
)


# ── Input derivation ──────────────────────────────────────────────────────────

def test_inputs_come_from_the_entry_task_schema():
    """Derived, not restated: the executor reads task input_schema, so keeping a
    second copy in template metadata would drift."""
    pipeline = {"tasks": [{"input_schema": [
        {"name": "watchlist", "type": "array", "label": "观察名单", "default": ["600519"]},
        {"name": "horizon", "type": "string", "description": "持有周期"},
    ]}]}
    inputs = _derive_inputs(pipeline)

    assert [i.name for i in inputs] == ["watchlist", "horizon"]
    assert inputs[0].type == "array"
    assert inputs[0].label == "观察名单"
    assert inputs[0].default == ["600519"]


def test_an_input_without_a_default_is_required():
    """So a catalog form can mark it, since nothing declares `required` today."""
    inputs = _derive_inputs({"tasks": [{"input_schema": [
        {"name": "with_default", "default": "x"},
        {"name": "without_default"},
    ]}]})
    assert inputs[0].required is False
    assert inputs[1].required is True


def test_explicit_required_wins_over_the_default_heuristic():
    inputs = _derive_inputs({"tasks": [{"input_schema": [
        {"name": "a", "default": "x", "required": True},
    ]}]})
    assert inputs[0].required is True


def test_pipelines_without_tasks_or_schema_yield_no_inputs():
    assert _derive_inputs({}) == []
    assert _derive_inputs({"tasks": []}) == []
    assert _derive_inputs({"tasks": [{}]}) == []


def test_malformed_schema_entries_are_skipped_not_fatal():
    inputs = _derive_inputs({"tasks": [{"input_schema": [
        {"name": "good"}, "not-a-dict", {"no_name": 1},
    ]}]})
    assert [i.name for i in inputs] == ["good"]


# ── Loading ───────────────────────────────────────────────────────────────────

def test_inline_pipeline_is_used_directly():
    assert _load_pipeline({"pipeline": {"agents": [1]}}) == {"agents": [1]}


def test_a_template_needs_a_pipeline():
    with pytest.raises(ValueError, match="pipeline"):
        _load_pipeline({"name": "x"})


def test_missing_pipeline_file_names_what_it_tried():
    """A bare 'not found' sends someone hunting; the paths are the useful part."""
    with pytest.raises(FileNotFoundError, match="tried:"):
        _load_pipeline({"pipeline_file": "does/not/exist.json"})


def test_one_bad_file_does_not_take_down_the_catalog(tmp_path, caplog):
    """A malformed template must not make the whole product unavailable."""
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "good.json").write_text(json.dumps({
        "id": "good", "name": "Good", "pipeline": {"tasks": []},
    }), encoding="utf-8")

    template_registry.clear()
    assert load_templates(tmp_path) == 1
    assert template_registry.get("good") is not None
    assert "broken.json" in caplog.text


def test_missing_catalog_directory_is_not_an_error(tmp_path):
    template_registry.clear()
    assert load_templates(tmp_path / "nope") == 0


# ── The shipped template ──────────────────────────────────────────────────────

def test_the_china_brief_template_loads():
    template_registry.clear()
    load_templates()

    t = template_registry.get("china-market-daily-brief")
    assert t is not None
    assert t.category == "finance"
    assert len(t.pipeline.get("agents", [])) == 11
    assert {i.name for i in t.inputs} >= {"watchlist", "risk_appetite", "vault_project"}


# ── The pipeline must not leak ────────────────────────────────────────────────

def test_pipeline_is_excluded_from_serialisation():
    """The workflow is the product. `exclude=True` means it cannot escape through
    the API even if someone returns the model directly."""
    t = Template(id="x", name="X", pipeline={"agents": [{"system_prompt": "secret"}]})

    assert "pipeline" not in t.model_dump()
    assert "secret" not in t.model_dump_json()
    # ...while still being available in-process for instantiation (OR-33).
    assert t.pipeline["agents"][0]["system_prompt"] == "secret"


def test_registry_sorts_by_category_then_name():
    reg = TemplateRegistry()
    reg.register(Template(id="b", name="Beta", category="finance"))
    reg.register(Template(id="a", name="Alpha", category="research"))
    reg.register(Template(id="c", name="Alpha", category="finance"))
    assert [t.id for t in reg.all()] == ["c", "b", "a"]


# ── Input resolution for a run (OR-33) ────────────────────────────────────────

def _tpl(**inputs):
    from app.templates.registry import TemplateInput
    return Template(
        id="t", name="T",
        inputs=[TemplateInput(name=n, **spec) for n, spec in inputs.items()],
    )


def test_defaults_are_applied_when_not_provided():
    from app.api.v1.templates import _resolve_inputs
    t = _tpl(horizon={"default": "短线"}, lang={"default": "简体中文"})
    assert _resolve_inputs(t, {}) == {"horizon": "短线", "lang": "简体中文"}


def test_provided_values_override_defaults():
    from app.api.v1.templates import _resolve_inputs
    t = _tpl(horizon={"default": "短线"})
    assert _resolve_inputs(t, {"horizon": "中线"}) == {"horizon": "中线"}


def test_unknown_inputs_are_rejected_not_ignored():
    """A silently dropped typo yields a plausible but wrong report, which for
    this product is worse than an error."""
    from fastapi import HTTPException

    from app.api.v1.templates import _resolve_inputs
    t = _tpl(horizon={"default": "短线"})
    with pytest.raises(HTTPException) as exc:
        _resolve_inputs(t, {"horzon": "中线"})
    assert exc.value.status_code == 422
    assert "horzon" in str(exc.value.detail)
    assert "horizon" in str(exc.value.detail)      # names what was accepted


def test_missing_required_input_is_rejected():
    from fastapi import HTTPException

    from app.api.v1.templates import _resolve_inputs
    t = _tpl(ticker={"required": True})
    with pytest.raises(HTTPException) as exc:
        _resolve_inputs(t, {})
    assert exc.value.status_code == 422
    assert "ticker" in str(exc.value.detail)


def test_a_required_input_can_be_supplied():
    from app.api.v1.templates import _resolve_inputs
    t = _tpl(ticker={"required": True})
    assert _resolve_inputs(t, {"ticker": "600519"}) == {"ticker": "600519"}


def test_falsy_provided_values_survive():
    """`False` and `0` must not be lost to a truthiness check."""
    from app.api.v1.templates import _resolve_inputs
    t = _tpl(include_global={"type": "boolean", "default": True})
    assert _resolve_inputs(t, {"include_global": False}) == {"include_global": False}
