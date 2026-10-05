#!/usr/bin/env python
"""Send text to say_daemon.py, starting it first if it isn't running.

Used by read_selection.sh. If the daemon is already up, this is a near-instant
socket send. If not, it starts the daemon in the background, announces that
via plain espeak-ng (instant -- no model to load) while the daemon spends its
~5s loading the model and misaki's G2P, then sends the real text once ready.
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "say-selection")
SOCKET_PATH = os.path.join(STATE_DIR, "daemon.sock")
ANNOUNCEMENT = "Starting the background text to speech process."


def send(text):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(SOCKET_PATH)
        sock.sendall(text.encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)


def start_daemon():
    subprocess.Popen(
        [os.path.join(HERE, ".venv", "bin", "python"), os.path.join(HERE, "say_daemon.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def wait_for_daemon(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            send("")  # zero-length probe: opens+closes a connection, speaks nothing
            return True
        except (ConnectionRefusedError, FileNotFoundError):
            time.sleep(0.2)
    return False


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    text = text.strip()
    if not text:
        return

    try:
        send(text)
        return
    except (ConnectionRefusedError, FileNotFoundError):
        pass

    start_daemon()
    subprocess.run(["espeak-ng", ANNOUNCEMENT], check=False)
    if not wait_for_daemon():
        sys.exit("say_daemon.py did not start in time")
    send(text)


if __name__ == "__main__":
    main()
