# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest

from firstdev.skills import normalize_skill, normalize_skills


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("JS", "javascript"),
        (" Postgres ", "postgresql"),
        ("C#", "c#"),
        ("C++", "c++"),
        ("C", "c"),
        (".NET", ".net"),
        ("Node.js", "node.js"),
        ("NodeJS", "node.js"),
        ("פייתון", "פייתון"),
        ("ＰＹＴＨＯＮ", "python"),
        ("", None),
        ("   ", None),
        ("x" * 61, None),
        ("x" * 60, "x" * 60),
    ],
)
def test_normalize_skill(raw, want):
    assert normalize_skill(raw) == want


def test_normalize_skills_sorted_unique():
    assert normalize_skills(["JS", "javascript", "Python", ""]) == ["javascript", "python"]


def test_distinct_skills_never_collapse():
    assert len(set(normalize_skills(["C", "C#", "C++"]))) == 3
