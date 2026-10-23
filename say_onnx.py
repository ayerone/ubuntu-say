#!/usr/bin/env python3
"""Read text aloud with Kokoro TTS via ONNX Runtime on CPU.

The model and voices files come from config.toml (see config.example.toml).

Usage:
  ./say_onnx.py "text"        ./say_onnx.py            (paste, Ctrl-D)
  ./say_onnx.py -l            loop mode: Enter sends each line to speech as you
                               type/paste; a blank line inserts a ~1s pause;
                               Ctrl-D ends input, Ctrl-C quits.
  ./say_onnx.py -v af_heart -s 1.1 --lead 2 "text"

Text -> phonemes goes through misaki's G2P, not kokoro_onnx's own phonemizer,
so numbers/dates read the human-readable way ("1,234" -> "one thousand two
hundred thirty-four") instead of literally ("one, two hundred thirty-four").
"""
import argparse
import os
import queue
import re
import subprocess
import sys
import threading
import time

import numpy as np
import onnxruntime as rt
from kokoro_onnx import Kokoro
from misaki import en, espeak

from say_config import load_config

HERE = os.path.dirname(os.path.abspath(__file__))
_config = load_config()
MODEL = os.path.join(HERE, _config["model"])      # absolute paths pass through join unchanged
VOICES = os.path.join(HERE, _config["voices"])
THREADS = max(1, (os.cpu_count() or 2) - 1)


def to_pcm(audio):
    """float [-1,1] -> 16-bit little-endian PCM bytes."""
    audio = np.asarray(audio, dtype=np.float32)
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


def play_segment(pcm, sr):
    """Play one complete PCM segment via its own aplay process (no underruns)."""
    subprocess.run(
        ["aplay", "-q", "-f", "S16_LE", "-r", str(sr), "-c", "1"],
        input=pcm,
        check=False,
    )


MAX_SEGMENT_CHARS = 250    # sentences longer than this are cut into pieces
MAX_TOKEN_CHARS = 30       # space-free strings longer than this are announced, not read


def cut_long(sentence):
    """Cut an over-long sentence at the last comma, else the last space, before the limit."""
    pieces = []
    while len(sentence) > MAX_SEGMENT_CHARS:
        window = sentence[:MAX_SEGMENT_CHARS + 1]
        cut = window.rfind(", ") + 1
        if cut <= 0:
            cut = window.rfind(" ")
        pieces.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    pieces.append(sentence)
    return pieces


def split_sentences(text):
    """Break a block of text into sentences.

    A blank line (two or more consecutive newlines) ends a segment just as
    terminal punctuation does, so unpunctuated lists and headings are not
    run together. Sentences over MAX_SEGMENT_CHARS are cut by cut_long, and
    space-free strings over MAX_TOKEN_CHARS are replaced by a spoken note.
    """
    sentences = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        block = " ".join(block.split())
        block = re.sub(
            rf"\S{{{MAX_TOKEN_CHARS + 1},}}",
            lambda m: f"dropping a continuous string of {len(m.group())} characters long",
            block,
        )
        marked = re.sub(r"([.!?]+[\"')\]]*)\s+", r"\1\n", block)
        for p in marked.split("\n"):
            if p.strip():
                sentences.extend(cut_long(p))
    return sentences


def load_kokoro():
    """Build a thread-tuned CPU InferenceSession and wrap it with kokoro-onnx."""
    for path in (MODEL, VOICES):
        if not os.path.exists(path):
            sys.exit(f"Missing model file: {path}\n"
                     "Download kokoro-v1.0.onnx and voices-v1.0.bin from "
                     "https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0 "
                     "or point model/voices in config.toml at other files.")
    opts = rt.SessionOptions()
    opts.intra_op_num_threads = THREADS          # leave one core free
    opts.graph_optimization_level = rt.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = rt.InferenceSession(MODEL, opts, providers=["CPUExecutionProvider"])
    return Kokoro.from_session(session, VOICES)


def load_g2p():
    """Build misaki's English G2P.

    Its lexicon does number/date normalization (num2words) that kokoro_onnx's
    own phonemizer skips entirely, so "1,234" reads as "one thousand two
    hundred thirty-four" instead of "one, two hundred thirty-four".
    """
    fallback = espeak.EspeakFallback(british=False)
    return en.G2P(trf=False, british=False, fallback=fallback, unk="")


def phonemize(g2p, text):
    ps, _ = g2p(text)
    return ps


_DONE = object()
_PAUSE = object()          # marks a blank-line paragraph break in loop mode
PARAGRAPH_PAUSE_S = 1.0    # length of the pause inserted for a blank line


def speak(kokoro, g2p, text, voice, speed, lead=1):
    """Producer/consumer playback: synthesize sentences ahead, play in order."""
    sentences = split_sentences(text)
    if not sentences:
        return
    q = queue.Queue(maxsize=64)

    def produce():
        try:
            for sentence in sentences:
                phonemes = phonemize(g2p, sentence)
                if not phonemes:
                    continue
                samples, sr = kokoro.create(phonemes, voice=voice, speed=speed, is_phonemes=True)
                if len(samples):
                    q.put((to_pcm(samples), sr))
        finally:
            q.put(_DONE)

    worker = threading.Thread(target=produce, daemon=True)
    worker.start()

    buffered = []
    done = False
    while len(buffered) < lead:
        item = q.get()
        if item is _DONE:
            done = True
            break
        buffered.append(item)

    try:
        for pcm, sr in buffered:
            play_segment(pcm, sr)
        while not done:
            item = q.get()
            if item is _DONE:
                done = True
            else:
                play_segment(*item)
    finally:
        worker.join(timeout=1)


def read_lines(line_q):
    """Continuously read lines from stdin, one per Enter press.

    Each non-blank line is queued as-is. A run of blank lines (after some real
    text has been seen) collapses to a single _PAUSE marker, so a pasted
    paragraph break reads as one pause instead of stacking several. EOF (Ctrl-D)
    pushes _DONE so the synthesis stage knows to wind down once it has drained
    whatever is already queued.
    """
    seen_text = False
    pending_pause = False
    try:
        while True:
            try:
                line = input()
            except EOFError:
                print("\n[Ctrl-D: finishing what's queued, then exiting]", file=sys.stderr)
                return
            if line.strip() == "":
                if seen_text:
                    pending_pause = True
                continue
            if pending_pause:
                line_q.put(_PAUSE)
                pending_pause = False
            line_q.put(line)
            seen_text = True
    finally:
        line_q.put(_DONE)


def synthesize_stream(kokoro, g2p, line_q, audio_q, voice, speed):
    """Pull lines off line_q as they arrive and synthesize onto audio_q.

    Runs for the lifetime of loop mode rather than being restarted per
    paragraph, so synthesis of the next line overlaps playback of the current
    one with no gap between them.
    """
    try:
        while True:
            item = line_q.get()
            if item is _DONE:
                return
            if item is _PAUSE:
                audio_q.put(_PAUSE)
                continue
            for sentence in split_sentences(item):
                phonemes = phonemize(g2p, sentence)
                if not phonemes:
                    continue
                samples, sr = kokoro.create(phonemes, voice=voice, speed=speed, is_phonemes=True)
                if len(samples):
                    audio_q.put((to_pcm(samples), sr))
    finally:
        audio_q.put(_DONE)


def loop_mode(kokoro, g2p, voice, speed, lead):
    """Interactive loop: Enter sends each line to speech as you type/paste."""
    line_q = queue.Queue()
    audio_q = queue.Queue(maxsize=64)

    threading.Thread(target=read_lines, args=(line_q,), daemon=True).start()
    threading.Thread(
        target=synthesize_stream, args=(kokoro, g2p, line_q, audio_q, voice, speed), daemon=True
    ).start()

    print(
        "Loop mode: type/paste text, Enter sends each line. Blank line = pause."
        "  (Ctrl-D ends input, Ctrl-C quits.)",
        file=sys.stderr,
    )

    def play(item):
        if item is _PAUSE:
            time.sleep(PARAGRAPH_PAUSE_S)
        else:
            play_segment(*item)

    buffered = []
    done = False
    try:
        while len(buffered) < lead:
            item = audio_q.get()
            if item is _DONE:
                done = True
                break
            buffered.append(item)
        for item in buffered:
            play(item)
        while not done:
            item = audio_q.get()
            if item is _DONE:
                done = True
            else:
                play(item)
    except KeyboardInterrupt:
        pass
    print("\nBye.", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="Read text aloud with Kokoro ONNX int8.")
    p.add_argument("text", nargs="*", help="text to read (optional; else read stdin)")
    p.add_argument("-v", "--voice", default="af_heart", help="voice name")
    p.add_argument("-s", "--speed", type=float, default=1.0, help="speech speed")
    p.add_argument("-l", "--loop", action="store_true",
                   help="keep model loaded; speak each line as soon as you press Enter")
    p.add_argument("--lead", type=int, default=1,
                   help="segments to pre-synthesize before playback (default 1)")
    args = p.parse_args()

    kokoro = load_kokoro()
    g2p = load_g2p()

    if args.loop:
        loop_mode(kokoro, g2p, args.voice, args.speed, args.lead)
        return

    if args.text:
        text = " ".join(args.text).strip()
    else:
        if sys.stdin.isatty():
            print("Paste/type text, then press Ctrl-D:", file=sys.stderr)
        text = sys.stdin.read().strip()
    if not text:
        sys.exit("No text given.")

    speak(kokoro, g2p, text, args.voice, args.speed, args.lead)


if __name__ == "__main__":
    main()
