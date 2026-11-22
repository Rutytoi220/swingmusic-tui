"""Swing Music REST API client."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

SORT_MODES: list[tuple[str, str]] = [
    ("newest", "Newest → Oldest"),
    ("oldest", "Oldest → Newest"),
    ("title_asc", "Title A → Z"),
    ("title_desc", "Title Z → A"),
    ("artist_asc", "Artist A → Z"),
    ("album_asc", "Album A → Z"),
    ("duration_asc", "Duration ↑"),
    ("duration_desc", "Duration ↓"),
    ("default", "Default / Track #"),
]

SORT_LABELS = dict(SORT_MODES)


@dataclass
class Track:
    trackhash: str
    title: str
    filepath: str
    artists: str = "Unknown Artist"
    album: str = ""
    albumhash: str = ""
    duration: int = 0
    track_num: int = 0
    disc: int = 1
    bitrate: int = 0
    is_favorite: bool = False
    last_mod: float = 0.0
    date: int = 0
    image: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Track":
        raw_artists = d.get("artists") or d.get("albumartists") or []
        if isinstance(raw_artists, list):
            artist_names = [
                a.get("name", "") if isinstance(a, dict) else str(a)
                for a in raw_artists
            ]
            artist_str = ", ".join(n for n in artist_names if n) or "Unknown Artist"
        else:
            artist_str = str(raw_artists) or "Unknown Artist"

        last_mod = d.get("last_mod") or d.get("lastmodified") or d.get("date") or 0
        try:
            last_mod_f = float(last_mod)
        except (TypeError, ValueError):
            last_mod_f = 0.0

        try:
            date_i = int(d.get("date") or 0)
        except (TypeError, ValueError):
            date_i = 0

        try:
            dur_i = int(d.get("duration") or 0)
        except (TypeError, ValueError):
            dur_i = 0

        return cls(
            trackhash=str(d.get("trackhash") or d.get("hash") or ""),
            title=str(d.get("title") or d.get("og_title") or "Untitled"),
            filepath=str(d.get("filepath") or ""),
            artists=artist_str,
            album=str(d.get("album") or d.get("og_album") or ""),
            albumhash=str(d.get("albumhash") or ""),
            duration=dur_i,
            track_num=int(d.get("track") or 0),
            disc=int(d.get("disc") or 1),
            bitrate=int(d.get("bitrate") or 0),
            is_favorite=bool(d.get("is_favorite", False)),
            last_mod=last_mod_f,
            date=date_i,
            image=str(d.get("image") or ""),
        )


@dataclass
class Folder:
    name: str
    path: str
    trackcount: int = 0
    foldercount: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Folder":
        return cls(
            name=str(d.get("name") or ""),
            path=str(d.get("path") or ""),
            trackcount=int(d.get("trackcount") or 0),
            foldercount=int(d.get("foldercount") or 0),
        )


@dataclass
class Album:
    albumhash: str
    title: str
    artists: str = "Unknown Artist"
    trackcount: int = 0
    date: int = 0
    duration: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Album":
        raw_artists = d.get("albumartists") or d.get("artists") or []
        if isinstance(raw_artists, list):
            names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in raw_artists]
            artist_str = ", ".join(n for n in names if n) or "Unknown Artist"
        else:
            artist_str = str(raw_artists) or "Unknown Artist"
        return cls(
            albumhash=str(d.get("albumhash") or ""),
            title=str(d.get("title") or d.get("og_title") or "Untitled Album"),
            artists=artist_str,
            trackcount=int(d.get("trackcount") or 0),
            date=int(d.get("date") or 0),
            duration=int(d.get("duration") or 0),
        )


@dataclass
class Artist:
    artisthash: str
    name: str
    trackcount: int = 0
    albumcount: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Artist":
        return cls(
            artisthash=str(d.get("artisthash") or ""),
            name=str(d.get("name") or "Unknown Artist"),
            trackcount=int(d.get("trackcount") or 0),
            albumcount=int(d.get("albumcount") or 0),
        )


@dataclass
class Playlist:
    id: str
    name: str
    count: int = 0
    duration: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Playlist":
        return cls(
            id=str(d.get("id") or ""),
            name=str(d.get("name") or "Untitled Playlist"),
            count=int(d.get("count") or 0),
            duration=int(d.get("duration") or 0),
        )


@dataclass
class FolderResult:
    path: str
    folders: list[Folder] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    total: int = 0
    home: str = ""


def sort_tracks(tracks: list[Track], mode: str) -> list[Track]:
    """Client-side sorting supporting oldest/newest, A-Z, Z-A, artist, album, duration."""
    if mode == "default":
        return list(tracks)
    has_timestamps = any(t.last_mod or t.date for t in tracks)
    if mode == "newest":
        if not has_timestamps:
            # Endpoints like /favorites/tracks & /nothome/recents/added already return Newest -> Oldest
            return list(tracks)
        return sorted(tracks, key=lambda t: (t.last_mod, t.date, t.title.lower()), reverse=True)
    if mode == "oldest":
        if not has_timestamps:
            return list(reversed(tracks))
        return sorted(tracks, key=lambda t: (t.last_mod, t.date, t.title.lower()))
    if mode == "title_asc":
        return sorted(tracks, key=lambda t: t.title.lower())
    if mode == "title_desc":
        return sorted(tracks, key=lambda t: t.title.lower(), reverse=True)
    if mode == "artist_asc":
        return sorted(tracks, key=lambda t: (t.artists.lower(), t.album.lower(), t.track_num))
    if mode == "album_asc":
        return sorted(tracks, key=lambda t: (t.album.lower(), t.disc, t.track_num, t.title.lower()))
    if mode == "duration_asc":
        return sorted(tracks, key=lambda t: t.duration)
    if mode == "duration_desc":
        return sorted(tracks, key=lambda t: t.duration, reverse=True)
    return list(tracks)


def _folder_sort_params(mode: str) -> dict[str, Any]:
    mapping: dict[str, tuple[str, bool, str, bool]] = {
        "newest": ("last_mod", True, "lastmod", True),
        "oldest": ("last_mod", False, "lastmod", False),
        "title_asc": ("title", False, "name", False),
        "title_desc": ("title", True, "name", True),
        "artist_asc": ("artists", False, "name", False),
        "album_asc": ("album", False, "name", False),
        "duration_asc": ("duration", False, "name", False),
        "duration_desc": ("duration", True, "name", True),
        "default": ("default", False, "lastmod", True),
    }
    t_by, t_rev, f_by, f_rev = mapping.get(mode, ("default", False, "lastmod", True))
    return {
        "sorttracksby": t_by,
        "tracksort_reverse": t_rev,
        "sortfoldersby": f_by,
        "foldersort_reverse": f_rev,
    }


class SwingMusicAPI:
    """HTTP client for a Swing Music server."""

    def __init__(self, base_url: str = "", access_token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self._client = httpx.Client(timeout=15.0, follow_redirects=True)
        self._apply_auth()

    def configure(self, base_url: str, access_token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self._apply_auth()

    def _apply_auth(self) -> None:
        self._client.headers.clear()
        self._client.cookies.clear()
        if self.access_token:
            self._client.headers["Authorization"] = f"Bearer {self.access_token}"
            self._client.cookies.set("access_token_cookie", self.access_token)

    def auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
            headers["Cookie"] = f"access_token_cookie={self.access_token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def check_auth(self) -> tuple[bool, str]:
        if not self.base_url:
            return False, "No server URL configured"
        try:
            r = self._client.get(self._url("/auth/user"))
            if r.status_code == 200:
                data = r.json()
                user = data.get("username") or data.get("user", {}).get("username") or "user"
                return True, str(user)
            return False, f"HTTP {r.status_code}"
        except Exception as exc:
            return False, str(exc)

    def login(self, server_url: str, username: str, password: str) -> tuple[bool, str, str]:
        """Returns (ok, access_token, message)."""
        self.configure(server_url, "")
        try:
            r = self._client.post(
                self._url("/auth/login"),
                json={"username": username, "password": password},
            )
            if r.status_code == 200:
                data = r.json()
                token = str(data.get("accesstoken") or data.get("access_token") or "")
                if not token:
                    token = str(r.cookies.get("access_token_cookie") or "")
                self.access_token = token
                self._apply_auth()
                return True, token, "Logged in"
            try:
                msg = r.json().get("msg") or f"HTTP {r.status_code}"
            except Exception:
                msg = f"HTTP {r.status_code}"
            return False, "", str(msg)
        except Exception as exc:
            return False, "", str(exc)

    def get_folder(self, path: str = "$home", sort_mode: str = "newest", limit: int = 500) -> FolderResult:
        payload = {
            "folder": path or "$home",
            "start": 0,
            "limit": limit,
            "tracks_only": False,
            **_folder_sort_params(sort_mode),
        }
        r = self._client.post(self._url("/folder"), json=payload)
        r.raise_for_status()
        data = r.json()
        folders = [Folder.from_dict(f) for f in (data.get("folders") or [])]
        tracks = [Track.from_dict(t) for t in (data.get("tracks") or [])]
        return FolderResult(
            path=str(data.get("path") or path),
            folders=folders,
            tracks=tracks,
            total=int(data.get("total") or len(tracks)),
            home=str(data.get("home") or ""),
        )

    def get_recently_added(self, limit: int = 80) -> list[Track]:
        try:
            r = self._client.get(self._url(f"/nothome/recents/added?limit={limit}"))
            r.raise_for_status()
            data = r.json()
            items = data.get("items") or data.get("tracks") or []
            tracks: list[Track] = []
            for item in items:
                inner = item.get("item") if isinstance(item, dict) and "item" in item else item
                if isinstance(inner, dict) and (inner.get("trackhash") or inner.get("filepath")):
                    tracks.append(Track.from_dict(inner))
            if tracks:
                return tracks
        except Exception:
            pass
        # Fallback to $home folder tracks sorted by newest last_mod
        return self.get_folder("$home", sort_mode="newest", limit=limit).tracks

    def get_recently_played(self, limit: int = 80) -> list[Track]:
        r = self._client.get(self._url(f"/nothome/recents/played?limit={limit}"))
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or data.get("tracks") or []
        tracks: list[Track] = []
        for item in items:
            inner = item.get("item") if isinstance(item, dict) and "item" in item else item
            if isinstance(inner, dict) and (inner.get("trackhash") or inner.get("filepath")):
                tracks.append(Track.from_dict(inner))
        return tracks

    def get_random_tracks(self, limit: int = 100) -> list[Track]:
        r = self._client.get(self._url(f"/track/random?limit={limit}"))
        r.raise_for_status()
        data = r.json()
        return [Track.from_dict(t) for t in (data.get("tracks") or [])]

    def get_favorites(self, limit: int = 500) -> list[Track]:
        r = self._client.get(self._url(f"/favorites/tracks?start=0&limit={limit}"))
        r.raise_for_status()
        data = r.json()
        raw = data.get("tracks") or data.get("data") or []
        tracks = [Track.from_dict(t) for t in raw]
        for t in tracks:
            t.is_favorite = True
        return tracks

    def toggle_favorite(self, track: Track) -> bool:
        endpoint = "/favorites/remove" if track.is_favorite else "/favorites/add"
        r = self._client.post(
            self._url(endpoint),
            json={"type": "track", "hash": track.trackhash},
        )
        if r.status_code == 200:
            track.is_favorite = not track.is_favorite
            return True
        return False

    def get_playlists(self) -> list[Playlist]:
        r = self._client.get(self._url("/playlists?no_images=true"))
        r.raise_for_status()
        data = r.json()
        return [Playlist.from_dict(p) for p in (data.get("data") or [])]

    def get_playlist_tracks(self, pid: str, limit: int = 500) -> list[Track]:
        r = self._client.get(self._url(f"/playlists/{pid}?no_tracks=false&start=0&limit={limit}"))
        r.raise_for_status()
        data = r.json()
        return [Track.from_dict(t) for t in (data.get("tracks") or [])]

    def get_albums(self, limit: int = 300, sort_by: str = "created_date", reverse: bool = True) -> list[Album]:
        r = self._client.get(
            self._url(f"/getall/albums?start=0&limit={limit}&sortby={sort_by}&reverse={1 if reverse else 0}")
        )
        r.raise_for_status()
        data = r.json()
        return [Album.from_dict(a) for a in (data.get("items") or [])]

    def get_album_tracks(self, albumhash: str) -> list[Track]:
        r = self._client.post(self._url("/album"), json={"albumhash": albumhash, "albumlimit": 0})
        r.raise_for_status()
        data = r.json()
        tracks = [Track.from_dict(t) for t in (data.get("tracks") or [])]
        return sorted(tracks, key=lambda t: (t.disc, t.track_num, t.title.lower()))

    def get_artists(self, limit: int = 300, sort_by: str = "name", reverse: bool = False) -> list[Artist]:
        r = self._client.get(
            self._url(f"/getall/artists?start=0&limit={limit}&sortby={sort_by}&reverse={1 if reverse else 0}")
        )
        r.raise_for_status()
        data = r.json()
        return [Artist.from_dict(a) for a in (data.get("items") or [])]

    def get_artist_tracks(self, artisthash: str) -> list[Track]:
        r = self._client.get(self._url(f"/artist/{artisthash}?tracklimit=200&albumlimit=0"))
        r.raise_for_status()
        data = r.json()
        return [Track.from_dict(t) for t in (data.get("tracks") or [])]

    def search_tracks(self, query: str, limit: int = 60) -> list[Track]:
        q = quote(query.strip())
        r = self._client.get(self._url(f"/search/?itemtype=tracks&start=0&q={q}&limit={limit}"))
        r.raise_for_status()
        data = r.json()
        return [Track.from_dict(t) for t in (data.get("results") or [])]

    def search_albums(self, query: str, limit: int = 200) -> list[Album]:
        ql = query.strip().lower()
        all_albums = self.get_albums(limit=5000)
        tokens = ql.split()
        matches = [
            a for a in all_albums
            if all(tok in a.title.lower() or tok in a.artists.lower() for tok in tokens)
        ]
        # Rank exact/prefix title matches first
        matches.sort(key=lambda a: (0 if a.title.lower().startswith(ql) else (1 if ql in a.title.lower() else 2), a.title.lower()))
        if matches:
            return matches[:limit]
        # Fallback to server fuzzy search if no substring match
        q = quote(query.strip())
        r = self._client.get(self._url(f"/search/?itemtype=albums&start=0&q={q}&limit={limit}"))
        r.raise_for_status()
        return [Album.from_dict(a) for a in (r.json().get("results") or [])]

    def search_artists(self, query: str, limit: int = 200) -> list[Artist]:
        ql = query.strip().lower()
        all_artists = self.get_artists(limit=5000)
        tokens = ql.split()
        matches = [a for a in all_artists if all(tok in a.name.lower() for tok in tokens)]
        matches.sort(key=lambda a: (0 if a.name.lower().startswith(ql) else 1, a.name.lower()))
        if matches:
            return matches[:limit]
        q = quote(query.strip())
        r = self._client.get(self._url(f"/search/?itemtype=artists&start=0&q={q}&limit={limit}"))
        r.raise_for_status()
        return [Artist.from_dict(a) for a in (r.json().get("results") or [])]

    def stream_url(self, track: Track, quality: str = "original", legacy: bool = True) -> str:
        fp = quote(track.filepath, safe="")
        if legacy:
            return self._url(f"/file/{track.trackhash}/legacy?filepath={fp}")
        return self._url(f"/file/{track.trackhash}?filepath={fp}&quality={quality}")

    def stream_urls(self, track: Track, quality: str = "original") -> list[str]:
        return [
            self.stream_url(track, quality=quality, legacy=True),
            self.stream_url(track, quality=quality, legacy=False),
        ]
