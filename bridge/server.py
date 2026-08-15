"""
Claude Code bridge.

Runs on the machine where Claude Code is installed. Exposes a small HTTP API that
spawns `claude -p --output-format stream-json` and relays every JSON line to the
browser as Server-Sent Events, so the web UI can render the same information the
terminal shows: thinking, tool calls, tool results, token usage and cost.

Stdlib only - no pip install required.

    python bridge/server.py

Config lives in bridge/config.json and is created on first run.
"""

import json
import os
import queue
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)
CONFIG_PATH = os.path.join(ROOT, "config.json")

IS_WINDOWS = os.name == "nt"

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8787,
    # Shared secret the web UI must send as `Authorization: Bearer <token>`.
    # Generated on first run.
    "token": "",
    # Path to the Claude Code executable, or just "claude" if it is on PATH.
    "claude_path": "claude",
    # Working directory Claude runs in. This is the folder it can read and edit.
    "default_cwd": PROJECT_ROOT,
    # Directories the web UI is allowed to switch to. Empty list = only default_cwd.
    "allowed_cwds": [],
    # "" means: use whatever model Claude Code is configured with.
    "default_model": "",
    # acceptEdits | dontAsk | plan | bypassPermissions | auto | manual
    # bypassPermissions gives the web UI unrestricted command execution on this
    # machine. Only use it if you trust every holder of the token.
    "default_permission_mode": "bypassPermissions",
    # Adds --dangerously-skip-permissions. Needed by some setups for tools to run
    # with no prompt at all in headless mode. Same trust requirement as above.
    "dangerously_skip_permissions": True,
    # Tools the browser is allowed to use. Empty list = every tool Claude Code has
    # (Bash, Read, Write, Edit, WebSearch, WebFetch, Task, ...).
    "allowed_tools": [],
    # CORS. Put your deployed site here once you know its URL, e.g.
    # ["https://your-site.netlify.app", "http://localhost:5173"]
    "allowed_origins": ["*"],
    # How many Claude runs may execute at the same time.
    "max_concurrent": 2,
    # Hard stop for a single run, in seconds.
    "run_timeout_seconds": 1800,
}

PERMISSION_MODES = {
    "acceptEdits",
    "dontAsk",
    "plan",
    "bypassPermissions",
    "auto",
    "manual",
}

EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def load_config():
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            config.update(json.load(handle))
    if not config.get("token"):
        config["token"] = secrets.token_urlsafe(32)
        save_config(config)
        print("Generated a new access token in bridge/config.json")
    return config


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)


CONFIG = load_config()

# runId -> Popen, so /api/abort can stop a run the browser no longer wants.
RUNS = {}
RUNS_LOCK = threading.Lock()
RUN_SLOTS = threading.BoundedSemaphore(max(1, int(CONFIG["max_concurrent"])))


def resolve_claude():
    configured = CONFIG.get("claude_path") or "claude"
    found = shutil.which(configured)
    if found:
        return found
    if os.path.isfile(configured):
        return configured
    return None


CLAUDE_BIN = resolve_claude()


def kill_process_tree(proc):
    """Claude Code spawns helper processes; killing only the parent leaves them running."""
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def allowed_cwd(requested):
    """Only let the browser pick from directories the operator listed."""
    default = os.path.abspath(CONFIG["default_cwd"])
    if not requested:
        return default
    requested = os.path.abspath(requested)
    permitted = [default] + [os.path.abspath(p) for p in CONFIG.get("allowed_cwds", [])]
    if requested in permitted and os.path.isdir(requested):
        return requested
    return default


def build_command(payload):
    cmd = [
        CLAUDE_BIN,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
    ]

    model = (payload.get("model") or CONFIG.get("default_model") or "").strip()
    if model:
        cmd += ["--model", model]

    mode = (payload.get("permissionMode") or CONFIG["default_permission_mode"]).strip()
    if mode in PERMISSION_MODES:
        cmd += ["--permission-mode", mode]

    if CONFIG.get("dangerously_skip_permissions") and mode == "bypassPermissions":
        cmd += ["--dangerously-skip-permissions"]

    allowed_tools = CONFIG.get("allowed_tools") or []
    if allowed_tools:
        cmd += ["--allowed-tools"] + list(allowed_tools)

    effort = (payload.get("effort") or "").strip()
    if effort in EFFORT_LEVELS:
        cmd += ["--effort", effort]

    session_id = (payload.get("sessionId") or "").strip()
    if session_id:
        cmd += ["--resume", session_id]

    return cmd


class Bridge(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ClaudeBridge/1.0"

    # ---------- plumbing ----------

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def origin_header(self):
        origin = self.headers.get("Origin", "")
        allowed = CONFIG.get("allowed_origins", ["*"])
        if "*" in allowed:
            return origin or "*"
        return origin if origin in allowed else ""

    def send_cors(self):
        origin = self.origin_header()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")

    def send_json(self, status, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_cors()
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        header = self.headers.get("Authorization", "")
        token = header[7:].strip() if header.startswith("Bearer ") else ""
        return secrets.compare_digest(token, CONFIG["token"])

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # ---------- routes ----------

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/api/health", "/health"):
            if not self.authorized():
                return self.send_json(401, {"error": "unauthorized"})
            with RUNS_LOCK:
                active = len(RUNS)
            return self.send_json(
                200,
                {
                    "ok": True,
                    "claudePath": CLAUDE_BIN,
                    "claudeFound": bool(CLAUDE_BIN),
                    "cwd": os.path.abspath(CONFIG["default_cwd"]),
                    "allowedCwds": [
                        os.path.abspath(p) for p in CONFIG.get("allowed_cwds", [])
                    ],
                    "defaultModel": CONFIG.get("default_model") or "(claude default)",
                    "defaultPermissionMode": CONFIG["default_permission_mode"],
                    "activeRuns": active,
                    "maxConcurrent": CONFIG["max_concurrent"],
                },
            )
        return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if not self.authorized():
            return self.send_json(401, {"error": "unauthorized"})

        if path == "/api/abort":
            try:
                payload = self.read_json_body()
            except Exception:
                return self.send_json(400, {"error": "invalid json body"})
            run_id = payload.get("runId")
            with RUNS_LOCK:
                proc = RUNS.get(run_id)
            if not proc:
                return self.send_json(404, {"error": "no such run"})
            kill_process_tree(proc)
            return self.send_json(200, {"ok": True, "runId": run_id})

        if path == "/api/chat":
            try:
                payload = self.read_json_body()
            except Exception:
                return self.send_json(400, {"error": "invalid json body"})
            return self.stream_chat(payload)

        return self.send_json(404, {"error": "not found"})

    # ---------- the streaming run ----------

    def stream_chat(self, payload):
        prompt = (payload.get("prompt") or "").strip()
        if not prompt:
            return self.send_json(400, {"error": "prompt is required"})
        if not CLAUDE_BIN:
            return self.send_json(
                500,
                {
                    "error": "Claude Code executable not found. Set claude_path in "
                    "bridge/config.json."
                },
            )

        if not RUN_SLOTS.acquire(blocking=False):
            return self.send_json(429, {"error": "bridge is busy, try again shortly"})

        run_id = uuid.uuid4().hex
        write_lock = threading.Lock()
        proc = None

        def emit(event, data):
            """Write one SSE frame. Returns False once the browser has gone away."""
            frame = "event: %s\ndata: %s\n\n" % (event, json.dumps(data))
            with write_lock:
                try:
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return False

        try:
            # The body has no Content-Length and isn't chunked, so under HTTP/1.1
            # the only unambiguous framing is close-delimited. Tunnels and proxies
            # mis-handle a keep-alive response with no length.
            self.close_connection = True

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            # Stops nginx / tunnel proxies from buffering the stream.
            self.send_header("X-Accel-Buffering", "no")
            self.send_cors()
            self.end_headers()

            cwd = allowed_cwd(payload.get("cwd"))
            cmd = build_command(payload)

            popen_kwargs = {
                "cwd": cwd,
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            }
            if IS_WINDOWS:
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            else:
                popen_kwargs["start_new_session"] = True

            proc = subprocess.Popen(cmd, **popen_kwargs)
            with RUNS_LOCK:
                RUNS[run_id] = proc

            emit(
                "bridge",
                {
                    "type": "started",
                    "runId": run_id,
                    "cwd": cwd,
                    "command": " ".join(cmd[1:]),
                },
            )

            # Hand the prompt over on stdin so long prompts and quotes survive.
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
            except Exception as exc:
                emit("error", {"type": "error", "message": "could not send prompt: %s" % exc})

            lines = queue.Queue()
            stderr_chunks = []

            # readline() rather than `for line in proc.stdout`: iterating a pipe
            # uses a read-ahead buffer, which holds lines back until the buffer
            # fills. That turns a live stream into one late burst.
            def pump_stdout():
                try:
                    for line in iter(proc.stdout.readline, ""):
                        lines.put(("out", line))
                except Exception:
                    pass
                finally:
                    lines.put(("eof", None))

            def pump_stderr():
                try:
                    for line in iter(proc.stderr.readline, ""):
                        stderr_chunks.append(line)
                except Exception:
                    pass

            threading.Thread(target=pump_stdout, daemon=True).start()
            threading.Thread(target=pump_stderr, daemon=True).start()

            deadline = time.time() + float(CONFIG["run_timeout_seconds"])
            alive = True

            while alive:
                if time.time() > deadline:
                    emit("error", {"type": "error", "message": "run timed out"})
                    kill_process_tree(proc)
                    break
                try:
                    kind, line = lines.get(timeout=10)
                except queue.Empty:
                    # Idle keepalive so tunnels don't drop a quiet connection.
                    with write_lock:
                        try:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            alive = False
                    continue

                if kind == "eof":
                    break

                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    # Anything Claude prints that isn't a JSON line.
                    alive = emit("notice", {"type": "notice", "text": line})
                    continue

                alive = emit("claude", parsed)

            if not alive:
                # Browser disconnected mid-run: don't leave Claude running.
                kill_process_tree(proc)
                return

            exit_code = proc.wait()
            stderr_text = "".join(stderr_chunks).strip()
            if exit_code != 0 and stderr_text:
                emit("error", {"type": "error", "message": stderr_text[:4000]})
            emit("done", {"type": "done", "runId": run_id, "exitCode": exit_code})

        except Exception as exc:
            emit("error", {"type": "error", "message": str(exc)})
        finally:
            with RUNS_LOCK:
                RUNS.pop(run_id, None)
            if proc:
                kill_process_tree(proc)
            RUN_SLOTS.release()


def main():
    host = CONFIG["host"]
    port = int(CONFIG["port"])
    server = ThreadingHTTPServer((host, port), Bridge)
    server.daemon_threads = True

    print("")
    print("  Claude Code bridge")
    print("  ------------------")
    print("  listening on   http://%s:%d" % (host, port))
    print("  claude binary  %s" % (CLAUDE_BIN or "NOT FOUND - set claude_path in config.json"))
    print("  working dir    %s" % os.path.abspath(CONFIG["default_cwd"]))
    print("  permissions    %s" % CONFIG["default_permission_mode"])
    print("")
    print("  access token   %s" % CONFIG["token"])
    print("  (paste this into the web UI's Settings panel)")
    print("")
    if CONFIG["default_permission_mode"] == "bypassPermissions":
        print("  !! bypassPermissions is on: anyone with the token can run any")
        print("  !! command on this machine. Rotate the token if it ever leaks.")
        print("")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        with RUNS_LOCK:
            for proc in list(RUNS.values()):
                kill_process_tree(proc)
        server.shutdown()


if __name__ == "__main__":
    main()
