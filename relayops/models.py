"""Strict application contracts; model text never establishes authorization."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Diagnosis(StrictModel):
    summary: str = Field(min_length=1, max_length=1200)
    cause: str = Field(min_length=1, max_length=200)
    evidence_ids: list[str] = Field(min_length=1, max_length=12)
    hypotheses: list[str] = Field(max_length=5)
    recommendation: str = Field(min_length=1, max_length=1200)
    action: Literal["retry_export", "reconcile_receipt", "prepare_patch", "escalate", "none"]


class CreateCase(StrictModel):
    scenario_id: str = Field(min_length=1, max_length=80)


class InvestigationRequest(StrictModel):
    mode: Literal["fixture", "openai"] = "fixture"


class DecisionRequest(StrictModel):
    decision: Literal["approve", "reject"]
    expected_hash: str = Field(min_length=64, max_length=64, pattern="^[a-f0-9]+$")


class ExecuteRequest(StrictModel):
    expected_hash: str = Field(min_length=64, max_length=64, pattern="^[a-f0-9]+$")


class EmptyRequest(StrictModel):
    pass
