"""Modules imported on first use instead of at startup."""
import importlib


class LazyModule:
    """Stands in for a module and imports it the first time one of its names is used.
    httpx takes ~0.3 s to import (longer right after a reboot) and isn't needed to show the window.
    Names set on the stand-in (tests patch e.g. httpx.Client) take precedence over the module's."""

    def __init__(self, name: str):
        self._name = name
        self._module = None

    def __getattr__(self, attr: str):
        if self._module is None:
            self._module = importlib.import_module(self._name)
        return getattr(self._module, attr)


httpx = LazyModule("httpx")
