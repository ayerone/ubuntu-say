# ubuntu-say

Local text-to-speech for Ubuntu. Hear highlighted text read aloud, launched by a keyboard shortcut. Real-time performance on CPU.

Check out the dual to this project (speech-to-text) [ubuntu-hear](https://github.com/ayerone/ubuntu-hear).

## Details

Uses [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) through ONNX Runtime.

The first Hotkey (keyboard shortcut) press after login starts a background daemon (python process) that loads the model. Subsequent presses get a warm start (daemon already running). Pressing the shortcut while it is still talking queues the new text.

## Tested on

Ubuntu 24.04, GNOME on Wayland, Mini PC (Intel N150). See `ENVIRONMENT.md` for exact versions. The selection is read with `wl-paste`, so an X11 session needs `xclip -o -selection primary` substituted in `read_selection.sh` (untested).

## Install

1. System packages:

   ```bash
   sudo apt install alsa-utils wl-clipboard espeak-ng
   ```

2. Python environment (3.12 tested). The scripts run `.venv/bin/python` from the checkout:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

   The daemon looks for `.venv/bin/python` in the project folder, so keep the venv there.

   `requirements.txt` lists the top-level packages and explains why `misaki[en]` is avoided (it pulls in PyTorch, which this project avoids for the large download). `requirements-lock.txt` is the exact tested set.

3. Model files, from the [kokoro-onnx release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0):

   ```bash
   curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
   curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
   ```

4. Bind a global keyboard shortcut (GNOME Settings, Keyboard, Custom Shortcuts) to the absolute path of `read_selection.sh` in this checkout. I chose ctrl-alt-c (reminiscent of ctrl-c).

## Usage

Select text anywhere and press the shortcut. Selecting just the text of any of these command words and pressing the shortcut runs it instead of speaking it:

| Word | Effect |
| --- | --- |
| `help` | List the commands. |
| `stop`, `clear` | Abort what is playing and queued. |
| `exit`, `quit` | Finish the queue, then shut the daemon down. |
| `kill` | Terminate the daemon immediately. |

The daemon restarts on the next press. To speak from a terminal, run `.venv/bin/python say_onnx.py "text"`, or `.venv/bin/python say_onnx.py -l` for loop mode (each Enter speaks a line). The `-v` and `-s` flags pick the voice and speed.

## Configuration

Copy `config.example.toml` to `config.toml` and edit it. `config.toml` is gitignored, and every setting is optional.

| Setting | Default | Meaning |
| --- | --- | --- |
| `model` | `kokoro-v1.0.onnx` | Kokoro ONNX model file, relative to this project or an absolute path. |
| `voices` | `voices-v1.0.bin` | Voices file that matches the model. |

The daemon reads the file at startup, so kill it (select `kill` and press the shortcut) after editing.

## Quantized model

I quantized my own build of Kokoro (mixed precision, with most of the model in int8 and the last few convolutions left in fp32) to run faster on my wimpy CPU. You can use any TTS model you want by pointing `model` in `config.toml` at your own file.

## How it works

- `read_selection.sh` reads the primary selection with `wl-paste` and runs `say_client.py`, which sends the text over a Unix socket (`~/.cache/say-selection/daemon.sock`) and starts the daemon first if needed. While the daemon loads, espeak-ng announces the startup.
- `say_daemon.py` keeps the model and misaki's G2P loaded and speaks queued text in order.
- `say_onnx.py` does the synthesis. Text goes to phonemes through misaki, not kokoro-onnx's own phonemizer, so numbers and dates read naturally ("1,234" becomes "one thousand two hundred thirty-four"). Audio plays through `aplay`.

## Pro-tip: Claude Code integration

I added a `Stop` hook (response finished) to my claude code that summarizes the response and then sends it to the TTS daemon. It's nice to get a spoken gist of an answer once a turn completes.

## Limitations

- GNOME on Wayland only, as tested.
- The first press after login takes a few seconds for the model to load.
