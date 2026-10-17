# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Clone fixtures/demo_world.json into a fresh sandbox world, in ONE transaction.

Nothing here commits: the caller commits once at the end or rolls everything back. All text in
the fixture is hand-written; CV extractions go through the real `validate_extraction`, so the
stored shape (evidence checks, gaps) is exactly what the CV pipeline would have stored.
"""

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from firstdev import auth
from firstdev.assessments.grade import compute_scores, issue_badges, raw_skill_pcts
from firstdev.matching.profile import build_skill_profile
from firstdev.models import (
    Assessment,
    AssessmentAnswer,
    AssessmentKind,
    AssessmentQuestion,
    AssessmentStatus,
    CvDocument,
    CvParse,
    CvStatus,
    DeveloperProfile,
    Job,
    JobKind,
    JobPosting,
    MatchScore,
    PostingStatus,
    QuestionKind,
    RepoAnalysis,
    Repository,
    Role,
    SandboxCreation,
    Tier,
    User,
)
from firstdev.pipelines.cv_parser import validate_extraction
from firstdev.pipelines.match_jobs import score_and_store
from firstdev.schemas.cv import CVExtraction

# shortcut: the fixture is read from the source tree; ship it with the image (Part 6).
FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "demo_world.json"
LIFETIME = timedelta(hours=24)
FIXTURE_MODEL = "demo-fixture"


@lru_cache
def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _new_user(db: Session, *, role: Role, name: str, world: str, pw: str, exp: datetime) -> User:
    # .invalid never resolves, and the random local part keeps emails unguessable and unique.
    user = User(
        email=f"{uuid.uuid4().hex}@sandbox.invalid",
        password_hash=pw,
        role=role,
        display_name=name,
        world_id=world,
        expires_at=exp,
    )
    db.add(user)
    db.flush()
    return user


def _add_developer(db: Session, dev: dict, user: User, now: datetime) -> DeveloperProfile:
    profile = DeveloperProfile(
        user_id=user.id,
        headline=dev["headline"],
        bio=dev["bio"],
        location=dev["location"],
        experience_tier=Tier(dev["tier"]),
        open_to_opportunities=dev["open_to_opportunities"],
    )
    db.add(profile)
    db.flush()
    text = dev["cv_text"]
    doc = CvDocument(
        profile_id=user.id,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        size=len(text.encode()),
        status=CvStatus.parsed,
        extracted_text=text,
        injection_flags=[],
    )
    db.add(doc)
    db.flush()
    data = validate_extraction(CVExtraction(**dev["cv"]), text)
    db.add(
        CvParse(
            cv_document_id=doc.id,
            schema_version=data.schema_version,
            model=FIXTURE_MODEL,
            data=data.model_dump(mode="json"),
        )
    )
    for r in dev["repos"]:
        repo = Repository(
            profile_id=user.id,
            owner=r["owner"],
            name=r["name"],
            is_fork=r["is_fork"],
            stars=r["stars"],
            pushed_at=now - timedelta(days=r["pushed_days_ago"]),
        )
        db.add(repo)
        db.flush()
        db.add(
            RepoAnalysis(
                repository_id=repo.id,
                commit_sha=r["commit_sha"],
                metrics=r["metrics"],
                assessment=r["assessment"],
                tutorial_likelihood=r["tutorial_likelihood"],
                model=FIXTURE_MODEL,
            )
        )
    db.flush()
    if dev.get("assessment"):
        _add_assessment(db, dev["assessment"], profile, now)
    build_skill_profile(db, profile, now=now, commit=False)  # after badges: fingerprints settle
    db.add(Job(user_id=user.id, kind=JobKind.embed_profile, payload={"profile_id": user.id}))
    return profile


def _add_assessment(db: Session, spec: dict, profile: DeveloperProfile, now: datetime) -> None:
    started = now - timedelta(days=spec["taken_days_ago"])
    a = Assessment(
        profile_id=profile.user_id,
        kind=AssessmentKind.practice,
        status=AssessmentStatus.graded,
        skills=spec["skills"],
        created_by=None,  # not a visitor-triggered assessment: sandbox quotas ignore it
        started_at=started,
        deadline=started + timedelta(minutes=20),
        submitted_at=started + timedelta(minutes=spec["minutes_taken"]),
        graded_at=started + timedelta(minutes=spec["minutes_taken"]),
    )
    db.add(a)
    db.flush()
    questions, answers = [], []
    for pos, q in enumerate(spec["questions"]):
        row = AssessmentQuestion(
            assessment_id=a.id,
            position=pos,
            kind=QuestionKind(q["kind"]),
            skill=q["skill"],
            difficulty=q["difficulty"],
            prompt=q["prompt"],
            options=q.get("options"),
            correct_index=q.get("correct_index"),
            explanation=q.get("explanation"),
            rubric=q.get("rubric"),
            model_answer=q.get("model_answer"),
        )
        db.add(row)
        db.flush()
        ans = AssessmentAnswer(
            question_id=row.id,
            choice_index=q.get("answer_index"),
            text=q.get("answer_text"),
            points=q["points"],
            criteria_met=q.get("criteria_met"),
            feedback=q.get("feedback"),
            injection_flags=[],
            answered_at=started + timedelta(minutes=pos + 1),
        )
        db.add(ans)
        questions.append(row)
        answers.append(ans)
    db.flush()
    a.overall_pct, a.skill_pcts = compute_scores(questions, answers)
    issue_badges(db, a, now=now, raw=raw_skill_pcts(questions, answers))


def create_sandbox(db: Session, role: str, ip_hash: str) -> User:
    """Build a whole world and return the visitor's user. Caller commits (or rolls back)."""
    fx = load_fixture()
    now = datetime.now(UTC)
    exp = now + LIFETIME
    world = str(uuid.uuid4())
    # One unusable hash for the whole world: a random secret nobody ever sees, so no persona
    # (and not the visitor) can ever log in by password. The visitor holds a session instead.
    pw = auth.hash_password(secrets.token_urlsafe(32))
    visitor_is_recruiter = role == "recruiter"

    recruiter = _new_user(
        db,
        role=Role.recruiter,
        name=fx["visitor"]["recruiter_name"] if visitor_is_recruiter else fx["recruiter"]["name"],
        world=world,
        pw=pw,
        exp=exp,
    )
    postings: dict[str, JobPosting] = {}
    for p in fx["postings"]:
        posting = JobPosting(
            recruiter_id=recruiter.id,
            title=p["title"],
            description=p["description"],
            required_skills=p["required_skills"],
            optional_skills=p["optional_skills"],
            tier=Tier(p["tier"]),
            salary_min=p["salary_min"],
            salary_max=p["salary_max"],
            currency=p["currency"],
            location=p["location"],
            remote=p["remote"],
            injection_flags=[],
            auto_assessment=False,  # sandboxes never auto-spend LLM budget
            status=PostingStatus.open,
        )
        db.add(posting)
        postings[p["key"]] = posting
    db.flush()

    # (profile, fixture key) for everyone who gets match scores.
    devs: list[tuple[DeveloperProfile, str]] = []
    visitor = recruiter
    for dev in fx["developers"]:
        user = _new_user(
            db, role=Role.developer, name=dev["display_name"], world=world, pw=pw, exp=exp
        )
        devs.append((_add_developer(db, dev, user, now), dev["key"]))
    if not visitor_is_recruiter:
        template = next(
            d for d in fx["developers"] if d["key"] == fx["visitor"]["developer_template"]
        )
        visitor = _new_user(
            db,
            role=Role.developer,
            name=fx["visitor"]["developer_name"],
            world=world,
            pw=pw,
            exp=exp,
        )
        devs.append((_add_developer(db, template, visitor, now), template["key"]))

    # Scores: formula first (fingerprints come from the freshly built skill profiles), then the
    # hand-written reasons and feedback on top, marked explained so nothing re-spends LLM calls.
    for profile, key in devs:
        for pkey, posting in postings.items():
            ms: MatchScore = score_and_store(
                db, None, posting=posting, profile=profile, explain=False, commit_profile=False
            )  # type: ignore[arg-type]  # explain=False never touches the LLM
            written = fx["matches"].get(key, {}).get(pkey)
            if written:
                ms.reasons, ms.feedback = written["reasons"], written["feedback"]
                ms.explained, ms.model = True, FIXTURE_MODEL

    for posting in postings.values():
        db.add(
            Job(
                user_id=recruiter.id, kind=JobKind.embed_posting, payload={"posting_id": posting.id}
            )
        )
    db.add(SandboxCreation(ip_hash=ip_hash))  # counted only if the clone succeeds
    db.commit()  # the one commit: the world exists completely or not at all
    return visitor
