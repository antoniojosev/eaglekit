
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os, subprocess, sys, shutil

from .config import META_DIR_NAME

@dataclass
class Project:
    name: str
    path: Path

    @property
    def meta_dir(self) -> Path:
        return self.path / META_DIR_NAME

    @property
    def todo_file(self) -> Path:
        return self.meta_dir / "todo.json"

    def ensure_meta(self) -> None:
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def open_in_editor(self) -> None:
        code = shutil.which("code")
        if code:
            subprocess.run([code, str(self.path)], check=False)
            return
        if sys.platform.startswith("win"):
            os.startfile(self.path)  # type: ignore
        elif sys.platform == "darwin":
            subprocess.run(["open", str(self.path)], check=False)
        else:
            subprocess.run(["xdg-open", str(self.path)], check=False)
