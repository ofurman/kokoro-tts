"""Persistent Kokoro worker and its Unix-socket client.

Loading torch and the 327 MB checkpoint costs about 3.5 s, which is paid on
every ``kokoro-tts`` invocation. This module keeps one warm process alive and
streams synthesized float32 audio to short-lived clients over a Unix socket.
Playback and WAV writing stay in the client, so the sinks are unchanged.

The daemon is started on demand by :func:`ensure_daemon` and exits after
``KOKORO_DAEMON_IDLE`` seconds without connections (default 1800, ``0`` keeps it
alive indefinitely). ``KOKORO_DAEMON_DIR`` moves the socket, lock and log.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from .engine import DEFAULT_VOICE, SAMPLE_RATE, AudioChunk, KokoroEngine

PROTOCOL_VERSION = 1
DEFAULT_IDLE_SECONDS = 1800.0
START_TIMEOUT_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_REQUEST_BYTES = 1 << 20

Synthesize = Callable[[str, str, float, str], Iterator[AudioChunk]]


class DaemonUnavailable(RuntimeError):
    """The worker could not be reached, so the caller should synthesize locally."""


def daemon_paths() -> tuple[Path, Path, Path]:
    """Return the socket, lock and log paths for the current user.

    Paths are absolute: the worker is spawned with a private cwd, so a relative
    ``KOKORO_DAEMON_DIR`` must not be re-resolved against a different directory.
    """
    root = Path(os.environ.get("KOKORO_DAEMON_DIR") or Path.home() / ".cache" / "kokoro-tts")
    root = root.expanduser().resolve()
    return root / "daemon.sock", root / "daemon.lock", root / "daemon.log"


def _connect(socket_path: Path, timeout: float = 2.0) -> socket.socket | None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(socket_path))
    except OSError:
        sock.close()
        return None
    return sock


def _is_ready(socket_path: Path) -> bool:
    sock = _connect(socket_path)
    if sock is None:
        return False
    sock.close()
    return True


def _log_tail(path: Path, limit: int = 800) -> str:
    try:
        text = path.read_bytes()[-limit:].decode("utf-8", "replace").strip()
    except OSError:
        return ""
    return f": {text.splitlines()[-1]}" if text else ""


def ensure_daemon(timeout: float = START_TIMEOUT_SECONDS) -> Path:
    """Start the worker if needed and return its socket path.

    A lock file serializes concurrent first calls so only one process spawns
    the daemon; the others connect to the socket it creates.
    """
    socket_path, lock_path, log_path = daemon_paths()
    if _is_ready(socket_path):
        return socket_path

    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if _is_ready(socket_path):
            return socket_path

        with open(log_path, "ab") as log_file:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "kokoro_mcp.server",
                    "--socket",
                    str(socket_path),
                ],
                # ``-m`` puts the caller's cwd on sys.path; a private cwd stops
                # a same-named package in a user's checkout from being executed.
                cwd=str(socket_path.parent),
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
                close_fds=True,
            )

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _is_ready(socket_path):
                return socket_path
            status = process.poll()
            if status is not None:
                raise DaemonUnavailable(
                    f"kokoro-tts daemon exited during startup (status {status})"
                    + _log_tail(log_path)
                )
            time.sleep(0.05)

    raise DaemonUnavailable(
        f"kokoro-tts daemon did not start within {timeout:.0f}s" + _log_tail(log_path)
    )


def _encode_json(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"


def _read_json(reader) -> dict | None:
    line = reader.readline(MAX_REQUEST_BYTES)
    if not line:
        return None
    if len(line) >= MAX_REQUEST_BYTES and not line.endswith(b"\n"):
        raise ValueError("daemon message is too large")
    payload = json.loads(line)
    if not isinstance(payload, dict):
        raise ValueError("daemon message is not a JSON object")
    return payload


def handle_connection(conn: socket.socket, synthesize: Synthesize) -> None:
    """Serve one request: a JSON line in, then JSON frames plus raw float32 PCM."""
    with conn, conn.makefile("rb") as reader:
        try:
            # Bound the request read so a client that connects and stalls cannot
            # keep a worker thread (and the idle timer) alive forever.
            conn.settimeout(REQUEST_TIMEOUT_SECONDS)
            request = _read_json(reader)
            if request is None:
                return
            text = str(request["text"])
            voice = str(request.get("voice", DEFAULT_VOICE))
            speed = float(request.get("speed", 1.0))
            lang = str(request.get("lang", "a"))
            conn.settimeout(None)  # sendall applies backpressure, never timing out

            conn.sendall(
                _encode_json(
                    {"protocol": PROTOCOL_VERSION, "sample_rate": SAMPLE_RATE}
                )
            )
            chunks = synthesize(text, voice, speed, lang)
            try:
                for index, chunk in enumerate(chunks):
                    conn.sendall(
                        _encode_json(
                            {
                                "index": index,
                                "text": chunk.text,
                                "phonemes": chunk.phonemes,
                                "n": int(chunk.samples.size),
                                "sample_rate": chunk.sample_rate,
                            }
                        )
                    )
                    conn.sendall(
                        np.ascontiguousarray(chunk.samples, dtype="<f4").tobytes()
                    )
            finally:
                close = getattr(chunks, "close", None)
                if close is not None:
                    close()
            conn.sendall(_encode_json({"done": True}))
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            # The client went away (an aborted utterance, a killed CLI).
            return
        except Exception as exc:  # report model/argument errors to the client
            try:
                conn.sendall(_encode_json({"error": str(exc)}))
            except OSError:
                pass


class KokoroServer:
    """Warm engine cache plus one-request-per-connection socket loop."""

    def __init__(
        self,
        socket_path: Path,
        idle_timeout: float = DEFAULT_IDLE_SECONDS,
        device: str | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.idle_timeout = idle_timeout
        self.device = device or _default_device()
        self._engines: dict[str, KokoroEngine] = {}
        self._lock = threading.Lock()
        self._active = 0
        self._active_lock = threading.Lock()
        self._last_activity = time.monotonic()

    def _engine(self, lang: str) -> KokoroEngine:
        engine = self._engines.get(lang)
        if engine is None:
            engine = KokoroEngine(lang_code=lang, device=self.device)
            if lang == "a":
                # The first call compiles MPS kernels and loads the default
                # voice; doing it now keeps later requests at steady-state
                # speed. Other languages skip it: DEFAULT_VOICE is English.
                list(engine.stream("Ready.", voice=DEFAULT_VOICE))
            self._engines[lang] = engine
        return engine

    def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        lang: str = "a",
    ) -> Iterator[AudioChunk]:
        with self._lock:
            chunks = self._engine(lang).stream(text, voice=voice, speed=speed)
        # Step the generator under the lock so two clients never share the
        # model, but release it while the client consumes or plays the chunk.
        try:
            while True:
                with self._lock:
                    try:
                        chunk = next(chunks)
                    except StopIteration:
                        return
                yield chunk
        finally:
            chunks.close()

    def serve_forever(self) -> None:
        if self.socket_path.exists():
            probe = _connect(self.socket_path, timeout=0.5)
            if probe is not None:
                probe.close()
                return  # another daemon owns this socket
            self.socket_path.unlink()

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        listener.listen(16)
        listener.settimeout(1.0)
        try:
            while True:
                if self.idle_timeout and self._idle():
                    return
                try:
                    conn, _ = listener.accept()
                except socket.timeout:
                    continue
                self._touch()
                with self._active_lock:
                    self._active += 1
                threading.Thread(
                    target=self._run_connection, args=(conn,), daemon=True
                ).start()
        finally:
            listener.close()
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass

    def _run_connection(self, conn: socket.socket) -> None:
        try:
            handle_connection(conn, self.synthesize)
        finally:
            self._touch()
            with self._active_lock:
                self._active -= 1

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    def _idle(self) -> bool:
        with self._active_lock:
            if self._active:
                return False
        return time.monotonic() - self._last_activity > self.idle_timeout


def _default_device() -> str:
    """Prefer MPS when the worker stays warm; the first call pays compilation."""
    explicit = os.environ.get("KOKORO_DEVICE")
    if explicit:
        return explicit
    try:
        import torch
    except ImportError:
        return "cpu"
    return "mps" if torch.backends.mps.is_available() else "cpu"


class DaemonClient:
    """Streams chunks from the worker over its Unix socket."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = Path(socket_path)

    def stream(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        lang: str = "a",
    ) -> Iterator[AudioChunk]:
        # Everything up to the first frame happens here, so connection and
        # argument errors are raised by this call instead of by ``next()``;
        # the CLI uses that to fall back to in-process synthesis.
        payload = _encode_json(
            {"text": text, "voice": voice, "speed": speed, "lang": lang}
        )
        if len(payload) >= MAX_REQUEST_BYTES:
            raise DaemonUnavailable(
                f"text needs {len(payload)} bytes but the worker accepts fewer "
                f"than {MAX_REQUEST_BYTES}; using a one-shot process"
            )
        sock = _connect(self.socket_path, timeout=10.0)
        if sock is None:
            raise DaemonUnavailable(f"cannot connect to {self.socket_path}")
        try:
            sock.sendall(payload)
            reader = sock.makefile("rb")
            header = _read_json(reader)
        except socket.timeout as exc:
            sock.close()
            raise DaemonUnavailable(
                "daemon did not answer the handshake within 10 s"
            ) from exc
        except BaseException:
            sock.close()
            raise
        if header is None:
            sock.close()
            raise DaemonUnavailable("daemon closed the connection before replying")
        if "error" in header:
            sock.close()
            raise RuntimeError(str(header["error"]))
        if header.get("protocol") != PROTOCOL_VERSION:
            sock.close()
            raise DaemonUnavailable(
                f"daemon protocol {header.get('protocol')!r} is not "
                f"{PROTOCOL_VERSION}; restart the worker"
            )
        # The 10 s deadline is for the handshake only. A cold first chunk can
        # take longer (checkpoint download), and playback backpressure is not
        # a failure, so streamed reads must not inherit it.
        sock.settimeout(None)
        return self._read_chunks(sock, reader, int(header.get("sample_rate", SAMPLE_RATE)))

    def _read_chunks(
        self, sock: socket.socket, reader, sample_rate: int
    ) -> Iterator[AudioChunk]:
        with sock, reader:
            while True:
                frame = _read_json(reader)
                if frame is None:
                    raise RuntimeError("daemon closed the connection mid-stream")
                if frame.get("done"):
                    return
                if "error" in frame:
                    raise RuntimeError(str(frame["error"]))
                count = int(frame["n"])
                payload = reader.read(count * 4)
                if payload is None or len(payload) != count * 4:
                    raise RuntimeError("daemon closed the connection mid-frame")
                yield AudioChunk(
                    index=int(frame["index"]),
                    text=str(frame.get("text", "")),
                    phonemes=str(frame.get("phonemes", "")),
                    samples=np.frombuffer(payload, dtype="<f4").copy(),
                    sample_rate=int(frame.get("sample_rate", sample_rate)),
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kokoro-tts-daemon",
        description="Warm Kokoro-82M worker for kokoro-tts (started automatically).",
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=daemon_paths()[0],
        help="Unix socket to listen on (default: %(default)s)",
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=float(os.environ.get("KOKORO_DAEMON_IDLE", DEFAULT_IDLE_SECONDS)),
        help="exit after this many idle seconds; 0 disables (default: %(default)s)",
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("KOKORO_DEVICE"),
        help="torch device: cpu or mps (default: mps when available)",
    )
    args = parser.parse_args(argv)

    device = args.device or _default_device()
    if device == "mps":
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    def stop(signum, frame):  # noqa: ARG001 - signal handler signature
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    server = KokoroServer(args.socket, idle_timeout=args.idle_timeout, device=device)
    print(
        f"kokoro-tts daemon: device={device} socket={args.socket} "
        f"idle_timeout={args.idle_timeout:g}s",
        flush=True,
    )
    try:
        server.serve_forever()
    except SystemExit:
        pass
    except Exception:
        # The log file captures tracebacks from the detached process.
        import traceback

        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
