"""Behavioural tests for `connection_panel` pure helpers.

The Streamlit widget calls themselves are smoke-tested via the help-text
guard in `test_ui_config_form_help.py`; here we exercise the *logic*
that lives behind those widgets — the session-state plumbing, the AMP
auto-connect path, and the collection / cluster id refresh helpers.

We swap the imported `st` module on `connection_panel` for a tiny
stub object whose only contract is a dict-like `session_state` — that
matches the surface area we actually touch from these helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from multihop_eval.clients.amp import AmpEnv
from multihop_eval.clients.arango_gateway import CollectionInfo
from multihop_eval.ui.components import connection_panel
from multihop_eval.ui.components.connection_panel import (
    STATUS_CONNECTED_AMP,
    STATUS_CONNECTED_MANUAL,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    get_live_collections,
    get_live_gateway,
    is_connected,
    refresh_cluster_ids,
    refresh_collections,
)
from multihop_eval.ui.state import (
    KEY_ARANGO_CLUSTER_IDS,
    KEY_ARANGO_COLLECTIONS,
    KEY_ARANGO_CONN_ERROR,
    KEY_ARANGO_CONN_STATUS,
    KEY_ARANGO_DB,
    KEY_ARANGO_DB_LIST,
    KEY_ARANGO_GATEWAY,
    KEY_ARANGO_LAST_TESTED,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _SessionState(dict):
    """Dict-shaped stand-in for `st.session_state` (supports `.get()`)."""


@dataclass
class _FakeStreamlitStub:
    """Minimal replacement for `streamlit` inside `connection_panel`.

    Only `session_state` is consumed by the pure helpers under test;
    the widget-emitting code paths are not exercised here (they're
    covered by the help-text/ast tests).
    """

    session_state: _SessionState = field(default_factory=_SessionState)


@pytest.fixture
def st_stub(monkeypatch) -> _FakeStreamlitStub:
    stub = _FakeStreamlitStub()
    monkeypatch.setattr(connection_panel, "st", stub)
    return stub


@dataclass
class _FakeGateway:
    """Just enough of `ArangoGateway` for the panel helpers."""

    cluster_ids: list[str] = field(default_factory=list)
    collections_to_return: list[CollectionInfo] = field(default_factory=list)
    raise_on_collections: bool = False
    config: Any = field(default_factory=lambda: SimpleNamespace(db="db_x"))

    def list_collections(self) -> list[CollectionInfo]:
        if self.raise_on_collections:
            raise RuntimeError("listing exploded")
        return list(self.collections_to_return)

    def list_cluster_ids(self, name: str) -> list[str]:
        self.last_cluster_request = name  # type: ignore[attr-defined]
        return list(self.cluster_ids)


# ---------------------------------------------------------------------------
# is_connected / get_live_gateway
# ---------------------------------------------------------------------------


def test_is_connected_true_for_amp_status(st_stub):
    st_stub.session_state[KEY_ARANGO_CONN_STATUS] = STATUS_CONNECTED_AMP
    assert is_connected() is True


def test_is_connected_true_for_manual_status(st_stub):
    st_stub.session_state[KEY_ARANGO_CONN_STATUS] = STATUS_CONNECTED_MANUAL
    assert is_connected() is True


def test_is_connected_false_for_disconnected(st_stub):
    st_stub.session_state[KEY_ARANGO_CONN_STATUS] = STATUS_DISCONNECTED
    assert is_connected() is False


def test_is_connected_false_for_error(st_stub):
    st_stub.session_state[KEY_ARANGO_CONN_STATUS] = STATUS_ERROR
    assert is_connected() is False


def test_is_connected_false_when_missing_status_key(st_stub):
    assert is_connected() is False


def test_get_live_gateway_returns_stored_value(st_stub):
    gw = _FakeGateway()
    st_stub.session_state[KEY_ARANGO_GATEWAY] = gw
    assert get_live_gateway() is gw


def test_get_live_gateway_returns_none_when_missing(st_stub):
    assert get_live_gateway() is None


# ---------------------------------------------------------------------------
# refresh_collections / refresh_cluster_ids
# ---------------------------------------------------------------------------


def test_refresh_collections_caches_listing_on_session_state(st_stub):
    gw = _FakeGateway(
        collections_to_return=[
            CollectionInfo(name="a", doc_count=3, kind="document", system=False),
            CollectionInfo(name="b", doc_count=0, kind="edge", system=False),
        ]
    )
    out = refresh_collections(gw)  # type: ignore[arg-type]
    assert [c.name for c in out] == ["a", "b"]
    cached = st_stub.session_state[KEY_ARANGO_COLLECTIONS]
    assert [c.name for c in cached] == ["a", "b"]


def test_refresh_collections_returns_empty_on_error(st_stub):
    gw = _FakeGateway(raise_on_collections=True)
    out = refresh_collections(gw)  # type: ignore[arg-type]
    assert out == []
    assert st_stub.session_state[KEY_ARANGO_COLLECTIONS] == []


def test_get_live_collections_returns_empty_when_no_cache(st_stub):
    assert get_live_collections() == []


def test_get_live_collections_returns_cached_listing(st_stub):
    listing = [CollectionInfo(name="x", doc_count=1, kind="document", system=False)]
    st_stub.session_state[KEY_ARANGO_COLLECTIONS] = listing
    assert get_live_collections() == listing


def test_refresh_cluster_ids_caches_and_forwards_collection_name(st_stub):
    gw = _FakeGateway(cluster_ids=["cluster_0", "cluster_1"])
    out = refresh_cluster_ids(gw, "dom")  # type: ignore[arg-type]
    assert out == ["cluster_0", "cluster_1"]
    assert st_stub.session_state[KEY_ARANGO_CLUSTER_IDS] == ["cluster_0", "cluster_1"]
    assert gw.last_cluster_request == "dom"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _set_status / _disconnect (private but worth exercising directly)
# ---------------------------------------------------------------------------


def test_set_status_clears_error_when_omitted(st_stub):
    st_stub.session_state[KEY_ARANGO_CONN_ERROR] = "boom"
    connection_panel._set_status(STATUS_CONNECTED_AMP)
    assert st_stub.session_state[KEY_ARANGO_CONN_STATUS] == STATUS_CONNECTED_AMP
    assert st_stub.session_state[KEY_ARANGO_CONN_ERROR] is None


def test_set_status_records_error(st_stub):
    connection_panel._set_status(STATUS_ERROR, error="bad creds")
    assert st_stub.session_state[KEY_ARANGO_CONN_STATUS] == STATUS_ERROR
    assert st_stub.session_state[KEY_ARANGO_CONN_ERROR] == "bad creds"


def test_disconnect_clears_gateway_listings_and_status(st_stub):
    st_stub.session_state[KEY_ARANGO_GATEWAY] = _FakeGateway()
    st_stub.session_state[KEY_ARANGO_DB] = "x"
    st_stub.session_state[KEY_ARANGO_COLLECTIONS] = ["a"]
    st_stub.session_state[KEY_ARANGO_CLUSTER_IDS] = ["c0"]
    st_stub.session_state[KEY_ARANGO_DB_LIST] = ["x", "_system"]
    st_stub.session_state[KEY_ARANGO_CONN_STATUS] = STATUS_CONNECTED_MANUAL

    connection_panel._disconnect()

    assert st_stub.session_state[KEY_ARANGO_GATEWAY] is None
    assert st_stub.session_state[KEY_ARANGO_DB] is None
    assert st_stub.session_state[KEY_ARANGO_COLLECTIONS] is None
    assert st_stub.session_state[KEY_ARANGO_CLUSTER_IDS] is None
    assert st_stub.session_state[KEY_ARANGO_DB_LIST] is None
    assert st_stub.session_state[KEY_ARANGO_CONN_STATUS] == STATUS_DISCONNECTED


def test_stash_gateway_records_status_db_and_timestamp(st_stub):
    gw = _FakeGateway()
    connection_panel._stash_gateway(gw, status=STATUS_CONNECTED_AMP, db="acme")  # type: ignore[arg-type]
    assert st_stub.session_state[KEY_ARANGO_GATEWAY] is gw
    assert st_stub.session_state[KEY_ARANGO_DB] == "acme"
    assert st_stub.session_state[KEY_ARANGO_CONN_STATUS] == STATUS_CONNECTED_AMP
    # Timestamp is an ISO-formatted string.
    assert isinstance(st_stub.session_state[KEY_ARANGO_LAST_TESTED], str)


# ---------------------------------------------------------------------------
# AMP-specific glue
# ---------------------------------------------------------------------------


def test_connect_amp_builds_jwt_config_and_pings(monkeypatch, st_stub, tmp_path):
    """`_connect_amp` should construct a JWT-mode gateway and stash it."""
    token_path = tmp_path / "token"
    token_path.write_text("jwt-abc", encoding="utf-8")
    amp = AmpEnv(endpoint="https://x.example.com:8529", token_path=str(token_path))

    pings: list[bool] = []

    class _PingableGateway:
        def __init__(self, cfg):
            self.config = cfg

        def ping(self) -> bool:
            pings.append(True)
            return True

    monkeypatch.setattr(connection_panel, "ArangoGateway", _PingableGateway)
    gw = connection_panel._connect_amp(amp, db="_system")
    assert gw is not None
    assert pings == [True]
    assert st_stub.session_state.get(KEY_ARANGO_CONN_ERROR) in (None,)


def test_connect_amp_surfaces_ping_failure(monkeypatch, st_stub, tmp_path):
    token_path = tmp_path / "token"
    token_path.write_text("jwt-abc", encoding="utf-8")
    amp = AmpEnv(endpoint="https://x.example.com:8529", token_path=str(token_path))

    class _FailingGateway:
        def __init__(self, cfg):
            self.config = cfg

        def ping(self) -> bool:
            return False

    monkeypatch.setattr(connection_panel, "ArangoGateway", _FailingGateway)
    assert connection_panel._connect_amp(amp, db="_system") is None
    assert st_stub.session_state[KEY_ARANGO_CONN_STATUS] == STATUS_ERROR
    assert "Ping failed" in (st_stub.session_state[KEY_ARANGO_CONN_ERROR] or "")


def test_connect_amp_surfaces_construction_error(monkeypatch, st_stub, tmp_path):
    token_path = tmp_path / "token"
    token_path.write_text("jwt-abc", encoding="utf-8")
    amp = AmpEnv(endpoint="https://x.example.com:8529", token_path=str(token_path))

    def _raise(*_a, **_k):  # noqa: ANN002,ANN003
        raise RuntimeError("nope")

    monkeypatch.setattr(connection_panel, "ArangoGateway", _raise)
    assert connection_panel._connect_amp(amp, db="_system") is None
    assert st_stub.session_state[KEY_ARANGO_CONN_STATUS] == STATUS_ERROR
    assert "nope" in (st_stub.session_state[KEY_ARANGO_CONN_ERROR] or "")


def test_refresh_db_list_falls_back_to_current_db_when_empty(st_stub):
    gw = _FakeGateway(config=SimpleNamespace(db="only_one"))

    # Stub list_databases on the fake to return an empty list.
    def _empty() -> list[str]:
        return []

    gw.list_databases = _empty  # type: ignore[attr-defined]
    dbs = connection_panel._refresh_db_list(gw)  # type: ignore[arg-type]
    assert dbs == ["only_one"]
    assert st_stub.session_state[KEY_ARANGO_DB_LIST] == ["only_one"]


def test_refresh_db_list_propagates_listing(st_stub):
    gw = _FakeGateway()

    def _list() -> list[str]:
        return ["_system", "acme", "blanket"]

    gw.list_databases = _list  # type: ignore[attr-defined]
    out = connection_panel._refresh_db_list(gw)  # type: ignore[arg-type]
    assert out == ["_system", "acme", "blanket"]
    assert st_stub.session_state[KEY_ARANGO_DB_LIST] == out
