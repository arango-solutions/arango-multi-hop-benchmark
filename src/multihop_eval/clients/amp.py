"""Arango Managed Platform (AMP) environment detection.

When the BYOC service is deployed to AMP with the kube-arangodb auth
sidecar enabled, the platform injects a small handful of env vars and
mounts a short-lived JWT into the pod. This module exposes a single
`detect_amp()` helper so the rest of the codebase can ask one question:

    >>> amp = detect_amp()
    >>> if amp is not None: ...  # we're inside AMP

The contract we rely on (per
https://arangodb.github.io/kube-arangodb/docs/integration-sidecar.html):

* `ARANGO_DEPLOYMENT_ENDPOINT` (alias `ARANGODB_ENDPOINT`) — the internal
  HTTPS endpoint of the ArangoDeployment (e.g. `https://deployment.default.svc:8529`).
* `ARANGO_TOKEN` — **path** to a JWT file. The file is rotated by the
  sidecar with a short TTL, so callers must re-read it on every connection
  (we expose `read_token` for exactly that).
* `ARANGO_DEPLOYMENT_CA` — optional path to the deployment's CA PEM.
* `ARANGO_DEPLOYMENT_NAME` — informational; surfaced in the UI status pill.

`AMP=true` (or `1`, `yes`) acts as an explicit override so developers can
exercise the AMP UI path against a non-AMP cluster.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_AMP_FLAG_TRUE = frozenset({"1", "true", "yes", "on"})

# Env var names we honour. Keep them in one place so tests can introspect.
ENV_AMP_FLAG = "AMP"
ENV_DEPLOYMENT_ENDPOINT_PRIMARY = "ARANGO_DEPLOYMENT_ENDPOINT"
ENV_DEPLOYMENT_ENDPOINT_ALIAS = "ARANGODB_ENDPOINT"
ENV_TOKEN_PATH = "ARANGO_TOKEN"
ENV_DEPLOYMENT_CA = "ARANGO_DEPLOYMENT_CA"
ENV_DEPLOYMENT_NAME = "ARANGO_DEPLOYMENT_NAME"


@dataclass(frozen=True)
class AmpEnv:
    """Snapshot of the AMP-injected environment.

    `token_path` is a **file path**, not the token itself — call
    `read_token(env.token_path)` whenever you need the current value so
    rotation is transparent.

    `endpoint` is the HTTPS URL to talk to (already validated to include a
    scheme). `ca_path` and `deployment_name` are both optional.
    """

    endpoint: str
    token_path: str
    ca_path: str | None = None
    deployment_name: str | None = None


def _amp_flag_set(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    raw = (env.get(ENV_AMP_FLAG) or "").strip().lower()
    return raw in _AMP_FLAG_TRUE


def _resolve_endpoint(environ: dict[str, str]) -> str | None:
    """Return the configured deployment endpoint, preferring the canonical name."""
    for key in (ENV_DEPLOYMENT_ENDPOINT_PRIMARY, ENV_DEPLOYMENT_ENDPOINT_ALIAS):
        value = (environ.get(key) or "").strip().rstrip("/")
        if value:
            return value
    return None


def detect_amp(environ: dict[str, str] | None = None) -> AmpEnv | None:
    """Return an `AmpEnv` if we look like we're running inside AMP, else None.

    Detection rules (per the user's "both" answer):

    1. If `ARANGO_DEPLOYMENT_ENDPOINT` (or its `ARANGODB_ENDPOINT` alias) is
       set AND the file at `ARANGO_TOKEN` exists and is readable, we treat
       this as AMP.
    2. If `AMP=true` is set we still require the endpoint + token-path env
       vars to be present (we can't fabricate them), but we tolerate a
       missing/unreadable token file — the caller will surface a clear
       error to the user when the gateway is built.

    `environ` lets tests inject a controlled environment without touching
    `os.environ`.
    """
    env = environ if environ is not None else os.environ
    flag_override = _amp_flag_set(env)

    endpoint = _resolve_endpoint(env)
    token_path = (env.get(ENV_TOKEN_PATH) or "").strip()
    ca_path = (env.get(ENV_DEPLOYMENT_CA) or "").strip() or None
    deployment_name = (env.get(ENV_DEPLOYMENT_NAME) or "").strip() or None

    if not endpoint or not token_path:
        if flag_override:
            log.warning(
                "AMP=true but %s and/or %s are missing — cannot auto-connect.",
                ENV_DEPLOYMENT_ENDPOINT_PRIMARY,
                ENV_TOKEN_PATH,
            )
        return None

    if not flag_override and not _token_file_readable(token_path):
        # Sidecar contract requires a readable token; without the override
        # we treat an unreadable token as "not AMP" so the manual form
        # stays available.
        log.info(
            "AMP endpoint env set but token file %r is not readable yet; "
            "skipping auto-connect.",
            token_path,
        )
        return None

    return AmpEnv(
        endpoint=endpoint,
        token_path=token_path,
        ca_path=ca_path,
        deployment_name=deployment_name,
    )


def _token_file_readable(path: str) -> bool:
    try:
        p = Path(path)
        return p.is_file() and os.access(p, os.R_OK)
    except OSError:  # pragma: no cover - defensive
        return False


def read_token(path: str) -> str:
    """Read the current JWT from `path`, stripped of trailing whitespace.

    Raises `FileNotFoundError` if the file doesn't exist and `ValueError`
    if it does but is empty. Callers should treat the returned string as
    sensitive — never log it.
    """
    token_path = Path(path)
    if not token_path.exists():
        raise FileNotFoundError(f"ArangoToken file not found: {path}")
    raw = token_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"ArangoToken file is empty: {path}")
    return raw
