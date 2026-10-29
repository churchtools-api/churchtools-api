"""Runs every Python example of the documentation against recorded responses.

Reference examples get the recording of their operation; guide snippets get
the recording matching each request. Examples without a recording, uploads of
local files and snippets that contact a fixed server are only type-checked
(`mypy --strict tests/doc_examples.py`).
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import typing as _t
import warnings
from pathlib import Path

import pytest

import churchtools_rs as ct

import doc_examples
from replay import ROOT, ReplayServer, recorded

CATALOG = {e["op_id"]: e for e in json.loads((ROOT / "python" / "tests" / "live" / "operations.json").read_text())}
FIXED_SERVER = ("ct.Client(", "login_with_password")


@pytest.fixture(scope="module")
def server() -> _t.Iterator[ReplayServer]:
    s = ReplayServer()
    yield s
    s.close()


def run(example: _t.Callable[[ct.Client], None], client: ct.Client) -> None:
    # Examples of deprecated operations show the call anyway; the warning is tested elsewhere.
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        example(client)


@pytest.mark.parametrize("op_id", list(doc_examples.REFERENCE))
def test_reference_example(op_id: str, server: ReplayServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if recorded(op_id) is None:
        pytest.skip("no recorded response")
    if any(p["kind"] == "upload" for p in CATALOG[op_id]["params"]):
        pytest.skip("uploads a local file")
    monkeypatch.chdir(tmp_path)  # examples for downloads write files
    server.op = op_id
    try:
        run(doc_examples.REFERENCE[op_id], ct.Client(server.url, token="replay"))
    finally:
        server.op = None


@pytest.mark.parametrize("section", list(doc_examples.GUIDE))
def test_guide_example(section: str, server: ReplayServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    example = doc_examples.GUIDE[section]
    if any(marker in inspect.getsource(example) for marker in FIXED_SERVER):
        pytest.skip("contacts a fixed server")
    monkeypatch.setenv("CT_URL", server.url)
    monkeypatch.setenv("CT_TOKEN", "replay")
    monkeypatch.chdir(tmp_path)
    run(example, ct.Client(server.url, token="replay"))
