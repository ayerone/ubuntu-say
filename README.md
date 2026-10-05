# ubuntu-say

Hotkey text-to-speech for Ubuntu. Highlight text in any window, press a shortcut, and it is read aloud. Synthesis runs locally with [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) through ONNX Runtime, on CPU only, with no network use after the model download.

The first press after login starts a small background daemon that loads the model. The daemon stays resident, so every later press only pays for synthesis. Pressing the shortcut while it is still talking queues the new text.

## Tested on

Ubuntu 24.04, GNOME on Wayland, Intel N150 (4 cores, no GPU). See `ENVIRONMENT.md` for exact versions. The selection is read with `wl-paste`, so an X11 session needs `xclip -o -selection primary` substituted in `read_selection.sh` (untested).

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

   `requirements.txt` lists the top-level packages and explains why `misaki[en]` is avoided (it pulls in PyTorch, which this project never uses). `requirements-lock.txt` is the exact tested set.

3. Model files, from the [kokoro-onnx release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0):

   ```bash
   curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
   curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
   ```

4. Bind a global keyboard shortcut (GNOME Settings, Keyboard, Custom Shortcuts) to the absolute path of `read_selection.sh` in this checkout.

## Usage

Select text anywhere and press the shortcut. Selecting one of these command words and pressing the shortcut runs it instead of speaking it:

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

I quantized my own build of Kokoro (mixed precision, with most of the model in int8 and the last few convolutions left in fp32) and use it day to day because it should run faster on a CPU than the stock model. I may upload it to GitHub at some point. If I do, this section will link to it, and you can switch to it by pointing `model` in `config.toml` at the file. Until then, the stock model from the install steps is what this repo expects.

## How it works

- `read_selection.sh` reads the primary selection with `wl-paste` and runs `say_client.py`, which sends the text over a Unix socket (`~/.cache/say-selection/daemon.sock`) and starts the daemon first if needed. While the daemon loads, espeak-ng announces the startup.
- `say_daemon.py` keeps the model and misaki's G2P loaded and speaks queued text in order.
- `say_onnx.py` does the synthesis. Text goes to phonemes through misaki, not kokoro-onnx's own phonemizer, so numbers and dates read naturally ("1,234" becomes "one thousand two hundred thirty-four"). Audio plays through `aplay`.

## Limitations

- GNOME on Wayland only, as tested.
- The first press after login waits a few seconds while the model loads.
