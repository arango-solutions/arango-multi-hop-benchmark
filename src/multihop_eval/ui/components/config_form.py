"""Configure tab — Arango / LLM / Eval / Personas / Rubric forms.

Every widget exposes a `help=` argument so Streamlit renders a small "ⓘ"
icon next to its label; hovering pops a one-or-two-sentence description of
what the parameter does. Help strings are kept inline with the widget so
the explanation stays next to the field it documents.

Connection details (host / username / password / AMP detection / database
picker) live in the sibling `connection_panel` module — this file owns
the *collection selection*, eval params, personas, and rubric only.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from multihop_eval.clients.arango_gateway import ArangoGateway, CollectionInfo
from multihop_eval.config import AppConfig, ArangoConfig, EvalConfig, LLMConfig
from multihop_eval.generation.personas import DEFAULT_PERSONAS, Persona
from multihop_eval.generation.rubric import DEFAULT_RUBRIC, RubricField
from multihop_eval.ui.components.connection_panel import (
    get_live_collections,
    refresh_cluster_ids,
    refresh_collections,
    render_connection_panel,
)
from multihop_eval.ui.state import (
    KEY_ARANGO_CLUSTER_IDS,
    KEY_ARANGO_COLLECTIONS,
)

# Map collection-role keys (matching ArangoConfig field names) → (label, help, default name).
_COLLECTION_ROLES: tuple[tuple[str, str, str, str], ...] = (
    (
        "sources_collection",
        "Sources collection",
        (
            "Collection containing the raw source documents. Each document must "
            "expose `content` and `filename` fields."
        ),
        "multihop_eval_sources",
    ),
    (
        "similarity_collection",
        "Similarity collection",
        (
            "Edge collection of document-to-document similarities. Each edge has "
            "`_from`, `_to` (source `_id`s) and `similarity_score`. Used to traverse "
            "between related documents when building a subgraph."
        ),
        "multihop_eval_similarities",
    ),
    (
        "relations_collection",
        "Relations collection",
        (
            "Edge collection that maps each source document to its cluster: "
            "`_from` = source `_id`, `_to` = cluster (domain) `_id`."
        ),
        "multihop_eval_corpus_relations",
    ),
    (
        "domains_collection",
        "Domains collection",
        (
            "Collection whose `_id`s are referenced as cluster ids by the relations "
            "edges (e.g. `domains/cluster_0`). Cluster picker draws its options from here."
        ),
        "multihop_eval_domains",
    ),
    (
        "rags_collection",
        "RAGs collection",
        (
            "Collection mapping clusters to a `rag_partition_id`. The partition id "
            "is tagged onto every generated QA pair so downstream RAG benchmarks can "
            "filter by partition."
        ),
        "multihop_eval_rags",
    ),
    (
        "qa_collection",
        "QA collection (output)",
        (
            "Collection that accepted QA pairs are written to. Created automatically "
            "on first run if it doesn't exist. Pick an existing collection to append, "
            "or type a fresh name to create a new one."
        ),
        "qa_pairs_multihop_eval_v1",
    ),
)


def _collection_label(info: CollectionInfo) -> str:
    """Format a collection name + doc count for display in a selectbox."""
    return f"{info.name}  ({info.doc_count:,} docs, {info.kind})"


def _suggest_default(
    role_key: str,
    *,
    prefill_name: str | None,
    fallback_default: str,
    available: list[CollectionInfo],
) -> str | None:
    """Pick a sensible pre-selection for a collection selectbox.

    Order of preference:

    1. The previously-saved value (`prefill_name`) if it exists in the DB.
    2. The hard-coded default name (e.g. `multihop_eval_sources`) if present.
    3. Any collection whose name *contains* a keyword derived from the role
       (e.g. `sources_collection` → looks for "sources").
    4. `None` (let the user pick).
    """
    if not available:
        return None
    names = {c.name for c in available}
    if prefill_name and prefill_name in names:
        return prefill_name
    if fallback_default in names:
        return fallback_default
    keyword = role_key.removesuffix("_collection")
    for c in available:
        if keyword and keyword in c.name:
            return c.name
    return None


def _render_collection_selectboxes(
    gateway: ArangoGateway,
    prefill: ArangoConfig | None,
) -> dict[str, str]:
    """Render the six collection-role selectboxes when a gateway is live."""
    if st.session_state.get(KEY_ARANGO_COLLECTIONS) is None:
        refresh_collections(gateway)
    available = get_live_collections()

    cols = st.columns([1, 1, 4])
    if cols[0].button(
        "Refresh collections",
        help="Re-list collections from the connected database.",
    ):
        refresh_collections(gateway)
        available = get_live_collections()
        st.rerun()
    if not available:
        cols[1].caption("(no collections returned)")
    else:
        cols[1].caption(f"{len(available)} collection(s) discovered")

    chosen: dict[str, str] = {}
    grid = st.columns(2)
    for idx, (role_key, label, helptext, default) in enumerate(_COLLECTION_ROLES):
        col = grid[idx % 2]
        prefill_name = getattr(prefill, role_key, None) if prefill else None
        names = [c.name for c in available]
        options = list(names)
        # qa_collection is an output — allow typing a brand-new name as well.
        custom_option = "<other / new collection…>"
        if role_key == "qa_collection":
            options = [*names, custom_option]
        default_value = _suggest_default(
            role_key,
            prefill_name=prefill_name,
            fallback_default=default,
            available=available,
        )
        if default_value is None:
            # No match: for qa_collection default to "create new"; for inputs
            # leave at index 0 so something is always selected.
            if role_key == "qa_collection":
                default_value = custom_option
            elif options:
                default_value = options[0]
        format_fn = (
            (lambda name: name)
            if role_key == "qa_collection"
            else (
                lambda name, _by={c.name: c for c in available}: (
                    _collection_label(_by[name]) if name in _by else name
                )
            )
        )
        if not options:
            chosen_name = col.text_input(
                label,
                value=prefill_name or default,
                help=helptext + " (No collections discovered; type a name.)",
            )
        else:
            index = options.index(default_value) if default_value in options else 0
            chosen_name = col.selectbox(
                label,
                options=options,
                index=index,
                format_func=format_fn,
                help=helptext,
                key=f"coll_pick_{role_key}",
            )
            if role_key == "qa_collection" and chosen_name == custom_option:
                chosen_name = col.text_input(
                    f"{label} — new name",
                    value=prefill_name or default,
                    help=(
                        "Type a fresh collection name; it will be created the first "
                        "time the pipeline writes to it."
                    ),
                    key=f"coll_pick_{role_key}_new",
                )
        chosen[role_key] = chosen_name

        # Doc-count hint: warn when an *input* collection looks empty.
        if role_key != "qa_collection":
            picked = next((c for c in available if c.name == chosen_name), None)
            if picked is not None and picked.doc_count == 0:
                col.warning(
                    f"`{chosen_name}` is empty — is this the right collection for "
                    f"**{label}**?"
                )

    return chosen


def _render_collection_text_inputs(prefill: ArangoConfig | None) -> dict[str, str]:
    """Render the legacy text inputs used when no gateway is live."""
    chosen: dict[str, str] = {}
    grid = st.columns(2)
    for idx, (role_key, label, helptext, default) in enumerate(_COLLECTION_ROLES):
        col = grid[idx % 2]
        prefill_value = getattr(prefill, role_key, None) if prefill else None
        chosen[role_key] = col.text_input(
            label,
            value=prefill_value or default,
            help=helptext,
            key=f"coll_text_{role_key}",
        )
    return chosen


def _collections_section(
    gateway: ArangoGateway | None,
    prefill: ArangoConfig | None,
) -> dict[str, str]:
    st.subheader("Collections")
    if gateway is None:
        st.caption(
            "Not connected — collection names are typed manually. Connect above to "
            "pick from a live list with doc-count hints."
        )
        return _render_collection_text_inputs(prefill)
    st.caption(
        "Pick which collection plays which role in the pipeline. Doc counts come "
        "from the live database; refresh if you just created or wrote to a collection."
    )
    return _render_collection_selectboxes(gateway, prefill)


def _llm_form(prefill: LLMConfig | None) -> dict[str, Any]:
    cols = st.columns(2)
    api_url = cols[0].text_input(
        "API URL",
        value=(prefill.api_url if prefill else "https://api.openai.com/v1/chat/completions"),
        help=(
            "OpenAI-compatible chat-completions endpoint. Works with OpenAI, Azure "
            "OpenAI, vLLM, OpenRouter, Together, and any other server that speaks the "
            "`/v1/chat/completions` schema."
        ),
    )
    api_key = cols[1].text_input(
        "API key",
        value=(prefill.api_key.get_secret_value() if prefill else ""),
        type="password",
        help="Bearer token sent in the `Authorization` header. Treated as a secret.",
    )
    cols = st.columns(2)
    model = cols[0].text_input(
        "Model",
        value=(prefill.model if prefill else "gpt-4.1"),
        help="Model identifier passed to the chat endpoint (e.g. `gpt-4.1`, `gpt-4o-mini`).",
    )
    temperature = cols[1].slider(
        "Temperature",
        min_value=0.0,
        max_value=2.0,
        value=float(prefill.temperature if prefill else 0.3),
        step=0.05,
        help=(
            "Sampling temperature for the generator LLM. Lower (0.0–0.3) gives more "
            "deterministic, on-topic questions; higher gives more variety. The "
            "multi-hop and proof-verification judges always run at temperature 0.0."
        ),
    )
    cols = st.columns(3)
    max_tokens = cols[0].number_input(
        "Max tokens",
        min_value=64,
        max_value=128_000,
        value=int(prefill.max_tokens if prefill else 4000),
        step=128,
        help=(
            "Hard cap on the LLM's output tokens per call. Increase if generations get "
            "truncated; decrease to save cost."
        ),
    )
    timeout_s = cols[1].number_input(
        "Timeout (s)",
        min_value=1,
        max_value=3600,
        value=int(prefill.timeout_s if prefill else 180),
        help="Per-HTTP-request timeout. Raise this if you see timeouts on long contexts.",
    )
    retries = cols[2].number_input(
        "Retries",
        min_value=1,
        max_value=10,
        value=int(prefill.retries if prefill else 3),
        help=(
            "Number of attempts on transient failures (5xx, timeouts) with exponential "
            "backoff. Context-length errors are surfaced immediately without retry so "
            "the pipeline can shrink the subgraph."
        ),
    )
    return {
        "api_url": api_url,
        "api_key": api_key,
        "model": model,
        "temperature": temperature,
        "max_tokens": int(max_tokens),
        "timeout_s": int(timeout_s),
        "retries": int(retries),
    }


def _target_clusters_widget(
    *,
    gateway: ArangoGateway | None,
    domains_collection: str | None,
    prefill_clusters: list[str],
) -> list[str]:
    """Multiselect when a gateway+domains collection are available, textarea otherwise."""
    if gateway is None or not domains_collection:
        clusters_str = st.text_area(
            "Target clusters (one per line)",
            value="\n".join(prefill_clusters),
            height=110,
            help=(
                "One cluster id per line. The generator processes each cluster in order, "
                "aiming to produce `Questions per cluster` accepted QA pairs from it. "
                "Cluster ids without a `/` are auto-prefixed with the domains collection."
            ),
        )
        return [c.strip() for c in clusters_str.splitlines() if c.strip()]

    cached = st.session_state.get(KEY_ARANGO_CLUSTER_IDS)
    if cached is None:
        cached = refresh_cluster_ids(gateway, domains_collection)
    cols = st.columns([3, 1])
    options = sorted({*cached, *prefill_clusters})
    if not options:
        cols[0].info(
            f"No cluster ids found in `{domains_collection}` yet. Type them manually "
            "below, or refresh after ingest finishes."
        )
        clusters_str = cols[0].text_area(
            "Target clusters (one per line)",
            value="\n".join(prefill_clusters),
            height=110,
            help="One cluster id per line.",
        )
        chosen = [c.strip() for c in clusters_str.splitlines() if c.strip()]
    else:
        default = [c for c in prefill_clusters if c in options] or options[:1]
        chosen = cols[0].multiselect(
            "Target clusters",
            options=options,
            default=default,
            help=(
                f"Pick the cluster ids to evaluate against. Drawn from "
                f"`{domains_collection}._key` in the connected database."
            ),
            key="target_clusters_picker",
        )
    if cols[1].button(
        "Refresh clusters",
        help=f"Re-list cluster ids from `{domains_collection}`.",
    ):
        refresh_cluster_ids(gateway, domains_collection)
        st.rerun()
    return chosen


def _eval_form(
    prefill: EvalConfig | None,
    *,
    gateway: ArangoGateway | None,
    domains_collection: str | None,
) -> dict[str, Any]:
    cols = st.columns(2)
    prefill_clusters = list(prefill.target_clusters) if prefill else ["cluster_0"]
    with cols[0]:
        target_clusters = _target_clusters_widget(
            gateway=gateway,
            domains_collection=domains_collection,
            prefill_clusters=prefill_clusters,
        )
    n_questions = cols[1].number_input(
        "Questions per cluster",
        min_value=1,
        max_value=10_000,
        value=int(prefill.n_questions if prefill else 50),
        help=(
            "How many accepted QA pairs to aim for in each cluster. The pipeline runs "
            "a Pass 1 over decimated seeds, then a Pass 2 top-up over fresh seeds to "
            "hit this target."
        ),
    )
    cols = st.columns(3)
    max_verify_rounds = cols[0].number_input(
        "Max verify rounds",
        min_value=1,
        max_value=10,
        value=int(prefill.max_verify_rounds if prefill else 3),
        help=(
            "Number of times the proof-verification LLM may correct its own output "
            "before the candidate is rejected. 3 is a sensible default."
        ),
    )
    save_to_arango = cols[1].checkbox(
        "Save accepted rows to ArangoDB",
        value=bool(prefill.save_to_arango if prefill else True),
        help=(
            "When on, every accepted QA pair is inserted into the QA collection in "
            "real time. The Dashboard tab's Excel and JSON downloads work whether "
            "this is on or off."
        ),
    )
    score_with_rubric = cols[2].checkbox(
        "Score with rubric (judge LLM)",
        value=bool(prefill.score_with_rubric if prefill else True),
        help=(
            "When on, every accepted QA pair is scored against the rubric defined "
            "below by an additional judge-LLM call. Adds one LLM call per accepted row."
        ),
    )

    st.markdown("**Hop distribution**")
    hop_dist_str = st.text_input(
        "Hop sizes (comma-separated, all >= 2)",
        value=",".join(str(h) for h in (prefill.hop_dist if prefill else [2, 3])),
        help=(
            "How many documents a question should require to answer. `2,3` means most "
            "generated questions will need 2 or 3 documents combined. Values must be "
            "integers >= 2 (a 1-hop is a single-doc question, which isn't multi-hop)."
        ),
    )
    hop_weights_str = st.text_input(
        "Weights (must sum to 1.0)",
        value=",".join(str(w) for w in (prefill.hop_dist_weights if prefill else [0.7, 0.3])),
        help=(
            "Probability weights for each hop size, in the same order as 'Hop sizes'. "
            "Example: `0.7,0.3` means 70% of subgraphs target the first hop size, 30% "
            "the second. Must be non-negative and sum to exactly 1.0."
        ),
    )

    return {
        "target_clusters": target_clusters,
        "n_questions": int(n_questions),
        "hop_dist": [int(x) for x in hop_dist_str.split(",") if x.strip()],
        "hop_dist_weights": [float(x) for x in hop_weights_str.split(",") if x.strip()],
        "max_verify_rounds": int(max_verify_rounds),
        "save_to_arango": save_to_arango,
        "score_with_rubric": score_with_rubric,
    }


def _persona_editor(prefill: list[Persona]) -> list[Persona]:
    st.caption(
        "Edit the personas the question generator imitates. Each row is one "
        "persona; add or remove rows as needed."
    )
    df = pd.DataFrame([{"label": p.label, "instruction": p.instruction} for p in prefill])
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "label": st.column_config.TextColumn(
                "Label",
                width="small",
                help=(
                    "Short slug stored on every QA row (alphanumerics, underscores, or "
                    "hyphens only). Surfaces as the persona dimension in the Dashboard."
                ),
            ),
            "instruction": st.column_config.TextColumn(
                "Instruction",
                width="large",
                help=(
                    "Prompt fragment injected into the generator as 'Write as a …'. "
                    "Each persona steers the produced questions toward a different "
                    "style or audience."
                ),
            ),
        },
        key="persona_editor",
    )
    out: list[Persona] = []
    for _, row in edited.iterrows():
        label = (row.get("label") or "").strip()
        instruction = (row.get("instruction") or "").strip()
        if not label or not instruction:
            continue
        out.append(Persona(label=label, instruction=instruction))
    return out


def _rubric_editor(prefill: list[RubricField]) -> list[RubricField]:
    st.caption(
        "Define the criteria the judge LLM should score every accepted QA "
        "pair on. Higher weight = stronger influence on the weighted aggregate."
    )
    df = pd.DataFrame(
        [
            {
                "name": f.name,
                "description": f.description,
                "scale_min": f.scale_min,
                "scale_max": f.scale_max,
                "weight": f.weight,
            }
            for f in prefill
        ]
    )
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "name": st.column_config.TextColumn(
                "Name",
                width="small",
                help=(
                    "Short identifier (alphanumerics, underscores, or hyphens). Becomes "
                    "the JSON key the judge LLM must return for this criterion."
                ),
            ),
            "description": st.column_config.TextColumn(
                "Description",
                width="large",
                help=(
                    "Tell the judge LLM exactly what this criterion means and how to "
                    "score it. The clearer this is, the more consistent the scores."
                ),
            ),
            "scale_min": st.column_config.NumberColumn(
                "Min",
                min_value=0,
                max_value=10,
                step=1,
                help="Minimum integer score for this field (inclusive).",
            ),
            "scale_max": st.column_config.NumberColumn(
                "Max",
                min_value=1,
                max_value=100,
                step=1,
                help=(
                    "Maximum integer score for this field (inclusive). Each field's "
                    "score is normalised to 0..1 before the weighted aggregate is "
                    "computed, so different fields can use different scales."
                ),
            ),
            "weight": st.column_config.NumberColumn(
                "Weight",
                min_value=0.1,
                max_value=10.0,
                step=0.1,
                help=(
                    "Relative importance in the weighted aggregate. A field with "
                    "weight 2.0 counts twice as much as one with weight 1.0."
                ),
            ),
        },
        key="rubric_editor",
    )
    out: list[RubricField] = []
    for _, row in edited.iterrows():
        name = (row.get("name") or "").strip()
        description = (row.get("description") or "").strip()
        if not name or not description:
            continue
        try:
            out.append(
                RubricField(
                    name=name,
                    description=description,
                    scale_min=int(row.get("scale_min") or 1),
                    scale_max=int(row.get("scale_max") or 5),
                    weight=float(row.get("weight") or 1.0),
                )
            )
        except ValidationError as exc:
            st.warning(f"Skipping invalid rubric row {name!r}: {exc.errors()[0]['msg']}")
    return out


def _arango_config_from(
    gateway: ArangoGateway | None,
    *,
    collection_overrides: dict[str, str],
    fallback_prefill: ArangoConfig | None,
) -> ArangoConfig:
    """Build a fresh `ArangoConfig` carrying the live auth + the chosen collections.

    Connected case: clone `gateway.config` and overlay the chosen
    collection names. Disconnected case: fall back to `fallback_prefill`
    (or class defaults) so the user can still save.
    """
    if gateway is not None:
        base = gateway.config.model_dump()
        # `password` is a SecretStr in the live config; .model_dump() emits the
        # secret as `SecretStr('***')` which round-trips just fine.
        if gateway.config.password is not None:
            base["password"] = gateway.config.password.get_secret_value()
        base.update(collection_overrides)
        return ArangoConfig(**base)  # type: ignore[arg-type]
    if fallback_prefill is not None:
        base = fallback_prefill.model_dump()
        if fallback_prefill.password is not None:
            base["password"] = fallback_prefill.password.get_secret_value()
        base.update(collection_overrides)
        return ArangoConfig(**base)  # type: ignore[arg-type]
    return ArangoConfig(**collection_overrides)  # type: ignore[arg-type]


def render_config_form() -> AppConfig | None:
    """Render the full config form. Returns the assembled `AppConfig` once
    the user clicks Save (and validation succeeds), else `None`.
    """
    existing: AppConfig | None = st.session_state.get("app_config")
    arango_prefill = existing.arango if existing else None
    llm_prefill = existing.llm if existing else None
    eval_prefill = existing.eval if existing else None
    personas_prefill = (
        existing.eval.personas if existing else list(DEFAULT_PERSONAS)
    )
    rubric_prefill = (
        existing.eval.rubric_fields if existing else list(DEFAULT_RUBRIC)
    )

    st.subheader("ArangoDB connection")
    gateway = render_connection_panel(prefill=arango_prefill)

    collection_overrides = _collections_section(gateway, arango_prefill)

    with st.expander("LLM provider", expanded=existing is None):
        llm_data = _llm_form(llm_prefill)
    with st.expander("Evaluation parameters", expanded=existing is None):
        eval_data = _eval_form(
            eval_prefill,
            gateway=gateway,
            domains_collection=collection_overrides.get("domains_collection"),
        )

    st.subheader("Personas")
    personas = _persona_editor(personas_prefill)

    st.subheader("Evaluation rubric")
    rubric_fields = _rubric_editor(rubric_prefill)

    cols = st.columns([1, 1, 4])
    save_clicked = cols[0].button(
        "Save configuration",
        type="primary",
        help=(
            "Persist these values to the current session. They're picked up by the "
            "Run and Ad-hoc tabs immediately."
        ),
    )
    load_env_clicked = cols[1].button(
        "Load from env / .env",
        help=(
            "Replace the form with values read from environment variables and the "
            "`.env` (or `env`) file at the project root. See `.env.example` for the "
            "set of supported variables."
        ),
    )

    if load_env_clicked:
        try:
            cfg = AppConfig.from_env()
            st.session_state["app_config"] = cfg
            st.success("Loaded configuration from environment.")
            st.rerun()
        except ValidationError as exc:
            st.error(f"Could not load config from env: {exc}")
        return None

    if not save_clicked:
        return existing

    try:
        arango_cfg = _arango_config_from(
            gateway,
            collection_overrides=collection_overrides,
            fallback_prefill=arango_prefill,
        )
        cfg = AppConfig(
            arango=arango_cfg,
            llm=LLMConfig(**llm_data),  # type: ignore[arg-type]
            eval=EvalConfig(
                **eval_data,
                personas=personas,
                rubric_fields=rubric_fields,
            ),
        )
    except ValidationError as exc:
        st.error("Configuration is invalid:")
        for err in exc.errors():
            st.error(f"  • {' / '.join(str(p) for p in err['loc'])}: {err['msg']}")
        return None

    st.session_state["app_config"] = cfg
    st.success("Configuration saved for this session.")
    safe = cfg.to_safe_dict()
    with st.expander("Configuration preview (secrets redacted)"):
        st.code(json.dumps(safe, indent=2, default=str), language="json")
    return cfg
