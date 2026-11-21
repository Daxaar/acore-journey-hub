"""Serve existing outdoor map tiles from the configured local Wrath client."""
from collections import OrderedDict, deque
import os
import time
import re
import struct
import threading
import zlib

from client_models import Archives, blp, client_path


def png_tile(data):
    width, height, rgba = blp(data)
    if not (0 < width <= 256 and 0 < height <= 256):
        raise ValueError('Unsupported world map tile size')

    def chunk(kind, body):
        return (struct.pack('>I', len(body)) + kind + body
                + struct.pack('>I', zlib.crc32(kind + body)))

    stride = width * 4
    scanlines = b''.join(b'\0' + rgba[offset:offset+stride]
                         for offset in range(0, len(rgba), stride))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(scanlines, 3))
            + chunk(b'IEND', b''))


class ClientMapTiles:
    TTL = 20 * 60
    MAX_BYTES = 64 * 1024 * 1024
    MAX_ENTRIES = 32

    def __init__(self):
        self.condition = threading.Condition()
        self.cache = OrderedDict()
        self.bytes = 0
        self.pending = deque()
        self.loading = False
        self.foreground = 0
        self.warm_until = 0
        self.worker = None

    def _start_worker(self):
        if self.worker is None:
            self.worker = threading.Thread(target=self._run, name='map-preload', daemon=True)
            self.worker.start()

    def _prune(self):
        now = time.monotonic()
        while self.cache:
            key, (_, size, expires) = next(iter(self.cache.items()))
            if expires > now and self.bytes <= self.MAX_BYTES and len(self.cache) <= self.MAX_ENTRIES:
                break
            del self.cache[key]
            self.bytes -= size

    def _decode(self, key):
        try:
            result = self._load(*key)
            size = sum(map(len, result[0])) + sum(len(tile[-1]) for tile in result[1]) if result else 0
            with self.condition:
                if size <= self.MAX_BYTES:
                    self.cache[key] = (result, size, time.monotonic() + self.TTL)
                    self.bytes += size
                    self._prune()
            return result
        finally:
            with self.condition:
                self.loading = False
                self.condition.notify_all()

    def get(self, folder, map_id, zone_id):
        if not folder:
            return None
        key = (folder, map_id, zone_id)
        with self.condition:
            self._start_worker()
            self.foreground += 1
            try:
                while True:
                    self._prune()
                    if key in self.cache:
                        result, size, _ = self.cache.pop(key)
                        self.cache[key] = (result, size, time.monotonic() + self.TTL)
                        return result
                    if not self.loading:
                        self.loading = True
                        break
                    self.condition.wait()
            finally:
                self.foreground -= 1
        return self._decode(key)

    def warm(self, folder, zones, enabled):
        if not folder:
            return 0
        with self.condition:
            now = time.monotonic()
            if now < self.warm_until:
                return 0
            self.warm_until = now + self.TTL
            self._prune()
            maps = [(0, 0), (1, 0), (530, 0), (571, 0), *zones[:8]]
            self.pending = deque((folder, m, z) for m, z in dict.fromkeys(maps)
                                 if (folder, m, z) not in self.cache)
            self.warming_enabled = enabled
            self._start_worker()
            self.condition.notify_all()
            return len(self.pending)

    def _run(self):
        # Linux applies per-thread niceness, leaving the HTTP handlers at their usual priority.
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except (AttributeError, OSError):
            pass
        while True:
            with self.condition:
                self._prune()
                if self.pending and not self.warming_enabled():
                    self.pending.clear()
                if not self.pending or self.loading or self.foreground:
                    self.condition.wait(timeout=30)
                    continue
                key = self.pending.popleft()
                if key in self.cache:
                    continue
                self.loading = True
            try:
                self._decode(key)
            except Exception:
                # A failed background load must never prevent on-demand loading.
                pass
            time.sleep(1)

    @staticmethod
    def _load(folder, map_id, zone_id):
        try:
            archives = Archives(client_path(folder))
            try:
                data = archives.read(r'DBFilesClient\WorldMapArea.dbc')
                magic, count, fields, size, strings = struct.unpack_from('<4s4I', data)
                base = 20 + count * size
                if (magic, fields, size) != (b'WDBC', 11, 44) or base + strings != len(data):
                    return None
                for offset in range(20, base, size):
                    area_key, map_key, zone_key, name_offset = struct.unpack_from('<4I', data, offset)
                    floor = struct.unpack_from('<i', data, offset+36)[0]
                    if (map_key, zone_key) != (map_id, zone_id) or floor > 0 or name_offset >= strings:
                        continue
                    start = base + name_offset
                    name = data[start:data.index(b'\0', start)].decode('ascii')
                    if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', name):
                        continue
                    folder_name = 'Interface\\WorldMap\\' + name + '\\' + name
                    tiles = [png_tile(archives.read(folder_name + str(i) + '.blp'))
                             for i in range(1, 13)]
                    overlays = []
                    try:
                        overlays = exploration_tiles(archives, name, area_key)
                    except (OSError, ValueError, RuntimeError, NotImplementedError, struct.error, zlib.error):
                        pass
                    return tiles, overlays
            finally:
                archives.close()
        except (OSError, ValueError, RuntimeError, NotImplementedError, struct.error, zlib.error):
            return None
        return None

def exploration_tiles(archives, map_name, area_key):
    data = archives.read(r'DBFilesClient\WorldMapOverlay.dbc')
    magic, count, fields, size, strings = struct.unpack_from('<4s4I', data)
    base = 20 + count * size
    if (magic, fields, size) != (b'WDBC', 17, 68) or base + strings != len(data):
        return []
    tiles = []
    for offset in range(20, base, size):
        overlay_area = struct.unpack_from('<I', data, offset + 4)[0]
        if overlay_area != area_key:
            continue
        name_offset, width, height, x, y = struct.unpack_from('<IIIii', data, offset + 32)
        if name_offset >= strings or not (0 < width <= 1024 and 0 < height <= 1024):
            continue
        start = base + name_offset
        name = data[start:data.index(b'\0', start)].decode('ascii')
        if not re.fullmatch(r'[A-Za-z0-9_]{1,64}', name):
            continue
        path = 'Interface\\WorldMap\\' + map_name + '\\' + name
        parts = []
        try:
            for row in range(0, height, 256):
                for col in range(0, width, 256):
                    tile = png_tile(archives.read(path + str(len(parts)+1) + '.blp'))
                    parts.append((x+col, y+row, min(256, width-col), min(256, height-row), tile))
        except (OSError, ValueError, RuntimeError, NotImplementedError, struct.error, zlib.error):
            continue
        tiles.extend(parts)
    return tiles
