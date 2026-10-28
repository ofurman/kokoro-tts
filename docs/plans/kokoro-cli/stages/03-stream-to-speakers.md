# Stage 03: Stream to speakers

Goal: With no flags, the CLI plays each synthesized chunk through the machine speakers while later text is still generating.
Box: 1h · Review: no · Depends: 1

## Done when

- A no-flag run exits 0 after playing the whole text — check: `uv run kokoro-tts "Testing local playback."` — today: fails, no CLI.
- A no-flag run creates no file in the worktree — check: `git status --porcelain` — today: fails, no CLI.

## Facts

- No PortAudio on this machine, so `sounddevice` is unavailable (source: `/opt/homebrew/lib/libportaudio*` absent).
- `ffplay` 9.0.2 exists at `/opt/homebrew/bin/ffplay`; it plays a WAV file with exit 0 (source: smoke run).
- `ffplay -nodisp -autoexit -loglevel error -f f32le -ar 24000 -ch_layout mono -i pipe:0` accepts raw PCM on stdin and exits 0 at EOF (source: smoke run). ffplay 9 dropped `-ac`.
- Playback happens through one long-lived ffplay process, lazily started on the first chunk, so chunks stream as they are generated (decision D-03).

## Not in this stage

- `afplay` fallback, volume control, device selection, save mode changes.
