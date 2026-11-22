# swingmusic-tui

A terminal client for [Swing Music](https://github.com/swingmx/swingmusic) (`sw-tui`).

Vim-style navigation (`hjkl`), plays audio straight from your server using `mpv` / `vlc` / `ffplay`, and works with `playerctl` / MPRIS2 media keys on Linux.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Rutytoi220/swingmusic-tui/main/install.sh | bash
```

Or with `uv` / `pipx`:

```bash
uv tool install git+https://github.com/Rutytoi220/swingmusic-tui
```

You'll need Python 3.11+ and `mpv` (or `vlc` / `ffmpeg`) installed.

## Usage

```bash
sw-tui
```

First time you open it, just put in your Swing Music URL, username, and password. Config is saved in `~/.config/swingmusic-tui/config.json`.

### Main keys

- `j` / `k` — move down / up (`g` / `G` for top / bottom)
- `h` / `l` or `Enter` — go back / open or play
- `1`–`6` — Home, Favorites, Albums, Artists, Playlists, Queue
- `/` — search whatever tab you're in
- `s` / `S` — sort / reverse sort
- `Space` — play / pause
- `n` / `p` — next / previous track
- `[` / `]` — seek -10s / +10s
- `-` / `+` — volume
- `z` / `r` — shuffle / repeat
- `a` / `f` — add to queue / favorite
- `A` / `R` — go to album / go to artist
- `v` — switch artist tabs (Songs / Albums / Singles)
- `?` — help, `q` — quit

## License

MIT
