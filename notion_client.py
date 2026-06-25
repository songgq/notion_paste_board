"""Notion API client for saving clipboard records.

This module adapts to the actual Notion property types in the target data source.
For example, if the user's `来源` property is Rich Text, it writes rich_text;
if it is Select, it writes select. This avoids errors like:
`来源 is expected to be rich_text`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


@dataclass
class NotionRecord:
    record_type: str  # diary, vocabulary, file, image
    uploader: str
    original_content: str
    translated_content: str = ""
    phonetic_content: str = ""
    note: str = ""
    attachment_name: str = ""
    attachment_path: str = ""


class NotionError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, data_source_id: str, notion_version: str = "2026-03-11", timeout: int = 4):
        self.token = token.strip()
        self.data_source_id = data_source_id.strip()
        self.notion_version = notion_version.strip() or "2026-03-11"
        self.timeout = timeout
        self._schema_cache: Optional[Dict[str, Any]] = None
        if not self.token:
            raise NotionError("Notion Token 为空，请先在设置里填写。")
        if not self.data_source_id:
            raise NotionError("Notion Data Source ID 为空，请先在设置里填写。")

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.notion_version,
            "Content-Type": "application/json",
        }

    def retrieve_data_source(self) -> Dict[str, Any]:
        url = f"https://api.notion.com/v1/data_sources/{self.data_source_id}"
        r = requests.get(url, headers=self.headers, timeout=self.timeout)
        if not r.ok:
            raise NotionError(_format_error(r))
        return r.json()

    def _get_schema(self) -> Dict[str, Any]:
        if self._schema_cache is None:
            self._schema_cache = self.retrieve_data_source().get("properties") or {}
        return self._schema_cache

    def test_connection(self) -> str:
        data = self.retrieve_data_source()
        self._schema_cache = data.get("properties") or {}
        title = ""
        for item in data.get("title", []) or []:
            title += item.get("plain_text", "")
        prop_parts = []
        for name, info in self._schema_cache.items():
            prop_parts.append(f"{name}({info.get('type', 'unknown')})")
        return f"连接成功：{title or self.data_source_id}。字段：{', '.join(prop_parts)}"

    def create_record(self, record: NotionRecord, field_names: Dict[str, str]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        title = self._make_title(record)
        schema = self._get_schema()
        properties = self._build_properties(record, field_names, title, now, schema)
        children = self._build_children(record)
        body = {
            "parent": {"type": "data_source_id", "data_source_id": self.data_source_id},
            "properties": properties,
            "children": children,
        }
        r = requests.post("https://api.notion.com/v1/pages", headers=self.headers, json=body, timeout=self.timeout)
        if not r.ok:
            raise NotionError(_format_error(r))
        return r.json().get("id", "")

    def _make_title(self, record: NotionRecord) -> str:
        if record.record_type == "file" and record.attachment_name:
            return record.attachment_name[:80]
        source = record.original_content or record.translated_content or record.note or "剪贴板记录"
        source = " ".join(source.split())
        return source[:60] or "剪贴板记录"

    def _field_name(self, names: Dict[str, str], key: str, default: str, schema: Dict[str, Any], aliases: Optional[List[str]] = None) -> Optional[str]:
        """Return the configured Notion field name only if it exists in schema.

        We skip unknown fields instead of sending invalid properties to Notion.
        """
        candidates = [str(names.get(key, "") or ""), default]
        if aliases:
            candidates.extend(aliases)
        for name in candidates:
            if name and name in schema:
                return name
        return None

    def _title_field_name(self, names: Dict[str, str], schema: Dict[str, Any]) -> str:
        configured = str(names.get("title", "标题") or "标题")
        if configured in schema and schema[configured].get("type") == "title":
            return configured
        for name, info in schema.items():
            if info.get("type") == "title":
                return name
        return configured

    def _build_properties(self, record: NotionRecord, names: Dict[str, str], title: str, now_iso: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        props: Dict[str, Any] = {}

        title_name = self._title_field_name(names, schema)
        props[title_name] = {"title": _rich_text_array(title, limit=120)}

        field_specs = [
            ("type", "类型", record.record_type, ["单词"] if record.record_type == "vocabulary" else None),
            ("uploader", "上传人", record.uploader, None),
            ("original", "原文", record.original_content, None),
            ("translated", "译文", record.translated_content, None),
            ("phonetic", "音标", record.phonetic_content, None),
            ("note", "备注", record.note, None),
            ("created_at", "创建时间", now_iso, None),
            ("source", "来源", "clipboard", None),
        ]
        for key, default_name, value, aliases in field_specs:
            prop_name = self._field_name(names, key, default_name, schema, aliases)
            if prop_name:
                encoded = _encode_property(schema.get(prop_name, {}), value, now_iso if key == "created_at" else None)
                if encoded is not None:
                    props[prop_name] = encoded

        # Current app records file paths as metadata. It does not upload binary files yet.
        # Try common Chinese field names and adapt to the actual property type if present.
        if record.attachment_name:
            prop_name = self._field_name(names, "attachment_name", "附件名", schema, aliases=["附件"])
            if prop_name:
                encoded = _encode_property(schema.get(prop_name, {}), record.attachment_name)
                if encoded is not None:
                    props[prop_name] = encoded
        if record.attachment_path:
            prop_name = self._field_name(names, "attachment_path", "附件路径", schema, aliases=["附件地址", "附件链接"])
            if prop_name:
                encoded = _encode_property(schema.get(prop_name, {}), record.attachment_path)
                if encoded is not None:
                    props[prop_name] = encoded
        return props

    def _build_children(self, record: NotionRecord) -> List[Dict[str, Any]]:
        children: List[Dict[str, Any]] = []
        sections = [
            ("原文", record.original_content),
            ("译文", record.translated_content),
            ("音标", record.phonetic_content),
            ("备注", record.note),
        ]
        if record.attachment_name or record.attachment_path:
            sections.append(("附件", f"{record.attachment_name}\n{record.attachment_path}".strip()))
        for heading, content in sections:
            if not content:
                continue
            children.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": _rich_text_array(heading, limit=100)},
            })
            for chunk in _chunks(content, 1800):
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": _rich_text_array(chunk, limit=1900)},
                })
        return children[:90]


def _encode_property(schema_info: Dict[str, Any], value: Any, date_value: Optional[str] = None) -> Optional[Dict[str, Any]]:
    prop_type = schema_info.get("type")
    text = "" if value is None else str(value)

    if prop_type == "title":
        return {"title": _rich_text_array(text, limit=120)}
    if prop_type == "rich_text":
        return {"rich_text": _rich_text_array(text, limit=1800)}
    if prop_type == "select":
        if not text:
            return None
        return {"select": {"name": text}}
    if prop_type == "status":
        if not text:
            return None
        return {"status": {"name": text}}
    if prop_type == "multi_select":
        if not text:
            return None
        return {"multi_select": [{"name": text}]}
    if prop_type == "date":
        return {"date": {"start": date_value or text}}
    if prop_type == "url":
        if not text:
            return None
        # Notion URL properties require a valid URL. Local Windows paths are not valid URLs.
        if text.startswith(("http://", "https://")):
            return {"url": text[:2000]}
        return None
    if prop_type == "email":
        return {"email": text or None}
    if prop_type == "phone_number":
        return {"phone_number": text or None}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type == "number":
        try:
            return {"number": float(value)}
        except Exception:  # noqa: BLE001
            return None
    if prop_type == "files":
        # The current client does not upload file binaries. Only external URLs can be attached here.
        if text.startswith(("http://", "https://")):
            return {"files": [{"name": text.rsplit("/", 1)[-1] or "附件", "type": "external", "external": {"url": text}}]}
        return None

    # Unknown/unsupported property types are skipped. Details are still written into the page body.
    return None


def _chunks(text: str, size: int) -> List[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _rich_text_array(text: str, limit: int = 1800) -> List[Dict[str, Any]]:
    text = (text or "")[:limit]
    if not text:
        return []
    return [{"type": "text", "text": {"content": text}}]


def _format_error(response: requests.Response) -> str:
    try:
        data = response.json()
        message = data.get("message") or data.get("code") or response.text
    except Exception:  # noqa: BLE001
        message = response.text
    return f"Notion API 错误 {response.status_code}: {message}"
