# SPDX-License-Identifier: GPL-2.0-or-later
"""Same-directory package installation and recoverable rollback, independent of Qt.

Only manifest-owned files are written. A write-ahead journal and verified backups
allow recovery after process death; replacing a whole package is NOT atomic.
The helper runs from its staging folder, never from files it is replacing.
"""
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import time

MANIFEST = 'package-files.json'
STATE = '.gr2-update-state.json'
PROTOCOL = 1
RESERVED = {'user', 'savedata', 'savedata_backups', 'cache', 'mods', '.git',
            'settings.json', 'tlg.ini', 'eboot.bin', 'sce_module', 'sce_sys',
            STATE, '.gr2-update.lock', '.gr2-launcher.lock'}


class InstallError(Exception):
    def __init__(self, kind, detail=''):
        self.kind, self.detail = kind, str(detail)
        super().__init__(f'{kind}: {detail}')


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _json(path, data):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix='.gr2-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _read(path):
    try:
        path = Path(path)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('metadata too large')
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise InstallError('archive', error) from error


def _relative(name, allow_manifest=False):
    if not isinstance(name, str) or not name or '\\' in name:
        raise InstallError('archive', name)
    parts = name.split('/')
    if (PurePosixPath(name).is_absolute() or any(not p or p in ('.', '..') for p in parts)
            or any(':' in p or p.endswith((' ', '.')) or any(ord(c) < 32 for c in p) for p in parts)
            or any(re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', p, re.I) for p in parts)
            or any(p.casefold() in RESERVED for p in parts)
            or (name.casefold() == MANIFEST and not allow_manifest)):
        raise InstallError('archive', name)
    return name


def _path(root, name, protected=(), allow_manifest=False):
    _relative(name, allow_manifest)
    root = Path(root).resolve()
    path = root.joinpath(*name.split('/'))
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
            raise InstallError('archive', f'link: {parent}')
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or any(resolved.is_relative_to(Path(p).resolve()) for p in protected):
        raise InstallError('archive', str(path))
    return path


def _entries(manifest):
    if not isinstance(manifest, dict) or manifest.get('schema') != PROTOCOL:
        raise InstallError('protocol', MANIFEST)
    rows = manifest.get('files')
    if not isinstance(rows, list) or not rows or len(rows) > 50000:
        raise InstallError('archive', 'manifest files')
    result, folded = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            raise InstallError('archive', 'manifest entry')
        name = _relative(row.get('path'))
        if (name.casefold() in folded or not isinstance(row.get('size'), int) or row['size'] < 0
                or not re.fullmatch(r'[0-9a-f]{64}', str(row.get('sha256', '')))):
            raise InstallError('archive', name)
        folded.add(name.casefold())
        result[name] = row
    return result


def write_manifest(folder, version, paths=None):
    """Packaging entry point. No symlinks or personal-data paths in a release."""
    folder = Path(folder).resolve()
    if paths is None:
        paths = sorted(p.relative_to(folder).as_posix() for p in folder.rglob('*')
                       if p.is_file() and p.name != MANIFEST)
    rows = []
    for name in paths:
        path = _path(folder, name)
        rows.append({'path': name, 'size': path.stat().st_size, 'sha256': _hash(path)})
    manifest = {'schema': PROTOCOL, 'version': version, 'files': rows}
    _entries(manifest)
    _json(folder / MANIFEST, manifest)
    return manifest


def _check_payload(stage, protected=()):
    manifest = _read(Path(stage) / MANIFEST)
    entries = _entries(manifest)
    actual = set()
    for path in Path(stage).rglob('*'):
        name = path.relative_to(stage).as_posix()
        _path(stage, name, allow_manifest=True)
        if path.is_file() and name != MANIFEST:
            actual.add(name)
    if actual != set(entries):
        raise InstallError('archive', 'unlisted or missing package files')
    for name, row in entries.items():
        path = _path(stage, name)
        if path.stat().st_size != row['size'] or _hash(path) != row['sha256']:
            raise InstallError('checksum', name)
    return manifest, entries


def prepare(stage, target, release_tag, exe_name='Gravity Rush 2.exe', protected=()):
    stage, target = Path(stage).resolve(), Path(target).resolve()
    if (target / '.git').exists() or any((p / '.git').exists() for p in target.parents):
        raise InstallError('source', target)
    if not target.is_dir() or not (target / exe_name).is_file() or stage.is_relative_to(target):
        raise InstallError('archive', 'invalid source or destination')
    if stage.stat().st_dev != target.stat().st_dev:
        raise InstallError('write', 'staging must be on the installation volume')
    manifest, incoming = _check_payload(stage)
    if str(manifest.get('version')) != str(release_tag) or exe_name not in incoming:
        raise InstallError('protocol', 'version or launcher missing')
    old_manifest = target / MANIFEST
    old = _entries(_read(old_manifest)) if old_manifest.is_file() else {}
    protected = [str(Path(p).resolve()) for p in protected if p]
    operations = []
    for name in sorted(set(incoming) | set(old)) + [MANIFEST]:
        dest = _path(target, name, protected, allow_manifest=True)
        src = _path(stage, name, allow_manifest=True) if name in incoming or name == MANIFEST else None
        before = _hash(dest) if dest.is_file() else None
        if dest.exists() and not dest.is_file():
            raise InstallError('conflict', name)
        if name in old and before != old[name]['sha256']:
            raise InstallError('conflict', name)
        if old and name not in old and name != MANIFEST and before is not None:
            raise InstallError('conflict', name)
        operations.append({'path': name, 'before': before, 'after': _hash(src) if src else None,
                           'size': dest.stat().st_size if before else 0, 'state': 'pending'})
    need = sum(row['size'] for row in operations) + sum(r['size'] for r in incoming.values()) + 50_000_000
    if shutil.disk_usage(target).free < need:
        raise InstallError('space', str(need))
    transaction = stage.parent / 'transaction.json'
    if transaction.exists() and _read(transaction).get('status') not in ('rolled_back', 'prepared'):
        raise InstallError('conflict', transaction)
    # Distinct staging folders are used in production. Allow test/retry reuse only
    # after rollback, and replace the backup at the start of each apply.
    _json(transaction, {'schema': PROTOCOL, 'target': str(target), 'stage': str(stage),
                        'exe': exe_name, 'version': release_tag, 'protected': protected,
                        'status': 'prepared', 'operations': operations})
    return transaction


def _load(transaction):
    transaction = Path(transaction).resolve()
    data = _read(transaction)
    if (data.get('schema') != PROTOCOL or not Path(data.get('target', '')).is_absolute()
            or not Path(data.get('stage', '')).is_absolute()
            or Path(data['stage']).parent != transaction.parent
            or Path(data['stage']).resolve().is_relative_to(Path(data['target']).resolve())):
        raise InstallError('archive', 'invalid transaction')
    _relative(data.get('exe'))
    names = set()
    for row in data.get('operations', []):
        name = row.get('path')
        _path(data['target'], name, data.get('protected', ()), allow_manifest=True)
        _path(transaction.parent / 'backup', name, allow_manifest=True)
        if name.casefold() in names or row.get('state') not in ('pending', 'started', 'done', 'restored'):
            raise InstallError('archive', 'invalid journal entry')
        names.add(name.casefold())
        for key in ('before', 'after'):
            if row.get(key) is not None and not re.fullmatch('[0-9a-f]{64}', str(row[key])):
                raise InstallError('archive', 'invalid journal digest')
    if not names:
        raise InstallError('archive', 'empty journal')
    return transaction, data


@contextmanager
def install_lock(target, name='.gr2-update.lock'):
    path = Path(target) / name
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        raise InstallError('conflict', path)
    stream = path.open('a+b')
    try:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise InstallError('busy', target) from error
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise InstallError('busy', target) from error
        yield
    finally:
        stream.close()  # OS releases locks even on process death


def _copy(source, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.gr2-file-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'wb') as out, Path(source).open('rb') as inp:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dest)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _restore(transaction, data):
    data['status'] = 'recovering'
    _json(transaction, data)
    for row in reversed(data['operations']):
        if row['state'] not in ('started', 'done'):
            continue
        dest = _path(data['target'], row['path'], data.get('protected', ()), allow_manifest=True)
        if row['before'] is not None:
            # Already the old content when its replacement never happened (for example, a locked
            # file): nothing is written, so the lock cannot make the recovery fail.
            if not (dest.is_file() and _hash(dest) == row['before']):
                backup = _path(transaction.parent / 'backup', row['path'], allow_manifest=True)
                if not backup.is_file() or _hash(backup) != row['before']:
                    raise InstallError('recovery', row['path'])
                _copy(backup, dest)
        elif dest.exists():
            if not dest.is_file() or _hash(dest) != row['after']:
                raise InstallError('conflict', row['path'])
            dest.unlink()
        row['state'] = 'restored'
        _json(transaction, data)
    data['status'] = 'rolled_back'
    _json(transaction, data)
    _record_state(transaction, data)


def _record_state(transaction, data):
    # Keep completion evidence with the installation, independently of staging.
    _json(Path(data['target']) / STATE,
          {'transaction': str(transaction), 'completed': data})


def apply(transaction, wait_pid=0, after_replace=None):
    if wait_pid:
        wait_for_exit(wait_pid)
    transaction, data = _load(transaction)
    with install_lock(data['target']), install_lock(data['target'], '.gr2-launcher.lock'):
        if data['status'] != 'prepared':
            raise InstallError('recovery', 'transaction is not prepared')
        _check_payload(Path(data['stage']))
        # Check all destinations before any write: configuration cannot race the preview.
        for row in data['operations']:
            path = _path(data['target'], row['path'], data.get('protected', ()), allow_manifest=True)
            if (_hash(path) if path.is_file() else None) != row['before']:
                raise InstallError('conflict', row['path'])
        data['status'] = 'applying'
        _json(transaction, data)
        # Expected hashes survive the journal: an interrupted update can be reconciled without it.
        _json(Path(data['target']) / STATE, {
            'transaction': str(transaction), 'target': data['target'], 'protected': data.get('protected', []),
            'operations': [{key: row[key] for key in ('path', 'before', 'after', 'size')}
                           for row in data['operations']]})
        try:
            for index, row in enumerate(data['operations']):
                dest = _path(data['target'], row['path'], data.get('protected', ()), allow_manifest=True)
                if row['before'] is not None:
                    backup = _path(transaction.parent / 'backup', row['path'], allow_manifest=True)
                    _copy(dest, backup)
                    if _hash(backup) != row['before']:
                        raise InstallError('checksum', row['path'])
                row['state'] = 'started'
                _json(transaction, data)
                if row['after'] is not None:
                    src = _path(data['stage'], row['path'], allow_manifest=True)
                    if _hash(src) != row['after']:
                        raise InstallError('checksum', row['path'])
                    _copy(src, dest)
                else:
                    dest.unlink(missing_ok=True)
                if after_replace:
                    after_replace(index)
                row['state'] = 'done'
                _json(transaction, data)
            data['status'] = 'installed'
            _json(transaction, data)
            _record_state(transaction, data)
        except Exception as error:
            _restore(transaction, data)
            raise InstallError(getattr(error, 'kind', 'write'), str(error)) from error
    return 0


def recover(transaction, wait_pid=0):
    if wait_pid:
        wait_for_exit(wait_pid)
    transaction, data = _load(transaction)
    with install_lock(data['target']), install_lock(data['target'], '.gr2-launcher.lock'):
        if data['status'] != 'rolled_back':
            _restore(transaction, data)
    return 0


def _settle_interrupted(target, state, record):
    """Interrupted update whose journal is gone: consistent only if every managed file is all old or all new."""
    if Path(record.get('target', '')).resolve() != Path(target).resolve():
        raise InstallError('archive', 'wrong recovery destination')
    old_only = new_only = None
    for row in record['operations']:
        path = _path(target, row['path'], record.get('protected', ()), allow_manifest=True)
        if path.exists() and not path.is_file():
            raise InstallError('recovery', row['path'])
        current = _hash(path) if path.is_file() else None
        is_old, is_new = current == row['before'], current == row['after']
        if not (is_old or is_new):
            raise InstallError('recovery', row['path'])
        if is_old and not is_new:
            old_only = old_only or row['path']
        if is_new and not is_old:
            new_only = new_only or row['path']
    if old_only and new_only:  # mixture: keep the state file as evidence for the reinstall
        raise InstallError('recovery', f'mixed versions: {old_only} is old, {new_only} is new')
    state.unlink()


def pending(target):
    state = Path(target) / STATE
    if not state.is_file():
        return None
    record = _read(state)
    transaction = Path(record['transaction'])
    if not transaction.exists():
        if 'completed' not in record and record.get('operations'):
            _settle_interrupted(target, state, record)
            return None
        data = record.get('completed', {})
        status = data.get('status')
        if (status not in ('installed', 'confirmed', 'rolled_back')
                or Path(data.get('target', '')).resolve() != Path(target).resolve()
                or not data.get('operations')):
            raise InstallError('recovery', 'update journal missing; completion cannot be verified')
        # Losing rollback files after a completed update must not brick the launcher.
        # Verify the installed files before retiring its now unusable recovery state.
        for row in data['operations']:
            path = _path(target, row['path'], data.get('protected', ()), allow_manifest=True)
            expected = row['before'] if status == 'rolled_back' else row['after']
            if (path.exists() and not path.is_file()) or (_hash(path) if path.is_file() else None) != expected:
                raise InstallError('recovery', row['path'])
        state.unlink()
        return None
    transaction, data = _load(transaction)
    if Path(data['target']).resolve() != Path(target).resolve():
        raise InstallError('archive', 'wrong recovery destination')
    return transaction, data


def confirm(target):
    state = pending(target)
    if state and state[1]['status'] == 'installed':
        transaction, data = state
        data['status'] = 'confirmed'
        _json(transaction, data)
        _record_state(transaction, data)
        _prune(transaction.parent, target)


def _prune(keep, target):
    """Keeps only the newest confirmed update's folder: its backup restores the version before it."""
    for folder in Path(target).parent.glob('.gr2-update-*'):
        if (not folder.is_dir() or folder.is_symlink()
                or getattr(folder, 'is_junction', lambda: False)()
                or not (folder / 'transaction.json').is_file()
                or folder.resolve() == Path(keep).resolve()):
            continue
        try:
            _, data = _load(folder / 'transaction.json')
        except InstallError:
            continue
        if (Path(data['target']).resolve() == Path(target).resolve()
                and data['status'] in ('confirmed', 'rolled_back')):
            shutil.rmtree(folder, ignore_errors=True)


def wait_for_exit(pid, timeout=60):
    if int(pid) <= 0 or int(pid) == os.getpid():
        raise InstallError('busy', pid)
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, int(pid))
        if not handle:
            if ctypes.get_last_error() == 87:  # process already gone
                return
            raise InstallError('busy', 'cannot open parent process')
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise InstallError('busy', 'launcher did not exit')
        finally:
            kernel.CloseHandle(handle)
    else:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                os.kill(int(pid), 0)
            except ProcessLookupError:
                return
            time.sleep(.1)
        raise InstallError('busy', pid)


def helper(transaction, wait_pid, rollback=False):
    """Frozen launcher role; log beside the journal, never in the game's log."""
    transaction, data = _load(transaction)
    try:
        wait_for_exit(wait_pid)
        if game_running():
            raise InstallError('busy', 'game is running')
        (recover if rollback else apply)(transaction)
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
        env.pop('_MEIPASS2', None)
        subprocess.Popen([str(Path(data['target']) / data['exe'])], cwd=data['target'], env=env,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return 0
    except Exception as error:
        (transaction.parent / 'update-error.log').write_text(str(error), encoding='utf-8')
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, f'{error}\n\n{transaction.parent}',
                                            'Gravity Rush 2 — Update / Atualização', 0x10)
        return 1


def game_running():
    """Fail closed when Windows cannot report processes, rather than guessing idle."""
    if os.name != 'nt':
        import savemanager
        return savemanager.game_running()
    try:
        result = subprocess.run(['tasklist', '/FO', 'CSV', '/NH', '/FI', 'IMAGENAME eq tlg-probe.exe'],
                                capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise InstallError('busy', 'process check failed')
        return b'tlg-probe.exe' in result.stdout.lower()
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError('busy', 'cannot check game process') from error


def start_helper(transaction, rollback=False):
    transaction, data = _load(transaction)
    stage = Path(data['stage'])
    # Always run the verified staged launcher; it stays available for rollback.
    launcher = _path(stage, data['exe'])
    expected = _entries(_read(stage / MANIFEST))[data['exe']]['sha256']
    if _hash(launcher) != expected:
        raise InstallError('checksum', data['exe'])
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    env.pop('_MEIPASS2', None)
    return subprocess.Popen([str(launcher), '--rollback-update' if rollback else '--apply-update',
                             str(transaction), str(os.getpid())], cwd=str(stage), env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--manifest':
        write_manifest(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit('usage: update_install.py --manifest FOLDER VERSION')
