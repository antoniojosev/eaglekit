
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import typer
from rich.table import Table
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from typing import Optional, Dict, Any, List
from .config import (
    load_registry, save_registry, get_paths
)
from .core import Project
import yaml
import os
import sys

app = typer.Typer(
    help="""Eagle Kit — Development project manager CLI.

Eagle Kit helps you manage multiple development projects with:
• Project registry and workspace organization
• Task management and automation
• Git integration and .eagle/ directory handling
• Extensible plugin system
• First-run setup and configuration

Examples:
  ek add .                    # Register current directory as project
  ek list                     # Show all registered projects
  ek status                   # Show current project information
  ek run list                 # List available tasks
  ek ignore local             # Add .eagle/ to .git/info/exclude
  ek plugins                  # Show installed plugins

Get started:
  ek setup                    # Run configuration wizard
  ek --help                   # Show this help

For command-specific help: ek COMMAND --help
""", 
    add_completion=False,
    rich_markup_mode="rich"
)
console = Console()

# ---------- Plugin system ----------
_loaded_plugins = []
_failed_plugins = []

def _load_plugins():
    """Load plugins from entry points"""
    global _loaded_plugins, _failed_plugins
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        if hasattr(eps, 'select'):
            # Python 3.10+
            plugin_eps = eps.select(group='eaglekit.plugins')
        else:
            # Python 3.9
            plugin_eps = eps.get('eaglekit.plugins', [])
        
        for ep in plugin_eps:
            try:
                register_func = ep.load()
                register_func(app)
                _loaded_plugins.append({
                    'name': ep.name,
                    'module': ep.value,
                    'status': 'loaded'
                })
                console.print(f"[dim]Loaded plugin: {ep.name}[/]")
            except Exception as e:
                _failed_plugins.append({
                    'name': ep.name,
                    'module': ep.value,
                    'status': 'failed',
                    'error': str(e)
                })
                console.print(f"[yellow]Warning: Failed to load plugin {ep.name}: {e}[/]")
    except ImportError:
        # No importlib.metadata available
        pass
    except Exception as e:
        console.print(f"[yellow]Warning: Plugin loading failed: {e}[/]")

def _get_available_plugins():
    """Get all available plugins (loaded and failed)"""
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        if hasattr(eps, 'select'):
            # Python 3.10+
            plugin_eps = eps.select(group='eaglekit.plugins')
        else:
            # Python 3.9
            plugin_eps = eps.get('eaglekit.plugins', [])
        
        return [{'name': ep.name, 'module': ep.value} for ep in plugin_eps]
    except ImportError:
        return []
    except Exception:
        return []

# Load plugins on import
_load_plugins()

# ---------- Registry & project helpers ----------
def _reg() -> Dict[str, Any]:
    return load_registry()

def _save(reg: Dict[str, Any]) -> None:
    save_registry(reg)

def _cur_ws(reg: Dict[str, Any], override: Optional[str]) -> str:
    ws = override or reg.get("current_workspace", "default")
    reg.setdefault("workspaces", {})
    reg["workspaces"].setdefault(ws, {"projects": {}})
    return ws

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

def _project_from_name_or_cwd(name: Optional[str], ws: Optional[str]) -> Project:
    reg = _reg()
    wsname = _cur_ws(reg, ws)
    if name:
        pr = _projects(reg, wsname).get(name)
        if not pr:
            console.print(f"[red]Unknown project in workspace '{wsname}':[/] {name}")
            raise typer.Exit(code=1)
        return Project(name=name, path=Path(pr["path"]).expanduser())
    pr = _project_by_cwd(reg, wsname)
    if pr:
        return pr
    console.print("[red]No project matched the current directory.[/] Use -n/--name or --ws, or run inside a registered project.")
    raise typer.Exit(1)

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

# ---------- Defaults / first-run wizard ----------
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
    console.print(Panel("Bienvenido a Eagle Kit\n\n1) Tu nombre de usuario.\n2) Cómo ignorar .eagle/ en Git.\n\nPuedes cambiar todo luego con ek setup o ek ignore ...", title="First-run"))
    d = _load_defaults()
    uname = Prompt.ask("Tu nombre de usuario", default=str(d.get("user", {}).get("name", os.getenv("USER", "dev"))))
    d.setdefault("user", {})["name"] = uname
    console.print(Panel(".eagle/ contiene metadatos locales.\nOpciones: local (recomendado), global, repo, none.", title="Ignorar .eagle/ en Git"))
    choice = Prompt.ask("Política por defecto", choices=["local","global","repo","none"], default=str(d.get("preferences", {}).get("ignore_policy", "local")))
    d.setdefault("preferences", {})["ignore_policy"] = choice
    d["first_run_done"] = True
    _save_defaults(d)
    console.print(f"Listo — user.name = {uname}, ignore_policy = {choice}.")

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if _first_run_needed() and (not ctx.invoked_subcommand):
        _wizard()
        console.print("\nEscribe ek --help para ver los comandos.")
        raise typer.Exit(0)

@app.command("setup")
def setup():
    """Run the configuration wizard.

    Interactive setup to configure Eagle Kit for first use or
    to change existing settings. Configures:
    • User name
    • Default ignore policy for .eagle/ directories
    • Other preferences

    Examples:
      ek setup                   # Run interactive configuration

    This wizard runs automatically on first use of Eagle Kit.
    """
    _wizard()

# ---------- Ignore management ----------
ignore_app = typer.Typer(
    help="""Manage .eagle/ directory in Git ignore systems.

Eagle Kit creates .eagle/ directories to store project metadata.
This command group helps you configure Git to ignore these directories
using different strategies based on your workflow needs.

Strategies:
  local  → .git/info/exclude (personal, not versioned) [RECOMMENDED]
  repo   → .gitignore (versioned with repository)
  global → ~/.config/git/ignore (applies to all repos)
  none   → manual management

Examples:
  ek ignore explain             # Learn about ignore strategies
  ek ignore status              # Check current ignore configuration
  ek ignore local               # Add to .git/info/exclude
  ek ignore repo                # Add to .gitignore
  ek ignore global              # Add to global git ignore

The 'local' strategy is recommended for most users as it keeps
.eagle/ ignored without affecting other developers.
""",
    rich_markup_mode="rich"
)
app.add_typer(ignore_app, name="ignore")

@ignore_app.command("explain")
def ignore_explain():
    """Explain .eagle/ ignore strategies and their use cases.

    Shows detailed information about each ignore strategy:
    • local: Personal ignore via .git/info/exclude (recommended)
    • repo: Versioned ignore via .gitignore 
    • global: System-wide ignore via ~/.config/git/ignore
    • none: Manual management

    Helps you choose the right strategy for your workflow.
    """
    console.print(Panel("Opciones:\nlocal -> .git/info/exclude (solo tú) [recomendado]\nglobal -> ~/.config/git/ignore\nrepo -> .gitignore (versionado)\nnone -> no tocar nada", title="Eagle Kit — Ignore .eagle/"))

def _apply_repo_ignore(repo_root: Path) -> bool:
    gi = repo_root / ".gitignore"
    return _ensure_line(gi, ".eagle/")

def _apply_local_ignore(repo_root: Path) -> bool:
    excl = _git_path(repo_root, "info/exclude")
    if not excl:
        return False
    return _ensure_line(excl, ".eagle/")

def _ensure_global_excludes() -> Path:
    res = subprocess.run(["git", "config", "--global", "core.excludesFile"], capture_output=True, text=True)
    path = res.stdout.strip()
    if not path:
        path = os.path.expanduser("~/.config/git/ignore")
        subprocess.run(["git", "config", "--global", "core.excludesFile", path], check=False)
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.touch()
    return p

def _apply_global_ignore() -> bool:
    p = _ensure_global_excludes()
    return _ensure_line(p, ".eagle/")

@ignore_app.command("status")
def ignore_status():
    root = _git_root(Path.cwd())
    if not root:
        console.print("No es un repo Git.")
        return
    repo_has = (root / ".gitignore").exists() and (".eagle/" in (root / ".gitignore").read_text(encoding="utf-8"))
    excl = _git_path(root, "info/exclude")
    local_has = False
    if excl and excl.exists():
        local_has = ".eagle/" in excl.read_text(encoding="utf-8")
    res = subprocess.run(["git", "config", "--global", "core.excludesFile"], capture_output=True, text=True)
    gfile = res.stdout.strip() or "~/.config/git/ignore"
    from pathlib import Path as _P
    gpath = _P(os.path.expanduser(gfile))
    global_has = gpath.exists() and ".eagle/" in gpath.read_text(encoding="utf-8")
    table = Table(title=f"Ignore status for repo: {root.name}")
    table.add_column("Scope"); table.add_column("File"); table.add_column("Contains .eagle/?")
    table.add_row("repo (.gitignore)", str(root / ".gitignore"), "✅" if repo_has else "—")
    table.add_row("local (.git/info/exclude)", str(excl) if excl else "(n/a)", "✅" if local_has else "—")
    table.add_row("global (core.excludesFile)", str(gpath), "✅" if global_has else "—")
    console.print(table)

@ignore_app.command("repo")
def ignore_repo():
    root = _git_root(Path.cwd())
    if not root:
        console.print("No es un repo Git.")
        raise typer.Exit(1)
    changed = _apply_repo_ignore(root)
    console.print("Añadido .eagle/ a .gitignore" if changed else ".gitignore ya lo contiene")

@ignore_app.command("local")
def ignore_local():
    root = _git_root(Path.cwd())
    if not root:
        console.print("No es un repo Git.")
        raise typer.Exit(1)
    changed = _apply_local_ignore(root)
    console.print("Añadido .eagle/ a .git/info/exclude" if changed else "Ya estaba o no se pudo resolver info/exclude")

@ignore_app.command("global")
def ignore_global():
    changed = _apply_global_ignore()
    console.print("Añadido .eagle/ al exclude global" if changed else "El exclude global ya lo contiene")

# ---------- Tasks (run) ----------
run_app = typer.Typer(
    help="""Task management and execution system.

Eagle Kit's task system lets you define, manage, and execute project tasks
from configuration files. Tasks can be shell commands, scripts, or complex
multi-step processes with environment variables and parameters.

Task Configuration:
  Tasks are defined in .eagle/config.yaml (project-wide) or
  .eagle/branches/<branch>/config.yaml (branch-specific).

Task Types:
  • Shell commands: "npm run build"
  • Command arrays: ["python", "main.py", "--verbose"]  
  • Script tasks: {type: script, path: scripts/deploy.sh, shell: bash}

Examples:
  ek run list                    # Show available tasks
  ek run do build                # Run 'build' task
  ek run task test               # Run 'test' task (alternative syntax)
  ek run new deploy --bash       # Create new bash script task
  ek deploy                      # Direct task execution (if not a known command)

Branch tasks override project tasks with the same name.
""",
    rich_markup_mode="rich"
)
app.add_typer(run_app, name="run")

def _current_branch(proj: Project) -> str:
    res = subprocess.run(["git", "-C", str(proj.path), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    if res.returncode == 0:
        b = res.stdout.strip()
        return b if b else "detached"
    return "detached"

def _read_yaml(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def _load_tasks_for(proj: Project) -> Dict[str, Any]:
    cfg = _read_yaml(proj.meta_dir / "config.yaml")
    branch = _current_branch(proj)
    bcfg = _read_yaml(proj.meta_dir / "branches" / branch / "config.yaml")
    tasks = {}
    if isinstance(cfg.get("tasks"), dict):
        tasks.update(cfg["tasks"])
    if isinstance(bcfg.get("tasks"), dict):
        tasks.update(bcfg["tasks"])
    return tasks

def _exec_task(proj: Project, spec, extra_args: List[str] | None):
    import shlex
    env = os.environ.copy()
    # dict script
    if isinstance(spec, dict) and spec.get("type") == "script":
        path = spec.get("path"); shell = spec.get("shell")
        if isinstance(spec.get("env"), dict):
            env.update({str(k): str(v) for k,v in spec["env"].items()})
        if not path:
            console.print("[red]Script task missing 'path'[/]"); raise typer.Exit(1)
        script = (proj.path / path).resolve() if not Path(path).is_absolute() else Path(path)
        if not script.exists():
            console.print(f"[red]Script not found:[/] {script}"); raise typer.Exit(1)
        args = extra_args or []
        if shell in (None, "", "python"):
            cmd = [sys.executable, str(script)] + args
        elif shell == "bash":
            cmd = ["bash", str(script)] + args
        elif shell in ("pwsh","powershell"):
            cmd = ["pwsh", "-File", str(script)] + args
        elif shell in ("cmd","bat"):
            cmd = ["cmd.exe", "/c", str(script)] + args
        else:
            cmd = [str(script)] + args
        raise typer.Exit(subprocess.call(cmd, cwd=str(proj.path), env=env))

    # string -> shell
    if isinstance(spec, str):
        cmd = spec
        if extra_args:
            cmd += " " + " ".join(shlex.quote(a) for a in extra_args)
        raise typer.Exit(subprocess.call(cmd, shell=True, cwd=str(proj.path), env=env))

    # list -> exec
    if isinstance(spec, list):
        cmd = spec + (extra_args or [])
        raise typer.Exit(subprocess.call(cmd, cwd=str(proj.path), env=env))

    console.print("[red]Task spec must be string, list, or {type: script} dict[/]")
    raise typer.Exit(1)

@run_app.command("list")
def run_list(
    name: Optional[str] = typer.Argument(None, help="Project name (defaults to current directory)"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name")
):
    """List all available tasks for a project.

    Shows tasks defined in .eagle/config.yaml and branch-specific
    configuration. Branch tasks override project tasks with same name.

    Examples:
      ek run list                # Show tasks for current project
      ek run list myproject      # Show tasks for specific project
      ek run list --ws production # Show tasks in production workspace

    Tasks can be shell commands, script references, or command arrays.
    Use 'ek run do TASK' or 'ek run task TASK' to execute tasks.
    """
    reg = _reg(); wsname = _cur_ws(reg, ws)
    proj = _project_from_name_or_cwd(name, ws=wsname)
    tasks = _load_tasks_for(proj)
    table = Table(title=f"Tasks in {proj.name}")
    table.add_column("Task", style="bold"); table.add_column("Spec")
    if not tasks:
        console.print("No tasks configured. Crea .eagle/config.yaml con un mapa 'tasks'."); return
    for t, spec in tasks.items():
        table.add_row(t, (json.dumps(spec) if isinstance(spec, list) else str(spec)))
    console.print(table)

@run_app.command("do")
def run_do(name: Optional[str] = typer.Argument(None),
           task: Optional[str] = typer.Argument(None),
           ws: Optional[str] = typer.Option(None, "--ws"),
           args: List[str] = typer.Argument(None)):
    reg = _reg(); wsname = _cur_ws(reg, ws)
    proj = _project_from_name_or_cwd(name, ws=wsname)
    tasks = _load_tasks_for(proj)
    tname = task or "default"
    if tname not in tasks:
        console.print(f"[red]Unknown task:[/] {tname}"); raise typer.Exit(1)
    _exec_task(proj, tasks[tname], args)

@run_app.command("task")
def run_task(task: str,
             name: Optional[str] = typer.Argument(None),
             ws: Optional[str] = typer.Option(None, "--ws"),
             args: List[str] = typer.Argument(None)):
    reg = _reg(); wsname = _cur_ws(reg, ws)
    proj = _project_from_name_or_cwd(name, ws=wsname)
    tasks = _load_tasks_for(proj)
    if task not in tasks:
        console.print(f"[red]Unknown task:[/] {task}"); raise typer.Exit(1)
    _exec_task(proj, tasks[task], args)

@run_app.command("new")
def run_new(task: str,
            name: Optional[str] = typer.Argument(None),
            ws: Optional[str] = typer.Option(None, "--ws"),
            cmd: Optional[str] = typer.Option(None, "--cmd", help="Command string (shell) to run"),
            bash: bool = typer.Option(False, "--bash", help="Scaffold script .sh and map it"),
            python: bool = typer.Option(False, "--python", help="Scaffold script .py and map it"),
            batch: bool = typer.Option(False, "--batch", help="Scaffold script .bat and map it"),
            pwsh: bool = typer.Option(False, "--pwsh", help="Scaffold script .ps1 (PowerShell)"),
            branch: bool = typer.Option(False, "--branch/--project", help="Create in branch overlay instead of project")):
    reg = _reg(); wsname = _cur_ws(reg, ws)
    proj = _project_from_name_or_cwd(name, ws=wsname)
    proj.ensure_meta()
    scope_dir = proj.meta_dir if not branch else (proj.meta_dir / "branches" / _current_branch(proj))
    scope_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = scope_dir / "config.yaml"
    cfg = _read_yaml(cfg_path); cfg.setdefault("tasks", {})
    scripts_dir = proj.meta_dir / "scripts"
    if bash or python or batch or pwsh:
        scripts_dir.mkdir(parents=True, exist_ok=True)
        if bash:
            script = scripts_dir / f"{task}.sh"
            if not script.exists():
                script.write_text("#!/usr/bin/env bash\nset -euo pipefail\n# TODO\n", encoding="utf-8"); os.chmod(script, 0o775)
            spec = {"type": "script", "path": str(script.relative_to(proj.path)), "shell": "bash"}
        elif python:
            script = scripts_dir / f"{task}.py"
            if not script.exists():
                script.write_text("#!/usr/bin/env python3\nimport sys\nprint('Hello from', sys.argv[0])\n", encoding="utf-8"); os.chmod(script, 0o775)
            spec = {"type": "script", "path": str(script.relative_to(proj.path)), "shell": "python"}
        elif batch:
            script = scripts_dir / f"{task}.bat"
            if not script.exists():
                script.write_text("@echo off\r\necho Hello from %~nx0\r\n", encoding="utf-8")
            spec = {"type": "script", "path": str(script.relative_to(proj.path)), "shell": "cmd"}
        else:
            script = scripts_dir / f"{task}.ps1"
            if not script.exists():
                script.write_text("param([String[]]$Args)\nWrite-Host \"Hello from $($MyInvocation.MyCommand.Name)\"\n", encoding="utf-8")
            spec = {"type": "script", "path": str(script.relative_to(proj.path)), "shell": "pwsh"}
        cfg["tasks"][task] = spec
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
        console.print(f"Scaffolded {script} and mapped task '{task}'")
        raise typer.Exit(0)
    if not cmd:
        console.print("Provide --cmd OR one of --bash/--python/--batch/--pwsh")
        raise typer.Exit(1)
    cfg["tasks"][task] = cmd
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
    console.print(f"Task created: {task} -> {cmd} at {cfg_path}")

# ---------- Simple project commands ----------
@app.command()
def add(
    path: str = typer.Argument(..., help="Path to project directory"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Custom project name (defaults to directory name)"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Target workspace (defaults to 'default')")
):
    """Register a project directory in Eagle Kit.

    Adds a project to the registry for easy access and management.
    Automatically applies configured .eagle/ ignore policy.

    Examples:
      ek add .                          # Register current directory
      ek add ~/projects/myapp           # Register specific path
      ek add . --name webapp            # Register with custom name
      ek add ~/work/api --ws production # Register in 'production' workspace

    The project will be available for:
    • Task management (ek run ...)
    • Status tracking (ek status)
    • Git ignore management (ek ignore ...)
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        console.print(f"Path does not exist: {p}")
        raise typer.Exit(1)
    reg = _reg()
    wsname = _cur_ws(reg, ws)
    proj_name = name or p.name
    _projects(reg, wsname)[proj_name] = {"path": str(p)}
    _save(reg)
    # apply ignore default if configured
    d = _load_defaults()
    policy = d.get("preferences", {}).get("ignore_policy", "none")
    try:
        if policy == "repo":
            root = _git_root(p) or p
            _apply_repo_ignore(root)
        elif policy == "local":
            root = _git_root(p) or p
            _apply_local_ignore(root)
        elif policy == "global":
            _apply_global_ignore()
        if policy in ("repo","local","global"):
            console.print(f"Applied default ignore policy ({policy})")
    except Exception:
        pass
    console.print(f"Registered {proj_name} -> {p}")

@app.command("list")
def list_projects():
    """List all registered projects in current workspace.

    Shows a table of all projects registered in Eagle Kit with their
    names and absolute paths. Helps you see what projects are available
    for task management and other operations.

    Examples:
      ek list                    # Show all projects in default workspace

    Use 'ek add' to register new projects.
    Use 'ek status' when inside a project to see current context.
    """
    reg = _reg()
    cur = reg.get("current_workspace", "default")
    table = Table(title=f"Projects (ws: {cur})")
    table.add_column("Name", style="bold"); table.add_column("Path")
    for name, meta in sorted(_projects(reg, cur).items()):
        table.add_row(name, meta["path"])
    console.print(table)

@app.command("status")
def status():
    """Show current project information and context.

    Displays information about the current project based on your
    working directory. Shows workspace, project name, and path.

    Examples:
      ek status                  # Show current project info
      cd ~/myproject && ek status # Show info for myproject

    The current directory must be inside a registered project.
    Use 'ek add .' to register the current directory first.
    Use 'ek list' to see all registered projects.
    """
    reg = _reg()
    ws = reg.get("current_workspace", "default")
    pr = _project_by_cwd(reg, ws)
    if not pr:
        console.print("No project matched CWD. Usa 'ek add' o entra en un repo registrado.")
        raise typer.Exit(0)
    table = Table(title=f"Eagle Kit — status: {pr.name}")
    table.add_column("Field"); table.add_column("Value")
    table.add_row("Workspace", ws)
    table.add_row("Path", str(pr.path))
    console.print(table)

@app.command("plugins")
def plugins():
    """Show installed plugins and their status.

    Lists all Eagle Kit plugins with detailed information:
    • Plugin name and module
    • Loading status (loaded, failed, available)
    • Error messages for failed plugins
    • Summary statistics

    Examples:
      ek plugins                 # Show all plugins and their status

    Plugins extend Eagle Kit with additional commands and features.
    Install plugins as Python packages with 'eaglekit.plugins' entry points.
    """
    table = Table(title="Eagle Kit — Installed Plugins")
    table.add_column("Plugin", style="bold")
    table.add_column("Module")
    table.add_column("Status", style="bold")
    table.add_column("Error", style="red")
    
    # Show loaded plugins
    for plugin in _loaded_plugins:
        table.add_row(
            plugin['name'],
            plugin['module'], 
            "[green]✓ Loaded[/]",
            ""
        )
    
    # Show failed plugins
    for plugin in _failed_plugins:
        table.add_row(
            plugin['name'],
            plugin['module'],
            "[red]✗ Failed[/]", 
            plugin['error']
        )
    
    # Show plugins that weren't found during loading
    available = _get_available_plugins()
    loaded_names = {p['name'] for p in _loaded_plugins}
    failed_names = {p['name'] for p in _failed_plugins}
    
    for plugin in available:
        if plugin['name'] not in loaded_names and plugin['name'] not in failed_names:
            table.add_row(
                plugin['name'],
                plugin['module'],
                "[yellow]◐ Available[/]",
                "Not loaded during startup"
            )
    
    if not available:
        console.print("[yellow]No plugins found. Install plugins with entry point 'eaglekit.plugins'[/]")
        return
        
    console.print(table)
    
    # Show summary
    loaded_count = len(_loaded_plugins)
    failed_count = len(_failed_plugins)
    total_count = len(available)
    
    console.print(f"\n[green]Loaded:[/] {loaded_count}, [red]Failed:[/] {failed_count}, [blue]Total available:[/] {total_count}")
