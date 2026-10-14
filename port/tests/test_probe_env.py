"""The launcher's questions to tlg-probe (--cpu-features, --gamepad) run with the port's libraries.

A Linux package keeps SDL3/FFmpeg in out/lib; without them the probe could not start, the CPU
looked complete and Intel players got "no rewrite table matches the image"."""
from paths import ROOT
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(ROOT / 'launcher'))
import gr2_run as run  # noqa: E402


def fake_probe(folder, body):
    probe = Path(folder) / 'tlg-probe'
    probe.write_text('#!/bin/sh\n' + body + '\n')
    probe.chmod(0o755)
    return probe


@unittest.skipIf(os.name == 'nt', 'shell fakes')
class ProbeEnvTests(unittest.TestCase):
    def test_bundled_libraries_first(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'lib').mkdir()
            with patch.object(run, 'OUT_DIR', Path(folder)), patch.object(run, 'FROZEN', False), \
                 patch.dict(os.environ, {'LD_LIBRARY_PATH': '/opt/x'}):
                self.assertEqual(run.probe_env()['LD_LIBRARY_PATH'], os.pathsep.join([str(Path(folder) / 'lib'), '/opt/x']))

    def test_frozen_launcher_drops_its_own_libraries(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(run, 'OUT_DIR', Path(folder)), patch.object(run, 'FROZEN', True), \
                 patch.dict(os.environ, {'LD_LIBRARY_PATH': '/tmp/_internal'}, clear=False):
                os.environ.pop('LD_LIBRARY_PATH_ORIG', None)
                self.assertNotIn('LD_LIBRARY_PATH', run.probe_env())

    def test_cpu_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            cases = [('echo "CPU: missing SSE4A, MOVBE"', ['SSE4A', 'MOVBE']),
                     ('echo "CPU: complete"', []),
                     # The libraries were not found: unknown, so the table is built anyway.
                     ('echo "error while loading shared libraries: libavcodec.so.61" >&2; exit 127', None)]
            for body, expected in cases:
                probe = fake_probe(folder, body)
                lines = []
                with patch.object(run, 'PROBE', probe):
                    self.assertEqual(run.cpu_missing_sets(lines.append), expected, body)
                self.assertEqual(bool(lines), expected is None)

    def test_probe_sees_the_libraries(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'lib').mkdir()
            probe = fake_probe(folder, 'case "$LD_LIBRARY_PATH" in *"/lib"*) echo "CPU: missing SSE4A";; *) exit 127;; esac')
            with patch.object(run, 'OUT_DIR', Path(folder)), patch.object(run, 'PROBE', probe), \
                 patch.object(run, 'FROZEN', False):
                self.assertEqual(run.cpu_missing_sets(lambda line: None), ['SSE4A'])


if __name__ == '__main__':
    unittest.main()
