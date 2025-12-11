
from __future__ import annotations
import json
import logging
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
logger = logging.getLogger(__name__)

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
    except Exception as e:
        logger.warning(f"Could not retrieve plugin list: {e}")
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
        except Exception as e:
            logger.debug(f"Project {name} is not a parent of cwd: {e}")
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

def _resolve_project_path(project_name: str, ws: Optional[str] = None) -> Optional[Path]:
    """Resolve a project name to its absolute path.
    
    Returns None if project doesn't exist.
    """
    try:
        reg = _reg()
        wsname = _cur_ws(reg, ws)
        pr = _projects(reg, wsname).get(project_name)
        if pr:
            return Path(pr["path"]).expanduser().resolve()
        return None
    except Exception as e:
        logger.warning(f"Could not resolve path for project {project_name}: {e}")
        return None

def _clean_variable_name(name: str) -> str:
    """Clean project name to be a valid shell variable name."""
    import re
    # Replace non-alphanumeric chars with underscore, ensure starts with letter
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    clean = re.sub(r'^[0-9]', '_', clean)  # Can't start with number
    return clean

def _generate_project_variables(ws: Optional[str] = None) -> None:
    """Generate shell variables file for all registered projects."""
    reg = _reg()
    wsname = _cur_ws(reg, ws)
    projects = _projects(reg, wsname)
    
    if not projects:
        # If no projects, create empty file
        vars_file = Path.home() / '.eagle_projects'
        vars_file.write_text("# Eagle Kit project variables\n# No projects registered yet\n")
        return
    
    # Generate variables
    lines = ["# Eagle Kit project variables"]
    lines.append("# Auto-generated - do not edit manually")
    lines.append("")
    
    for name, meta in sorted(projects.items()):
        path = Path(meta["path"]).expanduser().resolve()
        var_name = _clean_variable_name(name)
        
        # Export variable without prefix
        lines.append(f'export {var_name}="{path}"')
    
    lines.append("")
    lines.append("# Usage: cd $project_name")
    
    # Write to file
    vars_file = Path.home() / '.eagle_projects'
    vars_file.write_text('\n'.join(lines) + '\n')
    
    console.print(f"[dim]✓ Variables updated: {len(projects)} projects in {vars_file}[/]")

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
    except Exception as e:
        logger.error(f"Could not load defaults from {p}: {e}")
        return {}

def _save_defaults(cfg: Dict[str, Any]) -> None:
    _defaults_path().parent.mkdir(parents=True, exist_ok=True)
    _defaults_path().write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")

def _first_run_needed() -> bool:
    d = _load_defaults()
    return not d.get("first_run_done", False)

def _wizard() -> None:
    # ASCII Art Logo
    logo = """
    ███████╗ █████╗  ██████╗ ██╗     ███████╗    ██╗  ██╗██╗████████╗
    ██╔════╝██╔══██╗██╔════╝ ██║     ██╔════╝    ██║ ██╔╝██║╚══██╔══╝
    █████╗  ███████║██║  ███╗██║     █████╗      █████╔╝ ██║   ██║   
    ██╔══╝  ██╔══██║██║   ██║██║     ██╔══╝      ██╔═██╗ ██║   ██║   
    ███████╗██║  ██║╚██████╔╝███████╗███████╗    ██║  ██╗██║   ██║   
    ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚══════╝    ╚═╝  ╚═╝╚═╝   ╚═╝   
                          
                    🦅 Development Project Manager 🦅
    """
    
    console.print(f"[bold cyan]{logo}[/]")
    console.print(Panel(
        "[bold green]¡Bienvenido a Eagle Kit![/]\n\n"
        "Eagle Kit te ayuda a gestionar proyectos de desarrollo con:\n"
        "• [blue]Registro de proyectos[/] y organización de workspaces\n"
        "• [blue]Gestión de tareas[/] y automatización\n"
        "• [blue]Integración con Git[/] y manejo de directorios .eagle/\n"
        "• [blue]Sistema de plugins[/] extensible\n\n"
        "[yellow]Vamos a configurar Eagle Kit para tu flujo de trabajo...[/]",
        title="🚀 Eagle Kit Setup",
        border_style="bold green",
        padding=(1, 2)
    ))
    
    d = _load_defaults()
    
    # 1. Configuración de usuario
    console.print("\n[bold blue]📝 Configuración de Usuario[/]")
    console.print("─" * 50)
    
    default_name = d.get("user", {}).get("name", os.getenv("USER", "dev"))
    uname = Prompt.ask(
        "[green]¿Cuál es tu nombre de usuario?[/]",
        default=str(default_name),
        show_default=True
    )
    d.setdefault("user", {})["name"] = uname
    console.print(f"[dim]✓ Usuario configurado como: {uname}[/]")
    
    # 2. Configuración de política de ignore
    console.print("\n[bold blue]📁 Configuración de .eagle/ en Git[/]")
    console.print("─" * 50)
    
    console.print(Panel(
        "[bold yellow]Eagle Kit crea directorios .eagle/ para metadatos del proyecto.[/]\n\n"
        "[blue]local[/]   → .git/info/exclude (solo tú, no versionado) [RECOMENDADO]\n"
        "[green]repo[/]    → .gitignore (versionado con el repositorio)\n"
        "[cyan]global[/]  → ~/.config/git/ignore (aplica a todos tus repos)\n"
        "[magenta]none[/]   → Sin configuración automática, control manual\n\n"
        "[dim]La opción 'local' es recomendada porque mantiene .eagle/ ignorado\n"
        "sin afectar a otros desarrolladores del proyecto.[/]",
        title="🔧 Estrategias de Ignore",
        border_style="blue"
    ))
    
    choice = Prompt.ask(
        "[green]¿Cómo quieres manejar .eagle/ en Git?[/]",
        choices=["local", "repo", "global", "none"],
        default=str(d.get("preferences", {}).get("ignore_policy", "local")),
        show_choices=True,
        show_default=True
    )
    
    d.setdefault("preferences", {})["ignore_policy"] = choice
    
    # Explicar la elección
    explanations = {
        "local": "✓ [green]Perfecto![/] .eagle/ será ignorado solo en tu copia local",
        "repo": "✓ [yellow]Atención:[/] .eagle/ será ignorado para todos los colaboradores",
        "global": "✓ [blue]Configurado![/] .eagle/ será ignorado en todos tus repositorios",
        "none": "✓ [magenta]Entendido![/] Tendrás control total sobre el ignore"
    }
    console.print(f"[dim]{explanations[choice]}[/]")
    
    # 3. Configuraciones adicionales (futuras expansiones)
    console.print("\n[bold blue]⚙️  Configuraciones Adicionales[/]")
    console.print("─" * 50)
    
    # Editor preferido (opcional)
    default_editor = d.get("preferences", {}).get("editor", os.getenv("EDITOR", ""))
    if default_editor:
        keep_editor = Prompt.ask(
            f"[green]¿Mantener editor por defecto '{default_editor}'?[/]",
            choices=["y", "n"],
            default="y"
        )
        if keep_editor == "n":
            editor = Prompt.ask("[green]¿Cuál es tu editor preferido?[/]", default="code")
            d.setdefault("preferences", {})["editor"] = editor
        else:
            d.setdefault("preferences", {})["editor"] = default_editor
    else:
        editor = Prompt.ask(
            "[green]¿Cuál es tu editor preferido?[/] [dim](opcional)[/]",
            default="",
            show_default=False
        )
        if editor:
            d.setdefault("preferences", {})["editor"] = editor
    
    # Variables de shell automáticas
    console.print("\n[bold blue]🔗 Variables de Shell[/]")
    console.print("─" * 50)
    
    console.print(Panel(
        "[bold yellow]¿Habilitar variables automáticas de proyecto?[/]\n\n"
        "[green]✓[/] [bold]cd $proyecto[/] → navega a cualquier proyecto registrado\n"
        "[blue]•[/] Se crean automáticamente al agregar proyectos\n"
        "[blue]•[/] Formato: export proyecto=\"/path/to/proyecto\"\n"
        "[blue]•[/] Requiere agregar source ~/.eagle_projects a tu shell\n\n"
        "[dim]Ejemplo: ek add . --name api → después cd $api funciona[/]",
        title="🔧 Project Variables",
        border_style="green"
    ))
    
    enable_vars = Prompt.ask(
        "[green]¿Habilitar variables automáticas?[/]",
        choices=["y", "n"],
        default="y",
        show_choices=True,
        show_default=True
    )
    
    if enable_vars == "y":
        d.setdefault("preferences", {})["shell_variables"] = True
        console.print("[dim]✓ Variables automáticas habilitadas[/]")
        
        # Auto-setup sourcing
        shell = os.environ.get('SHELL', '/bin/bash')
        if 'zsh' in shell:
            rc_file = Path.home() / '.zshrc'
        else:
            rc_file = Path.home() / '.bashrc'
            
        source_line = "source ~/.eagle_projects"
        
        # Check if already configured
        if rc_file.exists() and source_line in rc_file.read_text():
            console.print("[dim]✓ Auto-sourcing ya configurado[/]")
        else:
            # Add sourcing line
            with open(rc_file, 'a') as f:
                f.write(f"\n# Eagle Kit project variables\n{source_line}\n")
            console.print(f"[dim]✓ Auto-sourcing agregado a {rc_file.name}[/]")
            
    else:
        d.setdefault("preferences", {})["shell_variables"] = False
        console.print("[dim]✓ Variables automáticas deshabilitadas[/]")

    # Navegación directa con shell function
    console.print("\n[bold blue]🚀 Navegación Directa[/]")
    console.print("─" * 50)
    
    console.print(Panel(
        "[bold yellow]¿Habilitar navegación directa con 'ek cd proyecto'?[/]\n\n"
        "[green]✓[/] [bold]ek cd proyecto[/] → te mueve directamente al directorio\n"
        "[blue]•[/] Requiere instalar función en tu ~/.zshrc o ~/.bashrc\n"
        "[blue]•[/] Todos los otros comandos funcionan igual\n"
        "[blue]•[/] Puedes deshabilitarlo después con 'ek shell uninstall'\n\n"
        "[dim]Recomendado para máxima productividad[/]",
        title="🔧 Shell Integration",
        border_style="cyan"
    ))
    
    enable_nav = Prompt.ask(
        "[green]¿Habilitar navegación directa?[/]",
        choices=["y", "n"],
        default="y",
        show_choices=True,
        show_default=True
    )
    
    if enable_nav == "y":
        d.setdefault("preferences", {})["shell_integration"] = True
        console.print("[dim]✓ Se habilitará navegación directa[/]")
    else:
        d.setdefault("preferences", {})["shell_integration"] = False
        console.print("[dim]✓ Navegación directa deshabilitada[/]")

    # 4. Finalización
    d["first_run_done"] = True
    d["setup_version"] = "1.0"
    d["setup_date"] = str(Path.cwd())  # Placeholder for setup tracking
    _save_defaults(d)
    
    # Instalar shell integration si fue habilitada
    if d.get("preferences", {}).get("shell_integration"):
        try:
            shell_install()
            shell_installed = True
        except Exception as e:
            shell_installed = False
            logger.warning(f"Shell integration installation failed: {e}")
            console.print(f"[yellow]Warning: Could not install shell integration: {e}[/]")
    else:
        shell_installed = False
    
    # Resumen final
    console.print("\n" + "=" * 60)
    console.print(Panel(
        f"[bold green]🎉 ¡Configuración completada![/]\n\n"
        f"[blue]Usuario:[/] {uname}\n"
        f"[blue]Política de ignore:[/] {choice}\n" +
        (f"[blue]Editor:[/] {d.get('preferences', {}).get('editor', 'No configurado')}\n" if d.get('preferences', {}).get('editor') else "") +
        (f"[blue]Navegación directa:[/] {'✓ Habilitada' if shell_installed else '✗ Error en instalación'}\n" if d.get('preferences', {}).get('shell_integration') else "") +
        f"\n[yellow]Próximos pasos:[/]\n"
        f"• [dim]ek add .[/] - Registrar el directorio actual como proyecto\n"
        f"• [dim]ek list[/] - Ver todos tus proyectos\n"
        f"• [dim]ek run list[/] - Ver tareas disponibles\n" +
        (f"• [dim]ek cd proyecto[/] - Navegar directamente a un proyecto\n" if shell_installed else "") +
        f"• [dim]ek ignore {choice}[/] - Aplicar política de ignore\n" +
        (f"• [dim]ek ignore status[/] - Ver estado actual de ignore\n" if choice != "none" else "") +
        f"• [dim]ek --help[/] - Ver todos los comandos disponibles\n\n" +
        (f"[cyan]💡 Reinicia tu terminal para habilitar 'ek cd proyecto'[/]\n\n" if shell_installed else "") +
        f"[green]¡Eagle Kit está listo para usar! 🚀[/]",
        title="✅ Setup Completo",
        border_style="bold green",
        padding=(1, 2)
    ))

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    if _first_run_needed() and (not ctx.invoked_subcommand):
        _wizard()
        console.print("\n[bold blue]🎯 ¡Listo para empezar![/]")
        console.print("[dim]Escribe [bold]ek --help[/] para ver todos los comandos disponibles.[/]")
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

@ignore_app.command("none")
def ignore_none():
    """Configure no automatic ignore for .eagle/ directories.
    
    Choose this option if you want to manually handle .eagle/ 
    directory inclusion/exclusion in Git. Eagle Kit will not
    automatically modify any ignore files.
    """
    console.print("✓ [magenta]Configurado:[/] Eagle Kit no modificará archivos de ignore automáticamente")
    console.print("[dim]Puedes usar 'ek ignore status' para verificar el estado actual[/]")

# ---------- Shell Integration ----------
shell_app = typer.Typer(
    help="""Shell integration for direct navigation.

Configure shell functions to enable direct navigation with 'ek cd project'.
The shell integration allows you to navigate directly to registered projects
without needing to copy/paste commands.

Examples:
  ek shell install              # Install shell function
  ek shell uninstall            # Remove shell function  
  ek shell status               # Check integration status
  ek shell function             # Show function code

After installation: 'ek cd project' will navigate directly to the project.
""",
    rich_markup_mode="rich"
)
app.add_typer(shell_app, name="shell")

@shell_app.command("install")
def shell_install():
    """Install Eagle Kit shell function for direct navigation.
    
    Adds a shell function to your ~/.zshrc or ~/.bashrc that enables
    direct navigation with 'ek cd project'. The function intercepts
    'ek cd' commands and navigates directly while preserving all
    other Eagle Kit functionality.
    """
    import subprocess
    
    # Detect shell
    shell = os.environ.get('SHELL', '/bin/bash')
    if 'zsh' in shell:
        rc_file = Path.home() / '.zshrc'
    else:
        rc_file = Path.home() / '.bashrc'
    
    # Get shell function
    function_code = subprocess.run([
        sys.executable, "-c", 
        "from eaglekit.wrapper import generate_shell_function; print(generate_shell_function())"
    ], capture_output=True, text=True)
    
    if function_code.returncode != 0:
        console.print("[red]Error getting shell function[/]")
        raise typer.Exit(1)
    
    function = function_code.stdout.strip()
    marker_start = "# Eagle Kit shell integration - START"
    marker_end = "# Eagle Kit shell integration - END"
    
    # Check if already installed
    if rc_file.exists():
        content = rc_file.read_text()
        if marker_start in content:
            console.print("[yellow]Shell integration already installed[/]")
            console.print(f"[dim]Found in: {rc_file}[/]")
            return
    
    # Add function to rc file
    integration_block = f"\n{marker_start}\n{function}\n{marker_end}\n"
    
    with open(rc_file, 'a') as f:
        f.write(integration_block)
    
    console.print(f"[green]✓ Shell integration installed in {rc_file}[/]")
    console.print("[dim]Restart your shell or run: source ~/.zshrc[/]")
    console.print("[bold]Now you can use: ek cd project[/]")

@shell_app.command("uninstall") 
def shell_uninstall():
    """Remove Eagle Kit shell integration."""
    shell = os.environ.get('SHELL', '/bin/bash')
    rc_file = Path.home() / ('.zshrc' if 'zsh' in shell else '.bashrc')
    
    if not rc_file.exists():
        console.print("[yellow]No shell config file found[/]")
        return
    
    content = rc_file.read_text()
    marker_start = "# Eagle Kit shell integration - START"
    marker_end = "# Eagle Kit shell integration - END"
    
    if marker_start not in content:
        console.print("[yellow]Shell integration not found[/]")
        return
    
    # Remove integration block
    lines = content.split('\n')
    new_lines = []
    skip = False
    
    for line in lines:
        if marker_start in line:
            skip = True
            continue
        if marker_end in line:
            skip = False
            continue
        if not skip:
            new_lines.append(line)
    
    rc_file.write_text('\n'.join(new_lines))
    console.print(f"[green]✓ Shell integration removed from {rc_file}[/]")
    console.print("[dim]Restart your shell for changes to take effect[/]")

@shell_app.command("status")
def shell_status():
    """Check shell integration status."""
    shell = os.environ.get('SHELL', '/bin/bash')
    rc_file = Path.home() / ('.zshrc' if 'zsh' in shell else '.bashrc')
    
    console.print(f"[blue]Shell:[/] {shell}")
    console.print(f"[blue]Config file:[/] {rc_file}")
    
    if rc_file.exists():
        content = rc_file.read_text()
        installed = "# Eagle Kit shell integration - START" in content
        status = "[green]✓ Installed[/]" if installed else "[yellow]✗ Not installed[/]"
        console.print(f"[blue]Integration:[/] {status}")
    else:
        console.print(f"[blue]Integration:[/] [red]✗ Config file not found[/]")

@shell_app.command("function")
def shell_function():
    """Show the shell function code."""
    import subprocess
    
    result = subprocess.run([
        sys.executable, "-c", 
        "from eaglekit.wrapper import generate_shell_function; print(generate_shell_function())"
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        console.print("[bold]Eagle Kit Shell Function:[/]")
        console.print(result.stdout.strip())
    else:
        console.print("[red]Error getting shell function[/]")

@shell_app.command("refresh")
def shell_refresh():
    """Regenerate project variables file."""
    _generate_project_variables()
    console.print("[green]✓ Project variables refreshed[/]")
    console.print("[dim]Run 'source ~/.eagle_projects' to reload in current shell[/]")

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
  ek run task build              # Run 'build' task
  ek run task test               # Run 'test' task
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
    except Exception as e:
        logger.error(f"Could not read YAML from {p}: {e}")
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
    Use 'ek run task TASK' to execute tasks.
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

@run_app.command("task")
def run_task(task: str,
             name: Optional[str] = typer.Argument(None),
             ws: Optional[str] = typer.Option(None, "--ws"),
             args: List[str] = typer.Argument(None)):
    """Execute a task defined in project configuration.
    
    Runs a task from .eagle/config.yaml or branch-specific configuration.
    Tasks can be shell commands, scripts, or command arrays.
    
    Examples:
      ek run task build              # Run 'build' task in current project
      ek run task test myproject     # Run 'test' in specific project
      ek run task deploy --ws prod   # Run 'deploy' in production workspace
      
    Pass additional arguments after task and project name.
    """
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

# ---------- TODO Management ----------
todo_app = typer.Typer(
    help="""Task and TODO management for projects.

Manage TODOs and tasks for your projects with priorities, tags, and status tracking.
Each project stores its TODOs in .eagle/todos.yaml.

You can manage TODOs from anywhere using --project flag.

Examples:
  ek todo list                       # List TODOs for current project
  ek todo list --project api         # List TODOs for 'api' project
  ek todo add "Fix bug"              # Quick add TODO
  ek todo add                        # Interactive add with details
  ek todo done 1                     # Mark TODO #1 as done
  ek todo show 3                     # Show TODO #3 details
  ek todo list --priority high       # Filter by priority
  ek todo list --tag bug             # Filter by tag
  ek todo stats                      # Show statistics
""",
    rich_markup_mode="rich"
)
app.add_typer(todo_app, name="todo")

from datetime import datetime

def _get_todos_file(proj: Project) -> Path:
    """Get the path to todos.yaml for a project."""
    proj.ensure_meta()
    return proj.meta_dir / "todos.yaml"

def _load_todos(proj: Project) -> Dict[str, Any]:
    """Load TODOs from project's todos.yaml file."""
    todos_file = _get_todos_file(proj)
    if not todos_file.exists():
        return {"todos": [], "next_id": 1}
    try:
        data = yaml.safe_load(todos_file.read_text(encoding="utf-8"))
        if not data:
            return {"todos": [], "next_id": 1}
        # Ensure next_id exists
        if "next_id" not in data:
            data["next_id"] = max([t.get("id", 0) for t in data.get("todos", [])] or [0]) + 1
        return data
    except Exception as e:
        logger.error(f"Could not load TODOs from {todos_file}: {e}")
        return {"todos": [], "next_id": 1}

def _save_todos(proj: Project, data: Dict[str, Any]) -> None:
    """Save TODOs to project's todos.yaml file."""
    todos_file = _get_todos_file(proj)
    todos_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

def _get_priority_emoji(priority: str) -> str:
    """Get emoji for priority level."""
    return {"high": "🔴", "med": "🟡", "low": "🟢"}.get(priority.lower(), "⚪")

def _get_status_emoji(status: str) -> str:
    """Get emoji for status."""
    return {"todo": "⏳", "done": "✅", "blocked": "🚫"}.get(status.lower(), "⏳")

def _format_todo_row(todo: Dict[str, Any]) -> tuple:
    """Format a TODO as a table row."""
    status_emoji = _get_status_emoji(todo.get("status", "todo"))
    priority_emoji = _get_priority_emoji(todo.get("priority", "med"))
    
    status_text = f"{status_emoji} {todo.get('status', 'todo').upper()}"
    priority_text = f"{priority_emoji} {todo.get('priority', 'med').upper()}"
    tags_text = ", ".join(todo.get("tags", []))
    
    return (
        str(todo.get("id", "?")),
        status_text,
        priority_text,
        todo.get("title", "Untitled")[:40],
        tags_text[:20] if tags_text else "—"
    )

@todo_app.command("list")
def todo_list(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (defaults to current directory)"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status (todo, done, blocked)"),
    priority: Optional[str] = typer.Option(None, "--priority", help="Filter by priority (high, med, low)"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filter by tag"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Search in title/description")
):
    """List all TODOs for a project.
    
    Shows all TODOs with their status, priority, and tags.
    Can filter by various criteria.
    
    Examples:
      ek todo list                     # List all TODOs in current project
      ek todo list --project api       # List TODOs for 'api' project
      ek todo list --status todo       # Only pending TODOs
      ek todo list --priority high     # Only high priority
      ek todo list --tag bug           # Only TODOs tagged with 'bug'
      ek todo list --search "auth"     # Search for 'auth' in TODOs
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_todos(proj)
    todos = data.get("todos", [])
    
    # Apply filters
    if status:
        todos = [t for t in todos if t.get("status", "todo").lower() == status.lower()]
    if priority:
        todos = [t for t in todos if t.get("priority", "med").lower() == priority.lower()]
    if tag:
        todos = [t for t in todos if tag.lower() in [tg.lower() for tg in t.get("tags", [])]]
    if search:
        search_lower = search.lower()
        todos = [t for t in todos if 
                 search_lower in t.get("title", "").lower() or 
                 search_lower in t.get("description", "").lower()]
    
    if not todos:
        console.print(f"[yellow]No TODOs found for project '{proj.name}'[/]")
        console.print("[dim]Add one with: ek todo add \"Your task\"[/]")
        return
    
    # Create table
    table = Table(title=f"TODOs: {proj.name}")
    table.add_column("ID", style="bold cyan", justify="right")
    table.add_column("Status", style="bold")
    table.add_column("Priority", style="bold")
    table.add_column("Title")
    table.add_column("Tags", style="dim")
    
    pending = 0
    completed = 0
    
    for todo in todos:
        table.add_row(*_format_todo_row(todo))
        if todo.get("status", "todo").lower() == "done":
            completed += 1
        else:
            pending += 1
    
    console.print(table)
    console.print(f"\nTotal: {len(todos)} TODOs ([green]{pending} pending[/], [blue]{completed} completed[/])")

@todo_app.command("add")
def todo_add(
    title: Optional[str] = typer.Argument(None, help="TODO title (omit for interactive mode)"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (defaults to current directory)"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="Description"),
    priority: Optional[str] = typer.Option("med", "--priority", help="Priority: low, med, high"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags")
):
    """Add a new TODO to a project.
    
    Quick mode: provide title as argument
    Interactive mode: omit title for step-by-step input
    
    Examples:
      ek todo add "Fix login bug"                    # Quick add
      ek todo add                                    # Interactive add
      ek todo add "Update docs" --priority high      # With priority
      ek todo add "New feature" --tags feature,ui    # With tags
      ek todo add "Bug fix" --project api            # Add to 'api' project
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_todos(proj)
    
    # Interactive mode
    if not title:
        console.print("\n[bold blue]📝 Agregar nuevo TODO[/]\n")
        title = Prompt.ask("[green]Título[/]")
        description = Prompt.ask("[green]Descripción[/] [dim](opcional)[/]", default="")
        priority = Prompt.ask(
            "[green]Prioridad[/]",
            choices=["low", "med", "high"],
            default="med"
        )
        tags_input = Prompt.ask("[green]Tags[/] [dim](separados por comas, opcional)[/]", default="")
        tags_list = [t.strip() for t in tags_input.split(",") if t.strip()] if tags_input else []
    else:
        # Quick mode
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    
    # Create TODO
    todo_id = data.get("next_id", 1)
    new_todo = {
        "id": todo_id,
        "title": title,
        "description": description or "",
        "status": "todo",
        "priority": priority.lower(),
        "tags": tags_list,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    
    data["todos"].append(new_todo)
    data["next_id"] = todo_id + 1
    _save_todos(proj, data)
    
    priority_emoji = _get_priority_emoji(priority)
    console.print(f"\n✓ TODO #{todo_id} creado: [bold]\"{title}\"[/]")
    console.print(f"  [dim]Proyecto:[/] {proj.name}")
    console.print(f"  [dim]Prioridad:[/] {priority_emoji} {priority.upper()}")
    if tags_list:
        console.print(f"  [dim]Tags:[/] {', '.join(tags_list)}")
    console.print(f"\n[dim]Use 'ek todo show {todo_id}' para ver detalles[/]")

@todo_app.command("done")
def todo_done(
    todo_id: int = typer.Argument(..., help="TODO ID to mark as done"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name")
):
    """Mark a TODO as completed.
    
    Examples:
      ek todo done 1                  # Mark TODO #1 as done
      ek todo done 3 --project api    # Mark TODO #3 in 'api' project as done
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_todos(proj)
    
    todo = next((t for t in data["todos"] if t["id"] == todo_id), None)
    if not todo:
        console.print(f"[red]TODO #{todo_id} not found in project '{proj.name}'[/]")
        raise typer.Exit(1)
    
    todo["status"] = "done"
    todo["updated_at"] = datetime.now().isoformat()
    _save_todos(proj, data)
    
    console.print(f"✅ TODO #{todo_id} marcado como completado: [bold]\"{todo['title']}\"[/]")

@todo_app.command("remove")
def todo_remove(
    todo_id: int = typer.Argument(..., help="TODO ID to remove"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Remove a TODO permanently.
    
    Examples:
      ek todo remove 1                # Remove TODO #1
      ek todo remove 2 --force        # Remove without confirmation
      ek todo remove 3 --project api  # Remove from 'api' project
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_todos(proj)
    
    todo = next((t for t in data["todos"] if t["id"] == todo_id), None)
    if not todo:
        console.print(f"[red]TODO #{todo_id} not found in project '{proj.name}'[/]")
        raise typer.Exit(1)
    
    if not force:
        if not typer.confirm(f"Remove TODO #{todo_id}: \"{todo['title']}\"?"):
            console.print("[yellow]Cancelled[/]")
            raise typer.Exit(0)
    
    data["todos"] = [t for t in data["todos"] if t["id"] != todo_id]
    _save_todos(proj, data)
    
    console.print(f"🗑️  TODO #{todo_id} eliminado: [bold]\"{todo['title']}\"[/]")

@todo_app.command("show")
def todo_show(
    todo_id: int = typer.Argument(..., help="TODO ID to show"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name")
):
    """Show detailed information about a TODO.
    
    Examples:
      ek todo show 1                 # Show TODO #1 details
      ek todo show 2 --project api   # Show TODO #2 from 'api' project
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_todos(proj)
    
    todo = next((t for t in data["todos"] if t["id"] == todo_id), None)
    if not todo:
        console.print(f"[red]TODO #{todo_id} not found in project '{proj.name}'[/]")
        raise typer.Exit(1)
    
    status_emoji = _get_status_emoji(todo.get("status", "todo"))
    priority_emoji = _get_priority_emoji(todo.get("priority", "med"))
    
    console.print(f"\n{'━' * 60}")
    console.print(f"[bold cyan]TODO #{todo['id']}[/] - {proj.name}")
    console.print(f"{'━' * 60}\n")
    
    console.print(f"  [bold]Title:[/]       {todo['title']}")
    console.print(f"  [bold]Status:[/]      {status_emoji} {todo.get('status', 'todo').upper()}")
    console.print(f"  [bold]Priority:[/]    {priority_emoji} {todo.get('priority', 'med').upper()}")
    
    if todo.get("tags"):
        console.print(f"  [bold]Tags:[/]        {', '.join(todo['tags'])}")
    
    console.print(f"  [bold]Created:[/]     {todo.get('created_at', 'Unknown')}")
    console.print(f"  [bold]Updated:[/]     {todo.get('updated_at', 'Unknown')}")
    
    if todo.get("description"):
        console.print(f"\n  [bold]Description:[/]")
        for line in todo["description"].split("\n"):
            console.print(f"  {line}")
    
    console.print(f"\n{'━' * 60}\n")

@todo_app.command("edit")
def todo_edit(
    todo_id: int = typer.Argument(..., help="TODO ID to edit"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    title: Optional[str] = typer.Option(None, "--title", help="New title"),
    description: Optional[str] = typer.Option(None, "--desc", help="New description"),
    priority: Optional[str] = typer.Option(None, "--priority", help="New priority (low/med/high)"),
    status: Optional[str] = typer.Option(None, "--status", help="New status (todo/done/blocked)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="New tags (comma-separated)")
):
    """Edit an existing TODO.
    
    Examples:
      ek todo edit 1 --title "New title"        # Change title
      ek todo edit 2 --priority high            # Change priority
      ek todo edit 3 --status blocked           # Change status
      ek todo edit 4 --tags bug,urgent          # Change tags
      ek todo edit 5 --project api              # Edit TODO in 'api' project
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_todos(proj)
    
    todo = next((t for t in data["todos"] if t["id"] == todo_id), None)
    if not todo:
        console.print(f"[red]TODO #{todo_id} not found in project '{proj.name}'[/]")
        raise typer.Exit(1)
    
    changes = []
    
    if title:
        todo["title"] = title
        changes.append(f"título → \"{title}\"")
    
    if description is not None:  # Allow empty string
        todo["description"] = description
        changes.append("descripción")
    
    if priority:
        if priority.lower() not in ["low", "med", "high"]:
            console.print("[red]Priority must be: low, med, or high[/]")
            raise typer.Exit(1)
        todo["priority"] = priority.lower()
        changes.append(f"prioridad → {priority.upper()}")
    
    if status:
        if status.lower() not in ["todo", "done", "blocked"]:
            console.print("[red]Status must be: todo, done, or blocked[/]")
            raise typer.Exit(1)
        todo["status"] = status.lower()
        changes.append(f"estado → {status.upper()}")
    
    if tags is not None:
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        todo["tags"] = tags_list
        changes.append(f"tags → {', '.join(tags_list) if tags_list else '(ninguno)'}")
    
    if not changes:
        console.print("[yellow]No changes specified. Use --title, --desc, --priority, --status, or --tags[/]")
        raise typer.Exit(0)
    
    todo["updated_at"] = datetime.now().isoformat()
    _save_todos(proj, data)
    
    console.print(f"✓ TODO #{todo_id} actualizado:")
    for change in changes:
        console.print(f"  • {change}")

@todo_app.command("clear")
def todo_clear(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Remove all completed TODOs.
    
    Examples:
      ek todo clear                  # Clear completed TODOs
      ek todo clear --force          # Clear without confirmation
      ek todo clear --project api    # Clear in 'api' project
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_todos(proj)
    
    completed = [t for t in data["todos"] if t.get("status", "todo").lower() == "done"]
    
    if not completed:
        console.print(f"[yellow]No completed TODOs found in project '{proj.name}'[/]")
        return
    
    if not force:
        console.print(f"\n[bold]Completed TODOs to be removed:[/]")
        for todo in completed:
            console.print(f"  • #{todo['id']}: {todo['title']}")
        console.print()
        
        if not typer.confirm(f"Remove {len(completed)} completed TODO(s)?"):
            console.print("[yellow]Cancelled[/]")
            raise typer.Exit(0)
    
    data["todos"] = [t for t in data["todos"] if t.get("status", "todo").lower() != "done"]
    _save_todos(proj, data)
    
    console.print(f"✓ Eliminados {len(completed)} TODOs completados")

@todo_app.command("stats")
def todo_stats(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name")
):
    """Show TODO statistics for a project.
    
    Examples:
      ek todo stats                  # Stats for current project
      ek todo stats --project api    # Stats for 'api' project
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_todos(proj)
    todos = data.get("todos", [])
    
    if not todos:
        console.print(f"[yellow]No TODOs found for project '{proj.name}'[/]")
        return
    
    # Calculate statistics
    total = len(todos)
    pending = len([t for t in todos if t.get("status", "todo").lower() == "todo"])
    done = len([t for t in todos if t.get("status", "todo").lower() == "done"])
    blocked = len([t for t in todos if t.get("status", "todo").lower() == "blocked"])
    
    high = len([t for t in todos if t.get("priority", "med").lower() == "high"])
    med = len([t for t in todos if t.get("priority", "med").lower() == "med"])
    low = len([t for t in todos if t.get("priority", "med").lower() == "low"])
    
    # Count tags
    tag_counts = {}
    for todo in todos:
        for tag in todo.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Display statistics
    console.print(f"\n{'━' * 60}")
    console.print(f"[bold cyan]TODO Statistics[/] - {proj.name}")
    console.print(f"{'━' * 60}\n")
    
    console.print(f"  [bold]Total TODOs:[/]      {total}")
    console.print(f"  ⏳ Pending:          {pending}  ({pending/total*100:.1f}%)" if total > 0 else "  ⏳ Pending:          0")
    console.print(f"  ✅ Completed:        {done}  ({done/total*100:.1f}%)" if total > 0 else "  ✅ Completed:        0")
    if blocked > 0:
        console.print(f"  🚫 Blocked:          {blocked}  ({blocked/total*100:.1f}%)")
    
    console.print(f"\n  [bold]By Priority:[/]")
    console.print(f"    🔴 High:           {high}")
    console.print(f"    🟡 Medium:         {med}")
    console.print(f"    🟢 Low:            {low}")
    
    if top_tags:
        console.print(f"\n  [bold]Most used tags:[/]")
        for tag, count in top_tags:
            console.print(f"    • {tag} ({count})")
    
    console.print(f"\n{'━' * 60}\n")

# ---------- Comment Management ----------
comment_app = typer.Typer(
    help="""Comment and note system for projects.

Add comments, notes, and observations to your projects. Perfect for:
• Development notes and observations
• Bug reports and findings
• Ideas for future improvements
• Team communication
• Project changelog/diary

Each project stores comments in .eagle/comments.yaml.
You can manage comments from anywhere using --project flag.

Categories:
  note     → General note
  idea     → Idea for implementation
  bug      → Bug observation
  warning  → Warning/precaution
  done     → Completed task/change
  log      → Changelog entry

Examples:
  ek comment add "Refactor needed in auth module"
  ek comment add "Found critical bug" --category bug --tags urgent
  ek comment list --project api
  ek comment list --category bug
  ek comment search "auth"
  ek comment show 1 --project webapp
""",
    rich_markup_mode="rich"
)
app.add_typer(comment_app, name="comment")

def _get_comments_file(proj: Project) -> Path:
    """Get the path to comments.yaml for a project."""
    proj.ensure_meta()
    return proj.meta_dir / "comments.yaml"

def _load_comments(proj: Project) -> Dict[str, Any]:
    """Load comments from project's comments.yaml file."""
    comments_file = _get_comments_file(proj)
    if not comments_file.exists():
        return {"comments": [], "next_id": 1}
    try:
        data = yaml.safe_load(comments_file.read_text(encoding="utf-8"))
        if not data:
            return {"comments": [], "next_id": 1}
        if "next_id" not in data:
            data["next_id"] = max([c.get("id", 0) for c in data.get("comments", [])] or [0]) + 1
        return data
    except Exception as e:
        logger.error(f"Could not load comments from {comments_file}: {e}")
        return {"comments": [], "next_id": 1}

def _save_comments(proj: Project, data: Dict[str, Any]) -> None:
    """Save comments to project's comments.yaml file."""
    comments_file = _get_comments_file(proj)
    comments_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

def _get_category_emoji(category: str) -> str:
    """Get emoji for comment category."""
    return {
        "note": "📝",
        "idea": "💡",
        "bug": "🐛",
        "warning": "⚠️",
        "done": "✅",
        "log": "📅"
    }.get(category.lower(), "📝")

def _format_comment_row(comment: Dict[str, Any]) -> tuple:
    """Format a comment as a table row."""
    category_emoji = _get_category_emoji(comment.get("category", "note"))
    category_text = f"{category_emoji} {comment.get('category', 'note')}"
    
    # Format date
    created = comment.get("created_at", "")
    date_str = created[:10] if created else "Unknown"
    
    # Truncate message
    message = comment.get("message", "")[:50]
    if len(comment.get("message", "")) > 50:
        message += "..."
    
    tags_text = ", ".join(comment.get("tags", []))
    
    return (
        str(comment.get("id", "?")),
        category_text,
        date_str,
        message,
        tags_text[:15] if tags_text else "—"
    )

@comment_app.command("add")
def comment_add(
    message: str = typer.Argument(..., help="Comment message"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name (defaults to current directory)"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    category: str = typer.Option("note", "--category", "-c", help="Category: note, idea, bug, warning, done, log"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="Comma-separated tags")
):
    """Add a comment to a project.
    
    Comments are notes and observations about the project.
    
    Examples:
      ek comment add "Need to refactor auth"
      ek comment add "Critical bug found" --category bug
      ek comment add "Good idea for v2" --category idea --tags feature,ui
      ek comment add "Deployed to prod" --category log --project api
    """
    # Validate category
    valid_categories = ["note", "idea", "bug", "warning", "done", "log"]
    if category.lower() not in valid_categories:
        console.print(f"[red]Invalid category. Must be one of: {', '.join(valid_categories)}[/]")
        raise typer.Exit(1)
    
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_comments(proj)
    
    # Parse tags
    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    
    # Get author from environment or defaults
    author = os.getenv("USER", "unknown")
    
    # Create comment
    comment_id = data.get("next_id", 1)
    new_comment = {
        "id": comment_id,
        "message": message,
        "category": category.lower(),
        "tags": tags_list,
        "author": author,
        "created_at": datetime.now().isoformat()
    }
    
    data["comments"].append(new_comment)
    data["next_id"] = comment_id + 1
    _save_comments(proj, data)
    
    category_emoji = _get_category_emoji(category)
    console.print(f"\n✓ Comment #{comment_id} added to project [cyan]{proj.name}[/]")
    console.print(f"  [dim]Category:[/] {category_emoji} {category.upper()}")
    if tags_list:
        console.print(f"  [dim]Tags:[/] {', '.join(tags_list)}")

@comment_app.command("list")
def comment_list(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    recent: Optional[int] = typer.Option(None, "--recent", "-n", help="Show only N most recent")
):
    """List all comments for a project.
    
    Examples:
      ek comment list
      ek comment list --project api
      ek comment list --category bug
      ek comment list --tag urgent
      ek comment list --recent 10
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_comments(proj)
    comments = data.get("comments", [])
    
    # Apply filters
    if category:
        comments = [c for c in comments if c.get("category", "note").lower() == category.lower()]
    if tag:
        comments = [c for c in comments if tag.lower() in [t.lower() for t in c.get("tags", [])]]
    
    # Sort by date (newest first)
    comments.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    
    # Limit to recent
    if recent:
        comments = comments[:recent]
    
    if not comments:
        console.print(f"[yellow]No comments found for project '{proj.name}'[/]")
        console.print("[dim]Add one with: ek comment add \"Your note\"[/]")
        return
    
    # Create table
    table = Table(title=f"Comments: {proj.name}")
    table.add_column("ID", style="bold cyan", justify="right")
    table.add_column("Category", style="bold")
    table.add_column("Date")
    table.add_column("Comment")
    table.add_column("Tags", style="dim")
    
    for comment in comments:
        table.add_row(*_format_comment_row(comment))
    
    console.print(table)
    console.print(f"\n{len(comments)} comment(s) total")

@comment_app.command("show")
def comment_show(
    comment_id: int = typer.Argument(..., help="Comment ID to show"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name")
):
    """Show detailed information about a comment.
    
    Examples:
      ek comment show 1
      ek comment show 3 --project api
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_comments(proj)
    
    comment = next((c for c in data["comments"] if c["id"] == comment_id), None)
    if not comment:
        console.print(f"[red]Comment #{comment_id} not found in project '{proj.name}'[/]")
        raise typer.Exit(1)
    
    category_emoji = _get_category_emoji(comment.get("category", "note"))
    
    console.print(f"\n{'━' * 60}")
    console.print(f"[bold cyan]Comment #{comment['id']}[/] - {proj.name}")
    console.print(f"{'━' * 60}\n")
    
    console.print(f"  [bold]Category:[/]    {category_emoji} {comment.get('category', 'note').upper()}")
    console.print(f"  [bold]Author:[/]      {comment.get('author', 'unknown')}")
    console.print(f"  [bold]Created:[/]     {comment.get('created_at', 'Unknown')}")
    
    if comment.get("tags"):
        console.print(f"  [bold]Tags:[/]        {', '.join(comment['tags'])}")
    
    console.print(f"\n  [bold]Message:[/]")
    for line in comment.get("message", "").split("\n"):
        console.print(f"  {line}")
    
    console.print(f"\n{'━' * 60}\n")

@comment_app.command("edit")
def comment_edit(
    comment_id: int = typer.Argument(..., help="Comment ID to edit"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="New message"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="New category"),
    tags: Optional[str] = typer.Option(None, "--tags", "-t", help="New tags (comma-separated)")
):
    """Edit an existing comment.
    
    Examples:
      ek comment edit 1 --message "Updated note"
      ek comment edit 2 --category bug
      ek comment edit 3 --tags urgent,critical
      ek comment edit 4 --project api --message "New text"
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_comments(proj)
    
    comment = next((c for c in data["comments"] if c["id"] == comment_id), None)
    if not comment:
        console.print(f"[red]Comment #{comment_id} not found in project '{proj.name}'[/]")
        raise typer.Exit(1)
    
    changes = []
    
    if message:
        comment["message"] = message
        changes.append(f"message → \"{message[:30]}...\"" if len(message) > 30 else f"message → \"{message}\"")
    
    if category:
        valid_categories = ["note", "idea", "bug", "warning", "done", "log"]
        if category.lower() not in valid_categories:
            console.print(f"[red]Invalid category. Must be one of: {', '.join(valid_categories)}[/]")
            raise typer.Exit(1)
        comment["category"] = category.lower()
        changes.append(f"category → {category.upper()}")
    
    if tags is not None:
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        comment["tags"] = tags_list
        changes.append(f"tags → {', '.join(tags_list) if tags_list else '(none)'}")
    
    if not changes:
        console.print("[yellow]No changes specified. Use --message, --category, or --tags[/]")
        raise typer.Exit(0)
    
    _save_comments(proj, data)
    
    console.print(f"✓ Comment #{comment_id} updated:")
    for change in changes:
        console.print(f"  • {change}")

@comment_app.command("remove")
def comment_remove(
    comment_id: int = typer.Argument(..., help="Comment ID to remove"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Remove a comment permanently.
    
    Examples:
      ek comment remove 1
      ek comment remove 2 --force
      ek comment remove 3 --project api
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_comments(proj)
    
    comment = next((c for c in data["comments"] if c["id"] == comment_id), None)
    if not comment:
        console.print(f"[red]Comment #{comment_id} not found in project '{proj.name}'[/]")
        raise typer.Exit(1)
    
    if not force:
        preview = comment["message"][:50]
        if len(comment["message"]) > 50:
            preview += "..."
        if not typer.confirm(f"Remove comment #{comment_id}: \"{preview}\"?"):
            console.print("[yellow]Cancelled[/]")
            raise typer.Exit(0)
    
    data["comments"] = [c for c in data["comments"] if c["id"] != comment_id]
    _save_comments(proj, data)
    
    console.print(f"🗑️  Comment #{comment_id} removed")

@comment_app.command("search")
def comment_search(
    query: str = typer.Argument(..., help="Search query"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name")
):
    """Search for comments by text.
    
    Searches in both message content and tags.
    
    Examples:
      ek comment search "auth"
      ek comment search "bug" --project api
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_comments(proj)
    comments = data.get("comments", [])
    
    # Search in message and tags
    query_lower = query.lower()
    matches = []
    for comment in comments:
        if query_lower in comment.get("message", "").lower():
            matches.append(comment)
        elif any(query_lower in tag.lower() for tag in comment.get("tags", [])):
            matches.append(comment)
    
    if not matches:
        console.print(f"[yellow]No comments found matching '{query}' in project '{proj.name}'[/]")
        return
    
    console.print(f"\nFound [cyan]{len(matches)}[/] comment(s) matching '[bold]{query}[/]':\n")
    
    for comment in matches:
        category_emoji = _get_category_emoji(comment.get("category", "note"))
        message_preview = comment["message"][:60]
        if len(comment["message"]) > 60:
            message_preview += "..."
        
        console.print(f"  [cyan]#{comment['id']}[/] {category_emoji} [dim]{comment.get('created_at', '')[:10]}[/]")
        console.print(f"      {message_preview}")
        if comment.get("tags"):
            console.print(f"      [dim]Tags: {', '.join(comment['tags'])}[/]")
        console.print()

@comment_app.command("clear")
def comment_clear(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project name"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
    older_than: Optional[int] = typer.Option(None, "--older-than", help="Remove comments older than N days"),
    category: Optional[str] = typer.Option(None, "--category", help="Only remove comments of this category"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation")
):
    """Remove old comments.
    
    Examples:
      ek comment clear --older-than 30
      ek comment clear --category done
      ek comment clear --older-than 7 --category log
      ek comment clear --project api --older-than 60
    """
    proj = _project_from_name_or_cwd(project, ws)
    data = _load_comments(proj)
    comments = data.get("comments", [])
    
    if not comments:
        console.print(f"[yellow]No comments found in project '{proj.name}'[/]")
        return
    
    # Filter comments to remove
    to_remove = []
    cutoff_date = None
    
    if older_than:
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=older_than)
    
    for comment in comments:
        should_remove = True
        
        # Check age
        if older_than:
            try:
                comment_date = datetime.fromisoformat(comment.get("created_at", ""))
                if comment_date >= cutoff_date:
                    should_remove = False
            except Exception as e:
                logger.debug(f"Could not parse comment date: {e}")
                should_remove = False
        
        # Check category
        if category and comment.get("category", "note").lower() != category.lower():
            should_remove = False
        
        if should_remove and (older_than or category):
            to_remove.append(comment)
    
    if not to_remove:
        console.print(f"[yellow]No comments match the removal criteria[/]")
        return
    
    if not force:
        console.print(f"\n[bold]Comments to be removed:[/]")
        for comment in to_remove[:10]:  # Show max 10
            msg_preview = comment["message"][:40]
            if len(comment["message"]) > 40:
                msg_preview += "..."
            console.print(f"  • #{comment['id']}: {msg_preview}")
        
        if len(to_remove) > 10:
            console.print(f"  ... and {len(to_remove) - 10} more")
        
        console.print()
        if not typer.confirm(f"Remove {len(to_remove)} comment(s)?"):
            console.print("[yellow]Cancelled[/]")
            raise typer.Exit(0)
    
    # Remove comments
    data["comments"] = [c for c in comments if c not in to_remove]
    _save_comments(proj, data)
    
    console.print(f"✓ Removed {len(to_remove)} comment(s)")

# ---------- Simple project commands ----------
@app.command()
def add(
    path: str = typer.Argument(..., help="Path to project directory"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Custom project name (defaults to directory name)"),
    ws: Optional[str] = typer.Option(None, "--ws", help="Target workspace (defaults to 'default')"),
    eval_mode: bool = typer.Option(False, "--eval", help="Output shell commands for eval (advanced usage)")
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
    
    # Handle eval mode first (for advanced users/scripts)
    if eval_mode:
        var_name = _clean_variable_name(proj_name)
        print(f'export {var_name}="{p}"')
        print(f'echo "✓ Variable ${var_name} loaded for project {proj_name}"')
        return
    
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
    except Exception as e:
        logger.warning(f"Could not apply ignore policy '{policy}': {e}")
    
    # ALWAYS generate shell variables automatically (this is the core feature!)
    _generate_project_variables(ws)
    var_name = _clean_variable_name(proj_name)
    
    # Auto-setup shell integration (seamless, no questions asked)
    shell = os.environ.get('SHELL', '/bin/bash')
    shell_name = Path(shell).name
    
    if shell_name == 'zsh':
        rc_file = Path.home() / '.zshrc'
    elif shell_name == 'bash':
        rc_file = Path.home() / '.bashrc'
    else:
        rc_file = Path.home() / '.profile'
    
    # Check if auto-loading is already configured
    source_line = "source ~/.eagle_projects"
    auto_configured = False
    
    if rc_file.exists():
        content = rc_file.read_text()
        if source_line not in content:
            # Add auto-loading to shell config automatically
            with open(rc_file, 'a') as f:
                f.write(f"\n# Eagle Kit project variables (auto-added)\n")
                f.write(f"if [ -f ~/.eagle_projects ]; then\n")
                f.write(f"    {source_line}\n")
                f.write(f"fi\n")
            auto_configured = True
    else:
        # Create shell config with auto-loading
        with open(rc_file, 'w') as f:
            f.write(f"# Eagle Kit project variables (auto-added)\n")
            f.write(f"if [ -f ~/.eagle_projects ]; then\n")
            f.write(f"    {source_line}\n")
            f.write(f"fi\n")
        auto_configured = True
    
    # Show success and navigation info
    console.print(f"[bold green]✓[/] Project [cyan]{proj_name}[/] registered")
    console.print(f"[dim]  Path: {p}[/]")
    
    if auto_configured:
        console.print(f"[bold green]✓[/] Shell auto-loading configured in {rc_file.name}")
        console.print("")
        console.print(f"[bold yellow]🚀 Ready! Open a new terminal and use:[/]")
        console.print(f"   [cyan]cd ${var_name}[/]")
        console.print("")
        console.print(f"[dim]Or reload now: source {rc_file}[/]")
    else:
        console.print("")
        console.print(f"[bold yellow]🚀 Ready! Navigate with:[/]")
        console.print(f"   [cyan]cd ${var_name}[/]")
    
    console.print(f"[dim]Alternative: [bold]ek cd {proj_name}[/][/]")
    console.print("")
    console.print(f"[bold yellow]� Navigation Ready![/]")
    console.print(f"[green]1.[/] Load variables: [cyan]source ~/.eagle_projects[/]")
    console.print(f"[green]2.[/] Navigate:      [cyan]cd ${var_name}[/]")
    console.print("")
    console.print(f"[dim]Alternative: [bold]ek cd {proj_name}[/][/]")

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
    from rich.panel import Panel
    from rich.table import Table
    from rich.box import MINIMAL_DOUBLE_HEAD
    from rich.text import Text
    
    reg = _reg()
    cur = reg.get("current_workspace", "default")
    
    # Create elegant table with custom styling
    table = Table(
        box=MINIMAL_DOUBLE_HEAD,
        show_header=True,
        header_style="bold bright_cyan",
        border_style="bright_blue",
        padding=(0, 1),
        show_edge=True,
        expand=False
    )
    
    table.add_column("", width=2)
    table.add_column("Project Name", style="bold bright_white", width=20)
    table.add_column("Path", style="dim", overflow="fold")
    table.add_column("TODOs", justify="right", style="bold", width=10)
    
    # Get all projects and count their TODOs
    projects = sorted(_projects(reg, cur).items())
    
    for name, meta in projects:
        # Load TODO count for this project
        try:
            proj = Project(name=name, path=Path(meta["path"]))
            todos_file = proj.meta_dir / "todos.yaml"
            todo_count = "—"
            
            if todos_file.exists():
                todos_data = yaml.safe_load(todos_file.read_text(encoding="utf-8"))
                if todos_data and "todos" in todos_data:
                    # Count pending TODOs only
                    pending = [t for t in todos_data["todos"] if t.get("status") != "done"]
                    if len(pending) > 0:
                        todo_count = f"[yellow]{len(pending)}[/yellow]"
                    else:
                        todo_count = "[green]—[/green]"
        except Exception as e:
            todo_count = "—"
            logger.debug(f"Could not load TODO count for project {name}: {e}")
        
        table.add_row("▸", name, meta["path"], todo_count)
    
    # Create header with Text for better formatting
    header = Text()
    header.append("🦅 ", style="bold")
    header.append("EAGLE KIT", style="bold bright_cyan")
    header.append(" › ", style="dim")
    header.append("Projects Dashboard", style="dim bright_white")
    
    # Create panel with elegant styling
    panel = Panel(
        table,
        title=header,
        subtitle=f"[dim]workspace: {cur}[/dim]",
        border_style="bright_blue",
        padding=(1, 2)
    )
    
    console.print(panel)

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

@app.command("cd")
def cd_project(
    project_name: Optional[str] = typer.Argument(None, help="Name of the project to navigate to"),
    path_only: bool = typer.Option(False, "--path", help="Output only the project path for scripting"),
    workspace: Optional[str] = typer.Option(None, "--ws", help="Workspace name"),
):
    """Navigate to a registered project directory.

    Jump to any registered project by name. Outputs the cd command
    for you to copy or use in shell functions/scripts.

    Examples:
      ek cd api                  # Show cd command for 'api' project
      ek cd                      # List all available projects
      ek cd web --path           # Output only the path for 'web' project

    Since Eagle Kit can't change your shell's directory directly,
    this command shows you the path or cd command to use.

    For quick navigation, create a shell function:
      alias ecd='cd "$(ek cd --path "$1")"'
      ecd api                    # Quick navigate to 'api' project
    """
    if not project_name:
        # Show list of available projects
        reg = _reg()
        ws = _cur_ws(reg, workspace)
        projects = _projects(reg, ws)
        
        if not projects:
            console.print(f"[yellow]No projects registered in workspace '{ws}'[/]")
            console.print("[dim]Use 'ek add .' to register the current directory[/]")
            return
        
        console.print(f"[bold blue]📁 Available projects in workspace '{ws}':[/]")
        table = Table()
        table.add_column("Name", style="bold cyan")
        table.add_column("Path", style="dim")
        
        for name, meta in sorted(projects.items()):
            table.add_row(name, meta["path"])
        
        console.print(table)
        console.print(f"\n[dim]Use: ek cd <project-name> to navigate[/]")
        return
    
    # Resolve project path
    project_path = _resolve_project_path(project_name, workspace)
    
    if not project_path:
        reg = _reg()
        ws = _cur_ws(reg, workspace)
        available = list(_projects(reg, ws).keys())
        
        console.print(f"[red]❌ Project '{project_name}' not found in workspace '{ws}'[/]")
        if available:
            console.print(f"[dim]Available projects: {', '.join(sorted(available))}[/]")
        else:
            console.print("[dim]No projects registered. Use 'ek add .' to register current directory[/]")
        raise typer.Exit(1)
    
    if path_only:
        # Just output the path for scripting
        console.print(str(project_path))
        return
    
    # Show friendly navigation info
    cd_command = f"cd {project_path}"
    console.print(f"[bold green]📁 {project_name}[/] → [cyan]{project_path}[/]")
    console.print(f"[dim]Run:[/] [bold]{cd_command}[/]")
    
    # Try to copy to clipboard if possible
    try:
        import subprocess
        if subprocess.run(["which", "xclip"], capture_output=True).returncode == 0:
            subprocess.run(["xclip", "-selection", "clipboard"], input=cd_command.encode())
            console.print("📋 [dim]Command copied to clipboard[/]")
        elif subprocess.run(["which", "pbcopy"], capture_output=True).returncode == 0:
            subprocess.run(["pbcopy"], input=cd_command.encode())
            console.print("📋 [dim]Command copied to clipboard[/]")
    except Exception as e:
        logger.debug(f"Could not copy to clipboard: {e}")

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
        console.print("")
        console.print("[bold blue]Plugin Management:[/]")
        console.print("  [cyan]ek plugin uninstall <package>[/] - Remove a plugin")
        return
        
    console.print(table)
    
    # Show summary
    loaded_count = len(_loaded_plugins)
    failed_count = len(_failed_plugins)
    total_count = len(available)
    
    console.print(f"\n[green]Loaded:[/] {loaded_count}, [red]Failed:[/] {failed_count}, [blue]Total available:[/] {total_count}")
    console.print("")
    console.print("[bold blue]Plugin Management:[/]")
    console.print("  [cyan]ek plugin uninstall <package>[/] - Remove a plugin")

# ---------- Plugin management commands ----------
plugin_app = typer.Typer(
        help="""Plugin management for Eagle Kit.

Uninstall and manage Eagle Kit plugins. Plugins extend
Eagle Kit with additional commands and features.

Examples:
    ek plugin uninstall eaglekit-hooks   # Remove a plugin
    ek plugin list                       # Show all plugins
""",
    rich_markup_mode="rich"
)
app.add_typer(plugin_app, name="plugin")

@plugin_app.command("list")
def plugin_list():
    """List all installed plugins.
    
    Same as 'ek plugins' - shows detailed plugin status.
    """
    plugins()


@plugin_app.command("uninstall")
def plugin_uninstall(package: str = typer.Argument(..., help="Package name to uninstall")):
    """Uninstall a plugin package.
    
    Removes a Python package that provides Eagle Kit plugins.
    
    Examples:
      ek plugin uninstall eaglekit-hooks
    """
    console.print(f"[bold red]Uninstalling plugin package: {package}[/]")
    
    if not typer.confirm(f"Remove plugin package '{package}'?"):
        console.print("[yellow]Uninstall cancelled.[/]")
        raise typer.Exit(0)
    
    try:
        import subprocess
        result = subprocess.run([
            sys.executable, "-m", "pip", "uninstall", package, "-y"
        ], capture_output=True, text=True, check=False)
        
        if result.returncode == 0:
            console.print(f"[green]✓ Successfully uninstalled {package}[/]")
            # If uninstalling eaglekit-hooks, remove hooks from all projects
            if package == "eaglekit-hooks":
                reg = _reg()
                for ws in reg.get("workspaces", {}):
                    for name, meta in reg["workspaces"][ws]["projects"].items():
                        proj_path = Path(meta["path"]).expanduser().resolve()
                        git_hooks = proj_path / ".git" / "hooks"
                        if git_hooks.exists():
                            for hook_file in git_hooks.glob("eaglekit-*"):
                                try:
                                    hook_file.unlink()
                                    console.print(f"[dim]Removed hook: {hook_file}")
                                except Exception as e:
                                    console.print(f"[yellow]Warning: Could not remove hook {hook_file}: {e}[/]")
            console.print("")
            console.print("[bold yellow]Note:[/] Restart Eagle Kit to see changes")
        else:
            console.print(f"[red]✗ Failed to uninstall {package}[/]")
            console.print(f"[red]Error:[/] {result.stderr}")
            
    except Exception as e:
        console.print(f"[red]✗ Uninstall failed: {e}[/]")

# ---------- Uninstall command ----------
@app.command("uninstall")
def uninstall():
    """Completely remove Eagle Kit and all its data.
    
    This command will remove:
    • All project registries and workspaces
    • Shell variables file (~/.eagle_projects)
    • Auto-loading configuration from shell config files
    • Configuration directories and files
    • The Eagle Kit application itself (via pipx)
    
    WARNING: This action cannot be undone!
    
    Examples:
      ek uninstall                # Remove everything completely
    
    This is a complete removal - no need to run pipx uninstall separately.
    """
    console.print("[bold red]⚠️  Eagle Kit Complete Uninstall[/]")
    console.print("")
    console.print("This will permanently remove:")
    console.print("• [red]All project registries and workspaces[/]")
    console.print("• [red]Shell variables file (~/.eagle_projects)[/]")
    console.print("• [red]Shell configuration (auto-loading from .zshrc/.bashrc)[/]")
    console.print("• [red]All Eagle Kit configuration files[/]")
    console.print("• [red]The Eagle Kit application itself[/]")
    console.print("")
    console.print("[bold yellow]This action cannot be undone![/]")
    
    if not typer.confirm("Are you sure you want to completely remove Eagle Kit?"):
        console.print("[yellow]Uninstall cancelled.[/]")
        raise typer.Exit(0)
    
    console.print("")
    console.print("[bold blue]Removing Eagle Kit data...[/]")
    
    # Remove project variables file
    vars_file = Path.home() / '.eagle_projects'
    if vars_file.exists():
        vars_file.unlink()
        console.print("✓ Removed shell variables file")
    
    # Remove configuration directory
    paths = get_paths()
    config_dir = paths.config_dir
    if config_dir.exists():
        import shutil
        shutil.rmtree(config_dir)
        console.print("✓ Removed configuration directory")
    
    # Remove from shell configuration files
    shell_files = [
        Path.home() / '.zshrc',
        Path.home() / '.bashrc', 
        Path.home() / '.profile'
    ]
    
    for shell_file in shell_files:
        if shell_file.exists():
            try:
                content = shell_file.read_text()
                lines = content.split('\n')
                new_lines = []
                skip_block = False
                
                for line in lines:
                    # Skip Eagle Kit blocks
                    if 'Eagle Kit' in line and 'auto-added' in line:
                        skip_block = True
                        continue
                    elif skip_block and line.strip() == 'fi':
                        skip_block = False
                        continue
                    elif skip_block:
                        continue
                    # Skip other Eagle Kit references
                    elif any(keyword in line for keyword in ['eagle_projects', 'ek()', 'ek-core']):
                        continue
                    else:
                        new_lines.append(line)
                
                # Only write if content changed
                new_content = '\n'.join(new_lines)
                if new_content != content:
                    shell_file.write_text(new_content)
                    console.print(f"✓ Cleaned {shell_file.name}")
                    
            except Exception as e:
                console.print(f"[yellow]Warning: Could not clean {shell_file.name}: {e}[/]")
    
    console.print("")
    console.print("[bold blue]Removing Eagle Kit application...[/]")
    
    # Try to uninstall via pipx
    try:
        result = subprocess.run(['pipx', 'uninstall', 'eaglekit'], 
                              capture_output=True, text=True, check=False)
        if result.returncode == 0:
            console.print("✓ Removed Eagle Kit application via pipx")
        else:
            console.print(f"[yellow]Warning: Could not remove via pipx: {result.stderr}[/]")
            console.print("[dim]You may need to run: pipx uninstall eaglekit[/]")
    except FileNotFoundError:
        console.print("[yellow]Warning: pipx not found - could not auto-uninstall[/]")
        console.print("[dim]You may need to run: pipx uninstall eaglekit[/]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not auto-uninstall: {e}[/]")
        console.print("[dim]You may need to run: pipx uninstall eaglekit[/]")
    
    # Clean PATH remnants and development environments
    console.print("")
    console.print("[bold blue]Cleaning development environments...[/]")
    
    # Look for and clean common development paths
    dev_paths = [
        '/home/antonio/downloads/eaglekit_v2_1/test_env',
        Path.home() / 'downloads' / 'eaglekit_v2_1' / 'test_env',
    ]
    
    for dev_path in dev_paths:
        dev_path = Path(dev_path)
        if dev_path.exists():
            try:
                import shutil
                shutil.rmtree(dev_path)
                console.print(f"✓ Removed development environment: {dev_path}")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not remove {dev_path}: {e}[/]")
    
    # Check for ek commands in PATH and suggest cleanup
    try:
        which_result = subprocess.run(['which', 'ek'], capture_output=True, text=True, check=False)
        if which_result.returncode == 0 and which_result.stdout.strip():
            ek_path = which_result.stdout.strip()
            console.print(f"[yellow]Note: ek command still found at: {ek_path}[/]")
            
            # If it's in a test_env, try to remove the parent directory
            if 'test_env' in ek_path:
                test_env_dir = Path(ek_path).parent.parent
                if test_env_dir.exists() and 'test_env' in str(test_env_dir):
                    try:
                        import shutil
                        shutil.rmtree(test_env_dir)
                        console.print(f"✓ Removed test environment: {test_env_dir}")
                    except Exception as e:
                        console.print(f"[yellow]Warning: Could not remove {test_env_dir}: {e}[/]")
                        console.print(f"[dim]You may need to manually remove: {test_env_dir}[/]")
    except Exception as e:
        logger.debug(f"Could not check for ek command in PATH: {e}")  # which command might not be available
    
    console.print("")
    console.print("[bold green]✅ Eagle Kit completely removed![/]")
    console.print("")
    console.print("[bold blue]To reload your shell:[/]")
    console.print("  [cyan]source ~/.zshrc[/] (or restart terminal)")
    console.print("")
    console.print("[dim]Thank you for using Eagle Kit! 🦅[/]")
