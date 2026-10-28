"""End-to-end tests against the real Kokoro-82M model.

Excluded from the default run; execute with ``uv run pytest -m integration``.
"""

import subprocess
import sys
import wave

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
    )

    assert result.returncode == 0, result.stderr
    with wave.open(str(output), "rb") as handle:
        assert (handle.getnchannels(), handle.getframerate()) == (1, 24000)
        assert handle.getnframes() > 0
