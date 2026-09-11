"""QAReport — PASS / QUARANTINE / FAIL with per-check findings."""
from typing import Literal, Optional
from pydantic import BaseModel, Field

from m1.models.version import SCHEMA_VERSION

Verdict = Literal["PASS", "QUARANTINE", "FAIL"]


class QACheck(BaseModel):
    name: str
    passed: bool
    severity: Literal["critical", "warning", "info"] = "info"
    blocking: bool = False
    detail: str = ""


class QAReport(BaseModel):
    schema_version: str = SCHEMA_VERSION
    experiment_id: str = ""
    verdict: Verdict = "FAIL"
    checks: list[QACheck] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
