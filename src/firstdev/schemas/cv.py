# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""CV schemas. The LLM-facing models use only plain types (no regex/min/max constraints,
which structured outputs don't support); bounds are enforced in code after the call."""

from typing import Literal

from pydantic import BaseModel

Category = Literal[
    "language", "framework", "tool", "database", "cloud", "practice", "soft", "other"
]


# Deliberately no name/email/phone/address/photo fields: data minimization.
class Skill(BaseModel):
    name: str
    category: Category
    years: float | None
    evidence_quote: str


class Experience(BaseModel):
    title: str
    company: str
    start: str | None  # "YYYY-MM" or "YYYY"
    end: str | None  # "YYYY-MM", "YYYY" or "present"
    description: str | None
    evidence_quote: str


class Education(BaseModel):
    institution: str
    degree: str | None
    field: str | None
    start: str | None
    end: str | None
    evidence_quote: str


class CVExtraction(BaseModel):
    skills: list[Skill]
    experience: list[Experience]
    education: list[Education]
    languages_spoken: list[str]
    summary: str | None


class Gap(BaseModel):
    start: str  # "YYYY-MM", first month without a job
    end: str  # "YYYY-MM", last month without a job
    months: int


class Dropped(BaseModel):
    section: str
    reason: str


class CVData(CVExtraction):
    """What is stored: the validated extraction plus code-computed gaps and drop records."""

    gaps: list[Gap]
    dropped: list[Dropped]
    schema_version: int = 1
