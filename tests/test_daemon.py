"""Socket protocol tests; no model is loaded."""

import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from kokoro_mcp.engine import AudioChunk
from kokoro_mcp.server import (
    MAX_REQUEST_BYTES,
    DaemonClient,
    DaemonUnavailable,
    ensure_daemon,
    handle_connection,
)


def _chunk(index, value=0.25, size=4):
    return AudioChunk(
        index=index,
        text=f"chunk {index}",
        phonemes=f"fon {index}",
        samples=np.full(size, value, dtype=np.float32),
    )


class StubServer:
    """Accepts connections one at a time and serves a synthesized stub."""

    def __init__(self, path, synthesize):
        self.path = path
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        self.listener.listen(4)
        self.listener.settimeout(0.05)
        self.calls = []
        self._synthesize = synthesize
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            handle_connection(conn, self._synthesize)

    def close(self):
        self._stop.set()
        self.listener.close()
        self.thread.join(timeout=2)


@pytest.fixture
def serve():
    # macOS caps AF_UNIX paths at 104 bytes; pytest's tmp_path is too long.
    root = Path(tempfile.mkdtemp(prefix="kd-", dir="/tmp"))
    servers = []

    def start(synthesize):
        server = StubServer(root / f"d{len(servers)}.sock", synthesize)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()
    shutil.rmtree(root, ignore_errors=True)


def test_streams_chunks_in_order(serve):
    seen = []

    def synthesize(text, voice, speed, lang):
        seen.append((text, voice, speed, lang))
        yield _chunk(0, 0.25)
        yield _chunk(1, -0.5, size=6)

    server = serve(synthesize)
    chunks = list(DaemonClient(server.path).stream("hello", "am_michael", 1.25, "b"))

    assert seen == [("hello", "am_michael", 1.25, "b")]
    assert [chunk.index for chunk in chunks] == [0, 1]
    assert all(chunk.sample_rate == 24000 for chunk in chunks)
    assert chunks[0].text == "chunk 0"
    assert chunks[0].samples.dtype == np.float32
    np.testing.assert_allclose(chunks[0].samples, np.full(4, 0.25))
    np.testing.assert_allclose(chunks[1].samples, np.full(6, -0.5))


def test_synthesis_error_is_raised_by_client(serve):
    def synthesize(text, voice, speed, lang):
        raise RuntimeError("unknown voice")
        yield  # pragma: no cover - makes this a generator

    server = serve(synthesize)

    with pytest.raises(RuntimeError, match="unknown voice"):
        list(DaemonClient(server.path).stream("hello"))


def test_client_disconnect_stops_the_synthesis_generator(serve):
    stopped = threading.Event()

    def synthesize(text, voice, speed, lang):
        try:
            for index in range(1000):
                yield _chunk(index, size=24000)
        finally:
            stopped.set()

    server = serve(synthesize)
    stream = DaemonClient(server.path).stream("long text")
    next(stream)
    stream.close()

    assert stopped.wait(timeout=5), "server kept synthesizing after the client left"


def test_empty_probe_connection_is_ignored(serve):
    server = serve(lambda *args: iter(()))
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.connect(str(server.path))
    probe.close()

    # A follow-up request still works, so the probe did not wedge the server.
    assert list(DaemonClient(server.path).stream("hi")) == []


def test_missing_daemon_is_reported(tmp_path):
    with pytest.raises(DaemonUnavailable):
        DaemonClient(tmp_path / "absent.sock").stream("hi")


def test_oversized_request_falls_back_without_connecting(tmp_path):
    client = DaemonClient(tmp_path / "absent.sock")

    with pytest.raises(DaemonUnavailable, match="fewer than"):
        client.stream("x" * MAX_REQUEST_BYTES)


def test_ensure_daemon_uses_a_private_cwd_and_notices_a_dead_child(
    tmp_path, monkeypatch
):
    import kokoro_mcp.server as server

    root = tmp_path / "daemon"
    monkeypatch.setenv("KOKORO_DAEMON_DIR", str(root))
    spawned = {}

    class DeadProcess:
        returncode = 3

        def poll(self):
            return 3

    def fake_popen(args, **kwargs):
        spawned["args"] = args
        spawned["kwargs"] = kwargs
        return DeadProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    start = time.monotonic()
    with pytest.raises(DaemonUnavailable, match="exited during startup"):
        ensure_daemon(timeout=5)
    elapsed = time.monotonic() - start

    socket_path = server.daemon_paths()[0]
    assert elapsed < 2, "ensure_daemon waited for the full timeout after the child died"
    assert spawned["kwargs"]["cwd"] == str(socket_path.parent)
    assert spawned["args"][-2:] == ["--socket", str(socket_path)]


def test_cli_falls_back_when_daemon_setup_raises_oserror(monkeypatch, tmp_path):
    import kokoro_mcp.cli as cli
    import kokoro_mcp.server as server

    def broken_daemon():
        raise PermissionError("daemon directory is not writable")

    class FakeEngine:
        def __init__(self, **kwargs):
            pass

        def stream(self, *args, **kwargs):
            yield AudioChunk(
                index=0,
                text="hello",
                phonemes="hello",
                samples=np.zeros(240, dtype=np.float32),
            )

    monkeypatch.setattr(server, "ensure_daemon", broken_daemon)
    monkeypatch.setattr(cli, "KokoroEngine", FakeEngine)
    output = tmp_path / "fallback.wav"

    assert cli.main(["hello", "--save", str(output), "--quiet"]) == 0
    assert output.exists()


def test_empty_device_env_is_treated_as_unset(monkeypatch, tmp_path):
    import kokoro_mcp.cli as cli

    captured = {}

    class FakeEngine:
        def __init__(self, lang_code=None, device=None):
            captured["device"] = device

        def stream(self, *args, **kwargs):
            yield AudioChunk(
                index=0,
                text="hello",
                phonemes="hello",
                samples=np.zeros(240, dtype=np.float32),
            )

    monkeypatch.setenv("KOKORO_DEVICE", "")
    monkeypatch.setattr(cli, "KokoroEngine", FakeEngine)

    assert (
        cli.main(
            ["hello", "--save", str(tmp_path / "empty.wav"), "--quiet", "--no-daemon"]
        )
        == 0
    )
    assert captured["device"] is None
