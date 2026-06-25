"""Windows clipboard reading helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional
import hashlib
import logging


@dataclass
class ClipboardItem:
    kind: str  # text, files, image, unknown
    content: Any
    signature: str


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def read_clipboard() -> Optional[ClipboardItem]:
    """Read a lightweight snapshot of the clipboard.

    Uses Win32 APIs when available. It intentionally does not read large binary
    clipboard payloads; images are detected only by format.
    """
    try:
        import win32clipboard  # type: ignore
        import win32con  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logging.error("pywin32 is required on Windows: %s", exc)
        return None

    opened = False
    try:
        win32clipboard.OpenClipboard()
        opened = True

        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            if text is None:
                return None
            text = str(text).replace("\x00", "").strip()
            return ClipboardItem("text", text, _sha256("text:" + text))

        # File drop list.
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                files: List[str] = list(win32clipboard.GetClipboardData(win32con.CF_HDROP))
                payload = "\n".join(files)
                return ClipboardItem("files", files, _sha256("files:" + payload))
        except Exception as exc:  # noqa: BLE001
            logging.debug("Clipboard CF_HDROP check failed: %s", exc)

        # Detect bitmap/image without copying binary data.
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB) or win32clipboard.IsClipboardFormatAvailable(win32con.CF_BITMAP):
            return ClipboardItem("image", "剪贴板图片/截图", _sha256("image"))

        return ClipboardItem("unknown", "未知剪贴板内容", _sha256("unknown"))
    except Exception as exc:  # noqa: BLE001
        logging.debug("Clipboard read skipped: %s", exc)
        return None
    finally:
        if opened:
            try:
                win32clipboard.CloseClipboard()
            except Exception:  # noqa: BLE001
                pass
