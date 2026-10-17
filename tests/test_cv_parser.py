# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from datetime import date

import pytest

from firstdev.pipelines.cv_parser import (
    _norm,
    evidence_ok,
    parse_date,
    validate_extraction,
)
from firstdev.schemas.cv import CVExtraction, Education, Experience, Skill

TODAY = date(2026, 10, 17)


def skill(name="Python", quote="Python", years=None):
    return Skill(name=name, category="language", years=years, evidence_quote=quote)


def exp(start, end, quote="Dev at Acme", title="Dev", company="Acme", description=None):
    return Experience(
        title=title,
        company=company,
        start=start,
        end=end,
        description=description,
        evidence_quote=quote,
    )


def run(source="Python Dev at Acme", *, skills=(), experience=(), education=(), langs=()):
    ext = CVExtraction(
        skills=list(skills),
        experience=list(experience),
        education=list(education),
        languages_spoken=list(langs),
        summary=None,
    )
    return validate_extraction(ext, source, today=TODAY)


# --- evidence ---


def test_evidence_exact_case_whitespace():
    src = _norm("I   worked with\nPYTHON for 3 years")
    assert evidence_ok("worked with Python", src)
    assert evidence_ok("  python   for\t3 years ", src)


def test_evidence_hebrew_with_direction_marks():
    src = _norm("‏מפתח תוכנה בחברת גוגל‏")
    assert evidence_ok("מפתח תוכנה", src)
    assert evidence_ok("‏מפתח‏ תוכנה בחברת גוגל", src)


def test_evidence_fabricated_and_empty_dropped():
    d = run(skills=[skill(quote="Rust expert"), skill(quote=""), skill(quote="   "), skill()])
    assert [s.name for s in d.skills] == ["Python"]
    assert [x.reason for x in d.dropped] == ["evidence_not_found"] * 3


# --- dates ---


@pytest.mark.parametrize(
    ("value", "is_end", "expected"),
    [
        ("2020", False, "2020"),
        ("2020-05", False, "2020-05"),
        (" 2020-05 ", True, "2020-05"),
        ("present", True, "present"),
        ("PRESENT", True, "present"),
        ("היום", True, "present"),
        ("כיום", True, "present"),
        (None, True, None),
        ("", False, None),
    ],
)
def test_parse_date_valid(value, is_end, expected):
    assert parse_date(value, is_end=is_end, today=TODAY) == expected


@pytest.mark.parametrize(
    ("value", "is_end"),
    [
        ("2020-13", False),
        ("2020-00", False),
        ("1900", False),
        ("2028", False),
        ("garbage", True),
        ("present", False),
        ("2020-5", False),
        ("May 2020", False),
    ],
)
def test_parse_date_invalid(value, is_end):
    with pytest.raises(ValueError, match="date"):
        parse_date(value, is_end=is_end, today=TODAY)


def test_boundary_years_accepted():
    assert parse_date("1950", is_end=False, today=TODAY) == "1950"
    assert parse_date("2027", is_end=True, today=TODAY) == "2027"


def test_invalid_date_keeps_item_and_records():
    d = run(experience=[exp("2020-13", "garbage")])
    assert len(d.experience) == 1
    assert (d.experience[0].start, d.experience[0].end) == (None, None)
    assert [x.reason for x in d.dropped] == ["invalid_date"] * 2


def test_date_order_drops_item():
    d = run(experience=[exp("2021-05", "2020-01")])
    assert d.experience == [] and [x.reason for x in d.dropped] == ["date_order"]
    edu = Education(
        institution="Acme", degree=None, field=None, start="2022", end="2020", evidence_quote="Acme"
    )
    d = run(education=[edu])
    assert d.education == [] and d.dropped[0].reason == "date_order"


def test_same_year_not_out_of_order():
    assert len(run(experience=[exp("2020", "2020")]).experience) == 1


# --- gaps ---


def gaps(*pairs):
    d = run(experience=[exp(s, e) for s, e in pairs])
    return [(g.start, g.end, g.months) for g in d.gaps]


def test_no_gaps_and_adjacent():
    assert gaps(("2020-01", "2020-06"), ("2020-07", "2021-01")) == []
    assert gaps(("2020-01", "2020-06"), ("2020-09", "2021-01")) == []  # 2 months < 3


def test_overlapping_merged():
    assert gaps(("2020-01", "2021-12"), ("2020-06", "2020-08"), ("2021-06", "2022-03")) == []


def test_six_month_gap():
    assert gaps(("2019-01", "2020-06"), ("2021-01", "2022-01")) == [("2020-07", "2020-12", 6)]


def test_exactly_three_months_reported():
    assert gaps(("2020-01", "2020-06"), ("2020-10", "2021-01")) == [("2020-07", "2020-09", 3)]


def test_present_uses_today():
    assert gaps(("2019-01", "2020-01"), ("2022-01", "present")) == [("2020-02", "2021-12", 23)]
    assert gaps(("2019-01", "2019-06"), ("2026-10", "present")) != []  # sanity: today is 2026-10


def test_single_job_none_end_and_unsorted():
    assert gaps(("2020-01", "2021-01")) == []
    d = run(experience=[exp("2020-01", None), exp(None, "2021-01"), exp("2024-01", "2024-06")])
    assert d.gaps == []  # items without start+end are ignored
    assert gaps(("2021-01", "2022-01"), ("2018-01", "2019-01")) == [("2019-02", "2020-12", 23)]


def test_year_only_dates():
    assert gaps(("2018", "2019"), ("2021", "2022")) == [("2020-01", "2020-12", 12)]


# --- caps, truncation, bounds ---


def test_list_caps():
    d = run(
        source="Python",
        skills=[skill() for _ in range(151)],
        experience=[exp(None, None, quote="Python") for _ in range(51)],
        education=[
            Education(
                institution="x",
                degree=None,
                field=None,
                start=None,
                end=None,
                evidence_quote="Python",
            )
            for _ in range(21)
        ],
        langs=[str(i) for i in range(51)],
    )
    assert (len(d.skills), len(d.experience), len(d.education), len(d.languages_spoken)) == (
        150,
        50,
        20,
        50,
    )
    assert sorted(x.section for x in d.dropped) == [
        "education",
        "experience",
        "languages_spoken",
        "skills",
    ]
    assert all(x.reason == "list_cap" for x in d.dropped)


def test_string_truncation():
    long = "a" * 5000
    d = run(
        source=long,
        skills=[skill(name=long, quote=long)],
        experience=[exp(None, None, quote=long, title=long, company=long, description=long)],
    )
    assert len(d.skills[0].name) == 200 and len(d.skills[0].evidence_quote) == 200
    e = d.experience[0]
    assert (len(e.title), len(e.company), len(e.description)) == (200, 200, 2000)
    ext = CVExtraction(skills=[], experience=[], education=[], languages_spoken=[], summary=long)
    assert len(validate_extraction(ext, "x", today=TODAY).summary) == 2000


@pytest.mark.parametrize(
    ("years", "expected"),
    [(0, 0), (60, 60), (2.5, 2.5), (60.1, None), (-1, None), (float("nan"), None), (None, None)],
)
def test_years_bounds(years, expected):
    assert run(skills=[skill(years=years)]).skills[0].years == expected
