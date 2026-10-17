# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""One canonical spelling per skill so CVs, repos and postings compare equal."""

import re
import unicodedata
from collections.abc import Iterable

ALIASES: dict[str, str] = {
    "js": "javascript",
    "ecmascript": "javascript",
    "ts": "typescript",
    "py": "python",
    "python3": "python",
    "golang": "go",
    "postgres": "postgresql",
    "psql": "postgresql",
    "pg": "postgresql",
    "mongo": "mongodb",
    "k8s": "kubernetes",
    "node": "node.js",
    "nodejs": "node.js",
    "react.js": "react",
    "reactjs": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "next": "next.js",
    "nextjs": "next.js",
    "dotnet": ".net",
    "csharp": "c#",
    "cpp": "c++",
    "aws cloud": "aws",
    "amazon web services": "aws",
    "gcp": "google cloud",
    "ci/cd": "ci",
    "github actions": "ci",
    "sklearn": "scikit-learn",
    "tf": "terraform",
}

# Package names (casefolded) that prove a skill when found in a repo's manifests.
DEPENDENCY_SKILLS: dict[str, str] = {
    "fastapi": "fastapi",
    "django": "django",
    "flask": "flask",
    "sqlalchemy": "sqlalchemy",
    "psycopg": "postgresql",
    "psycopg2": "postgresql",
    "psycopg2-binary": "postgresql",
    "asyncpg": "postgresql",
    "pg": "postgresql",
    "pymongo": "mongodb",
    "mongoose": "mongodb",
    "redis": "redis",
    "celery": "celery",
    "pytest": "pytest",
    "pandas": "pandas",
    "numpy": "numpy",
    "scikit-learn": "scikit-learn",
    "torch": "pytorch",
    "tensorflow": "tensorflow",
    "react": "react",
    "react-dom": "react",
    "next": "next.js",
    "vue": "vue",
    "@angular/core": "angular",
    "express": "express",
    "jest": "jest",
    "typescript": "typescript",
    "tailwindcss": "tailwind",
    "prisma": "prisma",
    "graphql": "graphql",
    "docker": "docker",
    "boto3": "aws",
    "gin-gonic/gin": "gin",
    "tokio": "tokio",
    "serde": "serde",
    "pydantic": "pydantic",
    "anthropic": "llm apis",
}

_SPACES = re.compile(r"\s+")


def normalize_skill(s: str) -> str | None:
    s = _SPACES.sub(" ", unicodedata.normalize("NFKC", s)).strip().casefold()
    if not s or len(s) > 60:
        return None
    return ALIASES.get(s, s)  # exact-key lookup only: never collapse C#/C++ into C


def normalize_skills(xs: Iterable[str]) -> list[str]:
    return sorted({n for x in xs if (n := normalize_skill(x))})
