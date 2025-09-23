
from __future__ import annotations
import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich.panel import Panel
from typing import Optional, Dict, Any
from pathlib import Path
import yaml
import os
from .config import load_registry, save_registry, get_paths
from .core import Project

app = typer.Typer(help="Eagle Kit — dev project manager CLI.", add_completion=False)
console = Console()

def _reg() -> Dict[str, Any]:
    return load_registry()

def _save(reg: Dict[str, Any]) -> None:
    save_registry(reg)

def _projects(reg: Dict[str, Any], ws: str) -> Dict[str, Any]:
    return reg["workspaces"][ws]["projects"]

def _project_by_cwd(reg: Dict[str, Any], wsname: str, cwd: Path | None = None) -> Project | None:
    cwd = cwd or Path.cwd().resolve()
    best = None
    best_len = -1
    for name, meta in _projects(reg, wsname).items():
        p = Path(meta["path"]).expanduser().resolve()
        try:
            _ = cwd.relative_to(p)
            plen = len(str(p))
            if plen > best_len:
                best = Project(name=name, path=p)
                best_len = plen
        except Exception:
            continue
    return best

# ---------- Setup wizard ----------
def _defaults_path() -> Path:
    return get_paths().defaults_file

def _load_defaults() -> Dict[str, Any]:
    p = _defaults_path()
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def _save_defaults(cfg: Dict[str, Any]) -> None:
    _defaults_path().parent.mkdir(parents=True, exist_ok=True)
    _defaults_path().write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")

def _first_run_needed() -> bool:
    d = _load_defaults()
    return not d.get("first_run_done", False)

def _wizard() -> None:
    console.print(Panel("Welcome to Eagle Kit!\n\n1) Your username\n2) Git ignore preferences\n\nYou can change these later with 'ek setup'.", title="First-run Setup"))
    d = _load_defaults()
    uname = Prompt.ask("Your username", default=str(d.get("user", {}).get("name", os.getenv("USER", "dev"))))
    d.setdefault("user", {})["name"] = uname
    d["first_run_done"] = True
    _save_defaults(d)
    console.print(f"Setup complete — user.name = {uname}")

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if _first_run_needed() and (not ctx.invoked_subcommand):
        _wizard()
        console.print("\nType 'ek --help' to see available commands.")
        raise typer.Exit(0)

@app.command("setup")
def setup():
    """Run the setup wizard"""
    _wizard()

@app.command()
def hello():
    """Hello world command"""
    console.print("[green]Hello from Eagle Kit![/]")

@app.command()
def add(path: str, name: Optional[str] = typer.Option(None, "--name", "-n")):
    """Add a project to the registry"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        console.print(f"Path does not exist: {p}")
        raise typer.Exit(1)
    
    reg = _reg()
    reg.setdefault("workspaces", {})
    reg["workspaces"].setdefault("default", {"projects": {}})
    
    proj_name = name or p.name
    _projects(reg, "default")[proj_name] = {"path": str(p)}
    _save(reg)
    console.print(f"Added project: {proj_name} -> {p}")

@app.command("list")
def list_projects():
    """List all registered projects"""
    reg = _reg()
    cur = reg.get("current_workspace", "default")
    reg.setdefault("workspaces", {})
    reg["workspaces"].setdefault(cur, {"projects": {}})
    
    table = Table(title=f"Projects (ws: {cur})")
    table.add_column("Name", style="bold")
    table.add_column("Path")
    
    for name, meta in sorted(_projects(reg, cur).items()):
        table.add_row(name, meta["path"])
    console.print(table)

@app.command("status")
def status():
    """Show current project status"""
    reg = _reg()
    ws = reg.get("current_workspace", "default")
    reg.setdefault("workspaces", {})
    reg["workspaces"].setdefault(ws, {"projects": {}})
    
    pr = _project_by_cwd(reg, ws)
    if not pr:
        console.print("No project matched CWD. Use 'ek add' or enter a registered project directory.")
        raise typer.Exit(0)
    
    table = Table(title=f"Eagle Kit — status: {pr.name}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Workspace", ws)
    table.add_row("Path", str(pr.path))
    console.print(table)

if __name__ == "__main__":
    app()
