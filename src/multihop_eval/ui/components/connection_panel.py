"""ArangoDB connection panel — top of the Configure tab.

Responsibilities:

* Detect AMP (kube-arangodb sidecar) via `clients.amp.detect_amp()` and
  auto-build a JWT-mode `ArangoGateway` so the user lands on a connected
  state with zero typing when deployed to AMP.
* Fall back to the existing manual host/db/username/password form when
  no AMP signal is present.
* Once a gateway is live, expose a database picker (populated by
  `gateway.list_databases()`) so the user can switch DBs without losing
  the AMP credentials.
* Stash the live gateway + listing on `st.session_state` so every other
  tab can ask "are we connected?" without rebuilding anything.

Every widget exposes a `help=` tooltip — that's enforced by
`tests/unit/test_ui_config_form_help.py` for the Configure-tab files.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import streamlit as st

from multihop_eval.clients.amp import AmpEnv, detect_amp
from multihop_eval.clients.arango_gateway import ArangoGateway, CollectionInfo
from multihop_eval.config import AUTH_MODE_PASSWORD, ArangoConfig
from multihop_eval.ui.state import (
    KEY_ARANGO_AMP_ENV,
    KEY_ARANGO_CLUSTER_IDS,
    KEY_ARANGO_COLLECTIONS,
    KEY_ARANGO_CONN_ERROR,
    KEY_ARANGO_CONN_STATUS,
    KEY_ARANGO_DB,
    KEY_ARANGO_DB_LIST,
    KEY_ARANGO_GATEWAY,
    KEY_ARANGO_LAST_TESTED,
)

log = logging.getLogger(__name__)

STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTED_AMP = "connected_amp"
STATUS_CONNECTED_MANUAL = "connected_manual"
STATUS_ERROR = "error"

# Default starting database for the picker. Every JWT can read `_system`.
DEFAULT_DB_NAME = "_system"


def _set_status(status: str, *, error: str | None = None) -> None:
    st.session_state[KEY_ARANGO_CONN_STATUS] = status
    st.session_state[KEY_ARANGO_CONN_ERROR] = error


def _clear_listings() -> None:
    st.session_state[KEY_ARANGO_COLLECTIONS] = None
    st.session_state[KEY_ARANGO_CLUSTER_IDS] = None
    st.session_state[KEY_ARANGO_DB_LIST] = None


def _stash_gateway(gateway: ArangoGateway, *, status: str, db: str) -> None:
    st.session_state[KEY_ARANGO_GATEWAY] = gateway
    st.session_state[KEY_ARANGO_DB] = db
    st.session_state[KEY_ARANGO_LAST_TESTED] = datetime.now(UTC).isoformat(timespec="seconds")
    _set_status(status)


def _disconnect() -> None:
    st.session_state[KEY_ARANGO_GATEWAY] = None
    st.session_state[KEY_ARANGO_DB] = None
    _clear_listings()
    _set_status(STATUS_DISCONNECTED)


def _status_pill(status: str, amp_env: AmpEnv | None) -> None:
    """Render a small status banner at the top of the connection panel."""
    if status == STATUS_CONNECTED_AMP:
        deployment = (amp_env.deployment_name if amp_env else None) or "deployment"
        st.success(
            f"Connected via AMP (deployment **{deployment}**). "
            "The token rotates automatically; you don't need to re-enter credentials."
        )
    elif status == STATUS_CONNECTED_MANUAL:
        st.info(
            "Connected with manual credentials. Use **Disconnect** below to "
            "clear them from this session."
        )
    elif status == STATUS_ERROR:
        err = st.session_state.get(KEY_ARANGO_CONN_ERROR) or "Unknown error."
        st.error(f"Not connected — last error: {err}")
    else:
        if amp_env is not None:
            st.info(
                "AMP environment detected. Click **Connect via AMP** to use the "
                "deployment-supplied credentials, or fill in the manual form below."
            )
        else:
            st.warning(
                "Disconnected. Fill in the connection form below or set "
                "`ARANGO_DEPLOYMENT_ENDPOINT` + `ARANGO_TOKEN` to enable AMP auto-connect."
            )


def _build_gateway_or_error(cfg: ArangoConfig) -> ArangoGateway | None:
    """Try to construct a gateway and ping it. Surface errors via session state."""
    try:
        gateway = ArangoGateway(cfg)
    except Exception as exc:  # noqa: BLE001 - surface every reason to the UI
        _set_status(STATUS_ERROR, error=str(exc))
        return None
    if not gateway.ping():
        _set_status(STATUS_ERROR, error="Ping failed — credentials or endpoint may be wrong.")
        return None
    return gateway


def _connect_amp(amp: AmpEnv, db: str) -> ArangoGateway | None:
    """Build a JWT-mode gateway for the given DB inside an AMP deployment."""
    try:
        cfg = ArangoConfig.from_amp(amp, db=db)
    except Exception as exc:  # noqa: BLE001 - invalid env / missing token
        _set_status(STATUS_ERROR, error=f"AMP config invalid: {exc}")
        return None
    return _build_gateway_or_error(cfg)


def _refresh_db_list(gateway: ArangoGateway) -> list[str]:
    try:
        dbs = gateway.list_databases()
    except Exception as exc:  # noqa: BLE001
        log.warning("list_databases failed: %s", exc)
        dbs = []
    if not dbs:
        # At minimum the current DB is reachable.
        dbs = [gateway.config.db]
    st.session_state[KEY_ARANGO_DB_LIST] = dbs
    return dbs


def _amp_section(amp: AmpEnv) -> None:
    """Render the AMP block: auto-connect, DB picker, disconnect."""
    status: str = st.session_state.get(KEY_ARANGO_CONN_STATUS, STATUS_DISCONNECTED)
    gateway: ArangoGateway | None = st.session_state.get(KEY_ARANGO_GATEWAY)

    # First-time auto-connect: AMP detected and no gateway yet.
    if status == STATUS_DISCONNECTED and gateway is None:
        cols = st.columns([2, 1, 3])
        if cols[0].button(
            "Connect via AMP",
            type="primary",
            help=(
                "Build an ArangoDB gateway using the JWT mounted by the kube-arangodb "
                "sidecar. The token rotates automatically; you don't need to do anything."
            ),
        ):
            gw = _connect_amp(amp, db=DEFAULT_DB_NAME)
            if gw is not None:
                _stash_gateway(gw, status=STATUS_CONNECTED_AMP, db=DEFAULT_DB_NAME)
                _refresh_db_list(gw)
                st.rerun()

    if gateway is None or status != STATUS_CONNECTED_AMP:
        return

    # Connected: render DB picker + disconnect/refresh.
    dbs = st.session_state.get(KEY_ARANGO_DB_LIST) or _refresh_db_list(gateway)
    current_db: str = st.session_state.get(KEY_ARANGO_DB) or DEFAULT_DB_NAME
    if current_db not in dbs:
        dbs = sorted({*dbs, current_db})

    cols = st.columns([3, 1, 1])
    chosen_db = cols[0].selectbox(
        "Database",
        options=dbs,
        index=dbs.index(current_db),
        help=(
            "Pick the ArangoDB database to evaluate against. Defaults to `_system`. "
            "Switching rebuilds the gateway with the same AMP credentials."
        ),
        key="amp_db_picker",
    )
    if cols[1].button(
        "Refresh DBs",
        help="Re-list databases visible to the AMP JWT.",
    ):
        _refresh_db_list(gateway)
        st.rerun()
    if cols[2].button(
        "Disconnect",
        help="Drop the live gateway. The next interaction will require a fresh connect.",
    ):
        _disconnect()
        st.rerun()

    if chosen_db != current_db:
        gw = _connect_amp(amp, db=chosen_db)
        if gw is not None:
            _stash_gateway(gw, status=STATUS_CONNECTED_AMP, db=chosen_db)
            _clear_listings()
            st.rerun()


def _manual_section(prefill: ArangoConfig | None) -> None:
    """Render the manual host/db/user/password form + Connect button.

    Mirrors the original `_arango_form` from `config_form.py`, but builds
    a `ArangoGateway` on submission and stashes it on session state
    instead of returning a raw dict. Collection-name pickers are no
    longer part of this section — they live in `config_form.py`'s
    refactored collection picker, which only renders once a gateway is
    live.
    """
    status: str = st.session_state.get(KEY_ARANGO_CONN_STATUS, STATUS_DISCONNECTED)
    gateway: ArangoGateway | None = st.session_state.get(KEY_ARANGO_GATEWAY)

    cols = st.columns(2)
    host = cols[0].text_input(
        "Host",
        value=(prefill.host if prefill else "https://"),
        help=(
            "Base URL of your ArangoDB cluster, including scheme. "
            "Example: `https://my-cluster.arangodb.cloud`."
        ),
    )
    db = cols[1].text_input(
        "Database",
        value=(prefill.db if prefill else "_system"),
        help=(
            "Database to connect to. Once connected you can switch to any other "
            "database the credentials can read from the picker that appears below."
        ),
    )
    cols = st.columns(2)
    username = cols[0].text_input(
        "Username",
        value=(prefill.username if prefill else "root"),
        help="ArangoDB user with read access to the corpus and write access to the QA collection.",
    )
    password = cols[1].text_input(
        "Password",
        value=(prefill.password.get_secret_value() if prefill and prefill.password else ""),
        type="password",
        help="ArangoDB user password. Kept in session memory only; never written to disk.",
    )

    cols = st.columns([1, 1, 1, 3])
    connect_clicked = cols[0].button(
        "Connect",
        type="primary",
        disabled=status == STATUS_CONNECTED_MANUAL,
        help="Build a gateway with the supplied credentials and ping it before continuing.",
    )
    test_clicked = cols[1].button(
        "Test connection",
        disabled=gateway is None,
        help="Ping the live gateway to verify it still works. Helpful after long pauses.",
    )
    disconnect_clicked = cols[2].button(
        "Disconnect",
        disabled=gateway is None,
        help="Drop the cached gateway and credentials from this session.",
    )

    last_tested = st.session_state.get(KEY_ARANGO_LAST_TESTED)
    if last_tested:
        cols[3].caption(f"Last verified at **{last_tested}** UTC")

    if connect_clicked:
        try:
            cfg = ArangoConfig(  # type: ignore[call-arg]
                host=host,
                db=db,
                username=username,
                password=password or None,
                auth_mode=AUTH_MODE_PASSWORD,
            )
        except Exception as exc:  # noqa: BLE001
            _set_status(STATUS_ERROR, error=str(exc))
            st.rerun()
            return
        gw = _build_gateway_or_error(cfg)
        if gw is not None:
            _stash_gateway(gw, status=STATUS_CONNECTED_MANUAL, db=db)
            _refresh_db_list(gw)
        st.rerun()

    if test_clicked and gateway is not None:
        if gateway.ping():
            st.session_state[KEY_ARANGO_LAST_TESTED] = datetime.now(UTC).isoformat(
                timespec="seconds"
            )
            st.success("Ping OK.")
        else:
            _set_status(STATUS_ERROR, error="Ping failed.")
            st.rerun()

    if disconnect_clicked:
        _disconnect()
        st.rerun()

    # Manual-mode DB picker (once connected): same UX as AMP path.
    if gateway is not None and status == STATUS_CONNECTED_MANUAL:
        dbs = st.session_state.get(KEY_ARANGO_DB_LIST) or _refresh_db_list(gateway)
        current_db: str = st.session_state.get(KEY_ARANGO_DB) or db
        if current_db not in dbs:
            dbs = sorted({*dbs, current_db})
        chosen_db = st.selectbox(
            "Switch database",
            options=dbs,
            index=dbs.index(current_db),
            help=(
                "Switch the connected database. The gateway is rebuilt with the same "
                "credentials but a new database scope; cached collection lists are cleared."
            ),
            key="manual_db_picker",
        )
        if chosen_db != current_db:
            try:
                new_cfg = ArangoConfig(  # type: ignore[call-arg]
                    host=gateway.config.host,
                    db=chosen_db,
                    username=gateway.config.username,
                    password=(
                        gateway.config.password.get_secret_value()
                        if gateway.config.password
                        else None
                    ),
                    auth_mode=AUTH_MODE_PASSWORD,
                )
            except Exception as exc:  # noqa: BLE001
                _set_status(STATUS_ERROR, error=str(exc))
                st.rerun()
                return
            gw = _build_gateway_or_error(new_cfg)
            if gw is not None:
                _stash_gateway(gw, status=STATUS_CONNECTED_MANUAL, db=chosen_db)
                _clear_listings()
                st.rerun()


def render_connection_panel(prefill: ArangoConfig | None = None) -> ArangoGateway | None:
    """Render the connection panel at the top of the Configure tab.

    Returns the live `ArangoGateway` (or `None` if disconnected) so the
    surrounding form can render collection pickers only when there's
    something to populate them with.
    """
    # Detect AMP every render — the env doesn't change at runtime, but
    # caching here also tracks token-file readability so we re-detect after
    # the sidecar finally mounts the token.
    amp_env: AmpEnv | None = st.session_state.get(KEY_ARANGO_AMP_ENV)
    detected = detect_amp()
    if detected is not None:
        amp_env = detected
        st.session_state[KEY_ARANGO_AMP_ENV] = amp_env

    status: str = st.session_state.get(KEY_ARANGO_CONN_STATUS, STATUS_DISCONNECTED)
    _status_pill(status, amp_env)

    if amp_env is not None:
        _amp_section(amp_env)
        with st.expander("Manual credentials (override AMP)", expanded=False):
            _manual_section(prefill)
    else:
        _manual_section(prefill)

    return st.session_state.get(KEY_ARANGO_GATEWAY)


def get_live_gateway() -> ArangoGateway | None:
    """Return the connected gateway if one exists, else `None`.

    Cross-tab helper: other tabs call this instead of poking session
    state directly so the key names stay encapsulated here.
    """
    return st.session_state.get(KEY_ARANGO_GATEWAY)


def get_live_collections() -> list[CollectionInfo]:
    """Return the cached collection listing, or an empty list when disconnected."""
    cached = st.session_state.get(KEY_ARANGO_COLLECTIONS)
    return list(cached) if cached else []


def refresh_collections(gateway: ArangoGateway) -> list[CollectionInfo]:
    """List collections for the live gateway and cache them on session state."""
    try:
        cols = gateway.list_collections()
    except Exception as exc:  # noqa: BLE001 - surface to the UI
        log.warning("Failed to list collections: %s", exc)
        cols = []
    st.session_state[KEY_ARANGO_COLLECTIONS] = cols
    return cols


def refresh_cluster_ids(gateway: ArangoGateway, domains_collection: str) -> list[str]:
    """List cluster ids for the configured domains collection."""
    ids = gateway.list_cluster_ids(domains_collection)
    st.session_state[KEY_ARANGO_CLUSTER_IDS] = ids
    return ids


def is_connected() -> bool:
    """Quick boolean shortcut used by tabs that want to gate their actions."""
    status = st.session_state.get(KEY_ARANGO_CONN_STATUS)
    return status in {STATUS_CONNECTED_AMP, STATUS_CONNECTED_MANUAL}
