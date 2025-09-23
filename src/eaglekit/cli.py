
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
    except Exception:
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

def _generate_ekadd_function() -> str:
    """Generate ekadd helper function code."""
    return '''
# Eagle Kit helper function - auto-add with variable loading
ekadd() {
    ek add "$@"
    if [ $? -eq 0 ]; then
        source ~/.eagle_projects
        echo "✓ Variables recargadas automáticamente"
        
        # Extract project name for hint
        local proj_name=""
        local args=("$@")
        
        # Look for --name parameter
        for ((i=0; i<${#args[@]}; i++)); do
            if [[ "${args[i]}" == "--name" ]] || [[ "${args[i]}" == "-n" ]]; then
                proj_name="${args[i+1]}"
                break
            fi
        done
        
        # If no --name, use directory name
        if [ -z "$proj_name" ]; then
            proj_name=$(basename "$(realpath "${args[0]:-$(pwd)}")")
        fi
        
        # Clean name for shell variable
        local clean_name=$(echo "$proj_name" | sed 's/[^a-zA-Z0-9_]/_/g' | sed 's/^[0-9]/_&/')
        echo "💡 Usa: cd \\$${clean_name}"
    fi
}'''.strip()

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
        
        # Offer ekadd helper function
        console.print("\n[bold blue]🔧 Función Helper ekadd[/]")
        console.print("─" * 30)
        
        console.print(Panel(
            "[bold yellow]¿Instalar función helper ekadd?[/]\n\n"
            "[green]ekadd[/] → Agregar proyectos [blue]y cargar variables automáticamente[/]\n"
            "[blue]•[/] Combina 'ek add' + 'source ~/.eagle_projects'\n"
            "[blue]•[/] Te muestra el comando cd inmediatamente\n"
            "[blue]•[/] Sin configuración manual adicional\n\n"
            "[dim]Ejemplo: ekadd . --name api → auto-carga $api inmediatamente[/]",
            title="🚀 Helper Function",
            border_style="blue"
        ))
        
        install_ekadd = Prompt.ask(
            "[green]¿Instalar función ekadd?[/]",
            choices=["y", "n"],
            default="y",
            show_choices=True,
            show_default=True
        )
        
        if install_ekadd == "y":
            try:
                # Use the existing install_ekadd function
                _generate_project_variables()
                ekadd_function = _generate_ekadd_function()
                
                # Add function to config
                if rc_file.exists():
                    content = rc_file.read_text()
                    if 'ekadd()' not in content:
                        content += '\n# Eagle Kit ekadd helper function\n'
                        content += ekadd_function + '\n'
                        rc_file.write_text(content)
                        console.print("[dim]✓ Función ekadd instalada[/]")
                    else:
                        console.print("[dim]✓ Función ekadd ya existe[/]")
                else:
                    with open(rc_file, 'w') as f:
                        f.write(f"# Eagle Kit ekadd helper function\n{ekadd_function}\n")
                    console.print(f"[dim]✓ Función ekadd instalada en {rc_file.name}[/]")
                
                d.setdefault("preferences", {})["ekadd_helper"] = True
            except Exception as e:
                console.print(f"[red]Error instalando ekadd: {e}[/]")
                d.setdefault("preferences", {})["ekadd_helper"] = False
        else:
            d.setdefault("preferences", {})["ekadd_helper"] = False
            console.print("[dim]✓ Función ekadd no instalada[/]")
            
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
        except:
            shell_installed = False
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

@shell_app.command("install-ekadd", help="Install ekadd helper function for automatic variable loading")
def install_ekadd():
    """Install ekadd helper function in shell."""
    # Generate shell files
    _generate_project_variables()
    ekadd_function = _generate_ekadd_function()
    
    # Determine shell config file
    shell = os.environ.get('SHELL', '/bin/bash')
    shell_name = Path(shell).name
    
    if shell_name == 'zsh':
        config_file = Path.home() / '.zshrc'
    elif shell_name == 'bash':
        config_file = Path.home() / '.bashrc'
    else:
        config_file = Path.home() / '.profile'
    
    console.print(f"[bold blue]Installing ekadd function...[/]")
    
    # Check if already installed
    if config_file.exists():
        content = config_file.read_text()
        if 'ekadd()' in content:
            console.print("⚠️  ekadd function already exists in shell config")
            if not typer.confirm("Replace existing ekadd function?"):
                raise typer.Abort()
            
            # Remove existing function
            lines = content.split('\n')
            new_lines = []
            in_ekadd = False
            for line in lines:
                if line.strip().startswith('ekadd()'):
                    in_ekadd = True
                    continue
                elif in_ekadd and line.strip() == '}':
                    in_ekadd = False
                    continue
                elif not in_ekadd:
                    new_lines.append(line)
            
            content = '\n'.join(new_lines)
    else:
        content = ""
    
    # Add function to config
    if content and not content.endswith('\n'):
        content += '\n'
    
    content += '\n# Eagle Kit ekadd helper function\n'
    content += ekadd_function + '\n'
    
    # Add auto-loading
    content += '\n# Auto-load Eagle Kit project variables\n'
    content += 'if [ -f ~/.eagle_projects ]; then\n'
    content += '    source ~/.eagle_projects\n'
    content += 'fi\n'
    
    config_file.write_text(content)
    
    console.print(f"✅ Function ekadd installed in {config_file}")
    console.print("✅ Auto-loading of variables configured")
    console.print("")
    console.print("[bold yellow]Usage:[/]")
    console.print("  [cyan]ekadd /path/to/project[/] - Add project and auto-load variables")
    console.print("  [cyan]ekadd . --name myproject[/] - Add current dir with name")
    console.print("")
    console.print("[dim]Restart your shell or run:[/]")
    console.print(f"  [cyan]source {config_file}[/]")

@shell_app.command("vars")
def shell_vars():
    """Show current project variables."""
    vars_file = Path.home() / '.eagle_projects'
    
    if not vars_file.exists():
        console.print("[yellow]No project variables file found[/]")
        console.print("[dim]Variables are generated when you add projects[/]")
        return
    
    content = vars_file.read_text()
    
    # Parse variables
    variables = []
    for line in content.split('\n'):
        if line.startswith('export '):
            var_line = line[7:]  # Remove 'export '
            if '=' in var_line:
                name, path = var_line.split('=', 1)
                path = path.strip('"')
                variables.append((name, path))
    
    if not variables:
        console.print("[yellow]No variables found in file[/]")
        return
    
    console.print(f"[bold blue]📂 Project Variables ({len(variables)})[/]")
    table = Table()
    table.add_column("Variable", style="bold green")
    table.add_column("Path", style="dim")
    table.add_column("Usage", style="cyan")
    
    for var_name, path in variables:
        table.add_row(var_name, path, f"cd ${var_name}")
    
    console.print(table)
    console.print(f"\n[dim]File: {vars_file}[/]")
    console.print("[dim]Usage: cd $variable_name[/]")

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
    except Exception:
        pass
    
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
    except:
        pass

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
    except Exception:
        pass  # which command might not be available
    
    console.print("")
    console.print("[bold green]✅ Eagle Kit completely removed![/]")
    console.print("")
    console.print("[bold blue]To reload your shell:[/]")
    console.print("  [cyan]source ~/.zshrc[/] (or restart terminal)")
    console.print("")
    console.print("[dim]Thank you for using Eagle Kit! 🦅[/]")
