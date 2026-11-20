"""Native D-Bus MPRIS2 service (org.mpris.MediaPlayer2.swingmusic_tui)."""

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from dbus_next import Variant
from dbus_next.aio import MessageBus
from dbus_next.service import PropertyAccess, ServiceInterface, dbus_property, method

if TYPE_CHECKING:
    from .player import AudioPlayer

BUS_NAME = "org.mpris.MediaPlayer2.swingmusic_tui"
OBJECT_PATH = "/org/mpris/MediaPlayer2"


class _MediaPlayer2Interface(ServiceInterface):
    def __init__(self) -> None:
        super().__init__("org.mpris.MediaPlayer2")

    @method()
    def Raise(self):
        return

    @method()
    def Quit(self):
        return

    @dbus_property(access=PropertyAccess.READ)
    def CanQuit(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> "s":
        return "Swing Music"

    @dbus_property(access=PropertyAccess.READ)
    def DesktopEntry(self) -> "s":
        return "swingmusic-tui"

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> "as":
        return ["http", "https"]

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> "as":
        return ["audio/mpeg", "audio/flac", "audio/ogg", "audio/mp4"]


class _PlayerInterface(ServiceInterface):
    def __init__(self, player: "AudioPlayer") -> None:
        super().__init__("org.mpris.MediaPlayer2.Player")
        self._player = player

    @method()
    def Next(self):
        self._player.next_track()

    @method()
    def Previous(self):
        self._player.prev_track()

    @method()
    def Pause(self):
        self._player.pause()

    @method()
    def PlayPause(self):
        self._player.toggle_pause()

    @method()
    def Stop(self):
        self._player.stop()

    @method()
    def Play(self):
        self._player.play()

    @method()
    def Seek(self, offset: "x"):
        self._player.seek(offset / 1_000_000.0)

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return self._player.playback_status

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        t = self._player.current_track
        if t is None:
            return {"mpris:trackid": Variant("o", "/org/mpris/MediaPlayer2/TrackList/NoTrack")}
        track_id = f"/org/mpris/MediaPlayer2/Track/{t.trackhash or '0'}"
        meta: dict[str, Variant] = {
            "mpris:trackid": Variant("o", track_id),
            "xesam:title": Variant("s", t.title),
            "xesam:artist": Variant("as", [t.artists]),
            "xesam:album": Variant("s", t.album),
        }
        if t.duration > 0:
            meta["mpris:length"] = Variant("x", int(t.duration * 1_000_000))
        return meta

    @dbus_property(access=PropertyAccess.READWRITE)
    def Volume(self) -> "d":
        return self._player.volume / 100.0

    @Volume.setter
    def Volume(self, value: "d") -> None:
        self._player.set_volume(int(round(max(0.0, min(1.0, value)) * 100)))

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":
        return int(self._player.position * 1_000_000)

    @dbus_property(access=PropertyAccess.READ)
    def Rate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> "d":
        return 1.0

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> "b":
        return True

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> "b":
        return True


class MPRISService:
    """Runs the MPRIS2 D-Bus server in a background asyncio thread."""

    def __init__(self, player: "AudioPlayer") -> None:
        self._player = player
        self._loop: asyncio.AbstractEventLoop | None = None
        self._iface: _PlayerInterface | None = None
        self._thread = threading.Thread(target=self._run_thread, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run_thread(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            pass

    async def _serve(self) -> None:
        logging.getLogger().setLevel(logging.CRITICAL)
        bus = await MessageBus().connect()
        root_iface = _MediaPlayer2Interface()
        self._iface = _PlayerInterface(self._player)
        bus.export(OBJECT_PATH, root_iface)
        bus.export(OBJECT_PATH, self._iface)
        await bus.request_name(BUS_NAME)
        await bus.wait_for_disconnect()

    def emit_update(self) -> None:
        if self._loop is None or self._iface is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._emit_now)
        except Exception:
            pass

    def _emit_now(self) -> None:
        if self._iface is None:
            return
        try:
            self._iface.emit_properties_changed(
                {
                    "PlaybackStatus": self._iface.PlaybackStatus,
                    "Metadata": self._iface.Metadata,
                    "Volume": self._iface.Volume,
                }
            )
        except Exception:
            pass

    def stop(self) -> None:
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
