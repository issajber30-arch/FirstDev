# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""CannedLLM: the free `FIRSTDEV_LLM_MODE=fake` backend.

Returns deterministic outputs built from the input text, shaped so every code-side validator
(evidence checks, skill allowlists, rubric rules) accepts them. It parses the prompt blocks with
regexes and only reads them: nothing in the input is ever executed or followed. It makes no API
call and writes no budget ledger rows.
"""

import html
import json
import re

from pydantic import BaseModel

from firstdev.assessments.generate import (
    GeneratedAssessment,
    GeneratedQuestion,
    RubricItem,
)
from firstdev.assessments.grade import GradeItem, GradeResult
from firstdev.llm import LLMContext, LLMPermanentError, LLMResult
from firstdev.matching.explain import Feedback, MatchReview
from firstdev.schemas.cv import CVExtraction, Experience, Skill
from firstdev.schemas.repo import BestPractice, RepoAssessment
from firstdev.skills import ALIASES, normalize_skill

# ALIASES alone misses plain names (they map to themselves implicitly), so add the common ones.
_COMMON = {"python", "java", "go", "rust", "sql", "docker", "kubernetes", "react", "git", "linux"}
_KNOWN_SKILLS = set(ALIASES) | set(ALIASES.values()) | _COMMON
_TOKEN = re.compile(r"[a-z][a-z0-9+#.]*")


def _block(tag: str, text: str) -> str:
    m = re.search(rf"<untrusted_{tag}[^>]*>\n(.*?)\n</untrusted_{tag}>", text, re.DOTALL)
    return m.group(1) if m else ""


def _json_block(tag: str, text: str) -> dict:
    try:
        data = json.loads(_block(tag, text))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _cv(content: str) -> CVExtraction:
    body = _block("cv", content)
    # Lines with "<" or "&" may have been escaped by wrap_untrusted, so they aren't verbatim.
    lines = [ln.strip()[:200] for ln in body.splitlines() if ln.strip()]
    lines = [ln for ln in lines if "<" not in ln and "&" not in ln]
    skills, seen = [], set()
    for line in lines:
        for tok in _TOKEN.findall(line.casefold()):
            tok = tok.rstrip(".")
            if tok in _KNOWN_SKILLS and (name := normalize_skill(tok)) and name not in seen:
                seen.add(name)
                skills.append(Skill(name=name, category="other", years=None, evidence_quote=line))
    experience = []
    if lines:
        experience.append(
            Experience(
                title=lines[0][:60],
                company="Canned Co",
                start=None,
                end=None,
                description=None,
                evidence_quote=lines[0],
            )
        )
    return CVExtraction(
        skills=skills[:10],
        experience=experience,
        education=[],
        languages_spoken=[],
        summary=lines[0] if lines else None,
    )


def _repo(content: str) -> RepoAssessment:
    paths = [html.unescape(p) for p in re.findall(r'<untrusted_file path="([^"]*)">', content)]
    return RepoAssessment(
        architecture_summary=f"Canned assessment of {len(paths)} files.",
        complexity=3,
        best_practices=[
            BestPractice(practice="Source files are present", observed=True, evidence_path=p)
            for p in paths[:3]
        ],
        tutorial_likelihood=0.2,
        tutorial_reasons=[],
        strengths=["Canned strength"],
        concerns=[],
    )


def _review(content: str) -> MatchReview:
    cand = _json_block("candidate", content)
    post = _json_block("posting", content)
    have = [s["skill"] for s in cand.get("skills", []) if isinstance(s, dict) and "skill" in s]
    wanted = [*post.get("required", []), *post.get("optional", [])]
    shared = [s for s in wanted if normalize_skill(str(s)) in have]
    missing = [s for s in wanted if normalize_skill(str(s)) not in have]
    return MatchReview(
        equivalences=[],
        adjustment=0,
        adjustment_reason="",
        reasons=[f"Canned review: {len(shared)} of {len(wanted)} posting skills matched"],
        feedback=Feedback(
            strengths=[str(s) for s in shared],
            missing_skills=[str(s) for s in missing],
            suggestions=[f"Build a small project using {s}" for s in missing[:3]],
        ),
    )


def _assessment(content: str) -> GeneratedAssessment:
    skills = [str(s) for s in _json_block("assessment_context", content).get("skills", [])]
    skills = skills[:3] or ["python"]
    qs = []
    for i in range(8):
        skill = skills[i % len(skills)]  # 8 questions over <=3 skills: every skill gets >= 2
        if i < 6:
            qs.append(
                GeneratedQuestion(
                    kind="mcq",
                    skill=skill,
                    difficulty=1 + i % 3,
                    prompt=f"Canned question {i + 1} about {skill}?",
                    options=[f"Option {c} for question {i + 1}" for c in "ABCD"],
                    correct_index=i % 4,
                    explanation="Canned explanation.",
                )
            )
        else:
            qs.append(
                GeneratedQuestion(
                    kind="short",
                    skill=skill,
                    difficulty=2,
                    prompt=f"Canned short question {i + 1}: explain a core idea of {skill}.",
                    rubric=[
                        RubricItem(criterion="States the core idea", points=3),
                        RubricItem(criterion="Gives an example", points=2),
                    ],
                    model_answer="Canned model answer.",
                )
            )
    return GeneratedAssessment(questions=qs)


def _grades(content: str) -> GradeResult:
    ids = dict.fromkeys(re.findall(r'<untrusted_candidate_answer question_id="([^"]*)">', content))
    return GradeResult(
        grades=[
            GradeItem(question_id=html.unescape(i), criteria_met=[0], feedback="Canned feedback.")
            for i in ids
        ]
    )


_BUILDERS = {
    CVExtraction: _cv,
    RepoAssessment: _repo,
    MatchReview: _review,
    GeneratedAssessment: _assessment,
    GradeResult: _grades,
}


class CannedLLM:
    def extract[T: BaseModel](
        self,
        schema: type[T],
        system: str,
        user_content: str,
        *,
        max_tokens: int = 16000,
        context: LLMContext | None = None,
    ) -> LLMResult[T]:
        build = _BUILDERS.get(schema)
        if build is None:
            raise LLMPermanentError(f"CannedLLM has no output for {schema.__name__}")
        return LLMResult(build(user_content), "canned", None, 0, 0)  # type: ignore[arg-type]
