# Stage 04: CLI surface tests and docs

Goal: The CLI surface is complete, covered by fast tests plus one real-model integration test, and documented so a new user can run it verbatim.
Box: 1.5h · Review: no · Depends: 2, 3

## Done when

- Fast test suite passes — check: `uv run pytest -q` — today: fails, no tests.
- `--help` lists every documented flag — check: `uv run kokoro-tts --help` — today: fails, no CLI.

## Facts

- Flags to expose: `--save`, `--voice`, `--speed`, `--lang`, `--text-file`, `--list-voices`, `--quiet`, `-` for stdin (source: decisions D-05 to D-08).
- Text sources: positional words joined by spaces, `--text-file`, or stdin via `-`; none given and stdin is a TTY prints help with exit 2.
- Default voice `af_heart`, default speed 1.0, default lang `a` (American English); `Lang codes: a b e f h i j p z` from `KPipeline.LANG_CODES`.
- `--list-voices` reads `voices/*.pt` from the HF repo listing, so the list cannot go stale (decision D-06).
- Integration tests are marked `integration` and excluded from the default run; README shows `uv run pytest -m integration`.

## Not in this stage

- MCP server, ONNX backend, MPS tuning, MP3 output.
