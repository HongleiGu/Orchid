"""Template capability requirements and user attestations (OR-40).

The property under test is that every path fails closed. A requirement nobody
understands, an attestation missing from the catalog, a record for superseded
wording — each leaves the template unrunnable. A gate that exists because a
regulator might ask must not treat "I cannot tell" as "permitted".

The database paths are exercised against a real Postgres; what is covered here
is the resolution logic and the catalog, where a wrong answer is silent.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.attestations.registry import (
    Attestation,
    attestation_registry,
    load_attestations,
)
from app.attestations.service import (
    AttestationError,
    accept,
    is_satisfied,
    unmet_requirements,
)
from app.db.models.attestation import UserAttestation


@pytest.fixture(autouse=True)
def _isolate_registry():
    attestation_registry.clear()
    yield
    attestation_registry.clear()


TEXT = "本人确认知悉相关风险。"


def _register(**kwargs) -> Attestation:
    base = dict(id="securities_advisory", title="确认", text=TEXT, version="1")
    base.update(kwargs)
    item = Attestation(**base)
    attestation_registry.register(item)
    return item


def _record(item: Attestation, **overrides) -> UserAttestation:
    fields = dict(
        id="01REC", user_id="user-1", attestation_id=item.id,
        version=item.version, text_sha256=item.content_hash,
        source="api", accepted_at=datetime.now(timezone.utc), withdrawn_at=None,
    )
    fields.update(overrides)
    return UserAttestation(**fields)


class _Session:
    """Returns a fixed set of rows for the one query the service makes."""

    def __init__(self, rows: list[UserAttestation] | None = None):
        self._rows = rows or []

    async def execute(self, *_args, **_kwargs):
        rows = self._rows

        class _Result:
            def scalars(self):
                class _Scalars:
                    def all(self_inner):
                        # The service orders by accepted_at desc; mimic that so
                        # the "newest wins" logic is genuinely exercised.
                        return sorted(rows, key=lambda r: r.accepted_at, reverse=True)
                return _Scalars()
        return _Result()


# ── The catalog ───────────────────────────────────────────────────────────────

def test_requirement_string_is_derived_from_the_id():
    """Templates name requirements as "attestation:<id>"; nothing restates it."""
    assert _register().requirement == "attestation:securities_advisory"


def test_content_hash_tracks_the_text():
    a = _register()
    b = Attestation(id="x", title="t", text=TEXT)
    assert a.content_hash == b.content_hash
    assert a.content_hash != Attestation(id="x", title="t", text=TEXT + " ").content_hash


def test_shipped_catalog_loads():
    assert load_attestations() >= 1
    item = attestation_registry.get("securities_advisory")
    assert item is not None and item.text and item.version


def test_a_missing_catalog_is_not_an_error(tmp_path):
    assert load_attestations(tmp_path / "absent.json") == 0


def test_an_unreadable_catalog_does_not_crash_startup(tmp_path):
    bad = tmp_path / "a.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_attestations(bad) == 0


def test_a_malformed_entry_is_skipped_and_the_rest_load(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps({"attestations": [
        {"id": "no-text-so-invalid"},
        {"id": "good", "title": "T", "text": "x"},
    ]}), encoding="utf-8")
    assert load_attestations(path) == 1
    assert attestation_registry.ids() == ["good"]


async def test_a_catalog_that_failed_to_load_leaves_templates_locked(tmp_path):
    """Not an availability fallback: if the text cannot be loaded, nobody can
    have agreed to it, so the gate stays shut."""
    load_attestations(tmp_path / "absent.json")
    assert await unmet_requirements(
        _Session(), "user-1", ["attestation:securities_advisory"]
    ) == ["attestation:securities_advisory"]


# ── Requirement resolution ────────────────────────────────────────────────────

async def test_no_requirements_means_nothing_to_meet():
    assert await unmet_requirements(_Session(), "user-1", []) == []


async def test_a_held_attestation_satisfies_its_requirement():
    item = _register()
    session = _Session([_record(item)])
    assert await unmet_requirements(session, "user-1", [item.requirement]) == []
    assert await is_satisfied(session, "user-1", item.id) is True


async def test_no_record_means_unmet():
    item = _register()
    assert await unmet_requirements(_Session(), "user-1", [item.requirement]) == [
        item.requirement
    ]


async def test_an_unknown_requirement_scheme_fails_closed():
    """A typo in a template's `requires` must lock the template, not open it."""
    _register()
    unmet = await unmet_requirements(_Session(), "user-1", ["attestaton:typo"])
    assert unmet == ["attestaton:typo"]


async def test_a_requirement_naming_a_missing_attestation_fails_closed():
    _register()
    assert await unmet_requirements(
        _Session(), "user-1", ["attestation:never_defined"]
    ) == ["attestation:never_defined"]


async def test_a_bare_scheme_with_no_id_fails_closed():
    assert await unmet_requirements(_Session(), "user-1", ["attestation:"]) == [
        "attestation:"
    ]


async def test_every_unmet_requirement_is_reported_not_just_the_first():
    """The UI has to be able to prompt for all of them at once."""
    _register()
    unmet = await unmet_requirements(
        _Session(), "user-1", ["attestation:securities_advisory", "attestation:other"]
    )
    assert unmet == ["attestation:securities_advisory", "attestation:other"]


# ── Staleness ─────────────────────────────────────────────────────────────────

async def test_a_version_bump_invalidates_prior_acceptance():
    """Consent is to a wording. New wording, new consent."""
    old = _register(version="1")
    stale = _record(old)
    _register(version="2", text=TEXT + " 补充条款。")

    assert await unmet_requirements(
        _Session([stale]), "user-1", ["attestation:securities_advisory"]
    ) == ["attestation:securities_advisory"]


async def test_text_edited_without_a_version_bump_is_treated_as_stale(caplog):
    """The case nobody intends. It must not silently keep old consent alive."""
    item = _register(version="1")
    record = _record(item, text_sha256="0" * 64)

    with caplog.at_level("ERROR"):
        unmet = await unmet_requirements(
            _Session([record]), "user-1", [item.requirement]
        )

    assert unmet == [item.requirement]
    assert "without a version bump" in caplog.text


async def test_the_newest_record_wins():
    """Re-accepting after a version bump must not be masked by the old row."""
    item = _register(version="2")
    now = datetime.now(timezone.utc)
    old = _record(item, id="01OLD", version="1", text_sha256="0" * 64,
                  accepted_at=now - timedelta(days=30))
    new = _record(item, id="01NEW", accepted_at=now)

    assert await unmet_requirements(
        _Session([old, new]), "user-1", [item.requirement]
    ) == []


# ── Anonymous callers ─────────────────────────────────────────────────────────

async def test_a_static_deployment_key_is_exempt():
    """It is an operator credential, not a user credential: there is no user row
    to hold a record, and the operator is the licensee. Matches how plans treat
    an anonymous caller — and is why a multi-tenant deployment must issue
    per-user keys rather than sharing the deployment key."""
    item = _register()
    assert await unmet_requirements(_Session(), None, [item.requirement]) == []


async def test_but_an_anonymous_caller_holds_no_attestation():
    """Exempt from the gate is not the same as having agreed to something."""
    item = _register()
    assert await is_satisfied(_Session(), None, item.id) is False


# ── Accepting ─────────────────────────────────────────────────────────────────

class _WriteSession(_Session):
    def __init__(self):
        super().__init__()
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


async def test_accept_records_the_version_and_hash_actually_agreed_to():
    item = _register()
    db = _WriteSession()

    record = await accept(db, "user-1", item.id, version="1")

    assert record.version == "1"
    assert record.text_sha256 == item.content_hash
    assert record.source == "api"
    assert db.added == [record]


async def test_accept_refuses_a_version_the_catalog_has_moved_past():
    """The text changed between the page rendering and the button being pressed,
    so what the user read is not what is current. Recording that as consent to
    the current text would put a falsehood in the record."""
    item = _register(version="2")
    with pytest.raises(AttestationError, match="version 2"):
        await accept(_WriteSession(), "user-1", item.id, version="1")


async def test_accept_refuses_an_unknown_attestation():
    with pytest.raises(AttestationError, match="Unknown attestation"):
        await accept(_WriteSession(), "user-1", "not_a_thing", version="1")


# ── The shipped template ──────────────────────────────────────────────────────

def test_the_market_brief_declares_the_securities_attestation():
    """The 选股 node gives buy/sell calls, so the template is gated rather than
    removed — which is the point of OR-40."""
    from app.templates.registry import load_templates, template_registry

    template_registry.clear()
    load_templates()
    template = template_registry.get("china-market-daily-brief")
    assert template is not None
    assert "attestation:securities_advisory" in template.requires


def test_requirements_are_visible_to_clients_but_the_pipeline_is_not():
    """A UI must be able to say why a template is locked; it must still never
    receive the workflow."""
    from app.templates.registry import Template

    dumped = Template(
        id="t", name="T", requires=["attestation:x"], pipeline={"secret": 1}
    ).model_dump()
    assert dumped["requires"] == ["attestation:x"]
    assert "pipeline" not in dumped


# ── Profile allowlist ─────────────────────────────────────────────────────────

def test_the_run_only_profile_permits_reading_and_accepting():
    from app.auth.profile import is_request_permitted

    assert is_request_permitted("GET", "/api/v1/attestations")
    assert is_request_permitted("POST", "/api/v1/attestations/securities_advisory/accept")
    assert is_request_permitted("POST", "/api/v1/attestations/securities_advisory/withdraw")


def test_the_run_only_profile_still_refuses_editing_the_text():
    """The wording is config and ships with the release. Nothing may write it."""
    from app.auth.profile import is_request_permitted

    assert not is_request_permitted("POST", "/api/v1/attestations")
    assert not is_request_permitted("PUT", "/api/v1/attestations/securities_advisory")
    assert not is_request_permitted("DELETE", "/api/v1/attestations/securities_advisory")
    assert not is_request_permitted("GET", "/api/v1/attestations/securities_advisory/edit")
