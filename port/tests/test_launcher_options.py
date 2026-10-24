# SPDX-License-Identifier: GPL-2.0-or-later
"""Every option the launchers offer is read by this port: each in-game-menu / tlg.ini key of
launcher/backports_table.py is parsed by gpu/shim/tlg_settings.cpp, and each switch passed in the
environment is a getenv() of the GPU core or the runtime (GR2_X is copied to TLG_X by src/probe.c).
inFAMOUS-only switches (BP01-BP12, occlusion mode, LDS barriers, AMD workarounds) must not come back."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

from paths import ROOT
sys.path.insert(0, str(ROOT / 'launcher'))
import backports_table  # noqa: E402
import gr2_run  # noqa: E402

SETTINGS_CPP = ROOT / 'gpu' / 'shim' / 'tlg_settings.cpp'


def _sources():
    for folder in (ROOT / 'src', ROOT / 'gpu' / 'shim', ROOT / 'gpu' / 'shadps4'):
        for path in folder.rglob('*'):
            if path.suffix in ('.c', '.cpp', '.h') and 'third_party' not in path.parts:
                yield path


class LauncherOptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cpp = SETTINGS_CPP.read_text(encoding='utf-8')
        overlay = re.search(r'overlay_keys\[\] = \{([^}]*)\}', cpp).group(1)
        cls.ini_keys = set(re.findall(r'key == "([a-z0-9_]+)"', cpp)) | set(re.findall(r'"([a-z0-9_]+)"', overlay))
        text = '\n'.join(p.read_text(encoding='utf-8', errors='replace') for p in _sources())
        cls.getenv = set(re.findall(r'getenv\("(TLG_[A-Z0-9_]+)"\)', text)) | \
            set(re.findall(r'\{"(TLG_[A-Z0-9_]+)", "[a-z0-9_]+"\}', text))

    def test_ini_keys_are_parsed_by_the_game(self):
        for item in backports_table.ITEMS:
            if item.store == 'ini' and not item.pass_env:
                self.assertIn(item.key, self.ini_keys, item.id)
            if item.group == 'menu':
                self.assertIn(item.key, self.ini_keys, item.id)

    def test_environment_switches_are_read_by_the_core(self):
        for item in backports_table.ITEMS:
            if item.pass_env:
                self.assertIn(item.env, self.getenv, item.id)

    def test_no_infamous_only_switch(self):
        ids = {item.id for item in backports_table.ITEMS}
        for gone in ('BP01', 'BP06', 'BP09', 'BP10', 'TLG_OCCLUSION_MODE', 'TLG_BC_TINY', 'TLG_NO_MSAA',
                     'TLG_WQM', 'TLG_LDS_SMALL', 'TLG_RFL_ALL', 'menu:lod_scale', 'menu:far_clip'):
            self.assertNotIn(gone, ids)

    def test_environment_reaches_the_game(self):
        states = {item.id: None for item in backports_table.ITEMS}
        states['TLG_BLOCK1D'] = '1'
        self.assertEqual({'GR2_BLOCK1D': '1'}, backports_table.environment(states, {}))
        self.assertEqual({}, backports_table.environment(states, {'TLG_BLOCK1D': '0'}))

    def test_graphics_setting_rows_exist(self):
        try:
            from qt import graphics
        except ImportError:
            self.skipTest('PySide6 not installed')
        for key, _, _ in graphics.SETTING_ROWS.values():
            self.assertIn(key, gr2_run.DEFAULT_SETTINGS, key)
        ids = {i.id for i in backports_table.ITEMS}
        for _, rows in graphics.SECTIONS:
            for rid in rows:
                self.assertTrue(rid in graphics.SETTING_ROWS or rid in ids, rid)

class GameModuleTests(unittest.TestCase):
    def test_dlc_loader_is_linked_only_when_present(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = {'game_dir': folder, 'system_lib_dir': folder, 'native_audio': False}
            base = gr2_run.game_modules(settings)
            self.assertEqual(base[:3], ['libc.prx', 'libSceFios2.prx', 'libSceJobManager.prx'])
            self.assertFalse(any(m.endswith('dlcldr.prx') for m in base))
            (Path(folder) / 'dlcldr.prx').write_bytes(b'')
            self.assertEqual(gr2_run.game_modules(settings), base + [str(Path(folder) / 'dlcldr.prx')])


if __name__ == '__main__':
    unittest.main()
