# swingmusic-tui

A sleek, keyboard-first terminal client for **[Swing Music](https://github.com/swingmx/swingmusic)**, inspired by the Swing Music web UI with full Vim (`HJKL`) navigation, rich sorting, and native Linux **MPRIS2** (`playerctl`) integration.

## Features

- **Swing Music Web UI-inspired layout** — Left sidebar navigation, main track/folder browser with active sort pill, and persistent bottom Now Playing bar.
- **100% Keyboard-First (`HJKL`)** — Navigate folders, albums, artists, playlists, favorites, search, and queue without touching the mouse.
- **Flexible Sorting (`s` / `S`)** — Sort by **Newest → Oldest**, **Oldest → Newest**, **Title A → Z**, **Title Z → A**, **Artist A → Z**, **Album A → Z**, **Duration ↑/↓**, or **Default / Track #**.
- **Native MPRIS2 (`org.mpris.MediaPlayer2.swingmusic_tui`)** — Works out of the box with `playerctl`, Waybar, Hyprland media keys, and priority managers without fighting your browser tabs.
- **Zero-friction audio streaming** — Streams directly from your Swing Music server through a local authenticated proxy using `mpv`, `cvlc` (VLC), or `ffplay`.

## Installation

### Using `uv` (recommended)
```bash
git clone https://github.com/Rutytoi220/swingmusic-tui.git
cd swingmusic-tui
uv tool install .
```

### Run directly
```bash
swingmusic-tui
```

On first launch, a login modal prompts for your Swing Music server URL (e.g. `http://100.100.33.5:1970`), username, and password. Credentials/tokens are stored locally in `~/.config/swingmusic-tui/config.json` (`0600`).

## Keybindings

| Key | Action |
| --- | --- |
| `j` / `k` | Move cursor down / up |
| `g` / `G` | Jump to top / bottom |
| `h` / `l` | Go back / focus sidebar · Open folder/album/playlist or play track |
| `Enter` | Open item or play selected track |
| `1` – `7` | Jump to Home, Folders, Albums, Artists, Playlists, Favorites, Queue |
| `s` | Open Sort Picker (Newest, Oldest, A–Z, Z–A, Artist, Album, Duration) |
| `S` | Flip sort direction (Newest ↔ Oldest, A–Z ↔ Z–A) |
| `/` | Search tracks on server |
| `Space` | Play / Pause |
| `n` / `p` | Next / Previous track |
| `[` / `]` | Seek `-10s` / `+10s` |
| `-` / `+` | Volume `-5%` / `+5%` |
| `a` | Add selected track to queue |
| `f` | Toggle Favorite (`♥`) |
| `z` / `r` | Toggle Shuffle / Cycle Repeat (`off` → `all` → `one`) |
| `L` | Open Server Login / Settings |
| `?` | Show keybinding help |
| `q` | Quit |

## Requirements

- Python 3.11+
- One audio backend installed: `mpv` (recommended), `vlc` (`cvlc`), or `ffmpeg` (`ffplay`)

## License

MIT
