"""Pick a backend (Runner) without changing app code.

Order: `backend` argument > `--cui`/`--gui` in argv > env `FLOW_UI_BACKEND` > auto detection.
Auto: GUI if a display is available and PySide6 can be imported, otherwise CUI
(with a one-line note on stderr when a display exists but the PySide6 import failed).
The GUI module (PySide6) is only imported when the GUI is chosen.
"""

import os
import sys
from typing import Any, Callable, Optional

import base

BACKENDS = ("cui", "gui")
ENV_VAR = "FLOW_UI_BACKEND"


def has_display() -> bool:
    """On Linux and other X11/Wayland systems a display needs DISPLAY or WAYLAND_DISPLAY; macOS/Windows always have one."""
    if sys.platform in ("darwin", "win32", "cygwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def gui_available() -> bool:
    """A display exists and PySide6 imports. If only the import fails, say why on stderr (one line)."""
    if not has_display():
        return False
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError as e:
        print(f"flow-ui: a display was found but PySide6 could not be imported ({e}); using CUI", file=sys.stderr)
        return False
    return True


def backend_from_argv(argv: Optional[list[str]] = None) -> Optional[str]:
    """`--cui` / `--gui` (or bare `cui` / `gui`) in argv. Returns None if neither is given."""
    args = sys.argv[1:] if argv is None else argv
    for arg in args:
        name = arg[2:] if arg.startswith("--") else arg
        if name in BACKENDS:
            return name
    return None


def choose_backend(backend: Optional[str] = None, argv: Optional[list[str]] = None) -> str:
    choice = backend or backend_from_argv(argv) or os.environ.get(ENV_VAR, "").strip().lower() or None
    if choice is None:
        return "gui" if gui_available() else "cui"
    if choice not in BACKENDS:
        raise ValueError(f"unknown backend {choice!r}; use one of {', '.join(BACKENDS)} (via argument, --cui/--gui or {ENV_VAR})")
    return choice


def make_runner(
    data: Any = None, backend: Optional[str] = None, argv: Optional[list[str]] = None
) -> base.ApplicationRunnerBase:
    if choose_backend(backend, argv) == "gui":
        import gui

        return gui.GuiRunner(data)
    import cui

    return cui.CuiRunner(data)


def run(
    build_app: Callable[[base.ApplicationRunnerBase], base.ApplicationRunnerBase],
    data: Any = None,
    backend: Optional[str] = None,
    argv: Optional[list[str]] = None,
) -> base.ApplicationRunnerBase:
    """Create a runner for the chosen backend, let `build_app` add flows to it, and run it."""
    runner = build_app(make_runner(data, backend, argv))
    runner.run()
    return runner
