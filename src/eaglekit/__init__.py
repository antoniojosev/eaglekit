"""Eagle Kit - Development project manager CLI"""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("eaglekit")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["__version__"]
