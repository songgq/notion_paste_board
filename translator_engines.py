"""Simple translator engines with best-effort phonetic extraction.

These engines use public web endpoints and may change over time. All calls are
best-effort. `translate()` keeps backward compatibility and returns only the
translation text; `translate_details()` also returns phonetic symbols when the
selected engine exposes them.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import logging
import re
from typing import Any, List, Optional
from urllib.parse import quote_plus

import requests


@dataclass
class TranslationResult:
    text: str = ""
    us_phonetic: str = ""
    uk_phonetic: str = ""
    phonetic: str = ""
    engine: str = ""

    @property
    def phonetic_display(self) -> str:
        parts: List[str] = []
        if self.us_phonetic:
            parts.append(f"美 {_wrap_phone(self.us_phonetic)}")
        if self.uk_phonetic:
            parts.append(f"英 {_wrap_phone(self.uk_phonetic)}")
        if not parts and self.phonetic:
            parts.append(_wrap_phone(self.phonetic))
        return "   ".join(parts)


def _wrap_phone(value: str) -> str:
    value = _clean(value)
    if not value:
        return ""
    # Many dictionary APIs already return `/.../` or `[ ... ]`.
    if (value.startswith("/") and value.endswith("/")) or (value.startswith("[") and value.endswith("]")):
        return value
    return f"/{value}/"


def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\\[nrtd]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _dedupe(values: List[str], original: str = "") -> List[str]:
    cleaned: List[str] = []
    original_norm = original.strip().lower()
    for c in values:
        c = _clean(str(c))
        if not c:
            continue
        if original_norm and c.lower() == original_norm:
            continue
        if c not in cleaned:
            cleaned.append(c)
    return cleaned


def translate(text: str, engine: str = "youdao", timeout: int = 3) -> str:
    return translate_details(text, engine, timeout).text


def translate_details(text: str, engine: str = "youdao", timeout: int = 3) -> TranslationResult:
    engine = (engine or "youdao").lower().strip()
    functions = {
        "youdao": translate_youdao_details,
        "google": translate_google_details,
        "iciba": translate_iciba_details,
        "bing": translate_bing_details,
    }

    # Try the selected engine first, then a short fallback chain without
    # repeating the same engine. This keeps worst-case waiting time lower.
    order = [engine, "youdao", "google"]
    tried: set[str] = set()
    last_phonetic = TranslationResult(engine=engine)
    for name in order:
        if name in tried:
            continue
        tried.add(name)
        fn = functions.get(name)
        if not fn:
            continue
        try:
            result = fn(text, timeout=timeout)
            # Keep any phonetics we found, even if this engine did not produce
            # the best translation text.
            if result.phonetic_display and not last_phonetic.phonetic_display:
                last_phonetic = result
            if result.text:
                if not result.phonetic_display and last_phonetic.phonetic_display:
                    result.us_phonetic = last_phonetic.us_phonetic
                    result.uk_phonetic = last_phonetic.uk_phonetic
                    result.phonetic = last_phonetic.phonetic
                return result
        except Exception as exc:  # noqa: BLE001
            level = logging.WARNING if name == engine else logging.DEBUG
            logging.log(level, "Translator %s failed: %s", name, exc)
    return last_phonetic if last_phonetic.phonetic_display else TranslationResult(engine=engine)


def translate_google_details(text: str, timeout: int = 4) -> TranslationResult:
    url = "https://translate.googleapis.com/translate_a/single"
    params = {"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": text}
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    parts = [seg[0] for seg in data[0] if seg and seg[0]]
    return TranslationResult(text=_clean("".join(parts)), engine="google")


def translate_youdao_details(text: str, timeout: int = 4) -> TranslationResult:
    url = "https://dict.youdao.com/jsonapi"
    params = {"xmlVersion": "5.1", "jsonversion": "2", "q": text}
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    data = r.json()
    candidates: List[str] = []
    us_phone = ""
    uk_phone = ""
    generic_phone = ""

    us_keys = {"usphone", "us_phone", "amphone", "am_phone", "phone_us", "phonetic_us"}
    uk_keys = {"ukphone", "uk_phone", "enphone", "en_phone", "brphone", "br_phone", "phone_uk", "phonetic_uk"}
    generic_keys = {"phone", "phonetic", "phonetic_symbol"}

    def walk(obj: Any) -> None:
        nonlocal us_phone, uk_phone, generic_phone
        if isinstance(obj, dict):
            # Common Youdao structures.
            if "tran" in obj and isinstance(obj["tran"], str):
                candidates.append(obj["tran"])
            if "value" in obj and isinstance(obj["value"], str):
                candidates.append(obj["value"])
            if "l" in obj and isinstance(obj["l"], dict):
                i = obj["l"].get("i")
                if isinstance(i, str):
                    candidates.append(i)
                elif isinstance(i, list):
                    candidates.extend(str(x) for x in i if x)
            for key, value in obj.items():
                key_norm = str(key).lower().replace("-", "_")
                if isinstance(value, str):
                    val = _clean(value)
                    if key_norm in us_keys and val and not us_phone:
                        us_phone = val
                    elif key_norm in uk_keys and val and not uk_phone:
                        uk_phone = val
                    elif key_norm in generic_keys and val and not generic_phone:
                        generic_phone = val
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    cleaned = _dedupe(candidates, original=text)
    return TranslationResult(
        text="\n".join(cleaned[:6]),
        us_phonetic=us_phone,
        uk_phonetic=uk_phone,
        phonetic=generic_phone,
        engine="youdao",
    )


def translate_iciba_details(text: str, timeout: int = 4) -> TranslationResult:
    url = f"https://www.iciba.com/word?w={quote_plus(text)}"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    html_text = r.text
    matches = re.findall(r'"part_name"\s*:\s*"(.*?)".*?"means"\s*:\s*\[(.*?)\]', html_text, flags=re.S)
    lines: List[str] = []
    for part, means_blob in matches[:8]:
        means = re.findall(r'"(.*?)"', means_blob)
        if means:
            lines.append(f"{_clean(part)} {'；'.join(_clean(m) for m in means[:4])}")
    us = _first_match(html_text, [r'"ph_am"\s*:\s*"(.*?)"', r'"phone_am"\s*:\s*"(.*?)"'])
    uk = _first_match(html_text, [r'"ph_en"\s*:\s*"(.*?)"', r'"phone_en"\s*:\s*"(.*?)"'])
    return TranslationResult(text="\n".join(lines), us_phonetic=us, uk_phonetic=uk, engine="iciba")


def translate_bing_details(text: str, timeout: int = 4) -> TranslationResult:
    url = f"https://cn.bing.com/dict/search?q={quote_plus(text)}"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    html_text = r.text
    matches = re.findall(r'<span class="pos">(.*?)</span>\s*<span class="def">(.*?)</span>', html_text, flags=re.S)
    lines = [f"{_clean(pos)} {_clean(defn)}" for pos, defn in matches[:8]]
    us = _clean(re.sub("<.*?>", "", _first_match(html_text, [r'<div class="hd_prUS">(.*?)</div>', r'美\s*\[(.*?)\]'])))
    uk = _clean(re.sub("<.*?>", "", _first_match(html_text, [r'<div class="hd_pr">(.*?)</div>', r'英\s*\[(.*?)\]'])))
    return TranslationResult(text="\n".join(lines), us_phonetic=us, uk_phonetic=uk, engine="bing")


def _first_match(text: str, patterns: List[str]) -> str:
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.S)
        if m:
            return _clean(m.group(1))
    return ""


# Backward-compatible names used by older code/tests.
def translate_google(text: str, timeout: int = 4) -> str:
    return translate_google_details(text, timeout).text


def translate_youdao(text: str, timeout: int = 4) -> str:
    return translate_youdao_details(text, timeout).text


def translate_iciba(text: str, timeout: int = 4) -> str:
    return translate_iciba_details(text, timeout).text


def translate_bing(text: str, timeout: int = 4) -> str:
    return translate_bing_details(text, timeout).text
