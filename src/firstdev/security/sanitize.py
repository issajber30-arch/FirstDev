# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import re
import unicodedata


class EmptyInput(ValueError):
    pass


class InputTooLarge(ValueError):
    def __init__(self, length: int, max_chars: int):
        super().__init__(f"input too large: {length} > {max_chars} characters")
        self.length = length
        self.max_chars = max_chars


_ZERO_WIDTH = "​‌‍⁠﻿"
# LRM/RLM (U+200E/F) are deliberately not here: Hebrew text needs them.
_BIDI = "‪‫‬‭‮⁦⁧⁨⁩"
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # keeps \t (09) and \n (0a)
_ZERO_WIDTH_RE = re.compile(f"[{_ZERO_WIDTH}]")
_BIDI_RE = re.compile(f"[{_BIDI}]")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def sanitize_text_report(text: str, max_chars: int = 60_000) -> tuple[str, dict[str, int]]:
    """Clean untrusted text for the LLM; returns (text, counts of removed characters)."""
    # Newlines first: \r would otherwise be counted and stripped as a control char.
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    report = {"control": 0, "zero_width": 0, "bidi": 0}
    for key, rx in (("control", _CONTROL_RE), ("zero_width", _ZERO_WIDTH_RE), ("bidi", _BIDI_RE)):
        text, report[key] = rx.subn("", text)
    text = _BLANK_RUN_RE.sub("\n\n", text).strip()
    if not text:
        raise EmptyInput("no text content")
    if len(text) > max_chars:
        raise InputTooLarge(len(text), max_chars)  # never truncate silently
    return text, report


def sanitize_text(text: str, max_chars: int = 60_000) -> str:
    return sanitize_text_report(text, max_chars)[0]
