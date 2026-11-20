"""Textual TUI application for Swing Music."""

from __future__ import annotations

import os
from typing import Any

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, ListItem, ListView, Static

from .api import (
    SORT_LABELS,
    SORT_MODES,
    Album,
    Artist,
    Folder,
    Playlist,
    SwingMusicAPI,
    Track,
    sort_tracks,
)
from .config import AppConfig
from .mpris import MPRISService
from .player import AudioPlayer


def fmt_time(seconds: float | int) -> str:
    s = max(0, int(seconds))
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def make_progress_bar(pos: float, dur: float, width: int = 28) -> str:
    if dur <= 0:
        return "─" * width
    ratio = max(0.0, min(1.0, pos / dur))
    filled = int(round(ratio * width))
    if filled >= width:
        return "━" * width
    return "━" * filled + "●" + "─" * max(0, width - filled - 1)


NAV_ITEMS: list[tuple[str, str]] = [
    ("home", "⌂  Home"),
    ("folders", "▤  Folders"),
    ("albums", "◎  Albums"),
    ("artists", "♪  Artists"),
    ("playlists", "☰  Playlists"),
    ("favorites", "♥  Favorites"),
    ("queue", "≡  Queue"),
]


class LoginModal(ModalScreen[tuple[str, str, str] | None]):
    """Modal dialog to connect & authenticate with a Swing Music server."""

    CSS = """
    LoginModal {
        align: center middle;
        background: rgba(8, 9, 14, 0.80);
    }
    #login-box {
        width: 58;
        height: auto;
        padding: 1 2;
        background: #161822;
        border: round #5c7cfa;
    }
    #login-title {
        text-style: bold;
        color: #eef0f7;
        margin-bottom: 1;
    }
    .login-label {
        color: #858ba3;
        margin-top: 1;
    }
    #login-error {
        color: #ff6b81;
        margin-top: 1;
        height: auto;
    }
    #login-buttons {
        margin-top: 1;
        height: 3;
        align-horizontal: right;
    }
    #login-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, server_url: str = "", username: str = "", error_msg: str = "") -> None:
        super().__init__()
        self._server_url = server_url
        self._username = username
        self._error_msg = error_msg

    def compose(self) -> ComposeResult:
        with Vertical(id="login-box"):
            yield Static("♫  Connect to Swing Music", id="login-title")
            yield Label("Server URL (e.g. http://100.100.33.5:1970)", classes="login-label")
            yield Input(value=self._server_url, placeholder="http://192.168.1.5:1970", id="server-input")
            yield Label("Username", classes="login-label")
            yield Input(value=self._username, placeholder="admin", id="user-input")
            yield Label("Password", classes="login-label")
            yield Input(password=True, placeholder="••••••••", id="pass-input")
            yield Static(self._error_msg, id="login-error")
            with Horizontal(id="login-buttons"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Connect", variant="primary", id="btn-connect")

    def on_mount(self) -> None:
        if not self._server_url:
            self.query_one("#server-input", Input).focus()
        elif not self._username:
            self.query_one("#user-input", Input).focus()
        else:
            self.query_one("#pass-input", Input).focus()

    def _submit(self) -> None:
        url = self.query_one("#server-input", Input).value.strip().rstrip("/")
        user = self.query_one("#user-input", Input).value.strip()
        pw = self.query_one("#pass-input", Input).value
        if not url:
            self.query_one("#login-error", Static).update("Please enter a server URL.")
            return
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        self.dismiss((url, user, pw))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-connect":
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "server-input":
            self.query_one("#user-input", Input).focus()
        elif event.input.id == "user-input":
            self.query_one("#pass-input", Input).focus()
        else:
            self._submit()

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)


class SortModal(ModalScreen[str | None]):
    """HJKL-navigable modal to pick sort order."""

    CSS = """
    SortModal {
        align: center middle;
        background: rgba(8, 9, 14, 0.75);
    }
    #sort-box {
        width: 40;
        height: auto;
        padding: 1 2;
        background: #161822;
        border: round #8c52ff;
    }
    #sort-title {
        text-style: bold;
        color: #eef0f7;
        margin-bottom: 1;
    }
    #sort-list {
        height: auto;
        max-height: 14;
        background: #161822;
    }
    #sort-hint {
        color: #858ba3;
        margin-top: 1;
    }
    """

    def __init__(self, current_mode: str) -> None:
        super().__init__()
        self._current_mode = current_mode

    def compose(self) -> ComposeResult:
        with Vertical(id="sort-box"):
            yield Static("⇅  Sort Tracks", id="sort-title")
            items = []
            for key, label in SORT_MODES:
                prefix = "● " if key == self._current_mode else "  "
                items.append(ListItem(Label(f"{prefix}{label}"), id=f"sort-{key}"))
            yield ListView(*items, id="sort-list")
            yield Static("j/k: Move   Enter/l: Apply   Esc/q: Close", id="sort-hint")

    def on_mount(self) -> None:
        lv = self.query_one("#sort-list", ListView)
        lv.focus()
        for idx, (key, _) in enumerate(SORT_MODES):
            if key == self._current_mode:
                lv.index = idx
                break

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id and event.item.id.startswith("sort-"):
            self.dismiss(event.item.id[5:])

    def on_key(self, event: events.Key) -> None:
        lv = self.query_one("#sort-list", ListView)
        if event.key in ("escape", "q", "h"):
            event.stop()
            self.dismiss(None)
        elif event.key == "j":
            event.stop()
            lv.action_cursor_down()
        elif event.key == "k":
            event.stop()
            lv.action_cursor_up()
        elif event.key == "l":
            event.stop()
            lv.action_select_cursor()


class HelpModal(ModalScreen[None]):
    """Quick keyboard reference modal."""

    CSS = """
    HelpModal {
        align: center middle;
        background: rgba(8, 9, 14, 0.78);
    }
    #help-box {
        width: 64;
        height: auto;
        padding: 1 2;
        background: #161822;
        border: round #5c7cfa;
    }
    #help-text {
        color: #eef0f7;
    }
    """

    HELP_BODY = (
        "[b #8c52ff]♫  Swing Music TUI — Keybindings[/]\n\n"
        "[b]Navigation (HJKL)[/]\n"
        "  j / k         Move cursor down / up\n"
        "  g / G         Jump to top / bottom\n"
        "  h / l         Focus sidebar / Enter item (or go back)\n"
        "  Enter         Open folder/album/playlist or Play track\n"
        "  1 – 7         Jump directly to Home/Folders/Albums/Artists/Playlists/Favs/Queue\n\n"
        "[b]Sorting & Search[/]\n"
        "  s             Open Sort Picker (Newest, Oldest, A-Z, Z-A, Artist, Album, Duration)\n"
        "  S             Flip sort direction (Newest ↔ Oldest, A-Z ↔ Z-A)\n"
        "  /             Search tracks on server\n\n"
        "[b]Playback & Library[/]\n"
        "  Space         Play / Pause\n"
        "  n / p         Next / Previous track\n"
        "  [ / ]         Seek -10s / +10s\n"
        "  - / +         Volume -5% / +5%\n"
        "  a             Add selected track to Queue\n"
        "  f             Toggle Favorite (♥)\n"
        "  z / r         Toggle Shuffle / Cycle Repeat (off → all → one)\n"
        "  L             Server Login / Settings\n"
        "  q             Quit\n\n"
        "[dim]Press Esc, q, or ? to close[/]"
    )

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(self.HELP_BODY, id="help-text")

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "q", "question_mark", "?"):
            event.stop()
            self.dismiss(None)


class SwingMusicApp(App):
    """Swing Music TUI styled after the Swing Music web client with HJKL controls."""

    TITLE = "Swing Music"
    CSS = """
    Screen {
        background: #101116;
        color: #eef0f7;
    }

    #body {
        height: 1fr;
    }

    #sidebar {
        width: 22;
        background: #14161f;
        border-right: solid #242736;
        padding: 1 0;
    }

    #brand {
        padding: 0 2 1 2;
        color: #8c52ff;
        text-style: bold;
    }

    #nav-list {
        background: transparent;
        border: none;
        height: 1fr;
    }

    #nav-list > ListItem {
        padding: 0 2;
        height: 3;
        content-align: left middle;
        color: #9aa0b8;
        background: transparent;
    }

    #nav-list > ListItem.--highlight {
        background: #1f2335;
        color: #eef0f7;
        text-style: bold;
    }

    #nav-list:focus > ListItem.--highlight {
        background: #5c7cfa;
        color: #ffffff;
        text-style: bold;
    }

    #server-badge {
        padding: 1 2 0 2;
        color: #6c7390;
        height: auto;
    }

    #main-pane {
        width: 1fr;
        background: #101116;
    }

    #top-bar {
        height: 3;
        background: #14161f;
        border-bottom: solid #242736;
        padding: 0 2;
        align-vertical: middle;
    }

    #view-title {
        width: 1fr;
        color: #eef0f7;
        text-style: bold;
        content-align: left middle;
    }

    #sort-badge {
        width: auto;
        color: #b197fc;
        background: #1f1b33;
        padding: 0 2;
        content-align: right middle;
    }

    #search-bar {
        display: none;
        height: 3;
        margin: 0 1;
        background: #161822;
        border: round #5c7cfa;
    }

    #search-bar.visible {
        display: block;
    }

    #content-table {
        height: 1fr;
        background: #101116;
        border: none;
        padding: 0 1;
    }

    #content-table > .datatable--header {
        background: #14161f;
        color: #858ba3;
        text-style: bold;
    }

    #content-table > .datatable--cursor {
        background: #252942;
        color: #ffffff;
        text-style: bold;
    }

    #content-table:focus > .datatable--cursor {
        background: #5c7cfa;
        color: #ffffff;
        text-style: bold;
    }

    #status-line {
        height: 1;
        padding: 0 2;
        background: #101116;
        color: #7c829d;
    }

    #player-bar {
        height: 4;
        background: #14161f;
        border-top: solid #242736;
        padding: 0 2;
        align-vertical: middle;
    }

    #now-playing-left {
        width: 1fr;
        height: 3;
        content-align: left middle;
    }

    #now-playing-center {
        width: 44;
        height: 3;
        content-align: center middle;
    }

    #now-playing-right {
        width: 26;
        height: 3;
        content-align: right middle;
        color: #9aa0b8;
    }
    """

    BINDINGS = [
        Binding("q", "quit_app", "Quit", show=False),
        Binding("question_mark", "show_help", "Help", show=False),
        Binding("s", "open_sort", "Sort", show=False),
        Binding("S", "flip_sort", "Reverse Sort", show=False),
        Binding("slash", "open_search", "Search", show=False),
        Binding("space", "toggle_pause", "Play/Pause", show=False),
        Binding("n", "next_track", "Next", show=False),
        Binding("p", "prev_track", "Prev", show=False),
        Binding("[", "seek_back", "Seek -10s", show=False),
        Binding("]", "seek_forward", "Seek +10s", show=False),
        Binding("-", "vol_down", "Vol -5", show=False),
        Binding("+", "vol_up", "Vol +5", show=False),
        Binding("=", "vol_up", "Vol +5", show=False),
        Binding("z", "toggle_shuffle", "Shuffle", show=False),
        Binding("r", "cycle_repeat", "Repeat", show=False),
        Binding("a", "enqueue_selected", "Queue", show=False),
        Binding("f", "favorite_selected", "Favorite", show=False),
        Binding("L", "open_login", "Login", show=False),
        Binding("1", "nav_1", "Home", show=False),
        Binding("2", "nav_2", "Folders", show=False),
        Binding("3", "nav_3", "Albums", show=False),
        Binding("4", "nav_4", "Artists", show=False),
        Binding("5", "nav_5", "Playlists", show=False),
        Binding("6", "nav_6", "Favorites", show=False),
        Binding("7", "nav_7", "Queue", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.cfg = AppConfig.load()
        self.api = SwingMusicAPI(self.cfg.server_url, self.cfg.access_token)
        self.player = AudioPlayer(
            self.api,
            volume=self.cfg.volume,
            shuffle=self.cfg.shuffle,
            repeat=self.cfg.repeat,
            quality=self.cfg.quality,
            on_change=self._on_player_change,
        )
        self.mpris = MPRISService(self.player)

        self.current_view: str = "folders"
        self.current_folder_path: str = "$home"
        self.folder_stack: list[str] = []
        self.subview_stack: list[tuple[str, str]] = []  # e.g. [("album", hash)]
        self.rows_meta: list[tuple[str, Any]] = []  # ("folder"|"track"|"album"|"artist"|"playlist"|"parent", obj)
        self.current_tracks: list[Track] = []
        self.last_search_query: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("♫ SWING MUSIC", id="brand")
                yield ListView(
                    *[ListItem(Label(label), id=f"nav-{key}") for key, label in NAV_ITEMS],
                    id="nav-list",
                )
                yield Static("Not connected", id="server-badge")
            with Vertical(id="main-pane"):
                with Horizontal(id="top-bar"):
                    yield Static("Folders", id="view-title")
                    yield Static(f"⇅ {SORT_LABELS.get(self.cfg.sort_mode, 'Newest → Oldest')}  [s]", id="sort-badge")
                yield Input(placeholder="Search tracks on Swing Music... (Enter to search, Esc to cancel)", id="search-bar")
                yield DataTable(id="content-table", cursor_type="row")
                yield Static("j/k: Move   h/l: Back/Open   s: Sort   /: Search   Space: Play/Pause   ?: Help", id="status-line")
        with Horizontal(id="player-bar"):
            yield Static("[dim]Nothing playing[/]", id="now-playing-left")
            yield Static("", id="now-playing-center")
            yield Static("", id="now-playing-right")

    def on_mount(self) -> None:
        self.mpris.start()
        table = self.query_one("#content-table", DataTable)
        table.zebra_stripes = False
        table.focus()
        self.set_interval(0.5, self._refresh_player_bar)
        self._refresh_player_bar()

        if not self.cfg.server_url or not self.cfg.access_token:
            self.action_open_login()
        else:
            self._verify_and_load()

    def _on_player_change(self) -> None:
        self.mpris.emit_update()
        try:
            self.call_from_thread(self._refresh_player_bar)
        except Exception:
            pass

    def _refresh_player_bar(self) -> None:
        t = self.player.current_track
        left = self.query_one("#now-playing-left", Static)
        center = self.query_one("#now-playing-center", Static)
        right = self.query_one("#now-playing-right", Static)

        if t is None:
            left.update("[dim]Nothing playing — press Enter on a track[/]")
            center.update(f"[dim]00:00  {'─' * 26}  00:00[/]")
        else:
            icon = "[#51cf66]▶[/]" if self.player.is_playing else "[#fcc419]⏸[/]"
            fav = " [#ff6b81]♥[/]" if t.is_favorite else ""
            title = t.title[:38] + ("…" if len(t.title) > 38 else "")
            artist = t.artists[:38] + ("…" if len(t.artists) > 38 else "")
            left.update(f"{icon} [b]{title}[/]{fav}\n[dim]{artist}[/]")
            bar = make_progress_bar(self.player.position, self.player.duration, width=24)
            center.update(
                f"[b]{fmt_time(self.player.position)}[/]  [#5c7cfa]{bar}[/]  [dim]{fmt_time(self.player.duration)}[/]"
            )

        shf = "[#8c52ff]SHF[/]" if self.player.shuffle else "[dim]shf[/]"
        rpt_map = {"off": "[dim]rpt[/]", "all": "[#8c52ff]RPT[/]", "one": "[#51cf66]RPT1[/]"}
        rpt = rpt_map.get(self.player.repeat, "[dim]rpt[/]")
        right.update(f"{shf} {rpt}  🔊 {self.player.volume:>3}%\n[dim]{self.player.backend_name} • Q:{len(self.player.queue)}[/]")

    @work(thread=True)
    def _verify_and_load(self) -> None:
        ok, info = self.api.check_auth()
        if ok:
            self.call_from_thread(
                self.query_one("#server-badge", Static).update,
                f"[#51cf66]●[/] {info}\n[dim]{self.cfg.server_url.replace('http://', '').replace('https://', '')}[/]",
            )
            self.call_from_thread(self._load_current_view)
        else:
            self.call_from_thread(self._open_login_with_error, f"Session expired or unreachable ({info})")

    def _open_login_with_error(self, msg: str) -> None:
        self.push_screen(LoginModal(self.cfg.server_url, self.cfg.username, msg), self._handle_login_result)

    def action_open_login(self) -> None:
        self.push_screen(LoginModal(self.cfg.server_url, self.cfg.username), self._handle_login_result)

    def _handle_login_result(self, result: tuple[str, str, str] | None) -> None:
        if result is None:
            return
        url, user, pw = result
        self._do_login(url, user, pw)

    @work(thread=True)
    def _do_login(self, url: str, user: str, pw: str) -> None:
        ok, token, msg = self.api.login(url, user, pw)
        if ok:
            self.cfg.server_url = url
            self.cfg.username = user
            self.cfg.access_token = token
            self.cfg.save()
            self.call_from_thread(
                self.query_one("#server-badge", Static).update,
                f"[#51cf66]●[/] {user}\n[dim]{url.replace('http://', '').replace('https://', '')}[/]",
            )
            self.call_from_thread(self._set_status, f"Connected to {url} as {user}")
            self.call_from_thread(self._load_current_view)
        else:
            self.call_from_thread(self._open_login_with_error, f"Login failed: {msg}")

    def _set_status(self, msg: str) -> None:
        self.query_one("#status-line", Static).update(msg)

    def _update_sort_badge(self) -> None:
        label = SORT_LABELS.get(self.cfg.sort_mode, self.cfg.sort_mode)
        self.query_one("#sort-badge", Static).update(f"⇅ {label}  [s]")

    def _select_nav(self, view_key: str) -> None:
        self.current_view = view_key
        self.subview_stack.clear()
        lv = self.query_one("#nav-list", ListView)
        for idx, (k, _) in enumerate(NAV_ITEMS):
            if k == view_key:
                lv.index = idx
                break
        self._load_current_view()
        self.query_one("#content-table", DataTable).focus()

    def action_nav_1(self) -> None:
        self._select_nav("home")

    def action_nav_2(self) -> None:
        self._select_nav("folders")

    def action_nav_3(self) -> None:
        self._select_nav("albums")

    def action_nav_4(self) -> None:
        self._select_nav("artists")

    def action_nav_5(self) -> None:
        self._select_nav("playlists")

    def action_nav_6(self) -> None:
        self._select_nav("favorites")

    def action_nav_7(self) -> None:
        self._select_nav("queue")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "nav-list" and event.item.id and event.item.id.startswith("nav-"):
            self._select_nav(event.item.id[4:])

    def _load_current_view(self) -> None:
        self._update_sort_badge()
        if self.current_view == "queue":
            self._render_queue()
            return
        self._fetch_view_worker(self.current_view, self.current_folder_path, list(self.subview_stack), self.cfg.sort_mode)

    @work(thread=True, exclusive=True)
    def _fetch_view_worker(
        self,
        view: str,
        folder_path: str,
        subview_stack: list[tuple[str, str]],
        sort_mode: str,
    ) -> None:
        self.call_from_thread(self._set_status, "Loading…")
        try:
            if subview_stack:
                kind, key = subview_stack[-1]
                if kind == "album":
                    tracks = sort_tracks(self.api.get_album_tracks(key), sort_mode)
                    self.call_from_thread(self._render_tracks, f"Album  ({len(tracks)} tracks)", tracks, True)
                elif kind == "artist":
                    tracks = sort_tracks(self.api.get_artist_tracks(key), sort_mode)
                    self.call_from_thread(self._render_tracks, f"Artist  ({len(tracks)} tracks)", tracks, True)
                elif kind == "playlist":
                    tracks = sort_tracks(self.api.get_playlist_tracks(key), sort_mode)
                    self.call_from_thread(self._render_tracks, f"Playlist  ({len(tracks)} tracks)", tracks, True)
                return

            if view == "home":
                tracks = sort_tracks(self.api.get_recently_added(80), sort_mode)
                self.call_from_thread(self._render_tracks, f"Home • Recently Added ({len(tracks)})", tracks, False)
            elif view == "folders":
                res = self.api.get_folder(folder_path, sort_mode=sort_mode)
                self.current_folder_path = res.path
                self.call_from_thread(self._render_folder, res)
            elif view == "favorites":
                tracks = sort_tracks(self.api.get_favorites(500), sort_mode)
                self.call_from_thread(self._render_tracks, f"♥ Favorites ({len(tracks)})", tracks, False)
            elif view == "albums":
                rev = sort_mode in ("newest", "title_desc", "duration_desc")
                sby = "title" if sort_mode.startswith("title") else ("duration" if sort_mode.startswith("duration") else "created_date")
                albums = self.api.get_albums(300, sort_by=sby, reverse=rev)
                self.call_from_thread(self._render_albums, albums)
            elif view == "artists":
                rev = sort_mode in ("newest", "title_desc")
                artists = self.api.get_artists(300, sort_by="name", reverse=rev)
                self.call_from_thread(self._render_artists, artists)
            elif view == "playlists":
                playlists = self.api.get_playlists()
                self.call_from_thread(self._render_playlists, playlists)
            elif view == "search" and self.last_search_query:
                tracks = sort_tracks(self.api.search_tracks(self.last_search_query), sort_mode)
                self.call_from_thread(
                    self._render_tracks,
                    f"Search: \"{self.last_search_query}\" ({len(tracks)})",
                    tracks,
                    False,
                )
        except Exception as exc:
            self.call_from_thread(self._set_status, f"[#ff6b81]Error: {exc}[/]")

    def _reset_table(self, columns: list[str]) -> DataTable:
        table = self.query_one("#content-table", DataTable)
        table.clear(columns=True)
        for col in columns:
            table.add_column(col)
        self.rows_meta.clear()
        self.current_tracks.clear()
        return table

    def _render_folder(self, res) -> None:
        title = f"Folders  •  {res.path}"
        self.query_one("#view-title", Static).update(title)
        table = self._reset_table(["#", "Title / Folder", "Artist", "Album", "Time", "♥"])

        if self.folder_stack or (res.path and res.path not in ("$home", "/")):
            table.add_row("..", "↰  .. (Parent Folder)", "", "", "", "")
            self.rows_meta.append(("parent", None))

        for f in res.folders:
            info = f"{f.trackcount} tracks" if f.trackcount else f"{f.foldercount} folders"
            table.add_row("▤", f"{f.name}/", info, "", "", "")
            self.rows_meta.append(("folder", f))

        self.current_tracks = list(res.tracks)
        for i, t in enumerate(res.tracks, start=1):
            fav = "♥" if t.is_favorite else ""
            table.add_row(str(i), t.title, t.artists, t.album, fmt_time(t.duration), fav)
            self.rows_meta.append(("track", t))

        self._set_status(f"{len(res.folders)} folders, {len(res.tracks)} tracks  •  j/k: Move  l/Enter: Open/Play  h: Up  s: Sort")

    def _render_tracks(self, title: str, tracks: list[Track], has_back: bool) -> None:
        self.query_one("#view-title", Static).update(title)
        table = self._reset_table(["#", "Title", "Artist", "Album", "Time", "♥"])
        if has_back:
            table.add_row("..", "↰  .. (Back)", "", "", "", "")
            self.rows_meta.append(("parent", None))
        self.current_tracks = list(tracks)
        for i, t in enumerate(tracks, start=1):
            fav = "♥" if t.is_favorite else ""
            table.add_row(str(i), t.title, t.artists, t.album, fmt_time(t.duration), fav)
            self.rows_meta.append(("track", t))
        self._set_status(f"{len(tracks)} tracks  •  Enter/l: Play  a: Queue  f: Favorite  s: Sort  /: Search")

    def _render_albums(self, albums: list[Album]) -> None:
        self.query_one("#view-title", Static).update(f"Albums ({len(albums)})")
        table = self._reset_table(["#", "Album", "Artist", "Tracks", "Duration"])
        for i, a in enumerate(albums, start=1):
            table.add_row(str(i), a.title, a.artists, str(a.trackcount), fmt_time(a.duration))
            self.rows_meta.append(("album", a))
        self._set_status(f"{len(albums)} albums  •  Enter/l: Open album  s: Sort")

    def _render_artists(self, artists: list[Artist]) -> None:
        self.query_one("#view-title", Static).update(f"Artists ({len(artists)})")
        table = self._reset_table(["#", "Artist", "Albums", "Tracks"])
        for i, a in enumerate(artists, start=1):
            table.add_row(str(i), a.name, str(a.albumcount), str(a.trackcount))
            self.rows_meta.append(("artist", a))
        self._set_status(f"{len(artists)} artists  •  Enter/l: Open artist  s: Sort")

    def _render_playlists(self, playlists: list[Playlist]) -> None:
        self.query_one("#view-title", Static).update(f"Playlists ({len(playlists)})")
        table = self._reset_table(["#", "Playlist", "Tracks", "Duration"])
        for i, p in enumerate(playlists, start=1):
            table.add_row(str(i), p.name, str(p.count), fmt_time(p.duration))
            self.rows_meta.append(("playlist", p))
        self._set_status(f"{len(playlists)} playlists  •  Enter/l: Open playlist")

    def _render_queue(self) -> None:
        self.query_one("#view-title", Static).update(f"Queue ({len(self.player.queue)} tracks)")
        table = self._reset_table(["#", "Title", "Artist", "Album", "Time", "♥"])
        self.current_tracks = list(self.player.queue)
        for i, t in enumerate(self.player.queue, start=1):
            marker = "▶" if (i - 1) == self.player.index else str(i)
            fav = "♥" if t.is_favorite else ""
            table.add_row(marker, t.title, t.artists, t.album, fmt_time(t.duration), fav)
            self.rows_meta.append(("track", t))
        self._set_status(f"{len(self.player.queue)} tracks in queue  •  Enter/l: Jump to track")

    def _activate_row(self) -> None:
        table = self.query_one("#content-table", DataTable)
        if not self.rows_meta:
            return
        idx = table.cursor_row
        if not (0 <= idx < len(self.rows_meta)):
            return
        kind, obj = self.rows_meta[idx]

        if kind == "parent":
            self._go_back()
        elif kind == "folder" and isinstance(obj, Folder):
            self.folder_stack.append(self.current_folder_path)
            self.current_folder_path = obj.path
            self._load_current_view()
        elif kind == "album" and isinstance(obj, Album):
            self.subview_stack.append(("album", obj.albumhash))
            self._load_current_view()
        elif kind == "artist" and isinstance(obj, Artist):
            self.subview_stack.append(("artist", obj.artisthash))
            self._load_current_view()
        elif kind == "playlist" and isinstance(obj, Playlist):
            self.subview_stack.append(("playlist", obj.id))
            self._load_current_view()
        elif kind == "track" and isinstance(obj, Track):
            try:
                t_idx = self.current_tracks.index(obj)
            except ValueError:
                t_idx = 0
            self.player.play_tracks(self.current_tracks, start_index=t_idx)
            self._set_status(f"Playing: {obj.title} — {obj.artists}")
            if self.current_view == "queue":
                self._render_queue()

    def _go_back(self) -> bool:
        if self.subview_stack:
            self.subview_stack.pop()
            self._load_current_view()
            return True
        if self.current_view == "folders":
            if self.folder_stack:
                self.current_folder_path = self.folder_stack.pop()
                self._load_current_view()
                return True
            if self.current_folder_path not in ("$home", "/", ""):
                parent = os.path.dirname(self.current_folder_path.rstrip("/")) or "$home"
                self.current_folder_path = parent
                self._load_current_view()
                return True
        return False

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._activate_row()

    def on_key(self, event: events.Key) -> None:
        search_bar = self.query_one("#search-bar", Input)
        if search_bar.has_focus:
            if event.key == "escape":
                event.stop()
                search_bar.remove_class("visible")
                self.query_one("#content-table", DataTable).focus()
            return

        nav = self.query_one("#nav-list", ListView)
        table = self.query_one("#content-table", DataTable)

        if nav.has_focus:
            if event.key == "j":
                event.stop()
                nav.action_cursor_down()
            elif event.key == "k":
                event.stop()
                nav.action_cursor_up()
            elif event.key == "l":
                event.stop()
                nav.action_select_cursor()
        elif table.has_focus:
            if event.key == "j":
                event.stop()
                table.action_cursor_down()
            elif event.key == "k":
                event.stop()
                table.action_cursor_up()
            elif event.key == "g":
                event.stop()
                table.move_cursor(row=0)
            elif event.key == "G":
                event.stop()
                if table.row_count > 0:
                    table.move_cursor(row=table.row_count - 1)
            elif event.key == "l":
                event.stop()
                self._activate_row()
            elif event.key == "h":
                event.stop()
                if not self._go_back():
                    nav.focus()

    def action_open_sort(self) -> None:
        self.push_screen(SortModal(self.cfg.sort_mode), self._apply_sort_mode)

    def _apply_sort_mode(self, mode: str | None) -> None:
        if not mode or mode == self.cfg.sort_mode:
            return
        self.cfg.sort_mode = mode
        self.cfg.save()
        self._load_current_view()

    def action_flip_sort(self) -> None:
        flips = {
            "newest": "oldest",
            "oldest": "newest",
            "title_asc": "title_desc",
            "title_desc": "title_asc",
            "duration_asc": "duration_desc",
            "duration_desc": "duration_asc",
        }
        self._apply_sort_mode(flips.get(self.cfg.sort_mode, "newest"))

    def action_open_search(self) -> None:
        search_bar = self.query_one("#search-bar", Input)
        search_bar.add_class("visible")
        search_bar.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-bar":
            q = event.value.strip()
            event.input.remove_class("visible")
            self.query_one("#content-table", DataTable).focus()
            if q:
                self.last_search_query = q
                self.current_view = "search"
                self.subview_stack.clear()
                self._load_current_view()

    def action_toggle_pause(self) -> None:
        self.player.toggle_pause()

    def action_next_track(self) -> None:
        self.player.next_track()

    def action_prev_track(self) -> None:
        self.player.prev_track()

    def action_seek_back(self) -> None:
        self.player.seek(-10.0)

    def action_seek_forward(self) -> None:
        self.player.seek(10.0)

    def action_vol_down(self) -> None:
        self.player.set_volume(self.player.volume - 5)
        self.cfg.volume = self.player.volume
        self.cfg.save()

    def action_vol_up(self) -> None:
        self.player.set_volume(self.player.volume + 5)
        self.cfg.volume = self.player.volume
        self.cfg.save()

    def action_toggle_shuffle(self) -> None:
        self.cfg.shuffle = self.player.toggle_shuffle()
        self.cfg.save()

    def action_cycle_repeat(self) -> None:
        self.cfg.repeat = self.player.cycle_repeat()
        self.cfg.save()

    def action_enqueue_selected(self) -> None:
        table = self.query_one("#content-table", DataTable)
        if 0 <= table.cursor_row < len(self.rows_meta):
            kind, obj = self.rows_meta[table.cursor_row]
            if kind == "track" and isinstance(obj, Track):
                self.player.enqueue(obj)
                self._set_status(f"Queued: {obj.title} — {obj.artists}")

    def action_favorite_selected(self) -> None:
        table = self.query_one("#content-table", DataTable)
        if 0 <= table.cursor_row < len(self.rows_meta):
            kind, obj = self.rows_meta[table.cursor_row]
            if kind == "track" and isinstance(obj, Track):
                self._toggle_fav_worker(obj)

    @work(thread=True)
    def _toggle_fav_worker(self, track: Track) -> None:
        if self.api.toggle_favorite(track):
            state = "Added to" if track.is_favorite else "Removed from"
            self.call_from_thread(self._set_status, f"{state} Favorites: {track.title}")
            self.call_from_thread(self._load_current_view)

    def action_show_help(self) -> None:
        self.push_screen(HelpModal())

    def action_quit_app(self) -> None:
        self.player.shutdown()
        self.mpris.stop()
        self.exit()


def run() -> None:
    app = SwingMusicApp()
    try:
        app.run()
    finally:
        app.player.shutdown()
        app.mpris.stop()


if __name__ == "__main__":
    run()
