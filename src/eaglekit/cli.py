
from __future__ import annotations
import typer
from rich.console import Console

app = typer.Typer(help="Eagle Kit — dev project manager CLI.", add_completion=False)
console = Console()

@app.command()
def hello():
    """Hello world command"""
    console.print("[green]Hello from Eagle Kit![/]")

if __name__ == "__main__":
    app()
