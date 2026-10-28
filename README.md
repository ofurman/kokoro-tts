# kokoro-mcp

Local [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) text-to-speech with a streaming CLI.
Default behavior: speak on the machine's speakers while the rest of the text is still generating.
`--save`: write 24 kHz mono WAV files instead.

## Requirements

- macOS or Linux, Python 3.10-3.12 (uv installs 3.12 automatically)
- [uv](https://docs.astral.sh/uv/)
- Playback uses PortAudio through `sounddevice` (the macOS wheel bundles it); `ffplay` is
  only a fallback when PortAudio is unavailable.

## Install

```bash
uv sync
```

The first synthesis downloads `kokoro-v1_0.pth` (327 MB) plus the selected voice into
`~/.cache/huggingface`.

### Install as a uv tool (no `uv run`)

```bash
uv tool install .
kokoro-tts "Kokoro runs locally."
```

`uv` puts `kokoro-tts` in `~/.local/bin` (already on PATH here). Reinstall after source
changes with `uv tool install --force .`; remove it with `uv tool uninstall kokoro-mcp`.
The tool env is isolated from `.venv`, so it works from any directory and shares the
HuggingFace model cache, but not the repo checkout.

## Usage

```bash
# Play on the speakers (default)
uv run kokoro-tts "Kokoro runs locally on this machine."

# Save to one WAV (relative, absolute and ~ paths all work; parents are created)
uv run kokoro-tts "Kokoro runs locally." --save out.wav
uv run kokoro-tts "Kokoro runs locally." --save /tmp/kokoro/out.wav
uv run kokoro-tts "Kokoro runs locally." --save ~/Desktop/kokoro.wav

# Several sentences: one numbered file per chunk
uv run kokoro-tts "First sentence. Second sentence." --save out.wav
# -> out-001.wav, out-002.wav

# Voice, speed, language
uv run kokoro-tts "Hello there." --voice am_michael --speed 1.15
uv run kokoro-tts "Bonjour tout le monde." --lang f

# Text from a file or stdin
uv run kokoro-tts --text-file script.txt
printf 'Piped text.' | uv run kokoro-tts - --save piped.wav

# Discover voices
uv run kokoro-tts --list-voices
```

`--lang` codes: `a` American English, `b` British English, `e` Spanish, `f` French, `h` Hindi,
`i` Italian, `j` Japanese, `p` Brazilian Portuguese, `z` Mandarin Chinese. Japanese and Mandarin
need the extra misaki extras (`misaki[ja]`, `misaki[zh]`).

Progress goes to stderr; `--quiet` silences it. Each played chunk logs the output device,
e.g. `played on MacBook Pro Speakers`. If you hear nothing, check that this device is the
intended one in System Settings > Sound and that the output volume is up.

## Tests

```bash
uv run pytest              # fast unit tests
uv run pytest -m integration   # real model synthesis end to end
```

## Layout

- `src/kokoro_mcp/engine.py` - lazy `KPipeline` wrapper, sentence chunking, voice listing
- `src/kokoro_mcp/audio.py` - PCM16 WAV writer, ffplay speaker stream
- `src/kokoro_mcp/cli.py` - `kokoro-tts` entry point
- `docs/plans/kokoro-cli/` - the plan this iteration was built against

Model weights are Apache-2.0, from `hexgrad/Kokoro-82M`.
