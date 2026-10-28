# Plan: kokoro-cli

Date: 2026-10-28 · Branch: main (no commits yet) · Source: owner message 2026-10-28

Status lives in state.json. Executed by goal-execution-loop.

## Goal

A working local Kokoro-82M text-to-speech stack in this repo: a Python package around hexgrad's
`KPipeline`, and a `kokoro-tts` console command that synthesizes on this M4 Pro. By default it
streams speech to the machine's speakers as sentences are generated; with `--save` it writes WAV
files instead. This is the inference base the repo name (`kokoro-mcp`) later wraps as an MCP
server.

## Definition of Done

1. `kokoro_mcp` imports from the project venv — check: `uv run python -c "import kokoro_mcp"` — today: fails, no pyproject.toml.
2. Real 82M-model synthesis writes a 24 kHz mono WAV — check: `uv run kokoro-tts "Kokoro runs locally." --save /tmp/kokoro-dod.wav` then `ffprobe -v error -show_entries stream=sample_rate,channels -of csv=p=0 /tmp/kokoro-dod.wav` — today: fails, no CLI.
3. Saved speech is non-silent — check: `ffmpeg -hide_banner -i /tmp/kokoro-dod.wav -af volumedetect -f null -` reports mean_volume above -40 dB — today: fails, no file.
4. Multi-sentence text saves one WAV per pipeline chunk — check: `uv run kokoro-tts "One. Two. Three." --save /tmp/kokoro-multi.wav` then `ls /tmp/kokoro-multi-00*.wav` — today: fails, no CLI.
5. Speed 0.5 audio duration is at least 1.5x the speed 2.0 duration — check: `ffprobe -v error -show_entries format=duration -of csv=p=0 /tmp/kokoro-speed-slow.wav` then the same probe on `/tmp/kokoro-speed-fast.wav` — today: fails, no files.
6. Default no-flag run streams to speakers with exit status 0 — check: `uv run kokoro-tts "Testing local playback."` — today: fails, no CLI.
7. Default run leaves the worktree unchanged — check: `git status --porcelain` after a default run — today: fails, no CLI.
8. `--list-voices` prints `af_heart` — check: `uv run kokoro-tts --list-voices | grep -x af_heart` — today: fails, no CLI.
9. Text piped on stdin produces a playable WAV — check: `printf 'Hello from stdin.' | uv run kokoro-tts - --save /tmp/kokoro-stdin.wav` then `ffprobe -v error -show_entries format=duration -of csv=p=0 /tmp/kokoro-stdin.wav` — today: fails, no CLI.
10. Test suite passes — check: `uv run pytest -q` — today: fails, no tests.

## Constraints

- Allowed: create and edit files in this repo; `uv sync`, `uv run`, `uv lock` (creates `.venv`,
  `uv.lock`); download model weights into `~/.cache/huggingface` (327 MB model, 54 voice packs);
  write artifacts under `/tmp`; spawn `ffplay` for playback checks; run pytest.
- Protected: the machine's Homebrew install and system audio volume; the HF cache outside this
  repo is used read-only once populated.
- Hard stops: no git commit or push, no system package installs, no network beyond PyPI and
  HuggingFace, no spending money.

## Stages

| id | title | box (h) | review | depends |
|----|-------|---------|--------|---------|
| 1 | [Environment and first real audio](stages/01-environment-and-first-real-audio.md) | 1.5 | yes | - |
| 2 | [Save WAV files](stages/02-save-wav-files.md) | 1 | no | 1 |
| 3 | [Stream to speakers](stages/03-stream-to-speakers.md) | 1 | no | 1 |
| 4 | [CLI surface tests and docs](stages/04-cli-surface-tests-and-docs.md) | 1.5 | no | 2,3 |

## Iteration

Iteration 1 delivers end-to-end speech: model download, real synthesis, WAV saving, speaker
streaming, a tested CLI surface, and README instructions. Deferred on purpose: the MCP server
wrapper, ONNX or GPU backends, MP3 output (see backlog.md).
