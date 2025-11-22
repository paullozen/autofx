"""Socket.IO bridge to execute pipeline scripts and stream logs/input to the UI."""
from __future__ import annotations

import builtins
import contextlib
import queue
import runpy
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "backend" / "scripts"

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


@dataclass
class ExecutionContext:
    stage_id: str
    script_path: Path
    input_queue: "queue.Queue[str]" = field(default_factory=queue.Queue)
    thread: threading.Thread | None = None
    stopped: bool = False


executions: dict[str, ExecutionContext] = {}


def emit_log(stage_id: str, message: str, msg_type: str = "info") -> None:
    """Send a log line to the frontend terminal."""
    socketio.emit(
        "script_output",
        {"stage_id": stage_id, "output": message.rstrip(), "type": msg_type},
    )


class SocketIOWriter:
    """Redirect stdout/stderr to the Socket.IO channel."""

    def __init__(self, stage_id: str, msg_type: str = "info"):
        self.stage_id = stage_id
        self.msg_type = msg_type
        self._buffer: str = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        data = data.replace("\r", "\n")
        self._buffer += data
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                emit_log(self.stage_id, line, self.msg_type)
        return len(data)

    def flush(self) -> None:
        if self._buffer.strip():
            emit_log(self.stage_id, self._buffer, self.msg_type)
        self._buffer = ""


def run_stage(context: ExecutionContext) -> None:
    """Execute a Python script and bridge its IO over Socket.IO."""
    stage_id = context.stage_id
    script_path = context.script_path

    socketio.emit("execution_started", {"stage_id": stage_id})
    emit_log(stage_id, f"Launching {script_path.name}...", "system")

    sys.path.insert(0, str(SCRIPTS_DIR))
    sys.path.insert(0, str(ROOT_DIR))

    writer = SocketIOWriter(stage_id)
    original_input = builtins.input

    def patched_input(prompt: str = "") -> str:
        if context.stopped:
            raise SystemExit("Stage interrupted")
        # Do not log here to avoid duplicate messages; let the UI show the prompt once.
        socketio.emit("request_input", {"stage_id": stage_id, "prompt": prompt})
        try:
            user_value = context.input_queue.get(timeout=600)
        except queue.Empty as exc:  # pragma: no cover - defensive timeout path
            raise RuntimeError("Timed out waiting for user input.") from exc
        socketio.emit("input_sent", {"stage_id": stage_id, "input": user_value})
        return user_value

    try:
        builtins.input = patched_input
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            runpy.run_path(str(script_path), run_name="__main__")
        writer.flush()
        status = "stopped" if context.stopped else "success"
        socketio.emit("execution_complete", {"stage_id": stage_id, "status": status})
    except Exception as exc:  # pragma: no cover - surfaced to UI
        writer.flush()
        status = "stopped" if context.stopped else "error"
        if context.stopped:
            emit_log(stage_id, "Execution stopped by user", "system")
        else:
            socketio.emit(
                "execution_error",
                {"stage_id": stage_id, "error": f"{type(exc).__name__}: {exc}"},
            )
        socketio.emit("execution_complete", {"stage_id": stage_id, "status": status})
    finally:
        builtins.input = original_input
        executions.pop(stage_id, None)


def stage_exists(script_file: str) -> Path:
    """Validate and return the requested script path."""
    candidate = (SCRIPTS_DIR / script_file).resolve()
    if not candidate.is_file() or candidate.parent != SCRIPTS_DIR:
        raise FileNotFoundError(f"Unknown script: {script_file}")
    return candidate


@socketio.on("connect")
def handle_connect():
    socketio.emit("connected", {"message": "Backend connected"})


@socketio.on("execute_stage")
def handle_execute_stage(data: dict):
    stage_id = data.get("stage_id")
    script_file = data.get("script_file")

    if not stage_id or not script_file:
        socketio.emit(
            "execution_error",
            {"stage_id": stage_id or "unknown", "error": "Missing stage_id or script"},
        )
        return

    existing = executions.get(stage_id)
    if existing:
        if existing.thread and existing.thread.is_alive():
            socketio.emit(
                "execution_error",
                {"stage_id": stage_id, "error": "Stage already running"},
            )
            return
        executions.pop(stage_id, None)

    try:
        script_path = stage_exists(script_file)
    except FileNotFoundError as exc:
        socketio.emit("execution_error", {"stage_id": stage_id, "error": str(exc)})
        return

    ctx = ExecutionContext(stage_id=stage_id, script_path=script_path)
    thread = threading.Thread(target=run_stage, args=(ctx,), daemon=True)
    ctx.thread = thread
    executions[stage_id] = ctx
    thread.start()


@socketio.on("send_input")
def handle_send_input(data: dict):
    stage_id = data.get("stage_id")
    user_input = data.get("input", "")
    context = executions.get(stage_id)

    if not context:
        socketio.emit(
            "execution_error",
            {"stage_id": stage_id or "unknown", "error": "No running stage for input"},
        )
        return

    context.input_queue.put(user_input)


def _raise_async_exception(thread: threading.Thread, exc_type: type[BaseException]) -> bool:
    """Attempt to raise an exception inside a running thread."""
    import ctypes

    if not thread.ident:
        return False
    result = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(thread.ident), ctypes.py_object(exc_type)
    )
    if result == 0:
        return False
    if result > 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread.ident), None)
        return False
    return True


@socketio.on("stop_stage")
def handle_stop_stage(data: dict):
    stage_id = data.get("stage_id")
    context = executions.get(stage_id)

    if not stage_id or not context:
        socketio.emit(
            "execution_error",
            {"stage_id": stage_id or "unknown", "error": "No running stage to stop"},
        )
        return

    context.stopped = True
    emit_log(stage_id, "Stop requested by user", "system")

    thread = context.thread
    if thread and thread.is_alive():
        _raise_async_exception(thread, KeyboardInterrupt)
        thread.join(timeout=5)

    executions.pop(stage_id, None)
    socketio.emit("execution_complete", {"stage_id": stage_id, "status": "stopped"})


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
