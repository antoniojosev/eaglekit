
from __future__ import annotations
import typer
from rich.console import Console
from typing import Optional
from .config import load_registry, save_registry
from .core import Project

app = typer.Typer(help="Eagle Kit — dev project manager CLI.", add_completion=False)
console = Console()

@app.command()
def hello():
    """Hello world command"""
    console.print("[green]Hello from Eagle Kit![/]")

@app.command()
def add(path: str, name: Optional[str] = typer.Option(None, "--name", "-n")):
    """Add a project to the registry"""
    from pathlib import Path
    p = Path(path).expanduser().resolve()
    if not p.exists():
        console.print(f"Path does not exist: {p}")
        raise typer.Exit(1)
    
    reg = load_registry()
    reg.setdefault("workspaces", {})
    reg["workspaces"].setdefault("default", {"projects": {}})
    
    proj_name = name or p.name
    reg["workspaces"]["default"]["projects"][proj_name] = {"path": str(p)}
    save_registry(reg)
    console.print(f"Added project: {proj_name} -> {p}")

if __name__ == "__main__":
    app()
