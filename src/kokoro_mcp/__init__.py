"""Local Kokoro-82M text-to-speech.

Inference lives in :mod:`kokoro_mcp.engine`, audio sinks in :mod:`kokoro_mcp.audio`,
and the command line in :mod:`kokoro_mcp.cli`.
"""

from .engine import DEFAULT_VOICE, SAMPLE_RATE, AudioChunk, KokoroEngine, split_sentences

__all__ = [
    "DEFAULT_VOICE",
    "SAMPLE_RATE",
    "AudioChunk",
    "KokoroEngine",
    "split_sentences",
]
