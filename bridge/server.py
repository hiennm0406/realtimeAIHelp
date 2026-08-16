"""
Claude Code bridge.

Runs on the machine where Claude Code is installed. Exposes a small HTTP API that
spawns `claude -p --output-format stream-json` and relays every JSON line to the
browser as Server-Sent Events, so the web UI can render the same information the
terminal shows: thinking, tool calls, tool results, token usage and cost.

Each run lives in a background worker that is *independent of the browser
connection*. Its events are buffered in memory, so a client can disconnect (close
the tab, lose signal, walk away) and the agent keeps working. When the client
comes back it reconnects with `GET /api/stream?runId=...`, replays everything it
missed, and keeps tailing until the run finishes.

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
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)
CONFIG_PATH = os.path.join(ROOT, "config.json")
# Every run's transcript is written here as <runId>.jsonl, so a run survives a
# bridge restart and a client can still replay its result on reconnect.
RUNS_DIR = os.path.join(ROOT, "runs")

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
    # How long a finished run is kept (in memory and on disk) so a returning
    # browser can still replay its result. After this, the run is dropped and its
    # transcript file deleted; reconnecting to it returns 404. Raise it to step
    # away for longer.
    "run_retention_seconds": 21600,
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

# runId -> Run. A run outlives the browser connection that started it, so this is
# also what /api/stream reattaches to and what the reaper eventually clears.
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


class Run:
    """One Claude Code invocation, buffered so it can outlive any single client.

    `frames` is an append-only list of (event, data) pairs - exactly the SSE
    frames a client should receive. A frame's index in the list is its id, which
    is how a reconnecting client asks for "everything after N".
    """

    def __init__(self, run_id, prompt, cwd, command, conversation_id=""):
        self.id = run_id
        self.prompt = prompt
        self.cwd = cwd
        self.command = command
        self.conversation_id = conversation_id
        self.frames = []
        self.cond = threading.Condition()
        self.done = False
        self.status = "running"
        self.proc = None
        self.started_at = time.time()
        self.finished_at = None
        self._log = None
        self._open_log()

    def path(self):
        return os.path.join(RUNS_DIR, self.id + ".jsonl")

    def _open_log(self):
        """Start the on-disk transcript with a meta line describing the run."""
        try:
            os.makedirs(RUNS_DIR, exist_ok=True)
            self._log = open(self.path(), "a", encoding="utf-8")
            self._write_log(
                {
                    "kind": "meta",
                    "runId": self.id,
                    "prompt": self.prompt,
                    "cwd": self.cwd,
                    "command": self.command,
                    "conversationId": self.conversation_id,
                    "startedAt": self.started_at,
                }
            )
        except Exception:
            # Disk trouble shouldn't take the run down; it just won't survive a
            # restart. In-memory streaming still works.
            self._log = None

    def _write_log(self, obj):
        if not self._log:
            return
        try:
            self._log.write(json.dumps(obj) + "\n")
            self._log.flush()
        except Exception:
            pass

    def append(self, event, data):
        with self.cond:
            self._write_log(
                {"kind": "frame", "i": len(self.frames), "event": event, "data": data}
            )
            self.frames.append((event, data))
            self.cond.notify_all()

    def finish(self, status=None):
        with self.cond:
            if status:
                self.status = status
            self.done = True
            self.finished_at = time.time()
            self._write_log(
                {"kind": "end", "status": self.status, "finishedAt": self.finished_at}
            )
            if self._log:
                try:
                    self._log.close()
                except Exception:
                    pass
                self._log = None
            self.cond.notify_all()

    @classmethod
    def load(cls, path):
        """Rebuild a run from its transcript file (no live process attached)."""
        meta = None
        frames = []
        ended = False
        status = "done"
        finished_at = None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = obj.get("kind")
                    if kind == "meta":
                        meta = obj
                    elif kind == "frame":
                        frames.append((obj.get("event"), obj.get("data")))
                    elif kind == "end":
                        ended = True
                        status = obj.get("status", "done")
                        finished_at = obj.get("finishedAt")
        except Exception:
            return None
        if not meta:
            return None

        run = cls.__new__(cls)  # bypass __init__ so we don't reopen the log
        run.id = meta.get("runId") or os.path.splitext(os.path.basename(path))[0]
        run.prompt = meta.get("prompt", "")
        run.cwd = meta.get("cwd", "")
        run.command = meta.get("command", [])
        run.conversation_id = meta.get("conversationId", "")
        run.frames = frames
        run.cond = threading.Condition()
        run.proc = None
        run.started_at = meta.get("startedAt", time.time())
        run._log = None

        if ended:
            run.done = True
            run.status = status
            run.finished_at = finished_at or run.started_at
        else:
            # The bridge stopped while this run was in flight - the live process
            # is gone, so mark it interrupted but still let the client replay
            # whatever it managed to produce.
            run.frames.append(
                (
                    "error",
                    {
                        "type": "error",
                        "message": "The bridge restarted while this run was in "
                        "progress, so it was interrupted before finishing.",
                    },
                )
            )
            run.frames.append(("done", {"type": "done", "runId": run.id, "exitCode": -1}))
            run.done = True
            run.status = "interrupted"
            run.finished_at = run.started_at
        return run

    def delete_file(self):
        try:
            os.remove(self.path())
        except OSError:
            pass

    def title(self):
        line = " ".join((self.prompt or "").split())
        return line[:120]

    def summary(self):
        return {
            "runId": self.id,
            "status": self.status,
            "done": self.done,
            "conversationId": self.conversation_id,
            "startedAt": int(self.started_at * 1000),
            "finishedAt": int(self.finished_at * 1000) if self.finished_at else None,
            "frames": len(self.frames),
            "prompt": self.title(),
        }


def run_worker(run, payload):
    """Drives one Claude process to completion, writing every event into the run.

    This runs on its own thread and never touches a client socket, so a browser
    coming or going has no effect on it.
    """
    proc = None
    try:
        popen_kwargs = {
            "cwd": run.cwd,
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

        cmd = [CLAUDE_BIN] + run.command
        proc = subprocess.Popen(cmd, **popen_kwargs)
        run.proc = proc

        run.append(
            "bridge",
            {
                "type": "started",
                "runId": run.id,
                "cwd": run.cwd,
                "command": " ".join(run.command),
            },
        )

        # Hand the prompt over on stdin so long prompts and quotes survive.
        try:
            proc.stdin.write(run.prompt)
            proc.stdin.close()
        except Exception as exc:
            run.append("error", {"type": "error", "message": "could not send prompt: %s" % exc})

        lines = queue.Queue()
        stderr_chunks = []

        # readline() rather than `for line in proc.stdout`: iterating a pipe uses
        # a read-ahead buffer, which holds lines back until the buffer fills.
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
        timed_out = False

        while True:
            if time.time() > deadline:
                run.append("error", {"type": "error", "message": "run timed out"})
                kill_process_tree(proc)
                timed_out = True
                break
            try:
                # A short poll so the deadline is enforced even while Claude is
                # silent (no output line to wake us).
                kind, line = lines.get(timeout=5)
            except queue.Empty:
                continue

            if kind == "eof":
                break

            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                run.append("notice", {"type": "notice", "text": line})
                continue

            run.append("claude", parsed)

        exit_code = proc.wait()
        stderr_text = "".join(stderr_chunks).strip()
        if exit_code != 0 and stderr_text and not timed_out:
            run.append("error", {"type": "error", "message": stderr_text[:4000]})
        run.append("done", {"type": "done", "runId": run.id, "exitCode": exit_code})
        run.finish(status="done" if exit_code == 0 else "error")

    except Exception as exc:
        run.append("error", {"type": "error", "message": str(exc)})
        run.append("done", {"type": "done", "runId": run.id, "exitCode": -1})
        run.finish(status="error")
    finally:
        if proc:
            kill_process_tree(proc)
        RUN_SLOTS.release()


def reap_runs():
    """Drop finished runs, in memory and on disk, past the retention window."""
    retention = float(CONFIG.get("run_retention_seconds", 21600))
    while True:
        time.sleep(60)
        cutoff = time.time() - retention
        with RUNS_LOCK:
            for run_id in list(RUNS):
                run = RUNS[run_id]
                if run.done and run.finished_at and run.finished_at < cutoff:
                    run.delete_file()
                    del RUNS[run_id]


def load_persisted_runs():
    """On startup, bring back runs whose transcripts are still on disk.

    This is what makes a run survive a bridge restart: the browser reconnects
    with the same runId and replays the saved result.
    """
    if not os.path.isdir(RUNS_DIR):
        return
    retention = float(CONFIG.get("run_retention_seconds", 21600))
    cutoff = time.time() - retention
    loaded = 0
    for name in sorted(os.listdir(RUNS_DIR)):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(RUNS_DIR, name)
        run = Run.load(path)
        if not run:
            continue
        if run.finished_at and run.finished_at < cutoff:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        with RUNS_LOCK:
            RUNS[run.id] = run
        loaded += 1
    if loaded:
        print("  restored %d past run(s) from %s" % (loaded, RUNS_DIR))


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
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/api/health", "/health"):
            if not self.authorized():
                return self.send_json(401, {"error": "unauthorized"})
            with RUNS_LOCK:
                active = sum(1 for r in RUNS.values() if not r.done)
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

        if path == "/api/runs":
            if not self.authorized():
                return self.send_json(401, {"error": "unauthorized"})
            with RUNS_LOCK:
                runs = [run.summary() for run in RUNS.values()]
            runs.sort(key=lambda r: r["startedAt"], reverse=True)
            return self.send_json(200, {"runs": runs})

        if path == "/api/stream":
            if not self.authorized():
                return self.send_json(401, {"error": "unauthorized"})
            params = parse_qs(parsed.query)
            run_id = (params.get("runId", [""])[0] or "").strip()
            try:
                offset = int(params.get("offset", ["0"])[0])
            except ValueError:
                offset = 0
            with RUNS_LOCK:
                run = RUNS.get(run_id)
            if not run:
                return self.send_json(404, {"error": "no such run"})
            return self.stream_run(run, offset)

        if path == "/api/run":
            # A plain, non-streaming snapshot of a run from `offset`. Short
            # request/response, so it survives tunnels that buffer or drop the
            # long-lived /api/stream reconnect. Clients poll this to catch up.
            if not self.authorized():
                return self.send_json(401, {"error": "unauthorized"})
            params = parse_qs(parsed.query)
            run_id = (params.get("runId", [""])[0] or "").strip()
            try:
                offset = int(params.get("offset", ["0"])[0])
            except ValueError:
                offset = 0
            with RUNS_LOCK:
                run = RUNS.get(run_id)
            if not run:
                return self.send_json(404, {"error": "no such run"})
            with run.cond:
                offset = max(0, offset)
                frames = [list(f) for f in run.frames[offset:]]
                total = len(run.frames)
                done = run.done
                status = run.status
            return self.send_json(
                200,
                {
                    "runId": run.id,
                    "done": done,
                    "status": status,
                    "next": total,
                    "frames": frames,
                },
            )

        return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.authorized():
            return self.send_json(401, {"error": "unauthorized"})

        if path == "/api/abort":
            try:
                payload = self.read_json_body()
            except Exception:
                return self.send_json(400, {"error": "invalid json body"})
            run_id = payload.get("runId")
            with RUNS_LOCK:
                run = RUNS.get(run_id)
            if not run:
                return self.send_json(404, {"error": "no such run"})
            if run.proc:
                kill_process_tree(run.proc)
            return self.send_json(200, {"ok": True, "runId": run_id})

        if path == "/api/chat":
            try:
                payload = self.read_json_body()
            except Exception:
                return self.send_json(400, {"error": "invalid json body"})
            return self.start_chat(payload)

        return self.send_json(404, {"error": "not found"})

    # ---------- starting and streaming a run ----------

    def start_chat(self, payload):
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
        cwd = allowed_cwd(payload.get("cwd"))
        command = build_command(payload)[1:]  # drop the binary; worker re-adds it
        run = Run(
            run_id,
            prompt,
            cwd,
            command,
            conversation_id=(payload.get("conversationId") or "").strip(),
        )
        with RUNS_LOCK:
            RUNS[run_id] = run

        threading.Thread(target=run_worker, args=(run, payload), daemon=True).start()

        # Stream this run to the caller from the very first frame. If they drop,
        # stream_run just returns - the worker above keeps the run alive.
        self.stream_run(run, 0)

    def stream_run(self, run, offset):
        # The body has no Content-Length and isn't chunked, so under HTTP/1.1 the
        # only unambiguous framing is close-delimited. Tunnels and proxies
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

        index = max(0, offset)
        while True:
            with run.cond:
                while index >= len(run.frames) and not run.done:
                    run.cond.wait(timeout=10)
                pending = run.frames[index:]
                index += len(pending)
                drained = run.done and index >= len(run.frames)

            if pending:
                base = index - len(pending)
                for offset_in_batch, (event, data) in enumerate(pending):
                    if not self.emit(base + offset_in_batch, event, data):
                        return  # client gone; the worker carries on without us
            elif not drained:
                if not self.ping():
                    return

            if drained:
                return

    def emit(self, frame_id, event, data):
        """Write one SSE frame. Returns False once the client has gone away."""
        frame = "id: %d\nevent: %s\ndata: %s\n\n" % (frame_id, event, json.dumps(data))
        try:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def ping(self):
        """Idle keepalive so tunnels don't drop a quiet connection."""
        try:
            self.wfile.write(b": ping\n\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False


def main():
    host = CONFIG["host"]
    port = int(CONFIG["port"])
    server = ThreadingHTTPServer((host, port), Bridge)
    server.daemon_threads = True

    threading.Thread(target=reap_runs, daemon=True).start()

    print("")
    print("  Claude Code bridge")
    print("  ------------------")
    print("  listening on   http://%s:%d" % (host, port))
    print("  claude binary  %s" % (CLAUDE_BIN or "NOT FOUND - set claude_path in config.json"))
    print("  working dir    %s" % os.path.abspath(CONFIG["default_cwd"]))
    print("  permissions    %s" % CONFIG["default_permission_mode"])
    print("  runs kept for  %ss after finishing (survives a bridge restart)"
          % CONFIG.get("run_retention_seconds", 21600))
    load_persisted_runs()
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
            for run in list(RUNS.values()):
                if run.proc:
                    kill_process_tree(run.proc)
        server.shutdown()


if __name__ == "__main__":
    main()
