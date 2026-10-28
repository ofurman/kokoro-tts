# Stage 02: Save WAV files

Goal: `--save` turns synthesized chunks into standard 24 kHz mono PCM16 WAV files.
Box: 1h · Review: no · Depends: 1

## Done when

- A single-chunk run writes exactly one 24 kHz mono WAV — check: `uv run kokoro-tts "Kokoro runs locally." --save /tmp/kokoro-one.wav` then `ffprobe -v error -show_entries stream=sample_rate,channels -of csv=p=0 /tmp/kokoro-one.wav` — today: fails, no CLI.
- A three-sentence run writes three files numbered 001 through 003 — check: `uv run kokoro-tts "One. Two. Three." --save /tmp/kokoro-many.wav` then `ls /tmp/kokoro-many-00*.wav` — today: fails, no CLI.

## Facts

- CLI chunking uses `split_sentences` then `KPipeline` with `split_pattern=None` (decision D-05).
- WAV writing uses stdlib `wave` with `setnchannels(1)`, `setsampwidth(2)`, `setframerate(24000)`; float samples clip to [-1, 1] before int16 conversion (source: stage 1 engine output).
- Naming rule: one chunk keeps the exact `--save` path; two or more use `stem-001.wav`, `stem-002.wav`, and so on.
- Non-`.wav` suffixes are rejected in the CLI before synthesis.

## Not in this stage

- Playback, MP3/FLAC, resampling, voice listing, docs.
