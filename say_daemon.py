#!/usr/bin/env python
"""Persistent background TTS server for the read_selection.sh hotkey.

Loads the Kokoro model and misaki's G2P once (the ~5s cost
profiled in say_onnx.py) and then just sits there listening on a Unix socket,
so hotkey presses after the first only pay for synthesis, not startup.

Not meant to be run directly -- say_client.py starts it automatically the
first time it's needed. See read_selection.sh for the hotkey wiring.

Selecting and sending (via the hotkey) one of a few bare command words is
treated specially instead of being spoken as text: "help" lists commands,
"exit"/"quit" drains the queue and then shuts down, "stop"/"clear" abort
whatever is playing and queued, "kill" terminates immediately with no
ceremony.
"""
import argparse
import os
import queue
import signal
import socket
import subprocess
import sys
import threading

import say_onnx as base

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "say-selection")
SOCKET_PATH = os.path.join(STATE_DIR, "daemon.sock")

# Selecting one of these words (alone) and sending it via the hotkey is
# treated as a command rather than text to speak.
HELP_TEXT = (
    "Available commands: help lists commands. "
    "exit or quit finishes everything queued, then shuts down. "
    "stop or clear stops what's playing and clears the queue. "
    "kill terminates immediately."
)
EXIT_TEXT = "Exiting. Goodbye."


def cleanup_and_exit():
    """Remove the socket file and terminate immediately, from any thread."""
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    os._exit(0)


def command_name(text):
    """Normalize text for command matching: trim whitespace/punctuation, lowercase."""
    return text.strip().strip(".,!?;:\"'").lower()


class Daemon:
    """FIFO queue of utterances; stop/clear/kill interrupt, everything else waits its turn."""

    def __init__(self, kokoro, g2p, voice, speed):
        self.kokoro = kokoro
        self.g2p = g2p
        self.voice = voice
        self.speed = speed
        self.lock = threading.Lock()
        self.epoch = 0  # bumped only by cancel_all(); invalidates in-flight/queued jobs
        self.next_job_id = 0
        self.current_proc = None
        self.q = queue.Queue()
        self.exit_after_job_id = None

    def enqueue(self, text, mark_exit=False):
        with self.lock:
            job_id = self.next_job_id
            self.next_job_id += 1
            epoch = self.epoch
            if mark_exit:
                self.exit_after_job_id = job_id
        self.q.put((epoch, job_id, text))

    def cancel_all(self):
        """Stop current playback and drop everything queued (stop/clear/kill)."""
        with self.lock:
            self.epoch += 1
            self.exit_after_job_id = None
            if self.current_proc is not None:
                self.current_proc.terminate()
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def _stale(self, epoch):
        with self.lock:
            return epoch != self.epoch

    def speak_loop(self):
        while True:
            epoch, job_id, text = self.q.get()
            if self._stale(epoch):
                continue
            self._speak(text, epoch, job_id)

    def _speak(self, text, epoch, job_id):
        for sentence in base.split_sentences(text):
            if self._stale(epoch):
                return
            phonemes = base.phonemize(self.g2p, sentence)
            if not phonemes:
                continue
            samples, sr = self.kokoro.create(
                phonemes, voice=self.voice, speed=self.speed, is_phonemes=True
            )
            if self._stale(epoch) or not len(samples):
                continue
            self._play(base.to_pcm(samples), sr, epoch)
        # Reached the end without being interrupted: if this exact job was the
        # "exit" announcement, it actually finished playing, so shut down.
        with self.lock:
            if self.exit_after_job_id == job_id:
                cleanup_and_exit()

    def _play(self, pcm, sr, epoch):
        proc = subprocess.Popen(
            ["aplay", "-q", "-f", "S16_LE", "-r", str(sr), "-c", "1"],
            stdin=subprocess.PIPE,
        )
        with self.lock:
            if epoch != self.epoch:
                proc.terminate()
                return
            self.current_proc = proc
        proc.stdin.write(pcm)
        proc.stdin.close()
        proc.wait()
        with self.lock:
            if self.current_proc is proc:
                self.current_proc = None


def bind_socket():
    os.makedirs(STATE_DIR, exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(SOCKET_PATH)
            probe.close()
            sys.exit("say_daemon.py is already running.")
        except OSError:
            os.remove(SOCKET_PATH)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(SOCKET_PATH)
    except OSError:
        # Lost a race with another say_client.py-spawned daemon starting at
        # the same time; the winner already owns the socket.
        sys.exit("say_daemon.py: lost startup race, exiting.")
    sock.listen(8)
    return sock


def accept_loop(sock, daemon):
    while True:
        conn, _ = sock.accept()
        with conn:
            chunks = []
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        text = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if not text:
            continue
        cmd = command_name(text)
        if cmd == "help":
            daemon.enqueue(HELP_TEXT)
        elif cmd in ("exit", "quit"):
            daemon.enqueue(EXIT_TEXT, mark_exit=True)
        elif cmd in ("stop", "clear"):
            daemon.cancel_all()
        elif cmd == "kill":
            daemon.cancel_all()
            cleanup_and_exit()
        else:
            daemon.enqueue(text)


def main():
    p = argparse.ArgumentParser(description="Persistent TTS server (see say_client.py).")
    p.add_argument("-v", "--voice", default="af_heart")
    p.add_argument("-s", "--speed", type=float, default=1.0)
    args = p.parse_args()

    sock = bind_socket()
    kokoro = base.load_kokoro()
    g2p = base.load_g2p()
    daemon = Daemon(kokoro, g2p, args.voice, args.speed)
    threading.Thread(target=daemon.speak_loop, daemon=True).start()

    def handle_term(signum, frame):
        sock.close()
        cleanup_and_exit()

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)

    accept_loop(sock, daemon)


if __name__ == "__main__":
    main()
