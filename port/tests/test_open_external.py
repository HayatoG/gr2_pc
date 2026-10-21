# SPDX-License-Identifier: GPL-2.0-or-later
"""Links and folders the launcher opens (gr2_run.open_external): on Linux the frozen launcher
must not pass PyInstaller's LD_LIBRARY_PATH to the browser or file manager (the Linux package's
YouTube, Discord and sponsor links did nothing: the browser loaded the launcher's libraries)."""
import os
import sys
import unittest
from unittest import mock

from paths import ROOT
sys.path.insert(0, str(ROOT / 'launcher'))
import gr2_run  # noqa: E402


@unittest.skipIf(os.name == 'nt', 'Linux/macOS path')
class OpenExternalTests(unittest.TestCase):
    def opened(self, frozen, env):
        calls = []
        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(gr2_run, 'FROZEN', frozen), \
                mock.patch.object(gr2_run.subprocess, 'Popen', lambda *a, **k: calls.append((a, k))):
            for key in ('LD_LIBRARY_PATH', 'LD_LIBRARY_PATH_ORIG'):
                if key not in env:
                    os.environ.pop(key, None)
            self.assertTrue(gr2_run.open_external('https://discord.gg/UMkdMYZh9g'))
        return calls[0]

    def test_frozen_restores_the_original_library_path(self):
        (argv,), kw = self.opened(True, {'LD_LIBRARY_PATH': '/pkg/_internal', 'LD_LIBRARY_PATH_ORIG': '/usr/local/lib'})
        self.assertEqual(['xdg-open' if sys.platform != 'darwin' else 'open', 'https://discord.gg/UMkdMYZh9g'], argv)
        self.assertEqual('/usr/local/lib', kw['env']['LD_LIBRARY_PATH'])
        self.assertNotIn('LD_LIBRARY_PATH_ORIG', kw['env'])
        self.assertTrue(kw['start_new_session'])

    def test_frozen_without_an_original_drops_it(self):
        (_,), kw = self.opened(True, {'LD_LIBRARY_PATH': '/pkg/_internal'})
        self.assertNotIn('LD_LIBRARY_PATH', kw['env'])

    def test_source_tree_keeps_the_environment(self):
        (_,), kw = self.opened(False, {'LD_LIBRARY_PATH': '/opt/lib'})
        self.assertEqual('/opt/lib', kw['env']['LD_LIBRARY_PATH'])

    def test_a_missing_opener_falls_back_to_webbrowser(self):
        with mock.patch.object(gr2_run.subprocess, 'Popen', side_effect=OSError('no xdg-open')), \
                mock.patch('webbrowser.open', return_value=True) as wb:
            self.assertTrue(gr2_run.open_external('https://example.invalid/'))
        wb.assert_called_once()

    def test_every_launcher_link_uses_it(self):
        for name in ('qt/backend.py', 'qt/saves.py', 'qt/support.py', 'qt/updates.py',
                     'gr2_launcher.py'):
            text = (ROOT / 'launcher' / name).read_text(encoding='utf-8')
            self.assertNotIn('webbrowser.open(', text, name)
            self.assertNotIn('QDesktopServices.openUrl(', text, name)


if __name__ == '__main__':
    unittest.main()
