# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Fingerprints that decide when a cached embedding or match score is stale."""

import hashlib
import json

from firstdev.models import JobPosting


def posting_fingerprint(posting: JobPosting) -> str:
    """sha256 of the fields that influence matching."""
    data = {
        "title": posting.title,
        "description": posting.description,
        "required_skills": posting.required_skills,
        "optional_skills": posting.optional_skills,
        "tier": posting.tier,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
