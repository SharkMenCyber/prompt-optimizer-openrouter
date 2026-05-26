"""Prompt Optimizer (OpenRouter) desktop launcher.

Starts the FastAPI backend as a separate process, waits for it to answer the
health endpoint, then opens it in a native window (EdgeChromium / WebView2 on
Windows). On first launch the in-app setup screen asks for the OpenRouter API
key.

Two run modes:
  * default        -> GUI: start the backend, then open the window.
  * --run-server   -> run uvicorn in THIS process (used by the GUI to launch a
                      clean backend process; also how the frozen exe re-spawns
                      itself, since a bundled app has no python.exe to call).

Dev:    .venv\\Scripts\\pythonw.exe desktop.py   (no console window)
   or:  .venv\\Scripts\\python.exe  desktop.py   (with console, for debugging)
Frozen: launched as "Prompt Optimizer OpenRouter.exe" by the installer.
"""
from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8060  # distinct from the Venice edition (8050) so both can run at once
URL = f"http://{HOST}:{PORT}"
TITLE = "Prompt Optimizer (OpenRouter)"
APP_USER_MODEL_ID = "Hermes.PromptOptimizer.OpenRouter"

FROZEN = bool(getattr(sys, "frozen", False))


def _resource_dir() -> Path:
    """Bundled read-only resources (assets/, static/, app code)."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    """Writable user data (.env, db, logs). Outside the program folder when frozen."""
    if FROZEN:
        base = os.getenv("LOCALAPPDATA") or str(Path.home())
        path = Path(base) / "PromptOptimizerOpenRouter"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(__file__).resolve().parent


RESOURCE_DIR = _resource_dir()
DATA_DIR = _data_dir()
ICON = RESOURCE_DIR / "assets" / "skull.ico"
LOGS_DIR = DATA_DIR / "logs"


def _ensure_console_streams() -> None:
    """Under a windowed/pythonw process there is no console, so sys.stdout/stderr
    are None and uvicorn's logging crashes on first write. Point the missing
    streams at a log file."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOGS_DIR / "desktop.log", "a", buffering=1, encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def _run_server_mode() -> None:
    """Run uvicorn in this process. Invoked via the --run-server flag."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:
        log = open(LOGS_DIR / "server.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    import uvicorn

    from app.main import app

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def _server_healthy(timeout: float = 5.0) -> bool:
    # Check the real HTTP health endpoint, not just whether the port is open.
    # A previous instance can leave the port bound while its server is hung;
    # only a 200 here means the backend is actually serving requests. The empty
    # ProxyHandler bypasses Windows' localhost proxy auto-detection.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{URL}/api/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _server_python() -> str:
    for candidate in (RESOURCE_DIR / ".venv" / "Scripts" / "python.exe", RESOURCE_DIR / ".venv" / "Scripts" / "pythonw.exe"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _spawn_server() -> subprocess.Popen:
    # Run the backend as its own process rather than a background thread. A
    # threaded uvicorn shares the GUI process and hangs on Windows (the port
    # accepts connections but never answers HTTP); a separate process does not.
    # CREATE_NO_WINDOW suppresses the console; stdout/stderr are redirected to a
    # real file so uvicorn's logging has valid stream handles.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOGS_DIR / "server.log", "a", buffering=1, encoding="utf-8")
    if FROZEN:
        # No python.exe in a bundled app: re-spawn this exe in server mode.
        cmd = [sys.executable, "--run-server"]
    else:
        cmd = [
            _server_python(), "-m", "uvicorn", "app.main:app",
            "--host", HOST, "--port", str(PORT), "--log-level", "warning",
        ]
    return subprocess.Popen(
        cmd,
        cwd=str(RESOURCE_DIR),
        stdout=log,
        stderr=log,
        creationflags=creationflags,
    )


def _wait_for_healthy(timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_healthy(timeout=3.0):
            return True
        time.sleep(0.5)
    return False


def _apply_windows_taskbar_icon(window, timeout: float = 20.0) -> None:
    """Force the native Win32 window icon after pywebview creates the HWND.

    Some Windows/pywebview combinations still show the default icon on the
    taskbar even when the shortcut and pywebview icon are correct. WM_SETICON
    updates the actual window icon that the taskbar asks for.
    """
    if sys.platform != "win32":
        return

    deadline = time.time() + timeout
    hwnd = 0
    native = None

    while time.time() < deadline:
        native = getattr(window, "native", None)
        handle = getattr(native, "Handle", None)
        if handle is not None:
            try:
                hwnd = int(handle.ToInt64())
            except Exception:
                try:
                    hwnd = int(handle.ToInt32())
                except Exception:
                    hwnd = 0
        if hwnd:
            break
        time.sleep(0.1)

    if not hwnd:
        return

    # pywebview/WebView2 in a frozen build can leave the window created but
    # hidden (the page renders, but the form is never shown). Now that we have
    # the HWND, force it visible and to the foreground.
    try:
        import ctypes

        ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

    if not ICON.exists():
        return

    try:
        from System.Drawing import Icon as DotNetIcon

        native.Icon = DotNetIcon(str(ICON))
    except Exception:
        pass

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        image_icon = 1
        load_from_file = 0x00000010
        wm_seticon = 0x0080
        icon_small = 0
        icon_big = 1
        icon_small2 = 2
        gclp_hicon = -14
        gclp_hiconsm = -34

        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = wintypes.LPARAM

        hicon_big = user32.LoadImageW(None, str(ICON), image_icon, 256, 256, load_from_file)
        hicon_small = user32.LoadImageW(None, str(ICON), image_icon, 16, 16, load_from_file)

        if hicon_big:
            user32.SendMessageW(hwnd, wm_seticon, icon_big, hicon_big)
            try:
                user32.SetClassLongPtrW(hwnd, gclp_hicon, hicon_big)
            except AttributeError:
                user32.SetClassLongW(hwnd, gclp_hicon, hicon_big)

        if hicon_small:
            user32.SendMessageW(hwnd, wm_seticon, icon_small, hicon_small)
            user32.SendMessageW(hwnd, wm_seticon, icon_small2, hicon_small)
            try:
                user32.SetClassLongPtrW(hwnd, gclp_hiconsm, hicon_small)
            except AttributeError:
                user32.SetClassLongW(hwnd, gclp_hiconsm, hicon_small)
    except Exception:
        pass


def main() -> None:
    _ensure_console_streams()

    # Make Windows treat this as its own app (clean taskbar grouping / icon).
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass

    # Reuse an already-running healthy backend (e.g. the dev server) instead of
    # fighting over the port; otherwise start our own.
    server_proc = None
    if not _server_healthy():
        server_proc = _spawn_server()
        if not _wait_for_healthy():
            sys.stderr.write("Prompt Optimizer: the backend did not start in time.\n")
            if server_proc.poll() is None:
                server_proc.terminate()
            sys.exit(1)

    # Capture pywebview's own diagnostics so a window that fails to render
    # (e.g. a WebView2 init problem in a frozen build) leaves a trail.
    import logging

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        filename=str(LOGS_DIR / "pywebview.log"),
        filemode="w",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    import webview

    window = webview.create_window(
        TITLE,
        URL,
        width=1280,
        height=820,
        min_size=(900, 600),
        background_color="#0a0a0a",
    )

    # WebView2 needs a WRITABLE user-data folder. The default sits next to the
    # exe, which fails when the app is installed under Program Files (read-only)
    # and leaves the window stuck/blank. Pin it to the writable data dir.
    (DATA_DIR / "webview").mkdir(parents=True, exist_ok=True)
    start_kwargs = {"storage_path": str(DATA_DIR / "webview"), "private_mode": False}
    if ICON.exists():
        start_kwargs["icon"] = str(ICON)
    # NOTE: no `func=` is passed. A background worker that pokes the native
    # window (icons via cross-thread WinForms/COM + synchronous SendMessage)
    # deadlocks the GUI thread in a frozen build, leaving a blank "Not
    # Responding" window. pywebview shows and paints the window on its own.
    try:
        try:
            webview.start(**start_kwargs)
        except TypeError:
            webview.start()
    finally:
        # The window closed; stop the backend we started (if any).
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--run-server" in sys.argv:
        _run_server_mode()
    else:
        main()
