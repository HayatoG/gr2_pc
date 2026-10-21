# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows-only checks of the in-place updater against real file locks, real processes and the
game's process name. Plain-file tests live in test_update_install.py and run everywhere."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
import update_install as ui

LAUNCHER_DIR = str(Path(__file__).resolve().parents[1] / 'launcher')
CHILD_LOCK = ("import sys, time; sys.path.insert(0, sys.argv[2]); import update_install as ui\n"
              "cm = ui.install_lock(sys.argv[1]); cm.__enter__(); print('locked', flush=True); time.sleep(60)")
GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
FILE_SHARE_READ, FILE_SHARE_WRITE = 0x1, 0x2   # like a running image: readable, not replaceable
INVALID = ctypes.c_void_p(-1).value


def hold(path):
    """Keeps `path` open without FILE_SHARE_DELETE, so it cannot be replaced until release()."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                OPEN_EXISTING, 0, None)
    if not handle or handle == INVALID:
        raise OSError(ctypes.get_last_error(), str(path))
    return kernel, handle


def release(held):
    kernel, handle = held
    kernel.CloseHandle(handle)


@unittest.skipUnless(os.name == 'nt', 'file locks, processes and tasklist are Windows behaviour')
class WindowsUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='iss-win-update-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.target = root / 'instalação com espaços'
        self.stage = root / '.gr2-update-x' / 'payload'
        for folder in (self.target, self.stage):
            (folder / 'out').mkdir(parents=True)
        for folder, text in ((self.target, 'old'), (self.stage, 'new')):
            (folder / 'launcher.exe').write_text(text)
            (folder / 'out' / 'runtime.dll').write_text(text)
        ui.write_manifest(self.stage, 'new')
        ui.write_manifest(self.target, 'old', paths=['launcher.exe', 'out/runtime.dll'])
        (self.target / 'user').mkdir()
        (self.target / 'user' / 'dis.dat').write_text('save')

    def prepare(self):
        return ui.prepare(self.stage, self.target, 'new', exe_name='launcher.exe')

    def assert_old_and_personal(self):
        self.assertEqual((self.target / 'launcher.exe').read_text(), 'old')
        self.assertEqual((self.target / 'out' / 'runtime.dll').read_text(), 'old')
        self.assertEqual((self.target / 'user' / 'dis.dat').read_text(), 'save')

    def test_file_held_between_replacements_rolls_back_the_replaced_file(self):
        tx = self.prepare()
        held = []
        def hold_second(index):
            if index == 0:
                held.append(hold(self.target / 'out' / 'runtime.dll'))
        try:
            with self.assertRaises(ui.InstallError):
                ui.apply(tx, after_replace=hold_second)
        finally:
            for item in held:
                release(item)
        self.assert_old_and_personal()
        self.assertEqual(ui.pending(self.target)[1]['status'], 'rolled_back')

    def test_file_held_after_backup_is_not_written_again_on_recovery(self):
        tx = self.prepare()
        real_copy, held = ui._copy, []
        def hold_then_copy(source, dest):
            if Path(source).is_relative_to(self.stage) and Path(dest).name == 'runtime.dll':
                held.append(hold(dest))   # the replacement itself now fails, like a running image
            return real_copy(source, dest)
        ui._copy = hold_then_copy
        try:
            with self.assertRaises(ui.InstallError):
                ui.apply(tx)
        finally:
            ui._copy = real_copy
            for item in held:
                release(item)
        self.assert_old_and_personal()
        self.assertEqual(ui.pending(self.target)[1]['status'], 'rolled_back')

    def test_second_launcher_holding_the_install_lock_blocks_apply(self):
        child = subprocess.Popen([sys.executable, '-c', CHILD_LOCK, str(self.target), LAUNCHER_DIR],
                                 stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'locked')
            with self.assertRaises(ui.InstallError) as error:
                ui.apply(self.prepare())
            self.assertEqual(error.exception.kind, 'busy')
            self.assert_old_and_personal()
        finally:
            child.kill()
            child.wait()
            child.stdout.close()

    def test_wait_for_exit_returns_when_the_process_ends(self):
        child = subprocess.Popen([sys.executable, '-S', '-c', 'import time; time.sleep(0.5)'])
        ui.wait_for_exit(child.pid, timeout=30)
        self.assertIsNotNone(child.poll())

    def test_wait_for_exit_times_out_on_a_running_process(self):
        child = subprocess.Popen([sys.executable, '-S', '-c', 'import time; time.sleep(60)'])
        try:
            with self.assertRaises(ui.InstallError) as error:
                ui.wait_for_exit(child.pid, timeout=1)
            self.assertEqual(error.exception.kind, 'busy')
        finally:
            child.kill()
            child.wait()

    def test_game_running_sees_a_process_named_tlg_probe(self):
        probe = Path(self.tmp.name) / 'tlg-probe.exe'
        shutil.copy(sys.executable, probe)
        child = subprocess.Popen([str(probe), '-S', '-c', 'import time; time.sleep(60)'])
        try:
            deadline = time.monotonic() + 20
            while not ui.game_running() and time.monotonic() < deadline:
                time.sleep(0.5)
            self.assertTrue(ui.game_running())
        finally:
            child.kill()
            child.wait()
        deadline = time.monotonic() + 20
        while ui.game_running() and time.monotonic() < deadline:
            time.sleep(0.5)
        self.assertFalse(ui.game_running())


if __name__ == '__main__':
    unittest.main()
