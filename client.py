"""Clipboard Assistant main entry.

Run on Windows:
    pythonw client.py
"""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox
from typing import Any, Dict, Optional

from clipboard_reader import ClipboardItem, read_clipboard
from config_manager import load_config, save_config, get_notion_token
from language_utils import is_english_text
from notion_client import NotionClient, NotionError, NotionRecord
from retry_queue import enqueue, load_queue, rewrite_queue
from translator_engines import translate_details, TranslationResult
from ui import RecordPopup, SettingsWindow, ToastIcon

APP_DIR = Path(__file__).resolve().parent
LOG_PATH = APP_DIR / "client.log"


def setup_logging() -> None:
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[handler])


class ClipboardAssistantApp:
    def __init__(self) -> None:
        setup_logging()
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("notion_paste_board")
        self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_root)
        self.last_signature: Optional[str] = None
        self.pending_item: Optional[ClipboardItem] = None
        self.toast = ToastIcon(self.root, self.config, self.open_pending_popup)
        self.tray_icon = None
        self.debounce_after_id: Optional[str] = None
        self._retry_running = False
        self._setup_tray()
        self._schedule_monitor()
        self.root.after(2000, self.retry_failed_records)
        logging.info("notion_paste_board started")

    def run(self) -> None:
        self.root.mainloop()

    def hide_root(self) -> None:
        self.root.withdraw()

    def _setup_tray(self) -> None:
        try:
            import pystray  # type: ignore
            from PIL import Image, ImageDraw  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logging.warning("Tray disabled: %s", exc)
            return

        def make_image(active: bool = True):
            bg = "#2563eb" if active else "#6b7280"
            image = Image.new("RGB", (64, 64), bg)
            d = ImageDraw.Draw(image)
            d.rounded_rectangle((16, 10, 48, 54), radius=6, outline="white", width=4)
            d.line((24, 24, 40, 24), fill="white", width=3)
            d.line((24, 34, 40, 34), fill="white", width=3)
            d.line((24, 44, 36, 44), fill="white", width=3)
            if not active:
                # A small pause mark, so the tray icon is visibly different.
                d.rectangle((22, 20, 28, 44), fill="white")
                d.rectangle((36, 20, 42, 44), fill="white")
            return image

        self._tray_make_image = make_image

        def open_settings(_icon=None, _item=None):
            self.root.after(0, self.show_settings)

        def toggle_monitor(_icon=None, _item=None):
            self.config["monitor_enabled"] = not bool(self.config.get("monitor_enabled", True))
            save_config(self.config)
            logging.info("monitor_enabled=%s", self.config["monitor_enabled"])
            self._refresh_tray()

        def quit_app(_icon=None, _item=None):
            self.root.after(0, self.quit)

        def build_menu():
            monitor_text = "暂停监控" if self.config.get("monitor_enabled", True) else "恢复监控"
            return pystray.Menu(
                pystray.MenuItem("设置", open_settings),
                pystray.MenuItem(monitor_text, toggle_monitor),
                pystray.MenuItem("退出", quit_app),
            )

        self._tray_build_menu = build_menu
        active = bool(self.config.get("monitor_enabled", True))
        title = "notion_paste_board（监控中）" if active else "notion_paste_board（已暂停）"
        self.tray_icon = pystray.Icon("notion_paste_board", make_image(active), title, build_menu())
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _refresh_tray(self) -> None:
        if not self.tray_icon:
            return
        try:
            active = bool(self.config.get("monitor_enabled", True))
            self.tray_icon.title = "notion_paste_board（监控中）" if active else "notion_paste_board（已暂停）"
            make_image = getattr(self, "_tray_make_image", None)
            if make_image:
                self.tray_icon.icon = make_image(active)
            build_menu = getattr(self, "_tray_build_menu", None)
            if build_menu:
                self.tray_icon.menu = build_menu()
                self.tray_icon.update_menu()
        except Exception as exc:  # noqa: BLE001
            logging.debug("Failed to refresh tray: %s", exc)

    def _schedule_monitor(self) -> None:
        interval = int(self.config.get("poll_interval_ms", 300))
        self.root.after(interval, self.monitor_once)

    def monitor_once(self) -> None:
        try:
            if self.config.get("monitor_enabled", True):
                item = read_clipboard()
                if item and item.signature != self.last_signature:
                    self.last_signature = item.signature
                    if self.debounce_after_id:
                        self.root.after_cancel(self.debounce_after_id)
                    self.pending_item = item
                    self.debounce_after_id = self.root.after(350, self.process_pending_item)
        except Exception as exc:  # noqa: BLE001
            logging.exception("monitor_once failed: %s", exc)
        finally:
            self._schedule_monitor()

    def process_pending_item(self) -> None:
        item = self.pending_item
        if not item:
            return
        logging.info("Clipboard changed: kind=%s", item.kind)
        if item.kind == "text":
            text = str(item.content)
            if len(text) > int(self.config.get("max_text_length", 10000)):
                logging.info("Text skipped because it is too long: %s chars", len(text))
                if self.config.get("show_icon_for_non_english", True):
                    self.toast.show("📋")
                return
            english = is_english_text(
                text,
                float(self.config.get("english_letter_ratio_threshold", 0.5)),
                float(self.config.get("chinese_ratio_threshold", 0.1)),
            )
            if english and self.config.get("auto_popup_for_english", True):
                self.translate_and_popup(text)
            elif self.config.get("show_icon_for_non_english", True):
                logging.info("Non-English text detected; showing toast icon")
                self.toast.show("📋")
        elif item.kind == "files":
            if self.config.get("show_icon_for_non_english", True):
                logging.info("Files detected; showing toast icon")
                self.toast.show("📎")
        elif item.kind == "image":
            if self.config.get("show_icon_for_non_english", True):
                logging.info("Image detected; showing toast icon")
                self.toast.show("🖼")
        else:
            if self.config.get("show_icon_for_non_english", True):
                logging.info("Unknown clipboard content; showing toast icon")
                self.toast.show("📋")

    def translate_and_popup(self, text: str) -> None:
        # Show the popup immediately so slow translation endpoints do not make
        # the app feel frozen. The translation text is filled in asynchronously.
        popup = RecordPopup(
            self.root,
            self.config,
            "text",
            text,
            "翻译中...",
            self.save_record,
            record_type_default="vocabulary",
            translation_pending=True,
        )

        def worker():
            result = TranslationResult()
            try:
                result = translate_details(text, self.config.get("translator_engine", "youdao"), int(self.config.get("request_timeout_seconds", 3)))
            except Exception as exc:  # noqa: BLE001
                logging.warning("Translate failed: %s", exc)
            self.root.after(0, lambda r=result: popup.update_translation_result(r))

        threading.Thread(target=worker, daemon=True).start()

    def open_pending_popup(self) -> None:
        item = self.pending_item
        if not item:
            return
        if item.kind == "text":
            text = str(item.content)
            RecordPopup(self.root, self.config, "text", text, "", self.save_record, "diary")
        elif item.kind == "files":
            files_text = "\n".join(item.content)
            RecordPopup(self.root, self.config, "files", files_text, "", self.save_record, "file")
        elif item.kind == "image":
            RecordPopup(self.root, self.config, "image", "剪贴板中检测到图片/截图。当前版本会记录为图片剪贴板事件，不直接上传图片二进制。", "", self.save_record, "image")
        else:
            RecordPopup(self.root, self.config, "unknown", str(item.content), "", self.save_record, "diary")

    def save_record(self, record: NotionRecord) -> None:
        if not self.config.get("notion_enabled", True):
            messagebox.showwarning("未启用", "Notion 保存未启用，请先在设置中开启。")
            return

        def worker():
            try:
                token = get_notion_token(self.config)
                client = NotionClient(
                    token=token,
                    data_source_id=str(self.config.get("notion_data_source_id", "")),
                    notion_version=str(self.config.get("notion_version", "2026-03-11")),
                    timeout=int(self.config.get("request_timeout_seconds", 4)),
                )
                page_id = client.create_record(record, self.config.get("field_names", {}))
                logging.info("Record saved to Notion: %s", page_id)
            except Exception as exc:  # noqa: BLE001
                logging.exception("Save to Notion failed: %s", exc)
                if self.config.get("retry_enabled", True):
                    enqueue(record, str(exc))
                self.root.after(0, lambda: messagebox.showerror("保存失败", f"已写入本地重试队列：\n{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def retry_failed_records(self) -> None:
        """Retry queued Notion saves in a background thread.

        Earlier builds did this work on Tk's main thread. If Notion or the
        network reset the connection, the whole UI/clipboard monitor could look
        dead until the request timed out. Never block the UI loop here.
        """
        if self._retry_running:
            self.root.after(60_000, self.retry_failed_records)
            return

        def worker() -> None:
            self._retry_running = True
            try:
                if not (self.config.get("retry_enabled", True) and self.config.get("notion_enabled", True)):
                    return
                rows = load_queue()
                if not rows:
                    return
                remaining = []
                token = get_notion_token(self.config)
                client = NotionClient(
                    token=token,
                    data_source_id=str(self.config.get("notion_data_source_id", "")),
                    notion_version=str(self.config.get("notion_version", "2026-03-11")),
                    timeout=int(self.config.get("request_timeout_seconds", 2)),
                )
                for row in rows[:20]:
                    try:
                        record = NotionRecord(
                            record_type=row.get("record_type", "diary"),
                            uploader=row.get("uploader", "user"),
                            original_content=row.get("original_content", ""),
                            translated_content=row.get("translated_content", ""),
                            phonetic_content=row.get("phonetic_content", ""),
                            note=row.get("note", ""),
                            attachment_name=row.get("attachment_name", ""),
                            attachment_path=row.get("attachment_path", ""),
                        )
                        client.create_record(record, self.config.get("field_names", {}))
                    except Exception as exc:  # noqa: BLE001
                        row["last_error"] = str(exc)
                        remaining.append(row)
                if len(rows) > 20:
                    remaining.extend(rows[20:])
                rewrite_queue(remaining)
            except Exception as exc:  # noqa: BLE001
                logging.debug("retry_failed_records skipped: %s", exc)
            finally:
                self._retry_running = False
                try:
                    self.root.after(60_000, self.retry_failed_records)
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def show_settings(self) -> None:
        SettingsWindow(self.root, self.config, self.update_config)

    def update_config(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.toast.config = config
        self._refresh_tray()

    def quit(self) -> None:
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()


if __name__ == "__main__":
    app = ClipboardAssistantApp()
    app.run()
