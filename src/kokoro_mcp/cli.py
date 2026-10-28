"""``kokoro-tts`` command line: speak text or save WAV files."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .audio import Speaker, WavFileSink
from .engine import DEFAULT_VOICE, LANG_CODES, KokoroEngine, list_voices


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kokoro-tts",
        description="Speak text locally with Kokoro-82M. Plays on the speakers by default.",
        epilog=(
            "The first run downloads the 327 MB model and the requested voice to the "
            "HuggingFace cache. Audio is 24 kHz mono."
        ),
    )
    parser.add_argument(
        "text",
        nargs="*",
        metavar="TEXT",
        help="text to speak; use '-' to read stdin",
    )
    parser.add_argument(
        "--save",
        metavar="PATH",
        help="write WAV files instead of playing; multiple chunks become PATH-001.wav ...",
    )
    parser.add_argument(
        "--voice",
        default=DEFAULT_VOICE,
        help=f"voice id, e.g. af_heart or am_michael (default: {DEFAULT_VOICE})",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="speech speed, greater than 0 (default: 1.0)",
    )
    parser.add_argument(
        "--lang",
        default="a",
        choices=tuple(LANG_CODES),
        help="language code: "
        + ", ".join(f"{code}={name}" for code, name in LANG_CODES.items())
        + " (default: a)",
    )
    parser.add_argument(
        "--text-file",
        type=Path,
        metavar="PATH",
        help="read text from a UTF-8 file instead of arguments",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="print voice ids published in the model repo and exit",
    )
    parser.add_argument(
        "--no-daemon",
        action="store_true",
        help="synthesize in this process instead of the warm background worker",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress progress messages on stderr",
    )
    return parser


def _read_text(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    if args.text_file is not None and args.text:
        parser.error("pass text positionally or with --text-file, not both")
    if args.text_file is not None:
        try:
            return args.text_file.read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"cannot read {args.text_file}: {exc}")
    if args.text == ["-"]:
        return sys.stdin.read()
    if "-" in args.text:
        parser.error("'-' must be the only text argument")
    if args.text:
        return " ".join(args.text)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    parser.error("no text; pass TEXT, --text-file PATH or pipe text on stdin")
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_voices:
        try:
            voices = list_voices()
        except Exception as exc:  # network or hub error
            print(f"kokoro-tts: cannot list voices: {exc}", file=sys.stderr)
            return 1
        try:
            for voice in voices:
                print(voice)
        except BrokenPipeError:
            # e.g. `kokoro-tts --list-voices | head`; silence the shutdown flush.
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            return 0
        return 0

    text = _read_text(args, parser)
    if not text.strip():
        parser.error("text is empty")
    if args.speed <= 0:
        parser.error("--speed must be greater than 0")

    save_path = Path(args.save).expanduser() if args.save else None
    if save_path is not None and save_path.suffix.lower() != ".wav":
        parser.error("--save only supports .wav files")

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    def local_stream():
        return KokoroEngine(
            lang_code=args.lang, device=os.environ.get("KOKORO_DEVICE") or None
        ).stream(text, voice=args.voice, speed=args.speed)

    def open_stream():
        if args.no_daemon or os.environ.get("KOKORO_NO_DAEMON") not in (None, "", "0"):
            return local_stream()
        from .server import DaemonClient, DaemonUnavailable, ensure_daemon

        try:
            return DaemonClient(ensure_daemon()).stream(
                text, voice=args.voice, speed=args.speed, lang=args.lang
            )
        except (DaemonUnavailable, OSError) as exc:
            log(f"kokoro-tts: daemon unavailable ({exc}); using a one-shot process")
            return local_stream()

    chunks = None
    try:
        chunks = open_stream()
        if save_path is not None:
            sink = WavFileSink(save_path)
            for chunk in chunks:
                sink.write(chunk.samples, chunk.sample_rate)
                log(f"[{chunk.index + 1}] {chunk.duration:5.2f}s synthesized")
            if not sink.written:
                print("kokoro-tts: model produced no audio for this text", file=sys.stderr)
                return 1
            plural = "s" if len(sink.written) != 1 else ""
            log(f"wrote {len(sink.written)} file{plural}: " + ", ".join(str(p) for p in sink.written))
        else:
            played = 0
            with Speaker() as speaker:
                for chunk in chunks:
                    speaker.play(chunk.samples)
                    played += 1
                    log(
                        f"[{chunk.index + 1}] {chunk.duration:5.2f}s  played "
                        f"on {speaker.device_name}"
                    )
            if played == 0:
                print("kokoro-tts: model produced no audio for this text", file=sys.stderr)
                return 1
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        print(f"kokoro-tts: {exc}", file=sys.stderr)
        return 1
    finally:
        # Closing the client generator closes the socket, which tells the
        # worker to stop synthesizing the rest of an interrupted utterance.
        if chunks is not None:
            chunks.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
