"""Tkinter UI components."""
from __future__ import annotations

import ctypes
import logging
import os
import re
import tempfile
import threading
import tkinter as tk
import uuid
from tkinter import ttk, messagebox
from typing import Any, Callable, Dict, Optional, Tuple

import requests

from config_manager import get_notion_token, set_notion_token, save_config
from notion_client import NotionClient, NotionRecord
from translator_engines import TranslationResult


TEXT_FONT = ("Segoe UI", 10)
TEXT_FONT_FALLBACK = ("Lucida Sans Unicode", 10)
EMOJI_FONT = ("Segoe UI Emoji", 18)


def _get_work_area(win: tk.Misc) -> Tuple[int, int, int, int]:
    """Return usable screen area: left, top, right, bottom.

    On Windows this excludes the taskbar, which makes bottom-right placement
    much more reliable. On other systems we fall back to the full screen.
    """
    try:
        if os.name == "nt":
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            rect = RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
    except Exception as exc:  # noqa: BLE001
        logging.debug("Failed to read Windows work area: %s", exc)
    return 0, 0, int(win.winfo_screenwidth()), int(win.winfo_screenheight())


def _place_bottom_right(win: tk.Toplevel, width: int, height: int, margin_x: int = 24, margin_y: int = 72) -> None:
    """Place a window at the usable bottom-right corner and clamp coordinates."""
    left, top, right, bottom = _get_work_area(win)
    width = max(260, int(width))
    height = max(180, int(height))
    usable_w = max(260, right - left)
    usable_h = max(180, bottom - top)
    width = min(width, usable_w - 8)
    height = min(height, usable_h - 8)
    x = max(left + 4, right - width - margin_x)
    y = max(top + 4, bottom - height - margin_y)
    win.geometry(f"{width}x{height}+{x}+{y}")
    win.update_idletasks()
    try:
        win.attributes("-topmost", True)
    except Exception:  # noqa: BLE001
        pass





def _place_toast_bottom_right(win: tk.Toplevel, size: int, margin_x: int = 18, margin_y: int = 70) -> None:
    """Place the tiny non-English clipboard toast without using popup min sizes."""
    try:
        left, top, right, bottom = _get_work_area(win)
        size = max(22, min(int(size), 64))
        x = max(left + 4, right - size - margin_x)
        y = max(top + 4, bottom - size - margin_y)
        win.geometry(f"{size}x{size}+{x}+{y}")
        win.update_idletasks()
        try:
            win.attributes("-topmost", True)
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        logging.debug("Failed to place toast: %s", exc)


def _show_toolwindow_no_focus(win: tk.Toplevel) -> None:
    """Show a small tool window robustly without taking focus."""
    try:
        win.update_idletasks()
        if os.name == "nt":
            _apply_no_activate(win, tool_window=True)
            # Tk can keep a withdrawn Toplevel unmapped unless deiconify is called.
            # With WS_EX_NOACTIVATE already applied, this should not steal focus.
            try:
                win.deiconify()
            except Exception:  # noqa: BLE001
                pass
            hwnd = int(win.winfo_id())
            user32 = ctypes.windll.user32
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            SW_SHOWNOACTIVATE = 4
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
        else:
            win.deiconify()
            win.lift()
            win.attributes("-topmost", True)
    except Exception as exc:  # noqa: BLE001
        logging.debug("Toast no-focus show failed; falling back: %s", exc)
        try:
            win.deiconify()
            win.lift()
            win.attributes("-topmost", True)
        except Exception:  # noqa: BLE001
            pass


def _apply_no_activate(win: tk.Toplevel, tool_window: bool = True) -> None:
    """Make a popup visible without stealing focus on Windows."""
    if os.name != "nt":
        return
    try:
        win.update_idletasks()
        hwnd = int(win.winfo_id())
        user32 = ctypes.windll.user32
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        try:
            get_long = user32.GetWindowLongPtrW
            set_long = user32.SetWindowLongPtrW
        except AttributeError:
            get_long = user32.GetWindowLongW
            set_long = user32.SetWindowLongW
        style = get_long(hwnd, GWL_EXSTYLE)
        style |= WS_EX_NOACTIVATE
        if tool_window:
            style |= WS_EX_TOOLWINDOW
        set_long(hwnd, GWL_EXSTYLE, style)
    except Exception as exc:  # noqa: BLE001
        logging.debug("Failed to apply no-activate style: %s", exc)


def _show_no_activate(win: tk.Toplevel, tool_window: bool = True) -> None:
    """Show a window without taking keyboard focus where possible."""
    try:
        win.update_idletasks()
        if os.name == "nt":
            _apply_no_activate(win, tool_window=tool_window)
            hwnd = int(win.winfo_id())
            user32 = ctypes.windll.user32
            SW_SHOWNOACTIVATE = 4
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            SWP_NOACTIVATE = 0x0010
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE)
        else:
            win.deiconify()
            win.attributes("-topmost", True)
    except Exception as exc:  # noqa: BLE001
        logging.debug("Show no-activate failed, falling back to deiconify: %s", exc)
        try:
            win.deiconify()
        except Exception:  # noqa: BLE001
            pass



def _get_foreground_window() -> int:
    if os.name != "nt":
        return 0
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:  # noqa: BLE001
        return 0


def _restore_foreground_window(hwnd: int) -> None:
    if os.name != "nt" or not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        current = int(user32.GetForegroundWindow())
        # Only restore if our popup became active. This avoids fighting with the user.
        if current:
            user32.SetForegroundWindow(hwnd)
    except Exception as exc:  # noqa: BLE001
        logging.debug("Failed to restore foreground window: %s", exc)


def _show_reliably_without_keeping_focus(win: tk.Toplevel, root: tk.Tk, tool_window: bool = False) -> None:
    """Reliably show a Tk popup and return focus to the user's previous app.

    The previous pure WS_EX_NOACTIVATE path could fail on some Windows/Tk
    combinations, leaving the popup invisible. This path prioritizes showing the
    window, then immediately restores the previous foreground window so typing
    can continue in the original app.
    """
    previous_hwnd = _get_foreground_window()
    try:
        win.update_idletasks()
        if os.name == "nt":
            _apply_no_activate(win, tool_window=tool_window)
        win.deiconify()
        win.lift()
        try:
            win.attributes("-topmost", True)
        except Exception:  # noqa: BLE001
            pass
        if os.name == "nt":
            hwnd = int(win.winfo_id())
            user32 = ctypes.windll.user32
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
            # Restore after Tk/Windows has finished mapping the window.
            if previous_hwnd and previous_hwnd != hwnd:
                root.after(30, lambda h=previous_hwnd: _restore_foreground_window(h))
                root.after(120, lambda h=previous_hwnd: _restore_foreground_window(h))
    except Exception as exc:  # noqa: BLE001
        logging.debug("Reliable no-focus show failed, falling back to normal show: %s", exc)
        try:
            win.deiconify()
            win.lift()
            if previous_hwnd:
                root.after(50, lambda h=previous_hwnd: _restore_foreground_window(h))
        except Exception:  # noqa: BLE001
            pass

def _extract_pronunciation_word(text: str) -> str:
    """Pick a clean English word for dictionary pronunciation."""
    match = re.search(r"[A-Za-z]+(?:[\u2019'][A-Za-z]+)?", text or "")
    return match.group(0) if match else ""


def _mci_error_message(code: int) -> str:
    try:
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.winmm.mciGetErrorStringW(code, buf, 512)
        return buf.value or f"MCI error {code}"
    except Exception:  # noqa: BLE001
        return f"MCI error {code}"


def _mci_send(command: str) -> str:
    buf = ctypes.create_unicode_buffer(512)
    code = ctypes.windll.winmm.mciSendStringW(command, buf, 511, None)
    if code:
        raise RuntimeError(f"{_mci_error_message(code)} | command={command}")
    return buf.value


def _play_mp3_silently(path: str) -> None:
    """Play an MP3 with Windows MCI without opening an external player."""
    if os.name != "nt":
        raise RuntimeError("内置发音播放目前仅支持 Windows。")
    alias = "clipboard_voice_" + uuid.uuid4().hex
    opened = False
    try:
        _mci_send(f'open "{path}" type mpegvideo alias {alias}')
        opened = True
        _mci_send(f"play {alias} wait")
    finally:
        if opened:
            try:
                _mci_send(f"close {alias}")
            except Exception as exc:  # noqa: BLE001
                logging.debug("Failed to close MCI alias: %s", exc)


class ToastIcon:
    def __init__(self, root: tk.Tk, config: Dict[str, Any], on_click: Callable[[], None]):
        self.root = root
        self.config = config
        self.on_click = on_click
        self.win: Optional[tk.Toplevel] = None
        self.hide_after_id: Optional[str] = None
        self.paused = False

    def show(self, label: str = "📋") -> None:
        """Show a tiny clickable icon for non-English/file/image clipboard content."""
        self.hide()
        logging.info("Showing non-English toast icon: %s", label)
        self.win = tk.Toplevel(self.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", float(self.config.get("toast_opacity", 0.92)))
        try:
            self.win.configure(bg="#2563eb")
        except Exception:  # noqa: BLE001
            pass
        _apply_no_activate(self.win, tool_window=True)

        size = int(self.config.get("toast_icon_size", 34))
        icon_font_size = int(self.config.get("toast_icon_font_size", 14))
        frame = tk.Frame(self.win, bg="#2563eb", bd=0, highlightthickness=1, highlightbackground="#93c5fd")
        frame.pack(fill="both", expand=True)
        btn = tk.Label(
            frame,
            text=label,
            fg="white",
            bg="#2563eb",
            font=("Segoe UI Emoji", icon_font_size),
            padx=0,
            pady=0,
            cursor="hand2",
        )
        btn.pack(fill="both", expand=True)
        for widget in (frame, btn):
            widget.bind("<Button-1>", lambda _e: self._click())
            widget.bind("<Button-3>", lambda _e: self.hide())
            if self.config.get("icon_hover_pause", True):
                widget.bind("<Enter>", lambda _e: self._pause())
                widget.bind("<Leave>", lambda _e: self._resume())

        _place_toast_bottom_right(self.win, size, margin_x=18, margin_y=70)
        _show_toolwindow_no_focus(self.win)
        # Re-assert position/topmost after Windows maps the toolwindow. This fixes
        # cases where the toast was created but never visually surfaced.
        self.root.after(80, lambda: (_place_toast_bottom_right(self.win, size, margin_x=18, margin_y=70), _show_toolwindow_no_focus(self.win)) if self.win else None)
        self.root.after(300, lambda: (_place_toast_bottom_right(self.win, size, margin_x=18, margin_y=70), _show_toolwindow_no_focus(self.win)) if self.win else None)
        self._schedule_hide()

    def _schedule_hide(self) -> None:
        if not self.win or self.paused:
            return
        delay = int(self.config.get("icon_auto_hide_delay", 5000))
        self.hide_after_id = self.win.after(delay, self.hide)

    def _pause(self) -> None:
        self.paused = True
        if self.win and self.hide_after_id:
            self.win.after_cancel(self.hide_after_id)
            self.hide_after_id = None

    def _resume(self) -> None:
        self.paused = False
        self._schedule_hide()

    def _click(self) -> None:
        self.hide()
        self.on_click()

    def hide(self) -> None:
        if self.win:
            try:
                if self.hide_after_id:
                    self.win.after_cancel(self.hide_after_id)
            except Exception:  # noqa: BLE001
                pass
            try:
                self.win.destroy()
            except Exception:  # noqa: BLE001
                pass
        self.win = None
        self.hide_after_id = None
        self.paused = False


class RecordPopup:
    def __init__(
        self,
        root: tk.Tk,
        config: Dict[str, Any],
        item_kind: str,
        original: str,
        translated: str,
        on_save: Callable[[NotionRecord], None],
        phonetic: str = "",
        record_type_default: str = "diary",
        translation_pending: bool = False,
    ):
        self.root = root
        self.config = config
        self.item_kind = item_kind
        self.original = original
        self.translated = translated
        self.phonetic = phonetic
        self.translation_pending = translation_pending
        self.on_save = on_save
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.title("notion_paste_board")
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", float(config.get("popup_opacity", 0.85)))
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.record_type_default = record_type_default
        self.auto_close_id: Optional[str] = None
        self.voice_buttons: list[ttk.Button] = []
        self.translated_text: Optional[tk.Text] = None
        self.phonetic_label: Optional[ttk.Label] = None
        self._build()
        self._place_bottom_right()
        _show_reliably_without_keeping_focus(self.win, self.root, tool_window=False)
        self.root.after(50, self._place_bottom_right)
        self.root.after(120, self._place_bottom_right)
        self._bind_auto_close()

    def _make_text_area(self, parent: ttk.Frame, row: int, height: int, bg: Optional[str] = None) -> tk.Text:
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, sticky="nsew", pady=(2, 6))
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        text = tk.Text(
            box,
            height=height,
            wrap="word",
            font=TEXT_FONT,
            padx=7,
            pady=5,
            borderwidth=1,
            relief="solid",
            undo=False,
            exportselection=False,
        )
        if bg:
            text.configure(bg=bg)
        ybar = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=ybar.set)
        text.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        return text

    def _build(self) -> None:
        """Build a compact card-style popup.

        Older builds put every action in one top row, which easily overflowed at
        400px width. This layout separates the title/close area from the action
        buttons and moves the note/save controls to the bottom.
        """
        style = ttk.Style(self.win)
        try:
            style.configure("Primary.TButton", padding=(8, 4))
            style.configure("Compact.TButton", padding=(6, 3))
        except Exception:  # noqa: BLE001
            pass

        self.win.configure(bg="#f8fafc")
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(1, weight=1)

        header = tk.Frame(self.win, bg="#f8fafc", padx=10, pady=8)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        tk.Label(header, text="📋", bg="#f8fafc", fg="#2563eb", font=("Segoe UI Emoji", 14)).grid(row=0, column=0, sticky="w", padx=(0, 6))
        title_text = "notion_paste_board"
        if self.item_kind == "text" and self.translated:
            title_text = "英文翻译"
        elif self.item_kind == "files":
            title_text = "文件记录"
        elif self.item_kind == "image":
            title_text = "图片记录"
        tk.Label(header, text=title_text, bg="#f8fafc", fg="#0f172a", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=1, sticky="w")
        tk.Button(header, text="×", command=self.close, relief="flat", bg="#f8fafc", fg="#64748b", activebackground="#e2e8f0", font=("Segoe UI", 12), width=2).grid(row=0, column=2, sticky="e")

        body = ttk.Frame(self.win, padding=(10, 0, 10, 6))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=3)
        body.rowconfigure(3, weight=3 if self.translated else 0)
        body.rowconfigure(5, weight=1)

        ttk.Label(body, text="原文 / 内容").grid(row=0, column=0, sticky="w", pady=(2, 2))
        self.original_text = self._make_text_area(body, 1, 5)
        self.original_text.insert("1.0", self.original)
        self.original_text.configure(state="disabled")

        if self.translated:
            trans_head = ttk.Frame(body)
            trans_head.grid(row=2, column=0, sticky="ew", pady=(2, 2))
            trans_head.columnconfigure(1, weight=1)
            ttk.Label(trans_head, text="译文").grid(row=0, column=0, sticky="w")
            self.phonetic_label = ttk.Label(trans_head, text=self.phonetic, foreground="#64748b")
            self.phonetic_label.grid(row=0, column=1, sticky="w", padx=(10, 8))
            voice_frame = ttk.Frame(trans_head)
            voice_frame.grid(row=0, column=2, sticky="e")
            us_btn = ttk.Button(voice_frame, text="US", style="Compact.TButton", command=lambda: self.play_voice(2))
            uk_btn = ttk.Button(voice_frame, text="UK", style="Compact.TButton", command=lambda: self.play_voice(1))
            us_btn.pack(side="left", padx=(0, 4))
            uk_btn.pack(side="left")
            self.voice_buttons = [us_btn, uk_btn]
            self.translated_text = self._make_text_area(body, 3, 5, bg="#eef2ff")
            self.translated_text.insert("1.0", self.translated)
            self.translated_text.configure(state="disabled")

        ttk.Label(body, text="备注").grid(row=4, column=0, sticky="w", pady=(2, 2))
        self.note_text = self._make_text_area(body, 5, 2)

        footer = ttk.Frame(self.win, padding=(10, 4, 10, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(4, weight=1)
        ttk.Button(footer, text="记录日记", style="Primary.TButton", command=lambda: self.save("diary")).grid(row=0, column=0, padx=(0, 6), sticky="w")
        ttk.Button(footer, text="记录单词", style="Primary.TButton", command=lambda: self.save("vocabulary")).grid(row=0, column=1, padx=(0, 6), sticky="w")
        if self.item_kind == "files":
            ttk.Button(footer, text="记录文件", style="Primary.TButton", command=lambda: self.save("file")).grid(row=0, column=2, padx=(0, 6), sticky="w")
        ttk.Button(footer, text="关闭", command=self.close).grid(row=0, column=5, sticky="e")

        w = int(self.config.get("popup_width", 400))
        h = int(self.config.get("popup_height", 430))
        self.win.minsize(390, 320)
        self.win.geometry(f"{w}x{h}")

    def _place_bottom_right(self) -> None:
        self.win.update_idletasks()
        w = int(self.config.get("popup_width", max(400, self.win.winfo_reqwidth())))
        h = int(self.config.get("popup_height", max(430, self.win.winfo_reqheight())))
        _place_bottom_right(self.win, w, h, margin_x=24, margin_y=72)

    def _bind_auto_close(self) -> None:
        def pause(_e=None):
            if self.auto_close_id:
                try:
                    self.win.after_cancel(self.auto_close_id)
                except Exception:  # noqa: BLE001
                    pass
                self.auto_close_id = None

        def resume(_e=None):
            if not self.translation_pending:
                self._schedule_close()

        self.win.bind("<Enter>", pause)
        self.win.bind("<Leave>", resume)
        # When translation is pending, do not close before the result/error is shown.
        if not self.translation_pending:
            self._schedule_close()

    def _schedule_close(self) -> None:
        if self.auto_close_id:
            try:
                self.win.after_cancel(self.auto_close_id)
            except Exception:  # noqa: BLE001
                pass
        delay = int(self.config.get("auto_close_delay", 6000))
        if delay <= 0:
            return
        self.auto_close_id = self.win.after(delay, self.close)

    def update_translation(self, translated: str) -> None:
        self.update_translation_result(TranslationResult(text=translated))

    def update_translation_result(self, result: TranslationResult) -> None:
        if not self.win.winfo_exists():
            return
        self.translation_pending = False
        self.translated = result.text or "翻译失败：网络连接异常或翻译接口暂时不可用。"
        self.phonetic = result.phonetic_display
        if self.translated_text is not None:
            try:
                self.translated_text.configure(state="normal")
                self.translated_text.delete("1.0", "end")
                self.translated_text.insert("1.0", self.translated)
                self.translated_text.configure(state="disabled")
            except Exception as exc:  # noqa: BLE001
                logging.debug("Failed to update translation text: %s", exc)
        if self.phonetic_label is not None:
            try:
                self.phonetic_label.configure(text=self.phonetic)
            except Exception as exc:  # noqa: BLE001
                logging.debug("Failed to update phonetic label: %s", exc)
        self._place_bottom_right()
        self._schedule_close()

    def save(self, record_type: str) -> None:
        note = self.note_text.get("1.0", "end").strip()
        attachment_name = ""
        attachment_path = ""
        if self.item_kind == "files":
            paths = [line.strip() for line in self.original.splitlines() if line.strip()]
            attachment_path = "\n".join(paths)
            attachment_name = os.path.basename(paths[0]) if paths else ""
        record = NotionRecord(
            record_type=record_type,
            uploader=str(self.config.get("uploader", "user")),
            original_content=self.original,
            translated_content="" if self.translation_pending else self.translated,
            phonetic_content="" if self.translation_pending else self.phonetic,
            note=note,
            attachment_name=attachment_name,
            attachment_path=attachment_path,
        )
        self.on_save(record)
        self.close()

    def play_voice(self, accent_type: int) -> None:
        word = _extract_pronunciation_word(self.original)
        if not word:
            return

        def set_buttons_state(enabled: bool) -> None:
            state = "normal" if enabled else "disabled"
            for btn in self.voice_buttons:
                try:
                    btn.configure(state=state)
                except Exception:  # noqa: BLE001
                    pass

        def worker():
            path = ""
            try:
                self.root.after(0, lambda: set_buttons_state(False))
                url = "https://dict.youdao.com/dictvoice"
                r = requests.get(url, params={"audio": word, "type": accent_type}, timeout=5)
                r.raise_for_status()
                fd, path = tempfile.mkstemp(suffix=".mp3", prefix="clipboard_voice_")
                os.close(fd)
                with open(path, "wb") as f:
                    f.write(r.content)
                _play_mp3_silently(path)
            except Exception as exc:  # noqa: BLE001
                logging.warning("Voice playback failed: %s", exc)
            finally:
                if path:
                    try:
                        os.remove(path)
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    self.root.after(0, lambda: set_buttons_state(True))
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def close(self) -> None:
        try:
            if self.auto_close_id:
                self.win.after_cancel(self.auto_close_id)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.win.destroy()
        except Exception:  # noqa: BLE001
            pass


class SettingsWindow:
    def __init__(self, root: tk.Tk, config: Dict[str, Any], on_saved: Callable[[Dict[str, Any]], None]):
        self.root = root
        self.config = config
        self.on_saved = on_saved
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.title("notion_paste_board 设置")
        self.win.geometry("620x660")
        self.vars: Dict[str, tk.Variable] = {}
        self._build()
        self.win.update_idletasks()
        _place_bottom_right(self.win, 620, 660, margin_x=24, margin_y=72)
        self.win.deiconify()

    def _var(self, key: str, default: Any = "") -> tk.StringVar:
        value = self.config.get(key, default)
        var = tk.StringVar(value=str(value))
        self.vars[key] = var
        return var

    def _bool_var(self, key: str, default: bool = False) -> tk.BooleanVar:
        var = tk.BooleanVar(value=bool(self.config.get(key, default)))
        self.vars[key] = var
        return var

    def _build(self) -> None:
        """Build settings with three tabs: Notion, basic settings, popup trigger."""
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(self.win)
        notebook.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))

        notion_tab = ttk.Frame(notebook, padding=14)
        basic_tab = ttk.Frame(notebook, padding=14)
        trigger_tab = ttk.Frame(notebook, padding=14)
        for tab in (notion_tab, basic_tab, trigger_tab):
            tab.columnconfigure(1, weight=1)

        notebook.add(notion_tab, text="Notion")
        notebook.add(basic_tab, text="基础设置")
        notebook.add(trigger_tab, text="弹框触发")

        row = 0
        ttk.Label(notion_tab, text="Notion", font=("Microsoft YaHei UI", 12, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)); row += 1
        ttk.Checkbutton(notion_tab, text="启用 Notion 保存", variable=self._bool_var("notion_enabled", True)).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        row = self._entry(notion_tab, row, "Notion Token", "notion_token", show="*")
        self.vars["notion_token"].set(get_notion_token(self.config))
        row = self._entry(notion_tab, row, "Data Source ID", "notion_data_source_id")
        row = self._entry(notion_tab, row, "Notion API Version", "notion_version")
        ttk.Checkbutton(notion_tab, text="keyring 不可用时允许明文保存 Token（不推荐）", variable=self._bool_var("allow_plaintext_token_fallback", False)).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 10)); row += 1
        ttk.Button(notion_tab, text="测试 Notion 连接", command=self.test_notion).grid(row=row, column=0, sticky="w", pady=(0, 10)); row += 1
        ttk.Label(notion_tab, text="字段名需和 Notion 表格列名一致。默认字段：标题、类型、上传人、原文、译文、音标、备注、创建时间、来源、附件名、附件路径。", wraplength=540, foreground="#666").grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))

        row = 0
        ttk.Label(basic_tab, text="基础设置", font=("Microsoft YaHei UI", 12, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)); row += 1
        row = self._entry(basic_tab, row, "上传人", "uploader")
        row = self._combo(basic_tab, row, "翻译引擎", "translator_engine", ["youdao", "google", "iciba", "bing"])
        ttk.Checkbutton(basic_tab, text="启用剪贴板监控", variable=self._bool_var("monitor_enabled", True)).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        ttk.Checkbutton(basic_tab, text="保存失败时进入重试队列", variable=self._bool_var("retry_enabled", True)).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        row = self._entry(basic_tab, row, "轮询间隔 ms", "poll_interval_ms")
        row = self._entry(basic_tab, row, "最大文本长度", "max_text_length")
        row = self._entry(basic_tab, row, "网络请求超时秒", "request_timeout_seconds")

        row = 0
        ttk.Label(trigger_tab, text="弹框触发", font=("Microsoft YaHei UI", 12, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)); row += 1
        ttk.Checkbutton(trigger_tab, text="英文自动弹翻译窗", variable=self._bool_var("auto_popup_for_english", True)).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        ttk.Checkbutton(trigger_tab, text="非英文显示右下角图标", variable=self._bool_var("show_icon_for_non_english", True)).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        ttk.Checkbutton(trigger_tab, text="鼠标悬停图标时暂停消失", variable=self._bool_var("icon_hover_pause", True)).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        row = self._entry(trigger_tab, row, "图标自动消失 ms", "icon_auto_hide_delay")
        row = self._entry(trigger_tab, row, "非英文图标大小 px", "toast_icon_size")
        row = self._entry(trigger_tab, row, "弹框自动关闭 ms", "auto_close_delay")
        row = self._entry(trigger_tab, row, "弹框透明度 0.3-1.0", "popup_opacity")
        row = self._entry(trigger_tab, row, "弹框宽度", "popup_width")
        row = self._entry(trigger_tab, row, "弹框高度", "popup_height")
        row = self._entry(trigger_tab, row, "英文占比阈值", "english_letter_ratio_threshold")
        row = self._entry(trigger_tab, row, "中文占比阈值", "chinese_ratio_threshold")

        btns = ttk.Frame(self.win, padding=(12, 4, 12, 12))
        btns.grid(row=1, column=0, sticky="ew")
        ttk.Button(btns, text="保存", command=self.save).pack(side="left")
        ttk.Button(btns, text="取消", command=self.win.destroy).pack(side="left", padx=8)

    def _entry(self, frame: ttk.Frame, row: int, label: str, key: str, show: str = "") -> int:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(frame, textvariable=self._var(key), show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        return row + 1

    def _combo(self, frame: ttk.Frame, row: int, label: str, key: str, values: list[str]) -> int:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
        combo = ttk.Combobox(frame, textvariable=self._var(key), values=values, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", pady=4)
        return row + 1

    def _collect(self) -> Dict[str, Any]:
        new_config = dict(self.config)
        for key, var in self.vars.items():
            if key == "notion_token":
                continue
            value: Any = var.get()
            if isinstance(var, tk.BooleanVar):
                value = bool(value)
            elif key in {"auto_close_delay", "popup_width", "popup_height", "icon_auto_hide_delay", "toast_icon_size", "poll_interval_ms", "max_text_length", "request_timeout_seconds"}:
                value = int(float(value))
            elif key in {"popup_opacity", "english_letter_ratio_threshold", "chinese_ratio_threshold"}:
                value = float(value)
            new_config[key] = value
        return new_config

    def save(self) -> None:
        try:
            new_config = self._collect()
            token = str(self.vars["notion_token"].get()).strip()
            ok, msg = set_notion_token(token, new_config)
            if not ok:
                messagebox.showwarning("Token 未保存", msg)
                return
            save_config(new_config)
            self.on_saved(new_config)
            messagebox.showinfo("保存成功", msg)
            self.win.destroy()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("保存失败", str(exc))

    def test_notion(self) -> None:
        try:
            cfg = self._collect()
            token = str(self.vars["notion_token"].get()).strip()
            client = NotionClient(token, cfg.get("notion_data_source_id", ""), cfg.get("notion_version", "2026-03-11"), int(cfg.get("request_timeout_seconds", 4)))
            message = client.test_connection()
            messagebox.showinfo("测试成功", message)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("测试失败", str(exc))
