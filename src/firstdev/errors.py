# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Shared error bases so the job runner can treat retryable failures uniformly."""


class TransientError(Exception):
    """A failure that may succeed if the job is retried later (rate limit, 5xx, timeout)."""
