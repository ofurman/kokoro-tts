# Stage 01: Environment and first real audio

Goal: A uv-managed Python 3.12 env where the real Kokoro-82M model synthesizes a sentence into 24 kHz audio.
Box: 1.5h · Review: yes · Depends: none

## Done when

- Real synthesis returns non-empty float32 audio at 24 kHz — check: `uv run pytest -q -k real_synthesis` — today: fails, no package.
- The one-sentence WAV is longer than one second — check: `ffprobe -v error -show_entries format=duration -of csv=p=0 /tmp/kokoro-stage1.wav` — today: fails, no file.

## Facts

- PyPI `kokoro` 0.9.4 requires Python `<3.13`; uv has CPython 3.12.9 installed (source: PyPI metadata, `uv python list`).
- Default interpreter is 3.14.8, so the project must pin 3.12 (source: `python3 --version`).
- `KPipeline(lang_code, repo_id=..., device='cpu')` yields `Result` objects with `audio` a 24 kHz torch tensor (source: hexgrad/kokoro `pipeline.py`, `Result.audio`).
- `KPipeline` splits input with `split_pattern`; passing `split_pattern=None` makes one segment per call (source: `KPipeline.__call__`).
- Model cache: `hexgrad/Kokoro-82M` holds `kokoro-v1_0.pth` 327 MB plus 54 `voices/*.pt` (source: HF API listing).
- The first run downloads the model; later runs hit the HF cache (source: `hf_hub_download` in pipeline.py).
- `misaki[en]` (pulled by kokoro) bundles `espeakng-loader`, so the English OOD fallback works without Homebrew espeak-ng (source: misaki extras, espeak.py).

## Not in this stage

- Playback, `--save`, voice listing, stdin handling, docs.
