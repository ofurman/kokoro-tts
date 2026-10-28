# Backlog

- B-01: MCP server exposing Kokoro synthesis to agent clients (from: planning).
- B-02: ONNX Runtime backend for lower CPU latency, benchmarked against the torch path (from: planning).
- B-03: MP3/FLAC output via ffmpeg for smaller files (from: planning).
- B-04: MPS acceleration with `PYTORCH_ENABLE_MPS_FALLBACK=1`, measured on this M4 Pro (from: planning). DONE in D-11: worker defaults to MPS, 0.10 s versus 0.36 s CPU per 2.9 s sentence.
- B-05: Persistent model process for repeated CLI calls, avoiding per-run load time (from: planning). DONE in D-11: `server.py` worker, 0.17-0.21 s warm requests.
- B-06: Voice blending (`af_heart,af_bella`) and per-voice defaults in config (from: planning).
