# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
import re
from dataclasses import dataclass

# Heuristic, not a defense: these only produce flags for human review. The real defense is
# delimiters (wrap_untrusted) + no tools + schema-only output + evidence checks.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        kind,
        re.compile(rx, re.IGNORECASE),
    )
    for kind, rx in [
        (
            "instruction_override",
            r"\b(?:ignore|disregard|forget)\s+(?:(?:all|any|the)\s+)?"
            r"(?:previous|prior|above)\s+(?:instructions|prompts|rules)\b",
        ),
        ("instruction_override", r"התעלם\s+מ(?:כל\s+)?ה?הוראות"),
        ("role_hijack", r"\byou\s+are\s+now\b"),
        ("role_hijack", r"\bact\s+as\s+(?:an?|the)\s+(?:ai|assistant|system|recruiter)\b"),
        ("system_prompt", r"\bsystem\s+prompt\b"),
        ("delimiter_tag", r"<\s*/?\s*(?:system|assistant|untrusted_[a-z]+)\s*>"),
        (
            "score_manipulation",
            r"\b(?:give|assign|rate|score)\s+(?:me|this\s+(?:candidate|cv|resume))\s+"
            r"(?:an?\s+)?(?:\d{2,3}|perfect|maximum|top)\b",
        ),
        ("hire_directive", r"\bhire\s+(?:me|this\s+candidate)\b"),
        # Assessment answers: attempts to steer the grader rather than answer the question.
        (
            "grading_manipulation",
            r"\b(?:ignore|disregard|skip)\s+(?:the\s+|this\s+|your\s+)?"
            r"(?:rubric|grading|criteria|marking\s+scheme)\b",
        ),
        (
            "grading_manipulation",
            r"\b(?:award|give|grant|assign)\s+(?:me\s+|this\s+(?:answer|candidate)\s+)?"
            r"(?:full|maximum|max|all\s+(?:the\s+)?)\s*(?:marks|points|credit|score)\b",
        ),
    ]
]


@dataclass(frozen=True)
class InjectionFlag:
    kind: str
    excerpt: str  # at most 120 chars
    offset: int


def scan(text: str, removed: dict[str, int] | None = None) -> list[InjectionFlag]:
    """Informational only: never raises, never modifies text.

    `removed` is the report from sanitize_text_report; hidden characters are invisible by the
    time the text reaches us, so the caller passes in what sanitizing stripped.
    """
    flags = [
        InjectionFlag(kind, m.group(0)[:120], m.start())
        for kind, rx in _PATTERNS
        for m in rx.finditer(text)
    ]
    if removed and (removed.get("bidi", 0) or removed.get("zero_width", 0)):
        flags.append(InjectionFlag("hidden_characters", "bidi/zero-width characters removed", 0))
    return sorted(flags, key=lambda f: f.offset)


_TAG_RE = re.compile(r"[a-z_]{1,30}")
# Any "<" followed by optional "/" and "untrusted_" (whitespace tolerated) is an attempt to
# open or close our delimiter.
_DELIM_RE = re.compile(r"<(?=\s*/?\s*untrusted_)", re.IGNORECASE)


def _escape_attr(v: str) -> str:
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def wrap_untrusted(tag: str, content: str, attrs: dict[str, str] | None = None) -> str:
    if not _TAG_RE.fullmatch(tag):
        raise ValueError("invalid tag name")
    for k in attrs or {}:
        if not _TAG_RE.fullmatch(k):
            raise ValueError("invalid attribute name")
    attr_str = "".join(f' {k}="{_escape_attr(v)}"' for k, v in (attrs or {}).items())
    body = _DELIM_RE.sub("&lt;", content)
    return f"<untrusted_{tag}{attr_str}>\n{body}\n</untrusted_{tag}>"
