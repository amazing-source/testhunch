"""testhunch: learn from past CI runs which tests a change is likely to break."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("testhunch")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"
