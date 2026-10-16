"""Everything that differs between Windows and Linux, behind one set of names: windows.py and
linux.py define the same functions and constants, and `current` is the one for this system.

    from .platform import current as osys
    osys.enable_proxy(port)

Callers go through the module object (osys.name), so tests can patch a function in one place."""
import sys

if sys.platform == "win32":
    from . import windows as current
else:
    from . import linux as current

__all__ = ["current"]
