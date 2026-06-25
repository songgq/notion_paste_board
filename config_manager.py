"""Configuration and token storage for Clipboard Assistant."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Tuple

APP_NAME = "notion_paste_board"
SERVICE_NAME = "notion_paste_board_notion"
LEGACY_SERVICE_NAME = "ClipboardAssistantNotion"
TOKEN_ACCOUNT = "notion_token"
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "notion_enabled": True,
    "notion_data_source_id": "",
    "notion_version": "2026-03-11",
    "uploader": "user",
    "translator_engine": "youdao",
    "popup_opacity": 0.85,
    "auto_close_delay": 6000,
    "popup_width": 400,
    "popup_height": 430,
    "monitor_enabled": True,
    "poll_interval_ms": 300,
    "max_text_length": 10000,
    "auto_popup_for_english": True,
    "show_icon_for_non_english": True,
    "icon_auto_hide_delay": 5000,
    "icon_hover_pause": True,
    "toast_icon_size": 34,
    "toast_icon_font_size": 14,
    "toast_opacity": 0.92,
    "english_letter_ratio_threshold": 0.50,
    "chinese_ratio_threshold": 0.10,
    "request_timeout_seconds": 2,
    "retry_enabled": True,
    "allow_plaintext_token_fallback": False,
    "field_names": {
        "title": "标题",
        "type": "类型",
        "uploader": "上传人",
        "original": "原文",
        "translated": "译文",
        "phonetic": "音标",
        "note": "备注",
        "created_at": "创建时间",
        "source": "来源",
        "attachment_name": "附件名",
        "attachment_path": "附件路径",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, data)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Failed to load config, using defaults: %s", exc)
        return dict(DEFAULT_CONFIG)


def save_config(config: Dict[str, Any]) -> None:
    safe_config = dict(config)
    # Never save token unless user explicitly enabled fallback.
    if not safe_config.get("allow_plaintext_token_fallback"):
        safe_config.pop("notion_token", None)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(safe_config, f, ensure_ascii=False, indent=2)


def _try_import_keyring():
    try:
        import keyring  # type: ignore

        return keyring
    except Exception as exc:  # noqa: BLE001
        logging.warning("keyring unavailable: %s", exc)
        return None


def get_notion_token(config: Dict[str, Any] | None = None) -> str:
    keyring = _try_import_keyring()
    if keyring:
        try:
            token = keyring.get_password(SERVICE_NAME, TOKEN_ACCOUNT)
            if token:
                return token
            # Backward compatible with older builds that saved the token under
            # ClipboardAssistantNotion. This avoids forcing users to paste the
            # Notion token again after renaming the app.
            token = keyring.get_password(LEGACY_SERVICE_NAME, TOKEN_ACCOUNT)
            if token:
                return token
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to read token from keyring: %s", exc)
    config = config or load_config()
    return str(config.get("notion_token", "") or "")


def set_notion_token(token: str, config: Dict[str, Any]) -> Tuple[bool, str]:
    token = token.strip()
    keyring = _try_import_keyring()
    if keyring:
        try:
            keyring.set_password(SERVICE_NAME, TOKEN_ACCOUNT, token)
            config.pop("notion_token", None)
            save_config(config)
            return True, "Token 已保存到系统凭据。"
        except Exception as exc:  # noqa: BLE001
            logging.warning("Failed to save token to keyring: %s", exc)

    if config.get("allow_plaintext_token_fallback"):
        config["notion_token"] = token
        save_config(config)
        return True, "keyring 不可用，Token 已按设置明文保存到 config.json。"
    return False, "无法保存 Token：keyring 不可用。可勾选明文保存兜底，或安装/修复 keyring。"
