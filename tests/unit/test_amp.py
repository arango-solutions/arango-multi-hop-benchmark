"""Tests for `multihop_eval.clients.amp`."""

from __future__ import annotations

from pathlib import Path

import pytest

from multihop_eval.clients.amp import (
    AmpEnv,
    detect_amp,
    read_token,
)


def _write_token(tmp_path: Path, value: str = "jwt-abc") -> Path:
    p = tmp_path / "token"
    p.write_text(value, encoding="utf-8")
    return p


def test_detect_amp_returns_none_when_no_env():
    assert detect_amp(environ={}) is None


def test_detect_amp_returns_env_with_primary_endpoint(tmp_path):
    token = _write_token(tmp_path)
    env = detect_amp(
        environ={
            "ARANGO_DEPLOYMENT_ENDPOINT": "https://deployment.default.svc:8529/",
            "ARANGO_TOKEN": str(token),
        }
    )
    assert env is not None
    # Trailing slash is stripped to match ArangoConfig's host normalisation.
    assert env.endpoint == "https://deployment.default.svc:8529"
    assert env.token_path == str(token)
    assert env.ca_path is None
    assert env.deployment_name is None


def test_detect_amp_accepts_alias_endpoint(tmp_path):
    token = _write_token(tmp_path)
    env = detect_amp(
        environ={
            "ARANGODB_ENDPOINT": "https://alias.example.com:8529",
            "ARANGO_TOKEN": str(token),
        }
    )
    assert env is not None
    assert env.endpoint == "https://alias.example.com:8529"


def test_detect_amp_prefers_primary_over_alias(tmp_path):
    token = _write_token(tmp_path)
    env = detect_amp(
        environ={
            "ARANGO_DEPLOYMENT_ENDPOINT": "https://primary.example.com:8529",
            "ARANGODB_ENDPOINT": "https://alias.example.com:8529",
            "ARANGO_TOKEN": str(token),
        }
    )
    assert env is not None
    assert env.endpoint == "https://primary.example.com:8529"


def test_detect_amp_returns_none_when_token_file_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert detect_amp(
        environ={
            "ARANGO_DEPLOYMENT_ENDPOINT": "https://x.example.com:8529",
            "ARANGO_TOKEN": str(missing),
        }
    ) is None


def test_detect_amp_returns_none_when_token_env_unset(tmp_path):
    assert detect_amp(
        environ={"ARANGO_DEPLOYMENT_ENDPOINT": "https://x.example.com:8529"}
    ) is None


def test_detect_amp_returns_none_when_endpoint_unset(tmp_path):
    token = _write_token(tmp_path)
    assert detect_amp(environ={"ARANGO_TOKEN": str(token)}) is None


def test_detect_amp_includes_ca_and_deployment_name(tmp_path):
    token = _write_token(tmp_path)
    ca = tmp_path / "ca.pem"
    ca.write_text("---ca---", encoding="utf-8")
    env = detect_amp(
        environ={
            "ARANGO_DEPLOYMENT_ENDPOINT": "https://x.example.com:8529",
            "ARANGO_TOKEN": str(token),
            "ARANGO_DEPLOYMENT_CA": str(ca),
            "ARANGO_DEPLOYMENT_NAME": "my-deployment",
        }
    )
    assert env is not None
    assert env.ca_path == str(ca)
    assert env.deployment_name == "my-deployment"


def test_detect_amp_override_allows_unreadable_token(tmp_path):
    """AMP=true tolerates a missing token file (used for local debugging)."""
    missing = tmp_path / "missing-token"
    env = detect_amp(
        environ={
            "AMP": "true",
            "ARANGO_DEPLOYMENT_ENDPOINT": "https://x.example.com:8529",
            "ARANGO_TOKEN": str(missing),
        }
    )
    assert env is not None
    assert env.token_path == str(missing)


def test_detect_amp_override_still_requires_endpoint_and_token_envs():
    """AMP=true without endpoint/token env vars still bails out."""
    assert detect_amp(environ={"AMP": "true"}) is None
    assert detect_amp(
        environ={"AMP": "true", "ARANGO_DEPLOYMENT_ENDPOINT": "https://x:8529"}
    ) is None


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on", "TRUE", "Yes"])
def test_detect_amp_override_accepts_truthy_values(tmp_path, flag):
    env = detect_amp(
        environ={
            "AMP": flag,
            "ARANGO_DEPLOYMENT_ENDPOINT": "https://x.example.com:8529",
            "ARANGO_TOKEN": str(tmp_path / "missing"),
        }
    )
    assert env is not None


@pytest.mark.parametrize("flag", ["false", "0", "no", "", "off"])
def test_detect_amp_override_rejects_falsy_values(tmp_path, flag):
    """Falsy override + missing token → not AMP."""
    env = detect_amp(
        environ={
            "AMP": flag,
            "ARANGO_DEPLOYMENT_ENDPOINT": "https://x.example.com:8529",
            "ARANGO_TOKEN": str(tmp_path / "missing"),
        }
    )
    assert env is None


def test_read_token_strips_whitespace(tmp_path):
    p = _write_token(tmp_path, "  jwt-value-123  \n")
    assert read_token(str(p)) == "jwt-value-123"


def test_read_token_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_token(str(tmp_path / "nope"))


def test_read_token_raises_on_empty_file(tmp_path):
    p = _write_token(tmp_path, "   \n  ")
    with pytest.raises(ValueError):
        read_token(str(p))


def test_read_token_picks_up_rotated_value(tmp_path):
    """Simulate sidecar rotation: each read returns the latest content."""
    p = _write_token(tmp_path, "first")
    assert read_token(str(p)) == "first"
    p.write_text("second", encoding="utf-8")
    assert read_token(str(p)) == "second"


def test_amp_env_is_immutable(tmp_path):
    """Dataclass is frozen so callers can't mutate it mid-flight."""
    from dataclasses import FrozenInstanceError

    env = AmpEnv(endpoint="https://x:8529", token_path=str(tmp_path / "t"))
    with pytest.raises(FrozenInstanceError):
        env.endpoint = "other"  # type: ignore[misc]
