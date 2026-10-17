# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Direct-insert fixtures for assessment tests (no LLM, no generation job)."""

from firstdev.models import (
    Application,
    Assessment,
    AssessmentKind,
    AssessmentQuestion,
    AssessmentStatus,
)

OPTIONS = ["alpha", "beta", "gamma", "delta"]
RUBRIC = [{"criterion": "first idea", "points": 4}, {"criterion": "second idea", "points": 6}]
KEY_FIELDS = ("correct_index", "explanation", "rubric", "model_answer", "criteria", "points")


def seed(db, profile, *, kind=AssessmentKind.practice, status=AssessmentStatus.ready,
         posting=None, application=None, skills=("python", "sql"), **kw):  # fmt: skip
    """8 questions: 3 MCQ per skill (correct = index 1) then 1 short per skill (rubric 4 + 6)."""
    a = Assessment(
        profile_id=profile.user_id, kind=kind, status=status, skills=list(skills),
        posting_id=posting.id if posting else None,
        application_id=application.id if application else None, **kw,
    )  # fmt: skip
    db.add(a)
    db.flush()
    pos = 0
    for s in skills:
        for n in range(3):
            db.add(AssessmentQuestion(
                assessment_id=a.id, position=pos, kind="mcq", skill=s, difficulty=1,
                prompt=f"{s} mcq {n}", options=OPTIONS, correct_index=1,
                explanation=f"{s} because {n}",
            ))  # fmt: skip
            pos += 1
    for s in skills:
        db.add(AssessmentQuestion(
            assessment_id=a.id, position=pos, kind="short", skill=s, difficulty=2,
            prompt=f"{s} explain", rubric=RUBRIC, model_answer=f"{s} model answer",
        ))  # fmt: skip
        pos += 1
    db.commit()
    return a


def apply_to(db, profile, posting):
    app = Application(job_posting_id=posting.id, profile_id=profile.user_id)
    db.add(app)
    db.commit()
    return app
