"""Audio playback engine with authenticated local stream proxy (mpv / cvlc / ffplay)."""

from __future__ import annotations

import http.server
import json
import os
import random
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict
from typing import Callable

import httpx

from .api import SwingMusicAPI, Track
from .config import load_session, save_session


class _AuthStreamProxy:
    """Tiny localhost HTTP proxy that attaches Swing Music auth headers/cookies for mpv/cvlc."""

    def __init__(self, api: SwingMusicAPI, quality: str = "original") -> None:
        self.api = api
        self.quality = quality
        self._tracks: dict[str, Track] = {}
        self._lock = threading.Lock()
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    def start(self) -> None:
        if self._server is not None:
            return
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args) -> None:  # noqa: A002
                return

            def do_GET(self) -> None:
                key = self.path.lstrip("/").split("?", 1)[0]
                with proxy._lock:
                    track = proxy._tracks.get(key)
                if not track:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return

                headers = proxy.api.auth_headers()
                if "Range" in self.headers:
                    headers["Range"] = self.headers["Range"]

                urls = proxy.api.stream_urls(track, proxy.quality)
                try:
                    with httpx.Client(timeout=None, follow_redirects=True) as client:
                        for i, upstream_url in enumerate(urls):
                            with client.stream("GET", upstream_url, headers=headers) as resp:
                                if resp.status_code == 404 and i + 1 < len(urls):
                                    continue
                                self.send_response(resp.status_code)
                                for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
                                    if h in resp.headers:
                                        self.send_header(h, resp.headers[h])
                                self.send_header("Connection", "close")
                                self.end_headers()
                                for chunk in resp.iter_bytes(chunk_size=65536):
                                    if not chunk:
                                        continue
                                    try:
                                        self.wfile.write(chunk)
                                    except (BrokenPipeError, ConnectionResetError):
                                        break
                                return
                except Exception:
                    try:
                        self.send_response(502)
                        self.end_headers()
                    except Exception:
                        pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def register(self, track: Track) -> str:
        self.start()
        key = f"{track.trackhash}_{int(time.time() * 1000)}"
        with self._lock:
            # Keep only recent entries
            if len(self._tracks) > 12:
                oldest = list(self._tracks.keys())[:6]
                for k in oldest:
                    self._tracks.pop(k, None)
            self._tracks[key] = track
        return f"http://127.0.0.1:{self.port}/{key}"

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None


class AudioPlayer:
    """Queue + playback controller backed by mpv (preferred), cvlc, or ffplay."""

    def __init__(
        self,
        api: SwingMusicAPI,
        volume: int = 85,
        shuffle: bool = False,
        repeat: str = "off",
        quality: str = "original",
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.api = api
        self.volume = max(0, min(100, volume))
        self.shuffle = shuffle
        self.repeat = repeat  # off | all | one
        self.on_change = on_change

        self.queue: list[Track] = []
        self.index: int = -1
        self.current_track: Track | None = None
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.position: float = 0.0
        self.duration: float = 0.0

        self._proxy = _AuthStreamProxy(api, quality=quality)
        self._proc: subprocess.Popen | None = None
        self._sock_path: str = ""
        self._vlc_port: int = 0
        self._backend: str = self._detect_backend()
        self._stop_monitor = threading.Event()
        self._lock = threading.RLock()
        self._playback_gen: int = 0
        self._consec_failures: int = 0
        self._started_at: float = 0.0
        self._pending_seek: float = 0.0
        self._last_session_save: float = 0.0
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    @staticmethod
    def _detect_backend() -> str:
        if shutil.which("mpv"):
            return "mpv"
        if shutil.which("cvlc"):
            return "cvlc"
        if shutil.which("ffplay"):
            return "ffplay"
        return "none"

    @property
    def backend_name(self) -> str:
        return self._backend

    @property
    def playback_status(self) -> str:
        if self.current_track is None or not (self.is_playing or self.is_paused):
            return "Stopped"
        return "Paused" if self.is_paused else "Playing"

    def _notify(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def persist_session(self) -> None:
        with self._lock:
            if not self.queue or self.index < 0:
                return
            try:
                save_session([asdict(t) for t in self.queue], self.index, self.position)
                self._last_session_save = time.monotonic()
            except Exception:
                pass

    def restore_saved_session(self) -> bool:
        data = load_session()
        if not data:
            return False
        raw_q = data.get("queue") or []
        if not raw_q:
            return False
        tracks: list[Track] = []
        for item in raw_q:
            if isinstance(item, dict) and item.get("trackhash"):
                tracks.append(
                    Track(
                        trackhash=str(item.get("trackhash", "")),
                        title=str(item.get("title", "Untitled")),
                        filepath=str(item.get("filepath", "")),
                        artists=str(item.get("artists", "Unknown Artist")),
                        album=str(item.get("album", "")),
                        albumhash=str(item.get("albumhash", "")),
                        duration=int(item.get("duration") or 0),
                        track_num=int(item.get("track_num") or 0),
                        disc=int(item.get("disc") or 1),
                        bitrate=int(item.get("bitrate") or 0),
                        is_favorite=bool(item.get("is_favorite", False)),
                        last_mod=float(item.get("last_mod") or 0.0),
                        date=int(item.get("date") or 0),
                        image=str(item.get("image", "")),
                    )
                )
        if not tracks:
            return False
        idx = max(0, min(int(data.get("index") or 0), len(tracks) - 1))
        pos = max(0.0, float(data.get("position") or 0.0))
        with self._lock:
            self.queue = tracks
            self.index = idx
            self.current_track = tracks[idx]
            self.duration = float(tracks[idx].duration or 0)
            if self.duration > 0:
                pos = min(pos, max(0.0, self.duration - 1.0))
            self.position = pos
            self._pending_seek = pos
            self.is_playing = False
            self.is_paused = True
        self._notify()
        return True

    def play_tracks(self, tracks: list[Track], start_index: int = 0) -> None:
        with self._lock:
            if not tracks:
                return
            self.queue = list(tracks)
            self.index = max(0, min(start_index, len(self.queue) - 1))
            self._pending_seek = 0.0
            self._start_current()
            self.persist_session()

    def enqueue(self, track: Track) -> None:
        with self._lock:
            self.queue.append(track)
            if self.current_track is None:
                self.index = len(self.queue) - 1
                self._start_current()
            else:
                self._notify()

    def _kill_proc(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._sock_path and os.path.exists(self._sock_path):
            try:
                os.unlink(self._sock_path)
            except OSError:
                pass
            self._sock_path = ""

    def _start_current(self, start_pos: float = 0.0) -> None:
        self._kill_proc()
        if not (0 <= self.index < len(self.queue)):
            self.current_track = None
            self.is_playing = False
            self.is_paused = False
            self.position = 0.0
            self.duration = 0.0
            self._notify()
            return

        track = self.queue[self.index]
        self.current_track = track
        self.position = max(0.0, float(start_pos))
        self.duration = float(track.duration or 0)
        self.is_playing = True
        self.is_paused = False
        self._playback_gen += 1
        self._pending_seek = 0.0

        stream_url = self._proxy.register(track)
        tmp_dir = tempfile.gettempdir()
        self._sock_path = os.path.join(tmp_dir, f"swingmusic-tui-{os.getpid()}-{self._playback_gen}.sock")

        if self._backend == "mpv":
            cmd = [
                "mpv",
                "--no-video",
                "--no-terminal",
                "--really-quiet",
                f"--volume={self.volume}",
                f"--input-ipc-server={self._sock_path}",
            ]
            if start_pos > 0.5:
                cmd.append(f"--start={start_pos:.1f}")
            cmd.append(stream_url)
        elif self._backend == "cvlc":
            vlc_vol = int(round(self.volume * 2.56))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                self._vlc_port = s.getsockname()[1]
            cmd = [
                "cvlc",
                "--no-video",
                "--play-and-exit",
                "--quiet",
                "-I",
                "dummy",
                "--extraintf",
                "rc",
                "--rc-host",
                f"127.0.0.1:{self._vlc_port}",
            ]
            if start_pos > 0.5:
                cmd.append(f"--start-time={int(start_pos)}")
            cmd.append(stream_url)
            self._pending_vlc_vol = vlc_vol
        elif self._backend == "ffplay":
            cmd = [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(self.volume),
            ]
            if start_pos > 0.5:
                cmd.extend(["-ss", f"{start_pos:.1f}"])
            cmd.append(stream_url)
        else:
            self.is_playing = False
            self._notify()
            return

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._started_at = time.monotonic()
        self._notify()

    def _mpv_cmd(self, command: list) -> dict | None:
        if not self._sock_path or not os.path.exists(self._sock_path):
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.4)
                s.connect(self._sock_path)
                s.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
                data = s.recv(4096).decode("utf-8", errors="ignore")
                for line in data.splitlines():
                    if line.strip():
                        return json.loads(line)
        except Exception:
            return None
        return None

    def _vlc_cmd(self, command: str) -> str:
        if not self._vlc_port:
            return ""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.35)
                s.connect(("127.0.0.1", self._vlc_port))
                # Drain greeting banner if present
                s.settimeout(0.05)
                try:
                    s.recv(1024)
                except socket.timeout:
                    pass
                s.settimeout(0.35)
                s.sendall((command + "\n").encode("utf-8"))
                time.sleep(0.04)
                try:
                    return s.recv(2048).decode("utf-8", errors="ignore")
                except socket.timeout:
                    return ""
        except Exception:
            return ""

    def toggle_pause(self) -> None:
        with self._lock:
            if self.current_track is None:
                if self.queue:
                    self.index = max(0, self.index)
                    self._start_current()
                return
            if self._proc is None:
                # Resuming a restored session track from its saved timestamp!
                self._start_current(start_pos=self._pending_seek or self.position)
                self.persist_session()
                return
            if self._backend == "mpv":
                self._mpv_cmd(["cycle", "pause"])
                self.is_paused = not self.is_paused
                self.is_playing = not self.is_paused
            elif self._backend == "cvlc":
                self._vlc_cmd("pause")
                self.is_paused = not self.is_paused
                self.is_playing = not self.is_paused
            else:
                # ffplay cannot pause via IPC; stop/restart fallback
                if self.is_playing:
                    self._kill_proc()
                    self.is_playing = False
                    self.is_paused = True
                else:
                    self._start_current(start_pos=self.position)
            self.persist_session()
            self._notify()

    def play(self) -> None:
        with self._lock:
            if self.is_paused:
                self.toggle_pause()
            elif self.current_track is None and self.queue:
                self.index = max(0, self.index)
                self._start_current()

    def pause(self) -> None:
        with self._lock:
            if self.is_playing and not self.is_paused:
                self.toggle_pause()

    def stop(self) -> None:
        with self._lock:
            self._kill_proc()
            self.is_playing = False
            self.is_paused = False
            self.position = 0.0
            self._notify()

    def next_track(self) -> None:
        with self._lock:
            if not self.queue:
                return
            if self.repeat == "one" and self.current_track is not None:
                self._start_current()
                return
            if self.shuffle and len(self.queue) > 1:
                candidates = [i for i in range(len(self.queue)) if i != self.index]
                self.index = random.choice(candidates)
                self._start_current()
                return
            if self.index + 1 < len(self.queue):
                self.index += 1
                self._start_current()
            elif self.repeat == "all":
                self.index = 0
                self._start_current()
            else:
                self.stop()

    def prev_track(self) -> None:
        with self._lock:
            if not self.queue:
                return
            if self.position > 4.0:
                self.seek(-self.position)
                return
            if self.index > 0:
                self.index -= 1
                self._start_current()
            elif self.repeat == "all":
                self.index = len(self.queue) - 1
                self._start_current()
            else:
                self._start_current()

    def seek(self, delta_seconds: float) -> None:
        with self._lock:
            if self.current_track is None:
                return
            target = max(0.0, self.position + delta_seconds)
            if self.duration > 0:
                target = min(self.duration - 1.0, target)
            if self._backend == "mpv":
                self._mpv_cmd(["seek", delta_seconds, "relative"])
                self.position = target
            elif self._backend == "cvlc":
                self._vlc_cmd(f"seek {int(target)}")
                self.position = target
            self._notify()

    def set_volume(self, vol: int) -> None:
        with self._lock:
            self.volume = max(0, min(100, vol))
            if self._backend == "mpv":
                self._mpv_cmd(["set_property", "volume", self.volume])
            elif self._backend == "cvlc":
                self._vlc_cmd(f"volume {int(round(self.volume * 2.56))}")
            self._notify()

    def toggle_shuffle(self) -> bool:
        with self._lock:
            self.shuffle = not self.shuffle
            self._notify()
            return self.shuffle

    def cycle_repeat(self) -> str:
        with self._lock:
            order = ["off", "all", "one"]
            self.repeat = order[(order.index(self.repeat) + 1) % len(order)]
            self._notify()
            return self.repeat

    def _monitor_loop(self) -> None:
        while not self._stop_monitor.is_set():
            time.sleep(0.5)
            with self._lock:
                proc = self._proc
                if proc is None:
                    continue

                if proc.poll() is not None:
                    # Track finished or failed
                    self._proc = None
                    elapsed = time.monotonic() - self._started_at
                    if elapsed < 1.5:
                        self._consec_failures += 1
                    else:
                        self._consec_failures = 0
                    if self.is_playing and not self.is_paused:
                        if self._consec_failures >= 3:
                            self.is_playing = False
                            self.is_paused = False
                            self._consec_failures = 0
                            self._notify()
                        else:
                            self.next_track()
                    continue
                elif time.monotonic() - self._started_at >= 2.0:
                    self._consec_failures = 0

                if self._backend == "mpv":
                    pos_res = self._mpv_cmd(["get_property", "time-pos"])
                    if pos_res and isinstance(pos_res.get("data"), (int, float)):
                        self.position = float(pos_res["data"])
                    dur_res = self._mpv_cmd(["get_property", "duration"])
                    if dur_res and isinstance(dur_res.get("data"), (int, float)):
                        self.duration = float(dur_res["data"])
                elif self._backend == "cvlc":
                    if getattr(self, "_pending_vlc_vol", None) is not None and self._vlc_port:
                        if self._vlc_cmd(f"volume {self._pending_vlc_vol}") or True:
                            self._pending_vlc_vol = None
                    out = self._vlc_cmd("get_time")
                    for line in out.splitlines():
                        line = line.lstrip("> ").strip()
                        if line.isdigit():
                            self.position = float(int(line))
                            break
                    if self.duration <= 0:
                        dout = self._vlc_cmd("get_length")
                        for line in dout.splitlines():
                            line = line.lstrip("> ").strip()
                            if line.isdigit() and int(line) > 0:
                                self.duration = float(int(line))
                                break
                elif self._backend == "ffplay" and self.is_playing and not self.is_paused:
                    self.position += 0.5

                # Periodically save session every 3s while playing so closing the window preserves timestamp
                if self.is_playing and not self.is_paused and (time.monotonic() - self._last_session_save >= 3.0):
                    self.persist_session()

    def shutdown(self) -> None:
        self._stop_monitor.set()
        self.persist_session()
        with self._lock:
            self._kill_proc()
        self._proxy.stop()
