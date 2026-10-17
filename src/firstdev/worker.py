# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Entrypoint: python -m firstdev.worker"""

import logging

from sqlalchemy.orm import sessionmaker

from firstdev.assessments import generate, grade  # noqa: F401  (import registers handlers)
from firstdev.db import get_engine
from firstdev.jobs import worker_main
from firstdev.llm import get_llm
from firstdev.pipelines import (  # noqa: F401  (import registers handlers)
    cv_parser,
    match_jobs,
    repo_analyzer,
)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker_main(sessionmaker(get_engine(), expire_on_commit=False), get_llm())
