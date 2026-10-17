#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare and run Gravity Rush 2 (CUSA03694) through the native loader.

Shared by the command line (run_gr2.sh -> `gr2_run.py [seconds]`) and the launcher window
(gr2_launcher.py), so both start the game the same way:
  1. prepare.py / link_modules.py / content_profile.py build out/boot-linked.bin from the game
     folder (eboot + the game's libc, Fios2, JobManager and sysdata/libSceSecure, and
     libSceNgs2.sprx from the console firmware when present: native audio; otherwise the
     built-in mixer, runtime_ngs2.c); on a CPU without the PS4's SSE4A/MOVBE/BMI1/LZCNT
     (every Intel CPU lacks SSE4A) isa_rewrite.py writes out/isa-rewrite.bin, the
     instruction sites tlg-probe emulates;
  2. the TLG defaults below become TLG_* environment variables (each one validated in play);
  3. tlg-probe runs with its output in out/logs/run-<date>.log (last_run.log points to it).
"""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import shader_cache

# A packaged build (PyInstaller) keeps its folders next to the executable: scripts/, out/, user/.
FROZEN = bool(getattr(sys, 'frozen', False))
PORT_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
REPO_DIR = PORT_DIR.parent
sys.path.insert(0, str(PORT_DIR / 'scripts'))
import mod_patches  # noqa: E402
OUT_DIR = PORT_DIR / 'out'
USER_DIR = PORT_DIR / 'user'
MODS_DIR = USER_DIR / 'mods'          # shadPS4/GoldHEN cheat XML files the player drops in
MODS_CONFIG = USER_DIR / 'mods.json'  # {"enabled": [...], "disabled": [...]}
LOG_DIR = OUT_DIR / 'logs'
PROBE = OUT_DIR / ('tlg-probe.exe' if os.name == 'nt' else 'tlg-probe')
KEEP_LOGS = 30

# Game language: PS4 system language ids the game ships voice/text archives for.
GAME_LANGUAGES = {'en': 1, 'pt_BR': 17, 'es_LA': 20, 'fr_CA': 22}

# TLG defaults (see README "Opções" and the reasons in each comment).
DEFAULT_ENV = {
    'TLG_PIPELINE_BINARIES': '0',  # VK_KHR_pipeline_binary crashes on the NVIDIA 595 driver
    'TLG_READBACKS': '2',          # the game reads GPU compute results on the CPU (AsyncMap)
    'TLG_GC_BUDGET_MB': '5600',    # texture cache budget for 6 GB of VRAM
    'TLG_UPSCALER': 'off',         # native image: GoW3's temporal upscalers made it shake
    'TLG_JITTER': '0',
    'TLG_OBJECT_MOTION': '0',
    'TLG_FRAME_STATS': '1',        # FPS in the log every 5 s (scripts/watch_session.sh heartbeat)
}
# Gravity Rush 2: the comic outline pass (geometry shader with adjacency) is mistranslated and
# draws black streaks near characters (docs/BUG_LINHAS_PRETAS.md); off by default until fixed.

DEFAULT_SETTINGS = {
    # Source tree: the merged game view and the console modules of ~/decomp. Package: the player
    # picks the game folder; libSceNgs2.sprx goes in system_lib/ next to the executable.
    'game_dir': '' if FROZEN else str(REPO_DIR / 'game' / 'CUSA03694'),
    'system_lib_dir': str(PORT_DIR / 'system_lib') if FROZEN else str(REPO_DIR / 'dump' / 'system_lib'),
    'gs_outline_off': True,        # TLG_SKIP_ADJACENCY: no black streaks (outline pass)
    'game_language': 'pt_BR',
    'ui_language': 'auto',         # auto | pt_BR | en_US
    'show_fps': False,
    'display_mode': 'Windowed',    # Windowed | Borderless | Fullscreen (tlg.ini)
    'vsync': True,
    'vram_budget_mb': 5600,
    'native_audio': True,
}


def config_path():
    base = Path(os.environ.get('APPDATA') or os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'gr2-launcher' / 'settings.json'


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        settings.update(json.loads(config_path().read_text(encoding='utf-8')))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def check_game(game_dir):
    """Problems that keep the game from starting, as (key, detail) pairs; empty means ready."""
    game = Path(game_dir)
    problems = []
    if not (game / 'eboot.bin').is_file():
        problems.append(('missing', 'eboot.bin'))
    for module in ('libc.prx', 'libSceFios2.prx', 'libSceJobManager.prx'):
        if not (game / 'sce_module' / module).is_file():
            problems.append(('missing', f'sce_module/{module}'))
    if not (game / 'sysdata' / 'libSceSecure.prx').is_file():
        problems.append(('missing', 'sysdata/libSceSecure.prx'))
    for archive in ('Gravite2_Chunk0.psarc', 'Gravite2_Chunk1.psarc'):
        if not (game / archive).is_file():
            problems.append(('missing', archive))
    if not PROBE.is_file():
        problems.append(('not_built', str(PROBE)))
    return problems


def ngs2_module(settings):
    path = Path(settings['system_lib_dir']) / 'libSceNgs2.sprx'
    return path if settings.get('native_audio', True) and path.is_file() else None


def update_ini(path, values):
    """Sets keys in tlg.ini (the in-game menu's file), keeping every other line."""
    lines = path.read_text(encoding='utf-8').splitlines() if path.is_file() else ['# tlg settings']
    seen = set()
    for i, line in enumerate(lines):
        key = line.split('=', 1)[0].strip()
        if key in values:
            lines[i] = f'{key}={values[key]}'
            seen.add(key)
    lines += [f'{k}={v}' for k, v in values.items() if k not in seen]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


# The serial the GPU backend names this game's shader cache after (another region's copy: its
# param.sfo TITLE_ID, read from the game folder).
SHADER_CACHE_SERIALS = ('CUSA03694',)


def shader_cache_serials(settings):
    serial = shader_cache.title_id(settings['game_dir']) if settings.get('game_dir') else None
    return sorted({*SHADER_CACHE_SERIALS, *([serial] if serial else [])})


def gpu_user_dir():
    """Where the GPU backend keeps its caches (shaders, pipelines): the saves folder, on every OS.
    GR2_GPU_USER_DIR/TLG_GPU_USER_DIR move it (the more specific name wins)."""
    return Path(os.environ.get('GR2_GPU_USER_DIR') or os.environ.get('TLG_GPU_USER_DIR') or USER_DIR)


def shader_cache_size(settings):
    """Bytes of compiled shaders this game has on disk (launcher/shader_cache.py has the paths)."""
    return shader_cache.size(shader_cache_serials(settings), gpu_user_dir())


def clear_shader_cache(settings):
    """Deletes this game's compiled shaders: the next start rebuilds them (longer load, some
    stutter at first). Saves, settings and logs stay. Returns (bytes freed, [(path, error)])."""
    return shader_cache.clear(shader_cache_serials(settings), gpu_user_dir())


def python_command(script):
    """How to run one of scripts/*.py: the packaged executable runs them itself (--script)."""
    if FROZEN:
        return [sys.executable, '--script', str(script)]
    return [sys.executable, str(script)]


def attach_stdio():
    """A windowed Windows executable starts without sys.stdout; inherited pipes still exist."""
    if os.name != 'nt':
        return
    import ctypes
    import msvcrt
    for name, std in (('stdout', -11), ('stderr', -12)):
        if getattr(sys, name) is not None:
            continue
        stream = None
        handle = ctypes.windll.kernel32.GetStdHandle(std)
        if handle and handle != ctypes.c_void_p(-1).value:
            try:
                stream = open(msvcrt.open_osfhandle(handle, os.O_WRONLY), 'w', encoding='utf-8',
                              errors='replace', buffering=1)
            except OSError:
                stream = None
        setattr(sys, name, stream or open(os.devnull, 'w'))


NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)  # no console flashing for the scripts


def run_script(argv):
    """--script <path> [args]: runs a preparation script inside the packaged executable."""
    import runpy
    attach_stdio()
    script = Path(argv[0])
    sys.argv = [str(script), *argv[1:]]
    sys.path.insert(0, str(script.parent))
    try:
        runpy.run_path(str(script), run_name='__main__')
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
    return 0


def mods_dir():
    """TLG_MODS_DIR, else USER_DIR/mods (created empty on first use so the player sees where
    to drop shadPS4/GoldHEN cheat XML files)."""
    directory = Path(os.environ.get('TLG_MODS_DIR') or MODS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def mods_config():
    return Path(os.environ.get('TLG_MODS_CONFIG') or MODS_CONFIG)


def list_mods(settings):
    """[(key, name, note, enabled)] for the Mods tab: every shadPS4/GoldHEN cheat XML found in
    the mods folder for this game's version, with its current enabled state."""
    from gr2_patches import TITLE_IDS
    app_version = mod_patches.game_app_version(settings['game_dir'])
    found = mod_patches.external_patches(mods_dir(), app_version, TITLE_IDS)
    selected = {key for key, _, _ in mod_patches.external_selection(found, mods_config())}
    return [(key, meta.get('Name'), meta.get('Note', ''), key in selected) for key, _, meta in found]


def set_mod_enabled(key, enabled):
    """Updates mods.json: moves key into enabled/disabled, out of the other list."""
    path = mods_config()
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    on, off = set(data.get('enabled', [])), set(data.get('disabled', []))
    (on if enabled else off).add(key)
    (off if enabled else on).discard(key)
    path.write_text(json.dumps({'enabled': sorted(on), 'disabled': sorted(off)}, indent=2))


def prepare(settings, log=print):
    """Builds out/boot-linked.bin, out/content.bin and out/patches.bin (mods); returns the
    module list that was linked."""
    game = settings['game_dir']
    scripts = PORT_DIR / 'scripts'
    modules = ['libc.prx', 'libSceFios2.prx', 'libSceJobManager.prx',
               str(Path(game) / 'sysdata' / 'libSceSecure.prx')]
    ngs2 = ngs2_module(settings)
    if ngs2:
        modules.append(str(ngs2))
    steps = [
        [*python_command(scripts / 'prepare.py'), game, '--out', str(OUT_DIR)],
        [*python_command(scripts / 'link_modules.py'), game, '--out', str(OUT_DIR), '--modules', *modules],
        [*python_command(scripts / 'content_profile.py'), game, '--out', str(OUT_DIR)],
        [*python_command(scripts / 'gr2_patches.py'), game, '--out', str(OUT_DIR),
         '--mods-dir', str(mods_dir()), '--mods-config', str(mods_config())],
    ]
    for step in steps:
        result = subprocess.run(step, cwd=str(scripts), capture_output=True, text=True,
                                creationflags=NO_WINDOW)
        if result.returncode:
            name = next(Path(arg).name for arg in step if arg.endswith('.py'))
            raise RuntimeError(f'{name}: {result.stderr.strip() or result.stdout.strip()}')
        for line in result.stdout.splitlines():
            log(line)
    isa_table(log)
    return modules


ISA_TABLE = OUT_DIR / 'isa-rewrite.bin'


def probe_env():
    """The environment tlg-probe needs to start: on Linux the libraries packaged with the port
    (SDL3, FFmpeg, ...) live in out/lib, and the frozen launcher's own LD_LIBRARY_PATH (PyInstaller's
    _internal) is replaced by the one it had at start."""
    env = os.environ.copy()
    if os.name != 'nt':
        original = env.pop('LD_LIBRARY_PATH_ORIG', None) if FROZEN else env.get('LD_LIBRARY_PATH')
        bundled = OUT_DIR / 'lib'
        paths = [str(bundled)] if bundled.is_dir() else []
        if original:
            paths.append(original)
        if paths:
            env['LD_LIBRARY_PATH'] = os.pathsep.join(paths)
        else:
            env.pop('LD_LIBRARY_PATH', None)
    return env


def cpu_missing_sets(log=print):
    """Instruction sets `tlg-probe --cpu-features` reports missing ([] when complete); None when the
    probe could not tell (it did not start: the table is then built anyway, see isa_table). A CPU
    that lacks a set nothing can rewrite (AVX and older) stops here (exit 20) with the probe's reason."""
    try:
        result = subprocess.run([str(PROBE), '--cpu-features'], stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=30, creationflags=NO_WINDOW, env=probe_env())
    except (OSError, subprocess.SubprocessError):
        return []  # no probe yet: check_game reports it
    if result.returncode == 20:
        raise RuntimeError(result.stdout.strip() or 'this CPU cannot run the game')
    for line in result.stdout.splitlines():
        if line.startswith('CPU: missing '):
            return [name.strip() for name in line[len('CPU: missing '):].split(',') if name.strip()]
        if line.startswith('CPU: complete'):
            return []
    # Linux players with Intel CPUs met this: the probe could not load its libraries, so the CPU
    # looked complete, no table was built and the game stopped ("no rewrite table matches").
    detail = (result.stderr or result.stdout).strip().splitlines()
    log(f'CPU check failed (exit {result.returncode}): {detail[-1] if detail else "no output"}; '
        'building the instruction rewrite table anyway')
    return None


def red_zone_wanted(env=None):
    """Windows red-zone protection (scripts/red_zone.py, from iss_pc #29/#41): on by default on
    Windows, GR2_RED_ZONE_REWRITE=0 turns it off; on Linux only GR2_RED_ZONE_REWRITE=1 (tests) turns
    it on. TLG_RED_ZONE_REWRITE is still accepted."""
    env = os.environ if env is None else env
    policy = env.get('GR2_RED_ZONE_REWRITE') or env.get('TLG_RED_ZONE_REWRITE') or ''
    return policy != '0' if os.name == 'nt' else policy == '1'


def isa_table(log=print):
    """ps4_core ISA rewrite (upstream gow3_pc #129): on a CPU without MOVBE, BMI1, LZCNT or SSE4A
    (every Intel CPU: Gravity Rush 2 has 96 EXTRQ) the probe replaces those instructions in the
    image, from the table scripts/isa_rewrite.py writes (iced-x86). GR2_ISA_REWRITE=1 (every set)
    or a list such as GR2_ISA_REWRITE=sse4a builds it on any CPU (testing), =0 never; TLG_ISA_REWRITE
    is still accepted. The same table carries the red-zone protection (red_zone_wanted), so on
    Windows it is always built; the script keeps a table that already matches the image. A failed
    table is reported and the probe then explains what is missing."""
    policy = os.environ.get('GR2_ISA_REWRITE') or os.environ.get('TLG_ISA_REWRITE') or ''
    red_zone = red_zone_wanted()
    if not red_zone:
        ISA_TABLE.unlink(missing_ok=True)  # always matches the boot-linked.bin just written
    missing = cpu_missing_sets(log)
    # None (unknown) builds it too: the probe only rewrites the sets this CPU really lacks.
    if not ((policy and policy != '0') or (policy != '0' and (missing is None or missing)) or red_zone):
        return
    scripts = PORT_DIR / 'scripts'
    result = subprocess.run([*python_command(scripts / 'isa_rewrite.py'), str(OUT_DIR / 'boot-linked.bin'),
                             '--out', str(OUT_DIR), *(['--red-zone'] if red_zone else [])], cwd=str(scripts),
                            capture_output=True, text=True, creationflags=NO_WINDOW)
    if result.returncode:
        ISA_TABLE.unlink(missing_ok=True)
    for line in (result.stdout + result.stderr).splitlines():
        log(line)


def window_icon(settings):
    """The game's own icon0.png converted to BMP (SDL's built-in format) in out/; None if absent."""
    source = Path(settings['game_dir']) / 'sce_sys' / 'icon0.png'
    target = OUT_DIR / 'window_icon.bmp'
    try:
        if source.is_file() and (not target.is_file() or target.stat().st_mtime < source.stat().st_mtime):
            from PIL import Image  # optional: without Pillow the window keeps the default icon
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            Image.open(source).convert('RGB').resize((128, 128)).save(target)
        return target if target.is_file() else None
    except Exception:
        return None


def build_env(settings, extra=None):
    env = dict(os.environ)
    for key, value in DEFAULT_ENV.items():
        env.setdefault(key, value)  # explicit TLG_* in the environment always win
    env['TLG_GC_BUDGET_MB'] = os.environ.get('TLG_GC_BUDGET_MB', str(int(settings['vram_budget_mb'])))
    env['TLG_LANGUAGE'] = os.environ.get('TLG_LANGUAGE', str(GAME_LANGUAGES.get(settings['game_language'], 1)))
    if settings.get('ui_language', 'auto') != 'auto':
        env['TLG_UI_LANG'] = settings['ui_language']
    # Without the console module the port's own mixer (runtime_ngs2.c) plays the audio.
    env['TLG_NGS2'] = 'native' if ngs2_module(settings) else 'hle'
    env['TLG_CONFIG'] = str(USER_DIR / 'tlg.ini')
    # Window name, app id (matches gr2-pc.desktop for Alt+Tab and the dock) and icon.
    env.setdefault('TLG_APP_NAME', 'Gravity Rush 2')
    env.setdefault('TLG_APP_ID', 'gr2-pc')
    icon = window_icon(settings)
    if icon:
        env.setdefault('TLG_WINDOW_ICON', str(icon))
    if settings.get('gs_outline_off', True):
        env.setdefault('TLG_SKIP_ADJACENCY', '1')
    restart = f'"{sys.executable}" --play' if FROZEN else f'"{sys.executable}" "{Path(__file__).resolve()}"'
    env.setdefault('TLG_RESTART_COMMAND', restart)
    # Linux package: the libraries built with the port (SDL3, FFmpeg, ...) are in out/lib.
    if os.name != 'nt':
        libraries = probe_env().get('LD_LIBRARY_PATH')
        if libraries:
            env['LD_LIBRARY_PATH'] = libraries
        else:
            env.pop('LD_LIBRARY_PATH', None)
    # Shaders and pipelines beside the saves (the GPU reads it when it starts; before, Linux used
    # shadPS4's ~/.local/share/shadPS4 and Windows <saves>/user).
    env['TLG_GPU_USER_DIR'] = str(gpu_user_dir())
    if extra:
        env.update(extra)
    return env


def new_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f'run-{datetime.datetime.now():%Y%m%d-%H%M%S}.log'
    latest = OUT_DIR / 'last_run.log'
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(log)
    except OSError:
        pass
    for old in sorted(LOG_DIR.glob('run-*.log'), reverse=True)[KEEP_LOGS:]:
        old.unlink(missing_ok=True)
    return log


def launch(settings, seconds=0, extra_env=None):
    """Writes the in-game settings, starts the game; returns (process, log path).
    The process's combined output is a text pipe; the caller copies it to the log."""
    USER_DIR.mkdir(parents=True, exist_ok=True)
    update_ini(USER_DIR / 'tlg.ini', {
        'display_mode': str(settings['display_mode']).lower(),  # the game's keys: windowed|borderless|fullscreen
        'vsync': int(bool(settings['vsync'])),
        'show_fps': int(bool(settings['show_fps'])),
    })
    log = new_log()
    cmd = [str(PROBE), str(OUT_DIR / 'boot-linked.bin'), '--app0', settings['game_dir'],
           '--user', str(USER_DIR), '--content-profile', str(OUT_DIR / 'content.bin'),
           '--patches', str(OUT_DIR / 'patches.bin'), '--timeout', str(int(seconds))]
    if ISA_TABLE.is_file():
        cmd += ['--isa-rewrite', str(ISA_TABLE)]
    process = subprocess.Popen(cmd, cwd=str(USER_DIR), env=build_env(settings, extra_env),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding='utf-8', errors='replace', bufsize=1)
    return process, log


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    attach_stdio()
    seconds = int(argv[0]) if argv and argv[0].isdigit() else 0
    settings = load_settings()
    if os.environ.get('TLG_GAME_DIR'):
        settings['game_dir'] = os.environ['TLG_GAME_DIR']
    if argv[:1] == ['--clear-shader-cache']:
        freed, failures = clear_shader_cache(settings)
        print(f'Cache de shaders: {shader_cache.human_size(freed)} liberados', flush=True)
        for path, error in failures:
            print(f'Não apagado (em uso? feche o jogo): {path}: {error}', file=sys.stderr)
        return 1 if failures else 0
    if os.environ.get('TLG_NGS2') == 'hle':
        settings['native_audio'] = False
    problems = check_game(settings['game_dir'])
    if problems:
        for kind, detail in problems:
            print(f'{"Compile primeiro" if kind == "not_built" else "Faltando"}: {detail}', file=sys.stderr)
        return 1
    prepare(settings, log=lambda line: None)
    process, log = launch(settings, seconds)
    print(f'Rodando (log: {log})', flush=True)
    with open(log, 'w', encoding='utf-8') as out:
        for line in process.stdout:
            sys.stdout.write(line)
            out.write(line)
            out.flush()
    return process.wait()


if __name__ == '__main__':
    sys.exit(main())
