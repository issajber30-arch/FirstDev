# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Shared error bases so the job runner can treat retryable failures uniformly."""


class TransientError(Exception):
    """A failure that may succeed if the job is retried later (rate limit, 5xx, timeout)."""

    def __init__(self, *args: object, retry_after: float | None = None):
        super().__init__(*args)
        self.retry_after = retry_after  # seconds the remote service asked us to wait, if known
