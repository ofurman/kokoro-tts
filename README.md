# kokoro-mcp

Local [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) text-to-speech with a streaming CLI.
Default behavior: speak on the machine's speakers while the rest of the text is still generating.
`--save`: write 24 kHz mono WAV files instead.

Repeated calls reuse a warm background worker, so only the first invocation pays the model
load. See [Latency](#latency).

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

# Skip the background worker (one-shot process, useful for debugging)
uv run kokoro-tts "Kokoro runs locally." --no-daemon
```

The first invocation starts the worker as a detached
`python -m kokoro_mcp.server` (about 5 s including the MPS warm-up); later invocations
stream from it in roughly 0.2 s. The worker exits after 30 minutes without requests or on
`SIGTERM`. It lives in `~/.cache/kokoro-tts/` (`daemon.sock`, `daemon.lock`, `daemon.log`)
and holds about 1.3 GB resident while warm. If MPS misbehaves, set `KOKORO_DEVICE=cpu`; the
worker then trades roughly 0.25 s more synthesis per sentence for a cold start that is
0.5 s shorter.
After upgrading, restart a running worker (`pkill -f kokoro_mcp.server`) so it runs the new
code and protocol.

`--lang` codes: `a` American English, `b` British English, `e` Spanish, `f` French, `h` Hindi,
`i` Italian, `j` Japanese, `p` Brazilian Portuguese, `z` Mandarin Chinese. Japanese and Mandarin
need the extra misaki extras (`misaki[ja]`, `misaki[zh]`).

Progress goes to stderr; `--quiet` silences it. Each played chunk logs the output device,
e.g. `played on MacBook Pro Speakers`. If you hear nothing, check that this device is the
intended one in System Settings > Sound and that the output volume is up.

## Latency

Measured on this M4 Pro, warm HF cache, `--save` of a 2.9 s sentence:

| Path | Wall time |
|---|---|
| one-shot process (`--no-daemon`) | 4.7 s |
| first call that starts the worker (includes MPS warm-up) | 5.2 s |
| every later call through the warm worker | 0.17–0.21 s |

The remaining 0.1 s is synthesis: the worker keeps the model on the MPS backend (0.10 s for
that sentence versus 0.36 s on CPU) and streams float32 PCM as each chunk is produced.
Playback and WAV writing stay in the short-lived CLI, so the sinks are unchanged. The
daemon is a foreground `python -m kokoro_mcp.server` when started by hand; the CLI starts it
detached with `start_new_session=True`.

| Variable | Default | Purpose |
|---|---|---|
| `KOKORO_DAEMON_DIR` | `~/.cache/kokoro-tts` | Socket, lock and log directory |
| `KOKORO_DAEMON_IDLE` | `1800` | Exit after this many idle seconds; `0` keeps it alive |
| `KOKORO_DEVICE` | `mps` when available | Worker torch device (`cpu` or `mps`) |
| `KOKORO_NO_DAEMON` | unset | Set to `1` to force in-process synthesis |

## Speak omp responses

`integrations/omp/spoken-recap.js` is an [omp](https://omp.sh) hook that speaks
the first sentence of every completed main-session response.
It ignores subagent sessions, intermediate tool-loop settles, and aborted or
failed replies.

```bash
mkdir -p ~/.omp/agent/hooks/post
cp integrations/omp/spoken-recap.js ~/.omp/agent/hooks/post/
```

Restart omp. The hook resolves `kokoro-tts` from `~/.local/bin`, then `PATH`.
Environment overrides:

| Variable | Default | Purpose |
|---|---|---|
| `KOKORO_RECAP` | `1` | Set to `0` to disable speech without removing the hook |
| `KOKORO_RECAP_VOICE` | `af_heart` | Any voice id from `kokoro-tts --list-voices` |
| `KOKORO_RECAP_SPEED` | `1.0` | Speaking rate |
| `KOKORO_TTS_BIN` | auto | Explicit path to the `kokoro-tts` executable |
| `KOKORO_RECAP_HEADLESS` | unset | Set to `1` to also speak in `--print` and RPC runs |

The sentence is extracted locally from the final assistant message, so the hook
adds no model calls. Speech is capped at 200 characters, and a new response
interrupts the previous utterance. Because the hook calls the CLI, it gets the
warm worker for free: the first response after boot waits for the worker, later
responses start speaking in about 0.2 s.

## Tests

```bash
uv run pytest              # fast unit tests
uv run pytest -m integration   # real model synthesis end to end
```

## Layout

- `src/kokoro_mcp/engine.py` - lazy `KPipeline` wrapper, sentence chunking, voice listing
- `src/kokoro_mcp/audio.py` - PCM16 WAV writer, PortAudio/ffplay speaker stream
- `src/kokoro_mcp/server.py` - warm daemon, Unix-socket protocol, on-demand client
- `src/kokoro_mcp/cli.py` - `kokoro-tts` entry point
- `docs/plans/kokoro-cli/` - the plan this iteration was built against

Model weights are Apache-2.0, from `hexgrad/Kokoro-82M`.
