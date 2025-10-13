# EagleKit 🦅

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-0.2.1-green.svg)](https://github.com/youruser/eaglekit)

**The modular developer toolkit and plugin framework for Git power users.**

EagleKit is a command-line framework that provides a unified `ek` CLI interface for managing developer workflows, project organization, and Git-based automation. Built with extensibility at its core, EagleKit lets you compose your own developer toolkit through a rich plugin ecosystem.

---

## 🎯 Overview

EagleKit solves the common problem of managing multiple development projects, tools, and workflows by providing:

- **Unified Command Interface**: A single `ek` command to rule them all
- **Plugin Architecture**: Extend functionality through composable plugins
- **Project Registry**: Smart project discovery and navigation
- **Git Integration**: Safe, powerful Git workflow automation
- **Task Management**: Define and execute project-specific tasks
- **Developer Experience**: Rich terminal output, interactive prompts, and shell integration

Whether you're juggling microservices, managing complex Git workflows, or just want a better way to navigate your projects, EagleKit provides the foundation.

---

## ✨ Key Features

### 🔌 **Plugin System**
- **Auto-discovery** via Python entry points
- **Dynamic loading** - plugins extend the `ek` command namespace
- **Isolated architecture** - plugins don't interfere with each other
- **First-class integration** - plugins feel native to the CLI

### 📦 **Project Management**
- **Registry-based tracking** of all your projects
- **Workspace organization** for different contexts (work, personal, client projects)
- **Smart navigation** with shell variable generation (`cd $myproject`)
- **Automatic `.eagle/` directory handling** for project metadata

### ⚙️ **Task Automation**
- **YAML-based task definitions** in `.eagle/config.yaml`
- **Branch-specific tasks** that override project defaults
- **Multiple formats**: shell commands, script execution, command arrays
- **Task inheritance** and environment variable support

### 🔧 **Git Workflow Tools**
- **Safe Git operations** through a tested service layer
- **Multiple ignore strategies** (local, repo, global) for `.eagle/` directories
- **Hook support** for extending Git behavior
- **Commit tracking** and branch mirroring via plugins

### 🎨 **Developer Experience**
- **Rich terminal output** with colors and formatting
- **Interactive setup wizard** for first-run configuration
- **Shell integration** for direct project navigation
- **TODO and comment management** built-in

---

## 📥 Installation

### Recommended: pipx (Isolated Environment)

```bash
pipx install eaglekit
```

### Alternative: pip

```bash
pip install eaglekit
```

### From Source

```bash
git clone https://github.com/youruser/eaglekit.git
cd eaglekit
pip install -e .
```

> **Note**: Installing any EagleKit plugin (like `eaglekit-plugin-mirror`) will automatically install the core framework if not already present.

---

## 🚀 Quick Start

### First Run - Interactive Setup

```bash
ek
```

EagleKit will launch an interactive setup wizard on first run to configure:
- User preferences
- Git ignore policy for `.eagle/` metadata directories
- Shell integration for direct navigation
- Default workspace settings

### Register Your First Project

```bash
cd ~/projects/myapp
ek add .
```

Or with a custom name:

```bash
ek add ~/projects/api --name backend-api
```

### Navigate to Projects

After registering projects, you can navigate quickly:

```bash
# Using shell variables (auto-configured)
cd $myapp

```

### List All Projects

```bash
ek list
```

### Check Project Status

```bash
cd ~/projects/myapp
ek status
```

### Run Project Tasks

```bash
# List available tasks
ek run list

# Execute a task
ek run task build
```

---

## 🧩 Plugin System

EagleKit's true power comes from its plugin architecture. Plugins extend the `ek` command with new functionality, creating a personalized developer toolkit.

### How Plugins Work

1. **Entry Point Registration**: Plugins register via `[project.entry-points."eaglekit.plugins"]` in `pyproject.toml`
2. **Auto-Discovery**: EagleKit discovers plugins using Python's `importlib.metadata`
3. **Dynamic Loading**: Plugins are loaded at runtime and add commands to the CLI
4. **Namespace Isolation**: Each plugin gets its own command group (`ek <plugin-name> <subcommand>`)

### Available Plugins

#### 🪞 **Mirror Plugin** (`eaglekit-plugin-mirror`)
Dual-environment branch workflow automation for QA/Prod scenarios.

```bash
pip install eaglekit-plugin-mirror

# Usage
ek mirror create qa-mirror
ek mirror link feature-branch
ek mirror push
```

#### 📊 **Commit Tracker** (`eaglekit-plugin-commit-tracker`)
Sequential commit indexing with UUID-based cross-branch synchronization.

```bash
pip install eaglekit-plugin-commit-tracker

# Usage
ek tracker init
```

### Installing Plugins

```bash
# Install via pip/pipx
pipx inject eaglekit eaglekit-plugin-mirror
# or
pip install eaglekit-plugin-mirror

# Verify installation
ek plugins
```

---

## 🛠️ Creating Your Own Plugin

EagleKit makes it easy to build plugins that integrate seamlessly with the CLI.

### Minimal Plugin Structure

```
my-plugin/
├── pyproject.toml
└── src/
    └── eaglekit_plugin_myplugin/
        ├── __init__.py
        └── commands.py
```

### Plugin Code Example

```python
# src/eaglekit_plugin_myplugin/__init__.py
import typer
from rich.console import Console

console = Console()

def register(app):
    """Entry point called by EagleKit to register the plugin."""
    
    # Create command group
    my_plugin = typer.Typer(
        help="My custom development tools",
        rich_markup_mode="rich"
    )
    
    @my_plugin.command("hello")
    def hello(name: str):
        """Say hello to someone."""
        console.print(f"[bold green]Hello, {name}![/]")
    
    @my_plugin.command("status")
    def status():
        """Show plugin status."""
        console.print("[blue]Plugin is working![/]")
    
    # Register with EagleKit
    app.add_typer(my_plugin, name="myplugin")
```

### Plugin Configuration (`pyproject.toml`)

```toml
[project]
name = "eaglekit-plugin-myplugin"
version = "0.1.0"
description = "My awesome EagleKit plugin"
dependencies = [
    "eaglekit>=0.1.0",
    "typer>=0.12.3",
    "rich>=0.13.7",
]

[project.entry-points."eaglekit.plugins"]
myplugin = "eaglekit_plugin_myplugin:register"
```

### Usage

```bash
# Install your plugin
pip install -e .

# Use it
ek myplugin hello Antonio
ek myplugin status
```

### Plugin Best Practices

1. **Naming Convention**: Use `eaglekit-plugin-<name>` for package names
2. **Command Groups**: Each plugin should create its own Typer app for isolation
3. **Rich Output**: Use Rich console for colorful, formatted output
4. **Error Handling**: Provide clear error messages with context
5. **Documentation**: Include help text for all commands and options
6. **Dependencies**: Keep dependencies minimal; rely on EagleKit's included libraries
7. **Testing**: Include tests using pytest

---

## ⚙️ Configuration & Environment

### Directory Structure

EagleKit stores all configuration in platform-appropriate locations using `platformdirs`:

```
~/.config/eaglekit/          # Linux/macOS
├── registry.yaml            # Project registry and workspaces
├── defaults.yaml            # User preferences and defaults
└── workspaces/              # Workspace-specific configs
```

### Project Metadata (`.eagle/` Directory)

Each registered project gets a `.eagle/` directory for metadata:

```
myproject/
└── .eagle/
    ├── config.yaml          # Project configuration and tasks
    ├── todos.yaml           # TODO tracking
    ├── comments.yaml        # Development notes
    ├── scripts/             # Task scripts
    └── branches/            # Branch-specific configs
        └── main/
            └── config.yaml  # Branch-specific tasks
```

### Configuration Files

#### `registry.yaml` - Project Registry

```yaml
current_workspace: default
workspaces:
  default:
    projects:
      myapp:
        path: /home/user/projects/myapp
      backend:
        path: /home/user/work/backend
```

#### `.eagle/config.yaml` - Project Configuration

```yaml
tasks:
  build:
    type: script
    path: scripts/build.sh
    shell: bash
  test: "pytest tests/"
  deploy:
    - python
    - deploy.py
    - --env
    - production
```

### Ignore Strategies

EagleKit helps you manage `.eagle/` directories in Git:

- **local** (Recommended): Adds `.eagle/` to `.git/info/exclude` (not versioned)
- **repo**: Adds `.eagle/` to `.gitignore` (versioned with repo)
- **global**: Adds `.eagle/` to `~/.config/git/ignore` (all repos)
- **none**: Manual management

```bash
# Check current status
ek ignore status

# Apply strategy
ek ignore local   # Recommended for most users
```

---

## 🔧 Core Commands Reference

### Project Management

```bash
ek add <path>              # Register a project
ek list                    # List all projects
ek status                  # Show current project info
ek cd <project>            # Navigate to project (with shell integration)
```

### Task Execution

```bash
ek run list                # List available tasks
ek run task <name>         # Execute a task
ek run new <name>          # Create a new task
ek <taskname>              # Shorthand execution
```

### TODO Management

```bash
ek todo add "Task"         # Add TODO
ek todo list               # List TODOs
ek todo done <id>          # Mark as complete
ek todo show <id>          # Show details
```

### Comments & Notes

```bash
ek comment add "Note"      # Add comment
ek comment list            # List comments
ek comment search "term"   # Search comments
```

### Configuration

```bash
ek setup                   # Run configuration wizard
ek ignore <strategy>       # Configure .eagle/ ignore
ek shell install           # Enable shell integration
ek plugins                 # List installed plugins
```

---

## 🏗️ Architecture Overview

EagleKit follows a clean, layered architecture inspired by Domain-Driven Design:

```
┌─────────────────────────────────────────────────┐
│         Presentation Layer (CLI)                │
│  • Typer commands                               │
│  • Rich console output                          │
│  • User interaction & prompts                   │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│         Application Layer (Core)                │
│  • Plugin registry & loader                     │
│  • Command dispatcher                           │
│  • Task orchestration                           │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│         Domain Layer (Business Logic)           │
│  • Project entity                               │
│  • Configuration management                     │
│  • Task definitions                             │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│         Infrastructure Layer                    │
│  • YAML persistence                             │
│  • Git integration                              │
│  • File system operations                       │
│  • Shell integration                            │
└─────────────────────────────────────────────────┘
```

### Key Components

- **`cli.py`**: Main CLI application, command definitions, plugin loading
- **`core.py`**: Core business entities (Project, etc.)
- **`config.py`**: Configuration management and persistence
- **`router.py`**: Smart command routing and task shorthand
- **`wrapper.py`**: Shell integration and function generation

For detailed architecture documentation, see [ARCHITECTURE.md](./ARCHITECTURE.md) (coming soon).

---

## 🧪 Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/youruser/eaglekit.git
cd eaglekit

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Or using pipx
pipx install -e .
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/eaglekit --cov-report=html

# Run specific test file
pytest tests/test_cli.py
```

### Code Quality

```bash
# Format code
black src/

# Lint code
ruff check src/

# Type checking
mypy src/
```

### Plugin Development Workflow

1. Create plugin package structure
2. Implement `register(app)` function
3. Add entry point to `pyproject.toml`
4. Install in development mode: `pip install -e .`
5. Test with `ek plugins` and your plugin commands
6. Package and distribute

---

## 🤝 Contributing

Contributions are welcome! Whether it's:

- 🐛 Bug reports
- 💡 Feature requests
- 📝 Documentation improvements
- 🔌 New plugins
- 🧪 Test coverage

Please feel free to open issues or submit pull requests.

### Contribution Guidelines

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with clear commit messages
4. Add tests for new functionality
5. Ensure all tests pass (`pytest`)
6. Submit a pull request

---

## 📊 Ecosystem

### Official Plugins

| Plugin | Description | Status |
|--------|-------------|--------|
| [eaglekit-plugin-mirror](https://github.com/youruser/eaglekit-plugin-mirror) | Dual-environment branch workflows | ✅ Stable |
| [eaglekit-plugin-commit-tracker](https://github.com/youruser/eaglekit-plugin-commit-tracker) | Sequential commit indexing | ✅ Stable |

### Community Plugins

*(Coming soon - submit yours!)*

---

## 🔐 Security & Privacy

- **Local-first**: All data stored locally on your machine
- **No telemetry**: EagleKit doesn't collect or transmit any usage data
- **Git safe**: Built-in safeguards against destructive Git operations
- **Secrets management**: `.eagle/secrets/` directory with automatic `.gitignore` (coming soon)

---

## 📜 License

EagleKit is released under the [MIT License](LICENSE).

```
MIT License — 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files...
```

---

## 🙏 Acknowledgments

Built with:
- [Typer](https://typer.tiangolo.com/) - CLI framework with a rich feature set
- [Rich](https://rich.readthedocs.io/) - Beautiful terminal formatting
- [PyYAML](https://pyyaml.org/) - YAML parsing and generation
- [platformdirs](https://platformdirs.readthedocs.io/) - Platform-appropriate directory handling

---

## 📞 Support & Community

- **Issues**: [GitHub Issues](https://github.com/youruser/eaglekit/issues)
- **Discussions**: [GitHub Discussions](https://github.com/youruser/eaglekit/discussions)
- **Documentation**: [Wiki](https://github.com/youruser/eaglekit/wiki) (coming soon)

---

## 🗺️ Roadmap

- [ ] Enhanced plugin discovery and marketplace
- [ ] Secrets management integration
- [ ] Docker and container workflow support
- [ ] CI/CD integration templates
- [ ] Cloud sync for project registry (optional)
- [ ] Web dashboard for project overview
- [ ] VS Code extension

---

**Built with ❤️ for developers who love the command line.**

*EagleKit - Soar above your development workflow.* 🦅
