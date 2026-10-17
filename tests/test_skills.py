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


GERESH = "׳"
HEBREW = {
    "פייתון": "python",
    "ג׳אווהסקריפט": "javascript",
    "ג'אווהסקריפט": "javascript",
    "טייפסקריפט": "typescript",
    "ריאקט": "react",
    "נוד": "node.js",
    "נוד.ג׳ייאס": "node.js",
    "נוד.ג'ייאס": "node.js",
    "ג׳אווה": "java",
    "ג'אווה": "java",
    "דוקר": "docker",
    "קוברנטיס": "kubernetes",
    "פוסטגרס": "postgresql",
    "מונגו": "mongodb",
    "גיט": "git",
    "לינוקס": "linux",
    "אנגולר": "angular",
    "וויו": "vue",
    "ג׳נגו": "django",
    "ג'נגו": "django",
    "פלאסק": "flask",
    "סי שארפ": "c#",
    "סי פלוס פלוס": "c++",
}


@pytest.mark.parametrize(("raw", "want"), list(HEBREW.items()))
def test_hebrew_aliases(raw, want):
    assert normalize_skill(raw) == want


def test_hebrew_table_covers_both_geresh_forms():
    assert any(GERESH in k for k in HEBREW) and any("'" in k for k in HEBREW)
    assert (
        normalize_skill(f"ג{GERESH}אווהסקריפט") == normalize_skill("ג'אווהסקריפט") == "javascript"
    )


def test_hebrew_alias_tolerates_spacing_and_unrelated_hebrew_is_untouched():
    assert normalize_skill("  סי   שארפ ") == "c#"
    assert normalize_skill("שלום") == "שלום"
    assert normalize_skill("פייתון3") == "פייתון3"  # exact keys only
