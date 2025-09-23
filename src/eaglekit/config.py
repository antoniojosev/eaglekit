
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Tuple
import yaml
from platformdirs import user_config_dir
import subprocess

APP_NAME = "eaglekit"
META_DIR_NAME = ".eagle"

@dataclass
class Paths:
    config_dir: Path
    registry_file: Path
    defaults_file: Path
    workspaces_dir: Path
    secrets_dir: Path

def get_paths() -> Paths:
    cfg = Path(user_config_dir(APP_NAME))
    cfg.mkdir(parents=True, exist_ok=True)
    return Paths(
        config_dir=cfg,
        registry_file=cfg / "registry.yaml",
        defaults_file=cfg / "defaults.yaml",
        workspaces_dir=cfg / "workspaces",
        secrets_dir=cfg / "secrets",
    )

def _default_registry() -> Dict[str, Any]:
    return {
        "current_workspace": "default",
        "workspaces": {"default": {"projects": {}}},
    }

def _ensure_shape(reg: Dict[str, Any]) -> Dict[str, Any]:
    if not reg:
        reg = {}
    if "current_workspace" not in reg:
        reg["current_workspace"] = "default"
    if "workspaces" not in reg:
        reg["workspaces"] = {"default": {"projects": {}}}
    for ws, data in list(reg["workspaces"].items()):
        if data is None:
            reg["workspaces"][ws] = {"projects": {}}
        else:
            data.setdefault("projects", {})
    return reg

def load_registry() -> Dict[str, Any]:
    p = get_paths().registry_file
    if not p.exists():
        return _default_registry()
    with p.open("r", encoding="utf-8") as f:
        reg = yaml.safe_load(f) or _default_registry()
        return _ensure_shape(reg)

def save_registry(reg: Dict[str, Any]) -> None:
    reg = _ensure_shape(reg)
    p = get_paths().registry_file
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(reg, f, sort_keys=True)

# placeholder for future git sync helpers
def _git(cmd: list[str], cwd: Path) -> Tuple[int, str, str]:
    res = subprocess.run(["git", *cmd], cwd=str(cwd), capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()
