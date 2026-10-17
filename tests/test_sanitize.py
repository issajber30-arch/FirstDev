# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import pytest

from firstdev.security.sanitize import (
    EmptyInput,
    InputTooLarge,
    sanitize_text,
    sanitize_text_report,
)


def test_nfkc_and_newlines():
    assert sanitize_text("ﬁneＡ\r\nx\ry") == "fineA\nx\ny"


def test_removed_categories_counted():
    text, rep = sanitize_text_report("a\x00b\x07​c‮d⁦e\x85f")
    assert text == "abcdef"
    assert rep == {"control": 3, "zero_width": 1, "bidi": 2}


def test_keeps_tab_newline_lrm_rlm_hebrew_emoji():
    s = "שלום‏ world‎\t🚀\nok"
    assert sanitize_text(s) == s


def test_collapses_blank_lines_and_strips():
    assert sanitize_text("\n\n a\n\n\n\n\nb \n\n") == "a\n\nb"


def test_limits():
    assert len(sanitize_text("a" * 60_000)) == 60_000
    with pytest.raises(InputTooLarge) as e:
        sanitize_text("a" * 60_001)
    assert e.value.length == 60_001


@pytest.mark.parametrize("s", ["", "   \n\t", "​\x00"])
def test_empty_raises(s):
    with pytest.raises(EmptyInput):
        sanitize_text(s)
