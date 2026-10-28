import wave

import numpy as np
import pytest

from kokoro_mcp.audio import WavFileSink, write_wav


def read_wav(path):
    with wave.open(str(path), "rb") as handle:
        return (
            handle.getnchannels(),
            handle.getsampwidth(),
            handle.getframerate(),
            handle.getnframes(),
            handle.readframes(handle.getnframes()),
        )


def test_writes_mono_pcm16_at_model_rate(tmp_path):
    path = tmp_path / "out.wav"

    frames = write_wav(path, np.zeros(2400, dtype=np.float32))

    channels, width, rate, frame_count, _ = read_wav(path)
    assert (channels, width, rate) == (1, 2, 24000)
    assert frame_count == frames == 2400


def test_clips_samples_outside_unit_range(tmp_path):
    path = tmp_path / "limit.wav"

    write_wav(path, np.array([2.0, -2.0, 0.5], dtype=np.float32))

    _, _, _, _, raw = read_wav(path)
    pcm = np.frombuffer(raw, dtype="<i2")
    assert pcm.tolist() == [32767, -32767, round(0.5 * 32767)]


def test_single_chunk_keeps_the_requested_path(tmp_path):
    sink = WavFileSink(tmp_path / "out.wav")

    sink.write(np.zeros(240, dtype=np.float32))

    assert sink.written == [tmp_path / "out.wav"]
    assert not (tmp_path / "out-001.wav").exists()


def test_multiple_chunks_are_numbered_and_complete(tmp_path):
    sink = WavFileSink(tmp_path / "out.wav")

    for _ in range(3):
        sink.write(np.full(2400, 0.25, dtype=np.float32))

    assert [path.name for path in sink.written] == [
        "out-001.wav",
        "out-002.wav",
        "out-003.wav",
    ]
    assert not (tmp_path / "out.wav").exists()
    for path in sink.written:
        assert read_wav(path)[:4] == (1, 2, 24000, 2400)


def test_rejects_non_wav_output(tmp_path):
    with pytest.raises(ValueError, match="only .wav"):
        WavFileSink(tmp_path / "out.mp3")


def test_relative_save_path_resolves_to_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    sink = WavFileSink("out.wav")
    sink.write(np.zeros(240, dtype=np.float32))

    assert sink.path == tmp_path / "out.wav"
    assert sink.written == [tmp_path / "out.wav"]


def test_home_save_path_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    sink = WavFileSink("~/out.wav")

    assert sink.path == tmp_path / "out.wav"
