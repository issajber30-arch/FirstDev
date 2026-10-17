# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
"""Deterministic match score. Only skills and tier feed it, never gaps, names or contacts."""

# proven in a repo or by a passed assessment vs claimed in the CV with evidence
CREDIT = {"repo": 1.0, "assessment": 1.0, "cv": 0.6}
TIER_FIT = {
    ("junior", "junior"): 1.0,
    ("mid", "mid"): 1.0,
    ("junior", "mid"): 0.5,
    ("mid", "junior"): 0.75,
}  # (candidate, posting)


def base_score(skills, tier, posting, equivalences=None):
    """Return (base, components); components make every term of the score auditable."""
    have = {s["skill"]: s["level"] for s in skills}
    eq = equivalences or {}

    def credit(req: str) -> tuple[float, str | None]:
        level = have.get(req) or have.get(eq.get(req, ""))
        return (CREDIT[level], level) if level else (0.0, None)

    def coverage(names: list[str], empty: float) -> tuple[float, list[dict]]:
        detail = [{"skill": n, "level": credit(n)[1], "credit": credit(n)[0]} for n in names]
        return (sum(d["credit"] for d in detail) / len(names) if names else empty), detail

    req_cov, req_detail = coverage(posting.required_skills, 1.0)
    opt_cov, opt_detail = coverage(posting.optional_skills, 0.0)
    fit = TIER_FIT.get((tier, posting.tier), 1.0 if posting.tier is None else 0.5)
    base = 70 * req_cov + 15 * opt_cov + 15 * fit
    return base, {
        "required_cov": req_cov,
        "optional_cov": opt_cov,
        "tier_fit": fit,
        "required": req_detail,
        "optional": opt_detail,
    }


def apply_review(base: float, adjustment: int) -> int:
    return max(0, min(100, round(base + max(-10, min(10, adjustment)))))
