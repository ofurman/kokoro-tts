"""Kokoro-82M inference.

The heavy imports (torch, kokoro) are deferred so ``--help`` and ``--list-voices``
stay fast and the audio sinks can be tested without a model install.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

import numpy as np

SAMPLE_RATE = 24_000
DEFAULT_VOICE = "af_heart"
DEFAULT_REPO_ID = "hexgrad/Kokoro-82M"

# Language codes understood by KPipeline (a/b use misaki, the rest espeak-ng).
LANG_CODES: dict[str, str] = {
    "a": "American English",
    "b": "British English",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Brazilian Portuguese",
    "z": "Mandarin Chinese",
}

# Sentence boundary: end punctuation, optional closing quotes/brackets, then
# whitespace; or one or more newlines. Splitting happens after punctuation so
# the punctuation stays with the sentence it closes.
_SENTENCE_BOUNDARY = re.compile(
    r"(?:(?<=[.!?…])|(?<=[.!?…][\)\]\"'”’]))\s+|\n+"
)


def split_sentences(text: str) -> list[str]:
    """Split text into sentence-sized synthesis chunks.

    Empty pieces are dropped. Whitespace is not preserved between chunks; the
    spoken content is unchanged.
    """
    parts = (part.strip() for part in _SENTENCE_BOUNDARY.split(text.strip()))
    return [part for part in parts if part]


@dataclass(frozen=True)
class AudioChunk:
    """One synthesized chunk of speech."""

    index: int
    text: str
    phonemes: str
    samples: np.ndarray
    sample_rate: int = SAMPLE_RATE

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


def _to_mono_float32(audio) -> np.ndarray:
    """Convert a Kokoro torch tensor to a contiguous mono float32 array."""
    array = audio.detach().cpu().numpy()
    if array.ndim == 2:
        # Kokoro emits mono; tolerate either (1, n) or (n, 1).
        if array.shape[0] == 1:
            array = array[0]
        elif array.shape[1] == 1:
            array = array[:, 0]
        else:
            raise ValueError(f"expected mono audio, got shape {array.shape}")
    elif array.ndim != 1:
        raise ValueError(f"expected mono audio, got shape {array.shape}")
    return np.ascontiguousarray(array, dtype=np.float32)


class KokoroEngine:
    """Lazily loaded Kokoro-82M pipeline that streams audio per sentence."""

    def __init__(
        self,
        lang_code: str = "a",
        repo_id: str = DEFAULT_REPO_ID,
        device: str | None = None,
    ) -> None:
        if lang_code not in LANG_CODES:
            raise ValueError(
                f"unknown language {lang_code!r}; choose from {', '.join(LANG_CODES)}"
            )
        self.lang_code = lang_code
        self.repo_id = repo_id
        self.device = device
        self._pipeline = None

    @property
    def pipeline(self):
        if self._pipeline is None:
            from kokoro import KPipeline

            self._pipeline = KPipeline(
                lang_code=self.lang_code,
                repo_id=self.repo_id,
                device=self.device,
            )
        return self._pipeline

    def stream(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
    ) -> Iterator[AudioChunk]:
        """Yield audio chunks in order as they are synthesized.

        Text is split into sentences first so the first chunk can play before
        the rest is generated; the pipeline itself still chunks on phoneme
        length.
        """
        if speed <= 0:
            raise ValueError("speed must be greater than 0")

        sentences = split_sentences(text)
        if not sentences:
            raise ValueError("no text to synthesize")

        index = 0
        for sentence in sentences:
            for result in self.pipeline(
                sentence,
                voice=voice,
                speed=speed,
                split_pattern=None,
            ):
                if result.audio is None:
                    continue
                samples = _to_mono_float32(result.audio)
                if samples.size == 0:
                    continue
                yield AudioChunk(
                    index=index,
                    text=result.graphemes or sentence,
                    phonemes=result.phonemes,
                    samples=samples,
                )
                index += 1


def list_voices(repo_id: str = DEFAULT_REPO_ID) -> list[str]:
    """Return the voice ids published in the model repo (network on first call)."""
    from huggingface_hub import list_repo_files

    prefix, suffix = "voices/", ".pt"
    return sorted(
        name[len(prefix) : -len(suffix)]
        for name in list_repo_files(repo_id)
        if name.startswith(prefix) and name.endswith(suffix)
    )
