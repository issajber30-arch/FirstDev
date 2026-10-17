# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Entrypoint: python -m firstdev.worker"""

import logging

from sqlalchemy.orm import sessionmaker

from firstdev.db import get_engine
from firstdev.jobs import worker_main
from firstdev.llm import get_llm

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    worker_main(sessionmaker(get_engine(), expire_on_commit=False), get_llm())
