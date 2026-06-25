"""Language and clipboard content classification helpers."""
from __future__ import annotations

import re
from typing import Dict

CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
ENGLISH_LETTER_RE = re.compile(r"[A-Za-z]")
ENGLISH_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z'-]*\b")
URL_RE = re.compile(r"^https?://\S+$", re.I)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:\\")


def analyze_text(text: str) -> Dict[str, float | int | bool]:
    visible = [ch for ch in text if not ch.isspace()]
    total = max(len(visible), 1)
    english_letters = len(ENGLISH_LETTER_RE.findall(text))
    chinese_chars = len(CHINESE_RE.findall(text))
    words = ENGLISH_WORD_RE.findall(text)
    return {
        "total": total,
        "english_letters": english_letters,
        "chinese_chars": chinese_chars,
        "english_ratio": english_letters / total,
        "chinese_ratio": chinese_chars / total,
        "word_count": len(words),
        "is_url": bool(URL_RE.match(text.strip())),
        "is_email": bool(EMAIL_RE.match(text.strip())),
        "is_windows_path": bool(WINDOWS_PATH_RE.match(text.strip())),
    }


def is_english_text(text: str, english_threshold: float = 0.5, chinese_threshold: float = 0.1) -> bool:
    if not text or not text.strip():
        return False
    info = analyze_text(text)
    if info["is_url"] or info["is_email"] or info["is_windows_path"]:
        return False
    if int(info["word_count"]) < 1:
        return False
    return float(info["english_ratio"]) >= english_threshold and float(info["chinese_ratio"]) <= chinese_threshold
