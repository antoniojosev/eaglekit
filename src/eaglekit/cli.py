
from __future__ import annotations
import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich.panel import Panel
from typing import Optional, Dict, Any
from pathlib import Path
import subprocess
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

def _git_root(path: Path) -> Optional[Path]:
    res = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if res.returncode == 0:
        return Path(res.stdout.strip())
    return None

def _git_path(path: Path, what: str) -> Optional[Path]:
    res = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-path", what], capture_output=True, text=True)
    if res.returncode == 0:
        return Path(res.stdout.strip())
    return None

def _ensure_line(file: Path, line: str) -> bool:
    file.parent.mkdir(parents=True, exist_ok=True)
    if file.exists():
        txt = file.read_text(encoding="utf-8").splitlines()
        if any(l.strip() == line for l in txt):
            return False
    with file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return True

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
    console.print(Panel("Welcome to Eagle Kit!\n\n1) Your username\n2) Git ignore preferences for .eagle/\n\nYou can change these later with 'ek setup'.", title="First-run Setup"))
    d = _load_defaults()
    uname = Prompt.ask("Your username", default=str(d.get("user", {}).get("name", os.getenv("USER", "dev"))))
    d.setdefault("user", {})["name"] = uname
    
    console.print(Panel(".eagle/ contains local metadata.\nOptions: local (recommended), repo, global, none.", title="Git Ignore Policy"))
    choice = Prompt.ask("Default ignore policy", choices=["local","repo","global","none"], default=str(d.get("preferences", {}).get("ignore_policy", "local")))
    d.setdefault("preferences", {})["ignore_policy"] = choice
    
    d["first_run_done"] = True
    _save_defaults(d)
    console.print(f"Setup complete — user.name = {uname}, ignore_policy = {choice}")

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

# ---------- Ignore management ----------
ignore_app = typer.Typer(help="Manage how to ignore .eagle/ in Git")
app.add_typer(ignore_app, name="ignore")

@ignore_app.command("explain")
def ignore_explain():
    """Explain ignore options"""
    console.print(Panel("Options:\nlocal -> .git/info/exclude (only you) [recommended]\nrepo -> .gitignore (versioned)\nglobal -> ~/.config/git/ignore\nnone -> don't touch anything", title="Eagle Kit — Ignore .eagle/"))

def _apply_repo_ignore(repo_root: Path) -> bool:
    gi = repo_root / ".gitignore"
    return _ensure_line(gi, ".eagle/")

def _apply_local_ignore(repo_root: Path) -> bool:
    excl = _git_path(repo_root, "info/exclude")
    if not excl:
        return False
    return _ensure_line(excl, ".eagle/")

@ignore_app.command("repo")
def ignore_repo():
    """Add .eagle/ to .gitignore"""
    root = _git_root(Path.cwd())
    if not root:
        console.print("Not a Git repository.")
        raise typer.Exit(1)
    changed = _apply_repo_ignore(root)
    console.print("Added .eagle/ to .gitignore" if changed else ".gitignore already contains it")

@ignore_app.command("local")
def ignore_local():
    """Add .eagle/ to .git/info/exclude"""
    root = _git_root(Path.cwd())
    if not root:
        console.print("Not a Git repository.")
        raise typer.Exit(1)
    changed = _apply_local_ignore(root)
    console.print("Added .eagle/ to .git/info/exclude" if changed else "Already present or couldn't resolve info/exclude")

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
    
    # Apply ignore default if configured
    d = _load_defaults()
    policy = d.get("preferences", {}).get("ignore_policy", "none")
    try:
        if policy == "repo":
            root = _git_root(p) or p
            _apply_repo_ignore(root)
        elif policy == "local":
            root = _git_root(p) or p
            _apply_local_ignore(root)
        if policy in ("repo","local"):
            console.print(f"Applied default ignore policy ({policy})")
    except Exception:
        pass
    
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
