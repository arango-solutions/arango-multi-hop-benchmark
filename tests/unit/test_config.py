"""Tests for `multihop_eval.config`."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from multihop_eval.config import AppConfig, ArangoConfig, EvalConfig, LLMConfig
from multihop_eval.personas import DEFAULT_PERSONAS, Persona
from multihop_eval.rubric import DEFAULT_RUBRIC, RubricField


def test_arango_config_requires_scheme():
    with pytest.raises(ValidationError):
        ArangoConfig(host="arango.example.com", db="d", password="p")  # type: ignore[arg-type]


def test_arango_config_strips_trailing_slash():
    cfg = ArangoConfig(host="https://arango.example.com/", db="d", password="p")  # type: ignore[arg-type]
    assert cfg.host == "https://arango.example.com"


def test_arango_config_env_override(monkeypatch):
    monkeypatch.setenv("ARANGO_HOST", "https://from-env.example.com")
    monkeypatch.setenv("ARANGO_DB", "envdb")
    monkeypatch.setenv("ARANGO_PASSWORD", "envpw")
    monkeypatch.setenv("ARANGO_QA_COLLECTION", "qa_overridden")
    cfg = ArangoConfig()  # type: ignore[call-arg]
    assert cfg.host == "https://from-env.example.com"
    assert cfg.db == "envdb"
    assert cfg.qa_collection == "qa_overridden"
    assert cfg.password.get_secret_value() == "envpw"


def test_llm_config_env_override(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
    monkeypatch.setenv("LLM_MODEL", "gpt-9")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
    cfg = LLMConfig()  # type: ignore[call-arg]
    assert cfg.api_key.get_secret_value() == "sk-from-env"
    assert cfg.model == "gpt-9"
    assert cfg.temperature == 0.7


def test_llm_config_temperature_bounds():
    with pytest.raises(ValidationError):
        LLMConfig(api_key="x", temperature=5.0)  # type: ignore[arg-type]


def test_eval_config_defaults_are_valid():
    ec = EvalConfig()
    assert ec.target_clusters == ["cluster_wtw_ingest_0"]
    assert sum(ec.hop_dist_weights) == pytest.approx(1.0)
    assert len(ec.personas) == len(DEFAULT_PERSONAS)
    assert len(ec.rubric_fields) == len(DEFAULT_RUBRIC)


def test_eval_config_rejects_mismatched_weights():
    with pytest.raises(ValidationError):
        EvalConfig(hop_dist=[2, 3, 4], hop_dist_weights=[0.5, 0.5])


def test_eval_config_rejects_unnormalized_weights():
    with pytest.raises(ValidationError):
        EvalConfig(hop_dist=[2, 3], hop_dist_weights=[0.6, 0.6])


def test_eval_config_rejects_empty_clusters():
    with pytest.raises(ValidationError):
        EvalConfig(target_clusters=["", "  "])


def test_eval_config_rejects_one_hop():
    with pytest.raises(ValidationError):
        EvalConfig(hop_dist=[1, 2], hop_dist_weights=[0.5, 0.5])


def test_eval_config_requires_personas():
    with pytest.raises(ValidationError):
        EvalConfig(personas=[])


def test_eval_config_with_rubric_disabled_allows_empty_rubric():
    ec = EvalConfig(rubric_fields=[], score_with_rubric=False)
    assert ec.rubric_fields == []


def test_app_config_safe_dict_redacts_secrets():
    cfg = AppConfig(
        arango=ArangoConfig(host="https://x.example.com", db="d", password="hunter2"),  # type: ignore[arg-type]
        llm=LLMConfig(api_key="sk-12345"),  # type: ignore[arg-type]
    )
    safe = cfg.to_safe_dict()
    assert safe["arango"]["password"] == "***"
    assert safe["llm"]["api_key"] == "***"


def test_app_config_round_trip_preserves_personas_and_rubric():
    custom_persona = Persona(label="finance_director", instruction="Ask as a finance director investigating headcount cost." )
    custom_field = RubricField(name="numeric_precision", description="Are dollar amounts and dates exact?", weight=2.0)
    cfg = AppConfig(
        arango=ArangoConfig(host="https://x.example.com", db="d", password="p"),  # type: ignore[arg-type]
        llm=LLMConfig(api_key="sk"),  # type: ignore[arg-type]
        eval=EvalConfig(personas=[custom_persona], rubric_fields=[custom_field]),
    )
    data = json.loads(cfg.model_dump_json())
    rebuilt = AppConfig.model_validate(data)
    assert rebuilt.eval.personas[0].label == "finance_director"
    assert rebuilt.eval.rubric_fields[0].name == "numeric_precision"
    assert rebuilt.eval.rubric_fields[0].weight == 2.0


def test_persona_label_rejects_slashes():
    with pytest.raises(ValidationError):
        Persona(label="bad/label", instruction="this is a long enough instruction")


def test_rubric_scale_min_must_be_less_than_max():
    with pytest.raises(ValidationError):
        RubricField(name="x", description="long enough description here", scale_min=5, scale_max=5)


def test_rubric_name_must_be_identifier_safe():
    with pytest.raises(ValidationError):
        RubricField(name="bad name with spaces", description="long enough description here")
