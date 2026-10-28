"""End-to-end tests against the real Kokoro-82M model.

Excluded from the default run; execute with ``uv run pytest -m integration``.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from kokoro_mcp.engine import KokoroEngine


@pytest.mark.integration
def test_real_synthesis_produces_speech_audio():
    engine = KokoroEngine()

    chunks = list(
        engine.stream(
            "Kokoro is an open-weight text to speech model that runs locally on this machine."
        )
    )

    assert chunks
    samples = np.concatenate([chunk.samples for chunk in chunks])
    assert samples.dtype == np.float32
    assert all(chunk.samples.ndim == 1 for chunk in chunks)
    assert all(chunk.sample_rate == 24000 for chunk in chunks)
    assert len(samples) > 24000  # more than one second
    assert np.abs(samples).max() > 0.01  # not silence


@pytest.mark.integration
def test_cli_saves_playable_wav(tmp_path):
    output = tmp_path / "cli.wav"

    env = {**os.environ, "KOKORO_NO_DAEMON": "1"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "kokoro_mcp.cli",
            "Cli integration check.",
            "--save",
            str(output),
            "--quiet",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    with wave.open(str(output), "rb") as handle:
        assert (handle.getnchannels(), handle.getframerate()) == (1, 24000)
        assert handle.getnframes() > 0


@pytest.mark.integration
def test_daemon_reuses_the_warm_model():
    # /tmp keeps the Unix socket under the 104-byte macOS limit.
    root = Path(tempfile.mkdtemp(prefix="kokoro-daemon-", dir="/tmp"))
    env = {
        **os.environ,
        "KOKORO_DAEMON_DIR": str(root),
        "KOKORO_DAEMON_IDLE": "5",
        "KOKORO_DEVICE": "cpu",
    }

    def speak(name):
        output = root / name
        start = time.monotonic()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kokoro_mcp.cli",
                "The worker keeps the model warm between calls.",
                "--save",
                str(output),
                "--quiet",
            ],
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
        elapsed = time.monotonic() - start
        assert result.returncode == 0, result.stderr
        with wave.open(str(output), "rb") as handle:
            assert handle.getnframes() > 0
        return elapsed

    try:
        cold = speak("cold.wav")
        assert (root / "daemon.sock").exists()
        warm = speak("warm.wav")
        assert warm < cold / 2, f"cold={cold:.2f}s warm={warm:.2f}s"
        assert warm < 2.0, f"warm request took {warm:.2f}s"

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and (root / "daemon.sock").exists():
            time.sleep(0.1)
        assert not (root / "daemon.sock").exists(), "idle daemon did not clean up"
    finally:
        shutil.rmtree(root, ignore_errors=True)
