# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Result views built as explicit allowlist models: the developer report and the recruiter view.

The developer report carries answer keys, so it exists only for graded assessments. The recruiter
view never carries keys, rubrics or model answers.
"""

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstdev.assessments.grade import PASS_PCT, SHORT_WEIGHT
from firstdev.models import (
    Assessment,
    AssessmentAnswer,
    AssessmentQuestion,
    AssessmentStatus,
    QuestionKind,
)


class QuestionReport(BaseModel):
    position: int
    kind: str
    skill: str
    prompt: str
    correct: bool
    points: float
    possible: float
    # mcq
    options: list[str] | None = None
    your_choice: int | None = None
    correct_index: int | None = None
    explanation: str | None = None
    # short
    your_text: str | None = None
    criteria_met: list[str] | None = None
    criteria_missed: list[str] | None = None
    model_answer: str | None = None
    feedback: str | None = None


class StudySuggestion(BaseModel):
    skill: str
    pct: float
    missed_prompts: list[str]


class DeveloperReport(BaseModel):
    assessment_id: str
    overall_pct: float
    skill_pcts: dict[str, float]
    questions: list[QuestionReport]
    strengths: list[str]
    study_suggestions: list[StudySuggestion]


class ShortAnswerView(BaseModel):
    skill: str
    prompt: str
    text: str
    points: float | None
    criteria_met: list[str]
    injection_flags: list[dict]


class RecruiterView(BaseModel):
    assessment_id: str
    status: AssessmentStatus
    overall_pct: float | None
    skill_pcts: dict[str, float] | None
    time_taken_seconds: int | None
    short_answers: list[ShortAnswerView]


def _rows(db: Session, a: Assessment) -> list[tuple[AssessmentQuestion, AssessmentAnswer | None]]:
    qs = db.scalars(
        select(AssessmentQuestion)
        .where(AssessmentQuestion.assessment_id == a.id)
        .order_by(AssessmentQuestion.position)
    ).all()
    ans = {
        r.question_id: r
        for r in db.scalars(
            select(AssessmentAnswer).where(AssessmentAnswer.question_id.in_([q.id for q in qs]))
        )
    }
    return [(q, ans.get(q.id)) for q in qs]


def developer_report(db: Session, a: Assessment) -> DeveloperReport:
    if a.status != AssessmentStatus.graded:
        raise HTTPException(409, "report is available once the assessment is graded")
    questions: list[QuestionReport] = []
    missed: dict[str, list[str]] = {}
    for q, ans in _rows(db, a):
        pts = (ans.points or 0.0) if ans else 0.0
        if q.kind == QuestionKind.mcq:
            poss = 1.0
            r = QuestionReport(
                position=q.position, kind="mcq", skill=q.skill, prompt=q.prompt,
                correct=pts >= poss, points=pts, possible=poss, options=q.options,
                your_choice=ans.choice_index if ans else None,
                correct_index=q.correct_index, explanation=q.explanation,
            )  # fmt: skip
        else:
            poss = SHORT_WEIGHT
            rubric = q.rubric or []
            met = set((ans.criteria_met or []) if ans else [])
            r = QuestionReport(
                position=q.position, kind="short", skill=q.skill, prompt=q.prompt,
                correct=pts >= poss, points=pts, possible=poss,
                your_text=ans.text if ans else None,
                criteria_met=[c["criterion"] for i, c in enumerate(rubric) if i in met],
                criteria_missed=[c["criterion"] for i, c in enumerate(rubric) if i not in met],
                model_answer=q.model_answer, feedback=ans.feedback if ans else None,
            )  # fmt: skip
        if not r.correct:
            missed.setdefault(q.skill, []).append(q.prompt)
        questions.append(r)
    pcts = a.skill_pcts or {}
    return DeveloperReport(
        assessment_id=a.id,
        overall_pct=a.overall_pct or 0.0,
        skill_pcts=pcts,
        questions=questions,
        strengths=[s for s, p in pcts.items() if p >= PASS_PCT],
        study_suggestions=[
            StudySuggestion(skill=s, pct=p, missed_prompts=missed.get(s, []))
            for s, p in pcts.items()
            if p < PASS_PCT
        ],
    )


def recruiter_view(db: Session, a: Assessment) -> RecruiterView:
    shorts = []
    for q, ans in _rows(db, a):
        if q.kind != QuestionKind.short or ans is None or ans.text is None:
            continue
        met = set(ans.criteria_met or [])
        shorts.append(
            ShortAnswerView(
                skill=q.skill, prompt=q.prompt, text=ans.text, points=ans.points,
                criteria_met=[c["criterion"] for i, c in enumerate(q.rubric or []) if i in met],
                injection_flags=ans.injection_flags or [],
            )
        )  # fmt: skip
    taken = (
        int((a.submitted_at - a.started_at).total_seconds())
        if a.submitted_at and a.started_at
        else None
    )
    return RecruiterView(
        assessment_id=a.id,
        status=a.status,
        overall_pct=a.overall_pct,
        skill_pcts=a.skill_pcts,
        time_taken_seconds=taken,
        short_answers=shorts,
    )
