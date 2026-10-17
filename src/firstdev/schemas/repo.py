# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Repo-assessment schema. Plain types only (structured outputs reject bounds); the bounds
are enforced in code after the call."""

from pydantic import BaseModel


class BestPractice(BaseModel):
    practice: str
    observed: bool
    evidence_path: str


class RepoAssessment(BaseModel):
    architecture_summary: str
    complexity: int  # 1-5
    best_practices: list[BestPractice]
    tutorial_likelihood: float  # 0-1
    tutorial_reasons: list[str]
    strengths: list[str]
    concerns: list[str]
