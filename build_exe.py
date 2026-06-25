"""Build Windows EXE with PyInstaller.

Run on Windows:
    python build_exe.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "client.py"

cmd = [
    sys.executable,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name",
    "notion_paste_board",
    "--collect-all",
    "keyring",
    "--hidden-import",
    "win32timezone",
    str(ENTRY),
]

print("Running:", " ".join(cmd))
subprocess.check_call(cmd, cwd=ROOT)
print("\n完成：dist/notion_paste_board/notion_paste_board.exe")
