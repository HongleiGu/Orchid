"""Vault API: path safety (OR-45) and file access (OR-46).

The traversal cases are sent as raw, percent-encoded HTTP paths rather than
through the helper, because that is how the bug was reachable: %2e%2e is not
normalised away by the client, and Starlette decodes it into a path parameter
of "..".
"""
from __future__ import annotations

import os
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import vault as vault_module


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    project = root / "market-daily-brief"
    project.mkdir(parents=True)
    (project / "2026-09-18-01ABCDEF.md").write_text("# 每日简报\n\n| 指数 | 涨跌 |\n|---|---|\n| 上证 | +0.3% |\n", encoding="utf-8")
    (project / "facts.pdf").write_bytes(b"%PDF-1.7\n%binary\x00\x01")
    (project / "paper.tex").write_text("\\documentclass{article}", encoding="utf-8")
    (project / "每日简报.md").write_text("中文文件名", encoding="utf-8")
    (project / "assets").mkdir()                      # subdirectory: not listed
    (project / ".hidden.md").write_text("no")          # hidden: not listed
    (root / ".orchid").mkdir()                         # hidden project: not listed
    (root / ".orchid" / "index.json").write_text("{}")

    # A file outside the vault that traversal would reach.
    (tmp_path / "secret.txt").write_text("outside the vault")

    monkeypatch.setattr(vault_module, "VAULT_DIR", root)
    return root


@pytest.fixture
def client(vault):
    app = FastAPI()
    app.include_router(vault_module.router, prefix="/api/v1")
    return TestClient(app)


def raw_get(client: TestClient, path: str):
    """Send the path exactly as written — no client-side normalisation."""
    return client.get(path)


# ── traversal (OR-45) ────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/v1/vault/projects/%2e%2e/secret.txt",
    "/api/v1/vault/projects/%2E%2E/secret.txt",
    "/api/v1/vault/projects/..%2fvault/secret.txt",
    "/api/v1/vault/projects/%2e%2e/secret.txt/download",
    "/api/v1/vault/projects/market-daily-brief/%2e%2e",
    "/api/v1/vault/projects/market-daily-brief/..%5c..%5csecret.txt",
    "/api/v1/vault/projects/.orchid/index.json",
    "/api/v1/vault/projects/%2e%2e",
])
def test_nothing_outside_a_project_is_reachable(client, path):
    response = raw_get(client, path)
    assert response.status_code in (400, 404), f"{path} -> {response.status_code}"
    assert "outside the vault" not in response.text


def test_delete_cannot_escape_the_vault(client, vault):
    response = client.delete("/api/v1/vault/projects/%2e%2e/secret.txt")
    assert response.status_code in (400, 404)
    assert (vault.parent / "secret.txt").exists(), "a file outside the vault was deleted"


def test_a_symlink_planted_in_the_vault_does_not_lead_out(client, vault):
    link = vault / "market-daily-brief" / "escape.txt"
    try:
        os.symlink(vault.parent / "secret.txt", link)
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks needs privileges on this platform")
    assert client.get("/api/v1/vault/projects/market-daily-brief/escape.txt").status_code in (400, 404)
    assert client.get("/api/v1/vault/projects/market-daily-brief/escape.txt/download").status_code in (400, 404)
    names = [f["name"] for f in client.get("/api/v1/vault/projects/market-daily-brief").json()["data"]]
    assert "escape.txt" not in names


@pytest.mark.parametrize("name", ["..", ".", "", ".env", "a/b", "a\\b", "x\x00y"])
def test_segment_check_rejects_non_names(name):
    with pytest.raises(Exception) as info:
        vault_module._check_segment(name)
    assert getattr(info.value, "status_code", None) == 400


# ── listing (OR-46) ──────────────────────────────────────────────────────────

def test_projects_exclude_hidden_directories(client):
    names = [p["name"] for p in client.get("/api/v1/vault/projects").json()["data"]]
    assert names == ["market-daily-brief"]


def test_every_file_type_is_listed_not_only_markdown(client):
    files = {f["name"]: f for f in client.get("/api/v1/vault/projects/market-daily-brief").json()["data"]}
    assert set(files) == {"2026-09-18-01ABCDEF.md", "facts.pdf", "paper.tex", "每日简报.md"}
    assert files["facts.pdf"]["is_text"] is False
    assert files["facts.pdf"]["media_type"] == "application/pdf"
    assert files["2026-09-18-01ABCDEF.md"]["media_type"] == "text/markdown"
    assert files["paper.tex"]["is_text"] is True


def test_modified_times_carry_a_timezone(client):
    files = client.get("/api/v1/vault/projects/market-daily-brief").json()["data"]
    assert all(f["modified_at"].endswith("+00:00") for f in files)


def test_project_totals_count_all_files(client):
    project = client.get("/api/v1/vault/projects").json()["data"][0]
    assert project["file_count"] == 4
    assert project["modified_at"] is not None


# ── reading and downloading ──────────────────────────────────────────────────

def test_markdown_reads_inline(client):
    body = client.get("/api/v1/vault/projects/market-daily-brief/2026-09-18-01ABCDEF.md").json()["data"]
    assert body["content"].startswith("# 每日简报")
    assert body["media_type"] == "text/markdown"


def test_binary_files_are_refused_inline_and_served_as_downloads(client):
    assert client.get("/api/v1/vault/projects/market-daily-brief/facts.pdf").status_code == 415

    response = client.get("/api/v1/vault/projects/market-daily-brief/facts.pdf/download")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.7\n%binary\x00\x01"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in response.headers["cache-control"]


def test_download_keeps_a_chinese_filename(client):
    response = client.get("/api/v1/vault/projects/market-daily-brief/%E6%AF%8F%E6%97%A5%E7%AE%80%E6%8A%A5.md/download")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    encoded = disposition.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == "每日简报.md"
    # The plain filename= fallback must stay ASCII, or old clients choke.
    plain = disposition.split('filename="', 1)[1].split('"', 1)[0]
    assert plain.isascii()


def test_oversized_text_is_download_only(client, vault, monkeypatch):
    monkeypatch.setattr(vault_module, "MAX_INLINE_BYTES", 10)
    assert client.get("/api/v1/vault/projects/market-daily-brief/paper.tex").status_code == 413
    assert client.get("/api/v1/vault/projects/market-daily-brief/paper.tex/download").status_code == 200


def test_missing_things_are_404(client):
    assert client.get("/api/v1/vault/projects/nope").status_code == 404
    assert client.get("/api/v1/vault/projects/market-daily-brief/nope.md").status_code == 404
    assert client.get("/api/v1/vault/projects/market-daily-brief/assets").status_code == 404


def test_delete_removes_a_vault_file(client, vault):
    assert client.delete("/api/v1/vault/projects/market-daily-brief/paper.tex").status_code == 204
    assert not (vault / "market-daily-brief" / "paper.tex").exists()


def test_a_missing_vault_lists_nothing(client, vault, monkeypatch):
    monkeypatch.setattr(vault_module, "VAULT_DIR", vault / "does-not-exist")
    assert client.get("/api/v1/vault/projects").json()["data"] == []
