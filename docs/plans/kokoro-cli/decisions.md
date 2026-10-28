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

## D-11: Warm daemon with MPS, streaming PCM over a Unix socket
2026-10-28, speed pass. 87 % of a `kokoro-tts` run was per-process cost: 2.0 s of
`torch`/`kokoro` imports, 1.3-1.6 s of checkpoint load, and 0.1-0.3 s of MPS kernel
compilation. A detached `python -m kokoro_mcp.server` (started by the CLI on demand, idle exit
after 30 min) keeps one pipeline per language and streams JSON-framed float32 chunks to clients.
Measured on the M4 Pro for a 2.9 s sentence: 4.7 s one-shot, 5.2 s cold daemon start, 0.17-0.21 s
warm. MPS synthesizes in 0.10 s versus 0.36 s on CPU once warm, so the worker defaults to MPS and
pays its one-time compilation in `_engine()` before answering; `KOKORO_DEVICE=cpu` opts out.
Rejected in-process caching (the CLI exits), an HTTP stack (no dependency or port allocation
needed for a local tool), and `torch.multiprocessing` workers (model state and lifetime are
simpler in one threaded process). The socket is `0600` under `~/.cache/kokoro-tts`; playback and
WAV writing stay in the client so `Speaker` and `WavFileSink` are unchanged. A client that
disconnects (aborted hook utterance, Ctrl-C) closes the socket, which stops the server's
per-chunk `sendall` and the synthesis generator behind it.
