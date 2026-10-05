# Environment this was built and tested on

Recorded as a courtesy for future debugging -- if something doesn't work for
you, compare against this before assuming the code is wrong.

## System

- OS: Ubuntu 24.04.4 LTS (noble)
- Kernel: Linux 7.0.0-38-generic, x86_64
- CPU: Intel N150, 4 cores / 4 threads, no AVX-512, no AMX
- RAM: 15 GB, no GPU
- Desktop: GNOME Shell 46.0 on `ubuntu:GNOME`
- Display server: **Wayland** (`XDG_SESSION_TYPE=wayland`). `read_selection.sh`
  uses `wl-paste`, which is Wayland-specific -- an X11 session would need
  `xclip -o -selection primary` substituted in instead (untested here).

## System tools

| Tool | Version |
| --- | --- |
| `aplay` (alsa-utils) | 1.2.9 |
| `wl-clipboard` (`wl-paste`/`wl-copy`) | 2.2.1 |
| `espeak-ng` (CLI, used only for the daemon cold-start announcement) | 1.51 |
| `gsettings` (glib2.0, used for the one-time hotkey setup) | 2.80.0 |

## Python

- System Python: 3.12.3
- Venv: `.venv` at the repo root, so scripts resolve their interpreter as
  `HERE/.venv/bin/python`

**Gotcha we hit ourselves while building this**: if you have ROS2 (or
anything else) sourced in your shell, check `echo $PYTHONPATH` before
trusting `pip freeze` inside this venv. A sourced ROS install exports
`PYTHONPATH` pointing at its own `site-packages`, and Python puts `PYTHONPATH`
ahead of the venv's own site-packages on `sys.path` -- so `pip freeze` (and
imports in general) will silently show packages that were never actually
installed in this venv. Run `PYTHONPATH= pip freeze` to see the real picture,
or `env | grep PYTHONPATH` to check if this applies to you at all.

## Python packages (deliberately installed, not the full transitive closure)

Installed individually rather than via `misaki[en]`, specifically to avoid
that extra's unconditional pull of `spacy-curated-transformers` -> `torch`
(only needed for misaki's optional transformer-based G2P mode, which this
project never uses -- `trf=False` throughout):

| Package | Version |
| --- | --- |
| numpy | 2.5.1 |
| onnxruntime | 1.27.0 |
| kokoro-onnx | 0.5.0 |
| misaki | 0.9.4 |
| espeakng-loader | 0.2.4 |
| num2words | 0.5.14 |
| phonemizer-fork | 3.3.2 |
| spacy | 3.8.14 |
| en_core_web_sm | 3.8.0 |
| click | 8.4.2 (spaCy's CLI submodule imports this even though we never call it; not auto-pulled by spaCy's own declared deps, install explicitly if missing) |

Confirmed **no torch** anywhere in this venv (`pip show torch` -> not found).
Full resolved dependency tree (everything pip pulled in transitively) is in
`requirements.txt` / `requirements-lock.txt`.
