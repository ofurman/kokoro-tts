# Decisions

## D-01: Official `kokoro` PyTorch package as the inference path
2026-10-28, planning. Use `kokoro==0.9.4` + `KPipeline`, the reference implementation with misaki
G2P and the 54 released voices. Rejected `kokoro-onnx` (espeak-only G2P, model files hosted
outside HF) and hand-written ONNX (duplicated preprocessing). Tradeoff: a heavier torch install;
accepted because quality and voice parity matter more than install size here.

## D-02: Python 3.12 via uv
2026-10-28, planning. `kokoro` declares `<3.13`; the machine default is 3.14.8. Pin
`requires-python = ">=3.10,<3.13"` and let uv select its 3.12.9 build. Rejected forcing 3.14
(unsupported) and a conda env (not installed).

## D-03: Playback through ffplay over stdin
2026-10-28, planning. One `ffplay -f f32le -ar 24000 -ch_layout mono -i pipe:0` process per run,
fed float32 chunks as they are generated. No PortAudio on this machine, so `sounddevice` would
need a Homebrew dependency; `afplay` cannot read a pipe. ffplay is already installed and its
file playback exits 0. ffplay 9 removed `-ac`, use `-ch_layout`.

## D-04: WAV PCM16 output via stdlib `wave`
2026-10-28, planning. 24 kHz mono PCM16 is universally readable and needs no encoder. Rejected
`soundfile` (native lib dependency) and MP3 (extra ffmpeg invocation) for iteration 1.

## D-05: Sentence-level chunking with `split_pattern=None`
2026-10-28, planning. The CLI splits text into sentences and feeds each to `KPipeline` with
`split_pattern=None` so the first audio plays before the whole paragraph is synthesized. The
pipeline still handles phoneme-length overflow internally. Tradeoff: prosody across sentence
boundaries is slightly less joined than one long generation; accepted for streaming latency.

## D-06: Voices listed from the HF repo, not hardcoded
2026-10-28, planning. `--list-voices` filters `voices/*.pt` from the `hexgrad/Kokoro-82M` repo
listing. A hardcoded 54-name list would go stale if voices are added.

## D-07: One `--save` path, numbered files for multiple chunks
2026-10-28, planning. A single chunk keeps the exact path; multiple chunks become
`stem-001.wav`, `stem-002.wav`. This streams to disk without buffering the whole text and keeps
chunk boundaries inspectable. Rejected concatenating into one file (needs buffering or reopen
tricks) and a separate `--save-dir` flag (extra surface).

## D-10: Distributable with `uv tool install .`
2026-10-28, execution. The package builds to a wheel with hatchling and exposes `kokoro-tts`,
so `uv tool install .` installs it into an isolated env with the executable in `~/.local/bin`.
Verified running from `/tmp` with playback. Rejected a shell wrapper around `uv run` (needs the
repo checkout and loses isolation).

## D-09: Playback through sounddevice/PortAudio, ffplay only as fallback
2026-10-28, execution. ffplay consumed the PCM in real time (10.68 s of audio took 11.04 s) but
nothing was audible on this machine, so SDL's device choice is not trusted. Switch the default
output to `sounddevice.OutputStream` at 24 kHz mono, which reports the default CoreAudio device
("MacBook Pro Speakers" here) before opening it; keep the ffplay path only when PortAudio is
missing. The CLI logs the device with each chunk so silence can be diagnosed.

## D-08: Console script `kokoro-tts`, package `kokoro_mcp`
2026-10-28, planning. The package keeps the repo identity and stays importable for the planned
MCP server; the console script names the actual behavior instead of the transport.
