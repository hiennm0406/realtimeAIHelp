"""
Claude Code bridge.

Runs on the machine where Claude Code is installed. Exposes a small HTTP API that
spawns `claude -p --output-format stream-json` and relays every JSON line to the
browser as Server-Sent Events, so the web UI can render the same information the
terminal shows: thinking, tool calls, tool results, token usage and cost.

Each run lives in a background worker that is *independent of the browser
connection*. Its events are streamed to a transcript under bridge/runs/, so a
client can disconnect (close the tab, lose signal, walk away) - and the bridge
itself can restart - while the agent keeps working. When the client comes back it
replays everything it missed from that transcript (`GET /api/run`, or
`GET /api/stream` for SSE) and keeps catching up until the run finishes.

The transcript is the source of truth. Frames are cached in memory while a run is
live and for a short while after, then dropped and re-read on demand, so a bridge
that has been up for days is not still holding every byte it ever streamed.

Stdlib only - no pip install required.

    python bridge/server.py

Config lives in bridge/config.json and is created on first run.
"""

import base64
import hashlib
import json
import os
import queue
import re
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
    # Tools that may run WITHOUT a prompt. Empty list = every tool Claude Code
    # has (Bash, Read, Write, Edit, WebSearch, WebFetch, Task, ...). Entries can
    # narrow by argument too, e.g. "Bash(git status:*)" or "Write(./data/**)".
    # Headless runs have nobody to answer a prompt, so with a non-empty list
    # anything outside it is effectively refused.
    "allowed_tools": [],
    # Tools refused outright, overriding anything in allowed_tools. Same syntax.
    # This is the hard boundary: it is passed on the command line, so a run
    # cannot lift it by editing a settings file in the working directory.
    "disallowed_tools": [],
    # Fence Read/Write/Edit into the working directory by generating deny rules
    # for everything outside it (see confinement_rules). Without this a run can
    # read any file the bridge's user can - other projects, ~/.ssh, and
    # ~/.claude/.credentials.json included.
    "confine_to_cwd": False,
    # Subdirectories of the working directory that Write/Edit may touch, e.g.
    # [".claude/skills", "data"]. Everything else in the project becomes
    # read-only. Empty = the whole working directory is writable. Requires
    # confine_to_cwd, since the rules travel in the same policy file.
    "writable_paths": [],
    # Permission modes the BROWSER may select in its Settings drawer. Empty (the
    # default) means the client cannot change the mode at all and
    # default_permission_mode always applies - otherwise anyone holding the
    # token could pick "bypassPermissions" and grant themselves a shell.
    "allowed_permission_modes": [],
    # CORS. Put your deployed site here once you know its URL, e.g.
    # ["https://your-site.netlify.app", "http://localhost:5173"]
    "allowed_origins": ["*"],
    # How many Claude runs may execute at the same time.
    "max_concurrent": 2,
    # Idle timeout: kill a run only after this many seconds with NO output at all
    # (no thinking, no tool call, no token). An actively working agent streams
    # constantly, so it resets this clock and is never reaped mid-work - only a
    # genuinely stuck/hung process is. This replaces the old wall-clock
    # "run_timeout_seconds", which killed long-but-healthy runs at 30 min.
    "run_idle_timeout_seconds": 1800,
    # Absolute backstop, in seconds. Ends even a run that keeps printing forever
    # (e.g. a tool stuck in a loop). Set high; the idle timeout is the real guard.
    "run_max_seconds": 21600,
    # How long a finished run's transcript is kept ON DISK, and therefore how
    # long a returning browser can still replay it. This is cheap - it is just a
    # file - so it defaults to a week. After this the transcript is deleted and
    # reconnecting to that run returns 404.
    "run_retention_seconds": 604800,
    # How long a finished run's frames stay in RAM after it is last touched.
    # Beyond this they are dropped and re-read from the transcript on demand, so
    # a long-lived bridge does not accumulate every byte of tool output it has
    # ever streamed. Replay still works - it just reads the file.
    "run_memory_seconds": 600,
    # Hard cap on a request body, in bytes. Guards against a bogus (or hostile)
    # Content-Length turning into an unbounded allocation. Attached images ride
    # in the body as base64, which inflates them by a third, so this sits well
    # above the image limits below.
    "max_body_bytes": 32 * 1024 * 1024,
}

# Image attachments. The API takes these as base64 content blocks, so the bytes
# pass through the bridge rather than being written anywhere - nothing lands on
# disk, and the confinement rules are untouched by this feature.
#
# The magic numbers are checked because `media_type` is what tells the API how
# to decode the payload: a mismatch is either a broken client or someone probing
# what the bridge will forward.
ALLOWED_IMAGE_TYPES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES_TOTAL_BYTES = 24 * 1024 * 1024

# Must match `claude --permission-mode` exactly. A value missing from this set is
# silently dropped rather than passed through, so the bridge would fall back to
# whatever Claude Code defaults to - the config would look applied but not be.
PERMISSION_MODES = {
    "default",
    "acceptEdits",
    "dontAsk",
    "plan",
    "bypassPermissions",
    "auto",
    "manual",
}

EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}

# A run id is used as a filename, so it is restricted to hex. The browser picks
# it (see start_chat) which is what lets Stop work before the first frame has
# made it back over a slow tunnel.
RUN_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")

# Most frames one /api/run snapshot will return. Replaying a long run is then a
# sequence of modest responses instead of a single multi-megabyte one.
MAX_SNAPSHOT_FRAMES = 400


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
# Run ids aborted before their Run object existed, mapped to when that happened.
# The browser picks the id and can hit Stop while POST /api/chat is still in
# flight, so without this the run would start anyway and keep working with
# nobody watching it. Entries that were never claimed are pruned by the reaper.
CANCELLED = {}
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


def deny_forms(path):
    """The same location spelled three ways.

    Which spelling the matcher normalises to is undocumented, and guessing wrong
    fails OPEN on the deny side, so all three go in.
    """
    trimmed = path.rstrip("\\/")
    drive, rest = os.path.splitdrive(trimmed)
    tail = rest.replace("\\", "/").strip("/")
    if not tail:
        return {"%s/**" % drive, "//%s/**" % drive[0].lower(), "%s\\**" % drive}
    bases = ["%s/%s" % (drive, tail),
             "//%s/%s" % (drive[0].lower(), tail),
             "%s\\%s" % (drive, rest.strip("\\"))]
    forms = set()
    for base in bases:
        sep = "\\" if "\\" in base else "/"
        forms.add(base + sep + "**")   # everything under it, if it is a directory
        forms.add(base)                # and the entry itself, if it is a file -
        # `foo.json/**` never matches the file `foo.json`, so without the bare
        # form a denied FILE was silently left writable.
    return forms


def siblings_of(keep_paths, roots):
    """Every entry under `roots` that is not on the path to something in `keep_paths`.

    This is how "everything except X" gets expressed in a deny list, which has
    no negation: walk down from each root and block whatever is not an ancestor
    of, or inside, something we mean to keep.
    """
    keep = set()
    for target in keep_paths:
        node = os.path.abspath(target)
        while True:
            keep.add(os.path.normcase(node))
            parent = os.path.dirname(node)
            if parent == node:
                break
            node = parent

    blocked, queue_ = [], list(roots)
    while queue_:
        node = queue_.pop()
        try:
            entries = os.listdir(node)
        except OSError:
            continue
        for name in entries:
            child = os.path.join(node, name)
            norm = os.path.normcase(child)
            if norm in keep:
                # On the way to something we keep - descend, unless this IS one
                # of the kept roots, in which case everything below it stays.
                if norm not in {os.path.normcase(os.path.abspath(k)) for k in keep_paths}:
                    queue_.append(child)
            else:
                blocked.append(child)
    return blocked


def write_scope_rules(cwd, writable):
    """Deny Write/Edit anywhere inside `cwd` except the `writable` subpaths."""
    targets = [os.path.join(cwd, rel.replace("/", os.sep)) for rel in writable]
    rules = []
    for path in siblings_of(targets, [cwd]):
        for form in sorted(deny_forms(path)):
            rules.append("Write(%s)" % form)
            rules.append("Edit(%s)" % form)
    # The kept locations may not exist yet; create them, or a first write lands
    # somewhere the walk never enumerated. An entry with a suffix is a file, so
    # only its parent gets created - makedirs on "CLAUDE.md" would produce a
    # directory by that name and quietly break the file it was meant to allow.
    for target in targets:
        directory = target if not os.path.splitext(target)[1] else os.path.dirname(target)
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
    return rules


def confinement_rules(cwd):
    """Deny rules that fence file tools into `cwd` and nothing else.

    Claude Code's permission rules match paths on the DENY side but (as of
    2.1.x on Windows) not on the ALLOW side, and a deny list cannot express
    "everything except X". So the exception is enumerated instead: walk from
    each drive root down to `cwd`, denying every sibling along the way. Nothing
    outside the project tree is left reachable.

    Regenerated on every start, so a folder created next to the project later is
    covered too - a hand-written list would silently stop covering it.
    """
    cwd = os.path.abspath(cwd)
    keep = []          # the project and each of its ancestors
    node = cwd
    while True:
        keep.append(os.path.normcase(node))
        parent = os.path.dirname(node)
        if parent == node:
            break
        node = parent
    keep = set(keep)

    blocked = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = letter + ":\\"
        if not os.path.exists(root):
            continue
        if os.path.normcase(root) not in keep:
            blocked.append(root)       # a whole drive the project is not on
            continue
        # The project's own drive: descend, blocking siblings at each level.
        node = root
        while os.path.normcase(node) != os.path.normcase(cwd):
            try:
                entries = os.listdir(node)
            except OSError:
                break
            nxt = None
            for name in entries:
                child = os.path.join(node, name)
                if os.path.normcase(child) in keep:
                    nxt = child
                else:
                    blocked.append(child)
            if nxt is None:
                break
            node = nxt

    rules = []
    for path in blocked:
        trimmed = path.rstrip("\\/")
        drive, rest = os.path.splitdrive(trimmed)
        tail = rest.replace("\\", "/").strip("/")
        # Three spellings of the same location, because which one the matcher
        # normalises to is not documented and getting it wrong fails OPEN here.
        forms = {
            "%s/%s/**" % (drive, tail) if tail else "%s/**" % drive,
            "//%s/%s/**" % (drive[0].lower(), tail) if tail else "//%s/**" % drive[0].lower(),
            "%s\\%s\\**" % (drive, rest.strip("\\")) if tail else "%s\\**" % drive,
        }
        for tool in ("Read", "Write", "Edit"):
            for form in sorted(forms):
                rules.append("%s(%s)" % (tool, form))
    return rules


def policy_dir():
    """Somewhere outside any project the agent might be pointed at."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "claude-bridge")


def write_policy_file(cwd):
    """Write the confinement deny rules to a settings file, return its path.

    Raises on failure. That is deliberate: if the policy cannot be written, the
    run must not start at all. Returning None here would have let it launch with
    no confinement - the one outcome this whole mechanism exists to prevent.
    """
    os.makedirs(policy_dir(), exist_ok=True)
    # Keyed by working directory so switching cwd cannot reuse another's rules.
    # hashlib, not hash(): the built-in is salted per process, so the filename
    # would change on every bridge restart and leave stale files behind.
    digest = hashlib.sha256(os.path.normcase(os.path.abspath(cwd)).encode("utf-8")).hexdigest()[:16]
    path = os.path.join(policy_dir(), "policy-%s.json" % digest)
    deny = confinement_rules(cwd)
    allow = []
    writable = CONFIG.get("writable_paths") or []
    if writable:
        deny += write_scope_rules(cwd, writable)
        # Some locations - `.claude/` above all - are gated by Claude Code even
        # when nothing denies them, and a headless run has nobody to ask. An
        # allow rule in the settings file lifts that. Note this only works via
        # the settings file: the same pattern passed as --allowed-tools does not
        # match, and the workspace must be trusted for allow rules to count.
        for rel in writable:
            target = os.path.join(cwd, rel.replace("/", os.sep))
            for form in sorted(deny_forms(target)):
                allow.append("Write(%s)" % form)
                allow.append("Edit(%s)" % form)
    body = {"permissions": {"deny": deny, "allow": allow}}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(body, handle, indent=2)
    return path


def sanitize_images(raw):
    """Validate attachments from the browser, or raise ValueError.

    Everything is re-encoded from the decoded bytes rather than forwarded as
    received, so whitespace, padding quirks and `data:` envelopes cannot reach
    the API as-is.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("images must be a list")
    if len(raw) > MAX_IMAGES:
        raise ValueError("at most %d images per message" % MAX_IMAGES)

    images = []
    total = 0
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("each image must be an object")

        media = str(entry.get("mediaType") or "").strip().lower()
        if media not in ALLOWED_IMAGE_TYPES:
            raise ValueError("unsupported image type: %s" % (media or "(missing)"))

        data = entry.get("data")
        if not isinstance(data, str) or not data:
            raise ValueError("image data must be a base64 string")
        if data.startswith("data:"):
            _, _, data = data.partition(",")
        data = "".join(data.split())

        try:
            blob = base64.b64decode(data, validate=True)
        except Exception:
            raise ValueError("image data is not valid base64")
        if not blob:
            raise ValueError("image is empty")
        if len(blob) > MAX_IMAGE_BYTES:
            raise ValueError("each image must be under %dMB" % (MAX_IMAGE_BYTES // 1048576))

        total += len(blob)
        if total > MAX_IMAGES_TOTAL_BYTES:
            raise ValueError(
                "attachments must total under %dMB" % (MAX_IMAGES_TOTAL_BYTES // 1048576)
            )

        if not any(blob.startswith(sig) for sig in ALLOWED_IMAGE_TYPES[media]):
            raise ValueError("the bytes do not look like %s" % media)
        # RIFF alone is a container - WebP is identified by the form type.
        if media == "image/webp" and blob[8:12] != b"WEBP":
            raise ValueError("the bytes do not look like image/webp")

        images.append(
            {"mediaType": media, "data": base64.b64encode(blob).decode("ascii")}
        )
    return images


def stdin_payload(prompt, images):
    """What gets handed to Claude Code on stdin.

    Plain text when there is nothing attached - that is the path every run took
    before images existed, and it stays byte-for-byte the same. With
    attachments, the prompt becomes one stream-json user message whose content
    is the images followed by the text, which is how the model receives them as
    something it can see rather than a path it would have to open.
    """
    if not images:
        return prompt

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image["mediaType"],
                "data": image["data"],
            },
        }
        for image in images
    ]
    # Text last: the images are what the question refers to, so they should
    # already be in view by the time the model reads it. An empty prompt is
    # allowed - sending a screenshot on its own is a complete request.
    if prompt:
        content.append({"type": "text", "text": prompt})
    message = {"type": "user", "message": {"role": "user", "content": content}}
    return json.dumps(message) + "\n"


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

    # The browser may only pick a permission mode the operator has explicitly
    # opened up. Without this a token holder could simply choose
    # "bypassPermissions" in the Settings drawer and undo whatever restriction
    # the bridge was configured with - the client would be deciding its own
    # privileges. Empty list (the default) = the bridge's mode always wins.
    requested = (payload.get("permissionMode") or "").strip()
    offerable = CONFIG.get("allowed_permission_modes") or []
    if requested and requested in PERMISSION_MODES and requested in offerable:
        mode = requested
    else:
        mode = (CONFIG["default_permission_mode"] or "").strip()
    if mode in PERMISSION_MODES:
        cmd += ["--permission-mode", mode]

    if CONFIG.get("dangerously_skip_permissions") and mode == "bypassPermissions":
        cmd += ["--dangerously-skip-permissions"]

    # Allow list: these run without a prompt. Anything outside it needs approval,
    # and headless has nobody to approve, so it is refused.
    allowed_tools = CONFIG.get("allowed_tools") or []
    if allowed_tools:
        cmd += ["--allowed-tools"] + list(allowed_tools)

    # Deny list: refused outright, even if something else would have allowed it.
    # These live in argv, which the agent cannot rewrite - unlike a settings
    # file sitting in the working directory.
    disallowed_tools = list(CONFIG.get("disallowed_tools") or [])
    if disallowed_tools:
        cmd += ["--disallowed-tools"] + disallowed_tools

    # Confinement is hundreds of rules - far past the 8191-character command
    # line cmd.exe allows when claude_path is a .cmd shim - so it travels in a
    # settings file instead. The file lives outside the working directory, which
    # the same rules make unreachable, so a run cannot edit its own policy.
    if CONFIG.get("confine_to_cwd"):
        cmd += ["--settings", write_policy_file(allowed_cwd(payload.get("cwd")))]

    effort = (payload.get("effort") or "").strip()
    if effort in EFFORT_LEVELS:
        cmd += ["--effort", effort]

    session_id = (payload.get("sessionId") or "").strip()
    if session_id:
        cmd += ["--resume", session_id]

    # Images can only be expressed as content blocks, which means stdin has to
    # carry a JSON message instead of raw text. Only switched on when there is
    # something to attach, so text-only runs keep the simpler path.
    if payload.get("images"):
        cmd += ["--input-format", "stream-json"]

    return cmd


class Run:
    """One Claude Code invocation, buffered so it can outlive any single client.

    Frames are an append-only sequence of (event, data) pairs - exactly the SSE
    frames a client should receive. A frame's index is its id, which is how a
    reconnecting client asks for "everything after N".

    The transcript on disk is the source of truth; `frames` is only a cache of
    it. A finished run that nobody has touched for a while has its frames
    dropped from RAM (`release_memory`) and re-read from the file on the next
    request (`frames_from`). That keeps replay working for as long as the
    transcript is kept - days, if you like - without holding every byte of tool
    output the bridge has ever streamed in memory.
    """

    def __init__(self, run_id, prompt, cwd, command, conversation_id="", images=None):
        self.id = run_id
        self.prompt = prompt
        # Held only until stdin has been written. They are megabytes each, and
        # the transcript deliberately never records them, so keeping them for
        # the life of the run would mean a finished run pinning its attachments
        # in RAM for as long as it stays reconnectable - a week, by default.
        self.images = images or []
        # Survives the list being dropped after stdin, and is all the title
        # needs. Restored from the transcript's meta line, so a run reloaded
        # after a bridge restart is still labelled.
        self.image_count = len(self.images)
        self.cwd = cwd
        self.command = command
        self.conversation_id = conversation_id
        self.frames = []
        # Total frames ever appended. Stays correct after frames are evicted,
        # so waiting/streaming logic never consults len(self.frames).
        self.count = 0
        self.in_memory = True
        self.cond = threading.Condition()
        self.done = False
        self.status = "running"
        self.proc = None
        self.started_at = time.time()
        self.finished_at = None
        self.touched_at = time.time()
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
                    # Shape only. Writing the base64 here would multiply the
                    # transcript's size by the attachments on every turn, for
                    # data the browser already holds and re-renders itself.
                    "images": [
                        {"mediaType": i["mediaType"], "bytes": (len(i["data"]) * 3) // 4}
                        for i in self.images
                    ],
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
            self._write_log({"kind": "frame", "i": self.count, "event": event, "data": data})
            self.frames.append((event, data))
            self.count += 1
            self.touched_at = time.time()
            self.cond.notify_all()

    # ----- frame access, memory-backed or disk-backed -----

    @staticmethod
    def _read_frames(path):
        """Every frame in a transcript, in order. Returns None if unreadable.

        Deliberately forgiving: a transcript is written by a long-running
        process and can be truncated or corrupted by a crash or a full disk. A
        damaged one must degrade to "replays less", never to an exception that
        takes a request - or the whole startup scan - down with it.
        """
        frames = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict) and obj.get("kind") == "frame":
                        frames.append((obj.get("event"), obj.get("data")))
        except Exception:
            return None
        return frames

    def frames_from(self, start, end=None):
        """Frames [start, end). Reloads them from disk if they were evicted."""
        with self.cond:
            if not self.in_memory:
                loaded = self._read_frames(self.path())
                if loaded is None:
                    # Transcript gone (deleted mid-flight?). Nothing to replay.
                    return []
                self.frames = loaded
                self.count = max(self.count, len(loaded))
                self.in_memory = True
            self.touched_at = time.time()
            stop = self.count if end is None else min(end, self.count)
            return self.frames[max(0, start):stop]

    def release_memory(self):
        """Drop cached frames for a finished run whose transcript is on disk."""
        with self.cond:
            if not self.done or not self.in_memory or not self.frames:
                return False
            if not os.path.exists(self.path()):
                return False  # nothing to reload from; keep them
            self.frames = []
            self.in_memory = False
            return True

    def finish(self, status=None):
        with self.cond:
            if status:
                self.status = status
            self.done = True
            self.finished_at = time.time()
            self.touched_at = self.finished_at
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
        """Index a run from its transcript file (no live process, no frames in RAM).

        Only the metadata and the frame *count* are kept; the frames themselves
        are read back on demand by `frames_from`. A transcript with no `end`
        line was in flight when the bridge stopped, so it is repaired on disk
        here - that way its interrupted state is recorded once rather than
        re-synthesised on every startup.
        """
        meta = None
        count = 0
        ended = False
        status = "done"
        finished_at = None
        # Broad except on purpose: this runs over every file in runs/ at startup,
        # and one damaged transcript must not stop the bridge from booting.
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    kind = obj.get("kind")
                    if kind == "meta":
                        meta = obj
                    elif kind == "frame":
                        count += 1
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
        # Bytes were never written to the transcript, only their shape - which
        # is all a reloaded run needs to label itself.
        run.images = []
        run.image_count = len(meta.get("images") or [])
        run.cwd = meta.get("cwd", "")
        run.command = meta.get("command", [])
        run.conversation_id = meta.get("conversationId", "")
        run.frames = []
        run.count = count
        run.in_memory = False
        run.cond = threading.Condition()
        run.proc = None
        run.started_at = meta.get("startedAt", time.time())
        run.done = True
        run._log = None

        if ended:
            run.status = status
            run.finished_at = finished_at or run.started_at
        else:
            # The bridge stopped while this run was in flight - the live process
            # is gone, so record it as interrupted but still let the client
            # replay whatever it managed to produce.
            run.status = "interrupted"
            run.finished_at = run.started_at
            run.count += run._repair(path)
        run.touched_at = time.time()
        return run

    def _repair(self, path):
        """Close off a transcript the bridge never got to finish. Returns frames added."""
        tail = [
            {
                "kind": "frame",
                "i": self.count,
                "event": "error",
                "data": {
                    "type": "error",
                    "message": "The bridge restarted while this run was in "
                    "progress, so it was interrupted before finishing.",
                },
            },
            {
                "kind": "frame",
                "i": self.count + 1,
                "event": "done",
                "data": {"type": "done", "runId": self.id, "exitCode": -1},
            },
            {"kind": "end", "status": "interrupted", "finishedAt": self.finished_at},
        ]
        try:
            with open(path, "a", encoding="utf-8") as handle:
                for obj in tail:
                    handle.write(json.dumps(obj) + "\n")
        except Exception:
            # Read-only disk, permissions, whatever: the run is still usable in
            # memory, it just gets re-marked interrupted on the next startup.
            return 0
        return 2

    def delete_file(self):
        try:
            os.remove(self.path())
        except OSError:
            pass

    def title(self):
        line = " ".join((self.prompt or "").split())
        if not line:
            # Image-only turns are legitimate, and an entry with a blank title
            # reads as a broken run in /api/runs.
            count = self.image_count
            return "(%d image%s)" % (count, "" if count == 1 else "s") if count else ""
        return line[:120]

    def summary(self):
        # Under the run's own lock: a worker may be appending frames and
        # finishing the run while /api/runs walks the table.
        with self.cond:
            return {
                "runId": self.id,
                "status": self.status,
                "done": self.done,
                "conversationId": self.conversation_id,
                "startedAt": int(self.started_at * 1000),
                "finishedAt": int(self.finished_at * 1000) if self.finished_at else None,
                "frames": self.count,
                "prompt": self.title(),
            }


def run_worker(run):
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

        # Start draining the pipes BEFORE handing over the prompt. Both pipes
        # hold ~64KB; a prompt bigger than that would otherwise block us in
        # stdin.write() while Claude blocks writing a full stdout - a deadlock
        # that only the idle timeout could break, half an hour later.
        threading.Thread(target=pump_stdout, daemon=True).start()
        threading.Thread(target=pump_stderr, daemon=True).start()

        # Hand the prompt over on stdin so long prompts and quotes survive.
        # With attachments this is a stream-json message carrying the image
        # bytes, which is why the pipes above had to be draining already: it can
        # be megabytes, far past what the pipe buffer holds.
        try:
            proc.stdin.write(stdin_payload(run.prompt, run.images))
            proc.stdin.close()
        except Exception as exc:
            run.append("error", {"type": "error", "message": "could not send prompt: %s" % exc})
        finally:
            # Sent, and never needed again - the model has them now and the
            # transcript stores only their shape.
            run.images = []

        # Back-compat: honor a legacy "run_timeout_seconds" as the idle timeout.
        idle_timeout = float(
            CONFIG.get("run_idle_timeout_seconds")
            or CONFIG.get("run_timeout_seconds")
            or 1800
        )
        hard_cap = float(CONFIG.get("run_max_seconds") or 21600)
        started = time.time()
        last_output = started
        timed_out = False

        while True:
            now = time.time()
            # Reap only on genuine silence, not on total elapsed time: a run that
            # is actively streaming resets last_output every line below.
            if now - last_output > idle_timeout:
                run.append(
                    "error",
                    {
                        "type": "error",
                        "message": "run stopped: no output for %d s (idle timeout)"
                        % int(idle_timeout),
                    },
                )
                kill_process_tree(proc)
                timed_out = True
                break
            if now - started > hard_cap:
                run.append(
                    "error",
                    {
                        "type": "error",
                        "message": "run stopped: exceeded max runtime of %d s"
                        % int(hard_cap),
                    },
                )
                kill_process_tree(proc)
                timed_out = True
                break
            try:
                # A short poll so the timeouts are enforced even while Claude is
                # silent (no output line to wake us).
                kind, line = lines.get(timeout=5)
            except queue.Empty:
                continue

            if kind == "eof":
                break

            # Any output - even a blank line - proves the run is alive.
            last_output = time.time()
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
    """Two-tier cleanup of finished runs.

    Frames leave RAM quickly (`run_memory_seconds`) but the transcript stays on
    disk for the full retention window, so replaying an old chat still works -
    it just costs a file read. Only when the transcript itself ages out does the
    run become unreachable (404).
    """
    retention = float(CONFIG.get("run_retention_seconds", 604800))
    memory_ttl = float(CONFIG.get("run_memory_seconds", 600))
    while True:
        time.sleep(60)
        now = time.time()
        with RUNS_LOCK:
            runs = list(RUNS.items())
            # A pre-emptive Stop whose POST /api/chat never arrived.
            for run_id, when in list(CANCELLED.items()):
                if when < now - 300:
                    CANCELLED.pop(run_id, None)
        for run_id, run in runs:
            if not run.done or not run.finished_at:
                continue
            if run.finished_at < now - retention:
                run.delete_file()
                with RUNS_LOCK:
                    RUNS.pop(run_id, None)
            elif run.touched_at < now - memory_ttl:
                run.release_memory()


def load_persisted_runs():
    """On startup, index runs whose transcripts are still on disk.

    This is what makes a run survive a bridge restart: the browser reconnects
    with the same runId and replays the saved result. Only metadata is read into
    memory here - the frames stay in the file until something asks for them.
    """
    if not os.path.isdir(RUNS_DIR):
        return
    retention = float(CONFIG.get("run_retention_seconds", 604800))
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
    # Applied to the connection socket. A client that opens a connection and
    # then stalls - mid-request-line, or mid-body after declaring a longer
    # Content-Length - releases its thread instead of holding it forever.
    # Streaming is unaffected: the long waits there are on the run's condition
    # variable, not on the socket, and each write is quick.
    timeout = 60

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
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        # compare_digest rejects non-ASCII str with a TypeError, so a token that
        # picked up a smart quote or an accent on the way through a chat app
        # would crash the handler and surface as "Failed to fetch" - which reads
        # as a network fault rather than the bad token it actually is. Compare
        # bytes instead, so a wrong token is always a plain 401.
        return secrets.compare_digest(
            token.encode("utf-8"), str(CONFIG["token"]).encode("utf-8")
        )

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("bad Content-Length")
        if length <= 0:
            return {}
        limit = int(CONFIG.get("max_body_bytes") or 4 * 1024 * 1024)
        if length > limit:
            raise ValueError("body too large")
        # Read in chunks so the declared length never becomes an up-front
        # allocation. A client that declares more than it sends is bounded by
        # the handler's socket timeout rather than parking the thread forever.
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return json.loads(b"".join(chunks).decode("utf-8"))

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
            # Snapshot the table, then build the summaries outside RUNS_LOCK.
            # summary() takes each run's own lock, and a worker can be holding
            # that across a disk flush - doing it under RUNS_LOCK would stall
            # every other route that touches the run table.
            with RUNS_LOCK:
                live = list(RUNS.values())
            runs = [run.summary() for run in live]
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
            offset = max(0, offset)
            # Sample `done` and `total` together, and BEFORE the frames. If the
            # run finishes in between, the client is merely told "not done yet"
            # and polls once more; the other order could report done while
            # frames were still being appended, and the client would stop early
            # on a truncated answer. When done is true, count can no longer
            # grow, so `total` is exact exactly when the client relies on it.
            with run.cond:
                done = run.done
                status = run.status
                total = run.count
            # Capped, so catching up on a run that produced a lot of tool output
            # is a series of small responses rather than one huge one that a
            # phone on a flaky tunnel would never finish downloading. The client
            # keeps asking while `next < total`.
            frames = [list(f) for f in run.frames_from(offset, offset + MAX_SNAPSHOT_FRAMES)]
            return self.send_json(
                200,
                {
                    "runId": run.id,
                    "done": done,
                    "status": status,
                    "next": offset + len(frames),
                    "total": max(total, offset + len(frames)),
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
            # Lower-cased to match start_chat, which normalises before it stores
            # the run - otherwise an upper-case hex id would abort nothing.
            run_id = (payload.get("runId") or "").strip().lower()
            with RUNS_LOCK:
                run = RUNS.get(run_id)
                if not run and RUN_ID_RE.match(run_id):
                    # Stop pressed while POST /api/chat is still in flight: the
                    # Run does not exist yet. Remember the id so start_chat
                    # refuses to launch it rather than leaving an orphan running
                    # with nobody watching.
                    CANCELLED[run_id] = time.time()
                    return self.send_json(200, {"ok": True, "runId": run_id, "pending": True})
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
        try:
            images = sanitize_images(payload.get("images"))
        except ValueError as exc:
            return self.send_json(400, {"error": str(exc)})
        # An image on its own is a complete request - "what is this?" is implied
        # by sending it - so only a message with neither is empty.
        if not prompt and not images:
            return self.send_json(400, {"error": "prompt is required"})
        # build_command reads this to decide the input format, so it has to see
        # the validated list rather than whatever the client sent.
        payload["images"] = images
        if not CLAUDE_BIN:
            return self.send_json(
                500,
                {
                    "error": "Claude Code executable not found. Set claude_path in "
                    "bridge/config.json."
                },
            )

        # The browser may name the run, so that Stop can abort it even before
        # the first frame has travelled back. Ids are hex only - they become
        # filenames - and must not collide with a run we already know about.
        run_id = (payload.get("runId") or "").strip().lower()
        if run_id:
            if not RUN_ID_RE.match(run_id):
                return self.send_json(400, {"error": "invalid runId"})
            with RUNS_LOCK:
                if run_id in RUNS:
                    return self.send_json(409, {"error": "runId already in use"})
        else:
            run_id = uuid.uuid4().hex

        if not RUN_SLOTS.acquire(blocking=False):
            return self.send_json(429, {"error": "bridge is busy, try again shortly"})

        cwd = allowed_cwd(payload.get("cwd"))
        try:
            command = build_command(payload)[1:]  # drop the binary; worker re-adds it
        except Exception as exc:
            # Most likely the confinement policy could not be written. Refuse the
            # run rather than starting one that is not fenced in.
            RUN_SLOTS.release()
            return self.send_json(
                500, {"error": "could not prepare a confined run: %s" % exc}
            )
        run = Run(
            run_id,
            prompt,
            cwd,
            command,
            conversation_id=(payload.get("conversationId") or "").strip(),
            images=images,
        )

        # Registering the run and honouring a pre-emptive Stop happen under one
        # lock, so an abort that lands in this exact window cannot slip between
        # the two and leave the run parented to nobody.
        with RUNS_LOCK:
            cancelled = CANCELLED.pop(run_id, None) is not None
            if not cancelled:
                RUNS[run_id] = run
        if cancelled:
            run.finish(status="cancelled")
            run.delete_file()
            RUN_SLOTS.release()
            return self.send_json(409, {"error": "run was cancelled before it started"})

        threading.Thread(target=run_worker, args=(run,), daemon=True).start()

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
                while index >= run.count and not run.done:
                    run.cond.wait(timeout=10)
                done = run.done

            # Outside the lock: an evicted run reads its frames back from disk.
            pending = run.frames_from(index)
            base = index
            index += len(pending)

            if pending:
                for offset_in_batch, (event, data) in enumerate(pending):
                    if not self.emit(base + offset_in_batch, event, data):
                        return  # client gone; the worker carries on without us
            elif done:
                return
            elif not self.ping():
                return

            with run.cond:
                if run.done and index >= run.count:
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
    # Python block-buffers stdout whenever it is not a terminal, so under
    # systemd / nohup / docker the startup banner - which is where the access
    # token is printed - would sit in a buffer indefinitely and `journalctl`
    # would look like the bridge never started. Line-buffer it here rather than
    # relying on PYTHONUNBUFFERED being set by whoever launches us.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

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
          % CONFIG.get("run_retention_seconds", 604800))
    print("  frames in RAM  %ss after last use, then re-read from disk"
          % CONFIG.get("run_memory_seconds", 600))
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
