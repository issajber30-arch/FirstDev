# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""The taking flow: start, current question, ordered answers, submit and the server-side deadline.

Every function that reads the clock takes `now` (default: the real UTC time). Answer keys are only
read here to grade MCQs in code; nothing in this module returns them.
"""

import dataclasses
import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from firstdev.assessments import grade
from firstdev.jobs import enqueue
from firstdev.models import (
    Assessment,
    AssessmentAnswer,
    AssessmentQuestion,
    AssessmentStatus,
    JobKind,
    QuestionKind,
    User,
)
from firstdev.security.injection import scan
from firstdev.security.sanitize import EmptyInput, InputTooLarge, sanitize_text_report

log = logging.getLogger("firstdev.assessments")

TIME_LIMIT = timedelta(minutes=20)
START_WINDOW = timedelta(days=7)
MAX_ANSWER_CHARS = 2000
_DONE = {AssessmentStatus.submitted, AssessmentStatus.graded, AssessmentStatus.failed}


def _questions(db: Session, a: Assessment) -> list[AssessmentQuestion]:
    return list(
        db.scalars(
            select(AssessmentQuestion)
            .where(AssessmentQuestion.assessment_id == a.id)
            .order_by(AssessmentQuestion.position)
        )
    )


def _answers(db: Session, questions: list[AssessmentQuestion]) -> dict[str, AssessmentAnswer]:
    rows = db.scalars(
        select(AssessmentAnswer).where(AssessmentAnswer.question_id.in_([q.id for q in questions]))
    )
    return {r.question_id: r for r in rows}


def total_questions(db: Session, a: Assessment) -> int:
    return len(_questions(db, a))


def current_question(
    db: Session, a: Assessment, *, now: datetime | None = None
) -> AssessmentQuestion | None:
    """The lowest-position question without an answer."""
    qs = _questions(db, a)
    answered = _answers(db, qs)
    return next((q for q in qs if q.id not in answered), None)


def start(db: Session, a: Assessment, *, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    finalize_if_expired(db, a, now=now)  # a stale `ready` becomes `expired`
    if a.status != AssessmentStatus.ready:
        raise HTTPException(409, f"cannot start an assessment that is {a.status}")
    a.started_at, a.deadline = now, now + TIME_LIMIT
    a.status = AssessmentStatus.in_progress
    db.commit()


def finalize_if_expired(db: Session, a: Assessment, *, now: datetime | None = None) -> bool:
    """Expire an unstarted assessment after 7 days; submit a running one past its deadline."""
    now = now or datetime.now(UTC)
    if a.status == AssessmentStatus.ready and now > a.created_at + START_WINDOW:
        a.status = AssessmentStatus.expired
        db.commit()
        return True
    if a.status == AssessmentStatus.in_progress and now > a.deadline:
        submit(db, a, now=now)
        return True
    return False


def record_answer(
    db: Session,
    a: Assessment,
    question_id: str,
    *,
    choice_index: int | None = None,
    text: str | None = None,
    now: datetime | None = None,
) -> None:
    now = now or datetime.now(UTC)
    if finalize_if_expired(db, a, now=now):
        raise HTTPException(409, "time is up")
    if a.status != AssessmentStatus.in_progress:
        raise HTTPException(409, f"assessment is {a.status}")
    q = current_question(db, a)
    if q is None or q.id != question_id:
        raise HTTPException(409, "not the current question")
    if q.kind == QuestionKind.mcq:
        if text is not None or choice_index is None or not 0 <= choice_index <= 3:
            raise HTTPException(422, "answer with choice_index 0-3")
        ans = AssessmentAnswer(question_id=q.id, choice_index=choice_index, answered_at=now)
    else:
        if choice_index is not None or text is None:
            raise HTTPException(422, "answer with text")
        try:
            clean, removed = sanitize_text_report(text, MAX_ANSWER_CHARS)
        except EmptyInput:
            clean, removed = "", {}
        except InputTooLarge:
            raise HTTPException(422, f"answer longer than {MAX_ANSWER_CHARS} characters") from None
        flags = [dataclasses.asdict(f) for f in scan(clean, removed)]  # informational only
        ans = AssessmentAnswer(question_id=q.id, text=clean, injection_flags=flags, answered_at=now)
    db.add(ans)
    db.commit()
    if current_question(db, a) is None:
        submit(db, a, now=now)


def submit(db: Session, a: Assessment, *, now: datetime | None = None) -> None:
    """Idempotent. MCQs are graded now; unanswered questions score 0."""
    if a.status in _DONE:
        return
    if a.status != AssessmentStatus.in_progress:
        raise HTTPException(409, f"cannot submit an assessment that is {a.status}")
    now = now or datetime.now(UTC)
    qs = _questions(db, a)
    answers = _answers(db, qs)
    for q in qs:
        ans = answers.get(q.id)
        if ans is None:
            db.add(AssessmentAnswer(question_id=q.id, points=0.0, answered_at=now))
        elif q.kind == QuestionKind.mcq:
            ans.points = 1.0 if ans.choice_index == q.correct_index else 0.0
    a.status = AssessmentStatus.submitted
    a.submitted_at = min(now, a.deadline)  # time taken never exceeds the limit
    if any(q.kind == QuestionKind.short for q in qs):
        owner = db.get(User, a.profile_id)  # profile_id is the owner's user id
        enqueue(db, owner, JobKind.assessment_grade, {"assessment_id": a.id})  # commits
    else:
        db.flush()
        grade.finalize(db, a, now=now)
