# SPDX-License-Identifier: GPL-2.0-or-later
"""Configuration files players share (launcher/preset_share.py), for Gravity Rush 2: format and game
header, only the options this port reads, round trip through the preset path, bad values refused."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from paths import ROOT
sys.path.insert(0, str(ROOT / 'launcher'))
import backports_table  # noqa: E402
import preset_share  # noqa: E402
from qt import gfxlogic  # noqa: E402


class PresetShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_header_names_this_game(self):
        preset = preset_share.export_preset({'vsync': True}, {}, 'Mine', 'desc', 'v2026.10.20-abc1234')
        self.assertEqual('gr2-preset', preset['format'])
        self.assertEqual('CUSA03694', preset['game'])
        self.assertTrue(preset_share.default_filename('Mine').endswith('.gr2-preset.json'))

    def test_export_has_only_shareable_settings(self):
        settings = {'vsync': False, 'show_fps': True, 'vram_budget_mb': 3500, 'game_dir': '/x', 'display_mode': 'Fullscreen'}
        preset = preset_share.export_preset(settings, {}, 'n')
        self.assertEqual({'vsync': False, 'show_fps': True}, preset['settings'])

    def test_every_built_in_preset_round_trips(self):
        for preset_id, _, _ in gfxlogic.PRESETS:
            settings, states = {'vsync': True}, {}
            gfxlogic.apply_targets(settings, states, gfxlogic.preset_targets(preset_id))
            path = preset_share.write_preset(preset_share.export_preset(settings, states, preset_id),
                                             self.dir / preset_id)
            preset, problems = preset_share.read_preset(path)
            self.assertIsNotNone(preset, problems)
            self.assertEqual([], [p for p in problems if p.fatal])
            fresh_settings, fresh_states = {'vsync': True}, {}
            gfxlogic.apply_targets(fresh_settings, fresh_states, gfxlogic.custom_targets(preset))
            self.assertEqual(preset_id, gfxlogic.matching_preset(fresh_settings, fresh_states))

    def test_foreign_options_are_ignored_and_bad_values_refused(self):
        data = {'format': 'gr2-preset', 'version': 1, 'game': 'CUSA03694', 'name': 'x',
                'settings': {'vsync': 'maybe', 'gpu_readbacks': '2'},
                'items': {'BP06': '1', 'TLG_OCCLUSION_MODE': '3', 'menu:rcas_strength': '999',
                          'TLG_STALE_READBACK': '1'}}
        path = self.dir / 'f.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        preset, problems = preset_share.read_preset(path)
        codes = {(p.code, p.detail.split(' ')[0].split('=')[0]) for p in problems}
        self.assertIn('unknown_item', {c for c, _ in codes})
        self.assertIn('bad_item', {c for c, _ in codes})
        self.assertEqual({'TLG_STALE_READBACK': '1'}, preset['items'])

    def test_not_a_preset_is_fatal(self):
        path = self.dir / 'g.json'
        path.write_text(json.dumps({'format': 'iss-preset', 'version': 1}), encoding='utf-8')
        preset, problems = preset_share.read_preset(path)
        self.assertIsNone(preset)
        self.assertTrue(any(p.fatal for p in problems))


if __name__ == '__main__':
    unittest.main()
