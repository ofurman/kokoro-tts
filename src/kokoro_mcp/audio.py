"""Audio sinks: PCM16 WAV files and live playback through CoreAudio/PortAudio."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from .engine import SAMPLE_RATE


def _pcm16(samples: np.ndarray) -> np.ndarray:
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim != 1:
        raise ValueError(f"expected mono samples, got shape {array.shape}")
    clipped = np.clip(array, -1.0, 1.0)
    return np.round(clipped * 32767.0).astype("<i2")


def write_wav(
    path: str | Path,
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
) -> int:
    """Write mono float samples as a PCM16 WAV; return the frame count."""
    path = Path(path)
    frames = _pcm16(samples)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames.tobytes())
    return len(frames)


class WavFileSink:
    """Writes each chunk to disk as it arrives.

    A single chunk keeps the exact path. From the second chunk on, files are
    numbered ``stem-001.wav``, ``stem-002.wav`` ...; the first file is renamed
    when the second chunk proves the run is multi-chunk.
    """

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        if path.suffix.lower() != ".wav":
            raise ValueError(
                f"unsupported output format {path.suffix!r}; only .wav is supported"
            )
        self.path = path
        self.written: list[Path] = []

    def _numbered(self, index: int) -> Path:
        return self.path.with_name(f"{self.path.stem}-{index:03d}{self.path.suffix}")

    def write(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
        index = len(self.written) + 1
        if index == 1:
            target = self.path
        else:
            if index == 2:
                first = self._numbered(1)
                self.written[0].replace(first)
                self.written[0] = first
            target = self._numbered(index)
        write_wav(target, samples, sample_rate)
        self.written.append(target)
        return target


class _SoundDeviceOutput:
    """Blocking PortAudio stream to the default output device (CoreAudio)."""

    def __init__(self, sample_rate: int) -> None:
        import sounddevice as sd

        info = sd.query_devices(kind="output")
        self.device_name = str(info["name"])
        self._stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
        )

    def start(self) -> None:
        self._stream.start()

    def play(self, samples: np.ndarray) -> None:
        clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
        self._stream.write(clipped)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()

    def abort(self) -> None:
        self._stream.abort()
        self._stream.close()


class _FfplayOutput:
    """Fallback output for machines without PortAudio: raw PCM into ffplay."""

    def __init__(self, sample_rate: int) -> None:
        self.device_name = "ffplay default device"
        executable = shutil.which("ffplay")
        if executable is None:
            raise RuntimeError(
                "no audio output available: install sounddevice or ffmpeg, "
                "or use --save PATH to write WAV files"
            )
        self._process: subprocess.Popen | None = subprocess.Popen(
            [
                executable,
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-f",
                "f32le",
                "-ar",
                str(sample_rate),
                "-ch_layout",
                "mono",
                "-i",
                "pipe:0",
            ],
            stdin=subprocess.PIPE,
        )

    def start(self) -> None:
        pass

    def play(self, samples: np.ndarray) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise RuntimeError("ffplay is not running")
        payload = np.ascontiguousarray(
            np.clip(samples, -1.0, 1.0), dtype="<f4"
        ).tobytes()
        try:
            process.stdin.write(payload)
            process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise RuntimeError("ffplay stopped before playback finished") from exc

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        status = process.wait()
        if status != 0:
            raise RuntimeError(f"ffplay exited with status {status}")

    def abort(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        process.kill()
        process.wait()


class Speaker:
    """Streams float32 mono PCM to the default speakers as chunks arrive.

    Uses sounddevice/PortAudio (CoreAudio on macOS), which needs no system
    PortAudio install: the wheel bundles the library. Machines without it fall
    back to ffplay.
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._output: _SoundDeviceOutput | _FfplayOutput | None = None

    def start(self) -> None:
        if self._output is not None:
            return
        try:
            self._output = _SoundDeviceOutput(self.sample_rate)
        except ImportError:
            self._output = _FfplayOutput(self.sample_rate)
        except Exception as exc:
            raise RuntimeError(f"cannot open audio output: {exc}") from exc
        self._output.start()

    def play(self, samples: np.ndarray) -> None:
        if self._output is None:
            self.start()
        assert self._output is not None
        self._output.play(samples)

    @property
    def device_name(self) -> str:
        return "not started" if self._output is None else self._output.device_name

    def close(self) -> None:
        output = self._output
        self._output = None
        if output is not None:
            output.close()

    def abort(self) -> None:
        output = self._output
        self._output = None
        if output is not None:
            output.abort()

    def __enter__(self) -> "Speaker":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            self.abort()
        else:
            self.close()
        return False
