
from __future__ import annotations
import typer
from rich.console import Console
from rich.table import Table
from typing import Optional, Dict, Any
from pathlib import Path
from .config import load_registry, save_registry
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
