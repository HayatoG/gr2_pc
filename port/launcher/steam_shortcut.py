# SPDX-License-Identifier: GPL-2.0-or-later
"""Adds the game to Steam as a non-Steam game (Windows).

Steam keeps non-Steam games in userdata/<account>/config/shortcuts.vdf, a binary KeyValues file
(type byte, null-terminated key, value; 0x00 map, 0x01 string, 0x02 int32, 0x07 uint64, 0x08 end),
and their art in config/grid/<appid>p.png (portrait), <appid>.png (wide), <appid>_hero.png.
The appid is crc32(exe + name) with the top bit set, stored as a signed int32: the same scheme as
Steam ROM Manager and SteamTinkerLaunch, so the art can be named before Steam starts.
Steam rewrites shortcuts.vdf from memory, so it must be closed while the file is written.
"""
import os
from pathlib import Path
import struct
import subprocess
import time
import zlib

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NAME = 'Gravity Rush 2'
PLAY_EXE = 'Play Gravity Rush 2.exe'
# Library art cut from the dump's letterboxed 1920x1080 sce_sys/pic1.png (picture rows 87-991):
# (file suffix, (left, top, right, bottom), shrink factor). p: portrait 600x900 around Kat;
# '': wide 960x448; _hero: 1920x620. icon0.png is copied as <appid>_icon.png.
ART_CUTS = (('p', (1080, 89, 1680, 989), 1), ('', (0, 91, 1920, 987), 2), ('_hero', (0, 230, 1920, 850), 1))


# -- binary KeyValues ----------------------------------------------------------------------------
def _cstring(data, pos):
    end = data.index(b'\0', pos)
    return data[pos:end].decode('utf-8', 'surrogateescape'), end + 1


def _parse_map(data, pos):
    items = {}
    while True:
        kind = data[pos]
        pos += 1
        if kind == 0x08:
            return items, pos
        key, pos = _cstring(data, pos)
        if kind == 0x00:
            items[key], pos = _parse_map(data, pos)
        elif kind == 0x01:
            items[key], pos = _cstring(data, pos)
        elif kind == 0x02:
            items[key] = struct.unpack_from('<i', data, pos)[0]
            pos += 4
        elif kind == 0x07:
            items[key] = ('u64', struct.unpack_from('<Q', data, pos)[0])
            pos += 8
        else:
            raise ValueError(f'shortcuts.vdf: unknown value type 0x{kind:02x} at byte {pos - 1}')


def loads(data):
    """Bytes of a binary KeyValues file -> nested dicts (the file's root map)."""
    if not data:
        return {}
    items, _ = _parse_map(data + b'\x08', 0)  # the root map has no 0x08 of its own in some files
    return items


def _dump_map(items, out):
    for key, value in items.items():
        name = key.encode('utf-8', 'surrogateescape') + b'\0'
        if isinstance(value, dict):
            out += b'\x00' + name
            _dump_map(value, out)
        elif isinstance(value, tuple) and value[0] == 'u64':
            out += b'\x07' + name + struct.pack('<Q', value[1])
        elif isinstance(value, int):
            out += b'\x02' + name + struct.pack('<i', value)
        else:
            out += b'\x01' + name + str(value).encode('utf-8', 'surrogateescape') + b'\0'
    out += b'\x08'


def dumps(items):
    out = bytearray()
    _dump_map(items, out)
    return bytes(out)


# -- Steam on this PC ----------------------------------------------------------------------------
def steam_dir():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
            path = Path(winreg.QueryValueEx(key, 'SteamPath')[0])
    except OSError:
        return None
    return path if (path / 'userdata').is_dir() else None


def _account_ids(steam):
    """The account that signed in last (loginusers.vdf: MostRecent, else the newest timestamp)."""
    best, best_rank = None, None
    try:
        text = (steam / 'config' / 'loginusers.vdf').read_text(encoding='utf-8', errors='replace')
    except OSError:
        text = ''
    user, fields = None, {}
    for raw in text.splitlines():
        parts = [p for p in raw.strip().split('"') if p.strip()]
        if len(parts) == 1 and parts[0].isdigit():
            user, fields = int(parts[0]), {}
        elif len(parts) == 2 and user:
            fields[parts[0].lower()] = parts[1]
            rank = (fields.get('mostrecent') == '1', int(fields.get('timestamp', '0') or 0))
            if best_rank is None or rank > best_rank:
                best, best_rank = user, rank
    if best:
        account = str(best - 76561197960265728)
        if (steam / 'userdata' / account).is_dir():
            return [account]
    return [p.name for p in (steam / 'userdata').iterdir() if p.name.isdigit() and p.name != '0']


def steam_running():
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq steam.exe', '/NH'], capture_output=True,
                            text=True, creationflags=NO_WINDOW)
    return 'steam.exe' in result.stdout.lower()


def close_steam(steam, timeout=60):
    """Asks Steam to exit (steam.exe -shutdown) and waits for it; True once it is gone."""
    subprocess.Popen([str(steam / 'steam.exe'), '-shutdown'], creationflags=NO_WINDOW)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1)
        if not steam_running():
            time.sleep(2)  # let it finish writing its own files
            return True
    return False


def start_steam(steam):
    subprocess.Popen([str(steam / 'steam.exe')], creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0),
                     close_fds=True)


# -- the shortcut --------------------------------------------------------------------------------
def shortcut_appid(exe_field, name):
    return zlib.crc32((exe_field + name).encode('utf-8')) | 0x80000000


def add_shortcut(steam, name, exe, start_dir):
    """Adds or updates the shortcut for `exe` in the signed-in account's shortcuts.vdf; its icon is
    grid/<appid>_icon.png, which the caller writes. Returns [(grid folder, unsigned appid)].
    Steam must not be running."""
    exe_field = f'"{exe}"'
    results = []
    for account in _account_ids(steam):
        config = steam / 'userdata' / account / 'config'
        config.mkdir(parents=True, exist_ok=True)
        path = config / 'shortcuts.vdf'
        data = path.read_bytes() if path.is_file() else b''
        root = loads(data)
        shortcuts = root.setdefault('shortcuts', {})
        entry = next((e for e in shortcuts.values() if isinstance(e, dict) and
                      str(e.get('Exe', e.get('exe', ''))).strip('"').lower() == str(exe).lower()), None)
        if entry is None:
            entry = {'appid': shortcut_appid(exe_field, name) - 0x100000000}
            shortcuts[str(max((int(k) for k in shortcuts if k.isdigit()), default=-1) + 1)] = entry
        entry.pop('appname', None)
        entry.pop('exe', None)
        grid, appid = config / 'grid', entry['appid'] & 0xFFFFFFFF
        entry.update({'AppName': name, 'Exe': exe_field, 'StartDir': f'"{start_dir}"',
                      'icon': str(grid / f'{appid}_icon.png')})
        for key, value in (('ShortcutPath', ''), ('LaunchOptions', ''), ('IsHidden', 0),
                           ('AllowDesktopConfig', 1), ('AllowOverlay', 1), ('OpenVR', 0), ('Devkit', 0),
                           ('DevkitGameID', ''), ('DevkitOverrideAppID', 0), ('LastPlayTime', 0),
                           ('FlatpakAppID', ''), ('tags', {})):
            entry.setdefault(key, value)
        if data:
            (config / 'shortcuts.vdf.bak').write_bytes(data)
        temp = config / 'shortcuts.vdf.tmp'
        temp.write_bytes(dumps(root))
        os.replace(temp, path)
        results.append((grid, appid))
    return results


def install(steam, exe, close_first, write_art):
    """The whole "Add to Steam": closes Steam when asked (False if it would not close), writes the
    shortcut, lets write_art([(grid, appid)]) put the art in place, opens Steam again if it was
    closed here. Art problems never undo the shortcut; they come back as the second value."""
    if close_first and not close_steam(steam):
        return False, None
    added = add_shortcut(steam, NAME, exe, Path(exe).parent)
    art_error = None
    try:
        write_art(added)
    except Exception as error:  # the shortcut is there; only the pictures failed
        art_error = error
    if close_first:
        start_steam(steam)
    return True, art_error
