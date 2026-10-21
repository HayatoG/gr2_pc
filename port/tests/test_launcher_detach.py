# SPDX-License-Identifier: GPL-2.0-or-later
"""The game runs detached from the launcher and writes its own log file: the log reader
(launcher/logtail.py), launch() without a pipe, closing the launcher with the game open, and the
'Close the launcher when the game starts' option."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from paths import ROOT
sys.path.insert(0, str(ROOT / 'launcher'))
import gr2_run  # noqa: E402
import logtail  # noqa: E402

try:
    from PySide6.QtCore import QCoreApplication
    from qt import backend as backend_module
    from qt.backend import Backend
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


class LogTailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'run.log'

    def append(self, data):
        with open(self.path, 'ab') as handle:
            handle.write(data)

    def test_missing_file_is_empty(self):
        self.assertEqual([], logtail.LogTail(self.path).poll())

    def test_reads_only_new_bytes_with_an_offset(self):
        tail = logtail.LogTail(self.path)
        self.append(b'one\ntwo\n')
        self.assertEqual(['one', 'two'], tail.poll())
        self.assertEqual(8, tail.offset)
        self.assertEqual([], tail.poll())
        self.append(b'three\n')
        self.assertEqual(['three'], tail.poll())
        self.assertEqual(['one', 'two', 'three'], list(tail.lines))

    def test_does_not_reread_the_whole_file(self):
        tail = logtail.LogTail(self.path)
        self.append(b'a\n' * 1000)
        tail.poll()
        self.append(b'b\n')
        real_open = open
        sizes = []

        def spy(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            read = handle.read
            handle.read = lambda n=-1: (sizes.append(n), read(n))[1]
            return handle
        with mock.patch('builtins.open', spy):
            self.assertEqual(['b'], tail.poll())
        self.assertEqual([2], sizes)

    def test_partial_line_waits_for_the_newline(self):
        tail = logtail.LogTail(self.path)
        self.append(b'start of a li')
        self.assertEqual([], tail.poll())
        self.append(b'ne\nnext')
        self.assertEqual(['start of a line'], tail.poll())
        self.assertEqual([], tail.poll())
        self.append(b' one\r\n')
        self.assertEqual(['next one'], tail.poll())

    def test_final_poll_returns_the_unfinished_line(self):
        tail = logtail.LogTail(self.path)
        self.append(b'done\nlast words')
        self.assertEqual(['done'], tail.poll())
        self.assertEqual(['last words'], tail.poll(final=True))

    def test_keeps_only_the_last_lines(self):
        tail = logtail.LogTail(self.path, max_lines=3)
        self.append(''.join(f'l{i}\n' for i in range(10)).encode())
        self.assertEqual(['l7', 'l8', 'l9'], tail.poll())
        self.assertEqual(['l7', 'l8', 'l9'], list(tail.lines))

    def test_a_flood_shows_only_the_end(self):
        tail = logtail.LogTail(self.path, max_lines=5)
        line = b'x' * 99 + b'\n'
        self.append(line * (logtail.MAX_CHUNK // 100 + 5000) + b'the end\n')
        new = tail.poll()
        self.assertEqual('the end', new[-1])
        self.assertEqual(5, len(new))
        self.assertTrue(all(l == 'x' * 99 for l in new[:-1]))   # no cut-in-half line

    def test_truncated_file_starts_over(self):
        tail = logtail.LogTail(self.path)
        self.append(b'old old old\n')
        tail.poll()
        self.path.write_bytes(b'new\n')
        self.assertEqual(['new'], tail.poll())

    def test_bad_utf8_is_replaced(self):
        tail = logtail.LogTail(self.path)
        self.append(b'caf\xe9\n')
        self.assertEqual(['caf�'], tail.poll())


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def launch(self):
        port = self.root / 'port'
        settings = dict(gr2_run.DEFAULT_SETTINGS, game_dir=str(self.root / 'game'))
        patches = [mock.patch.object(gr2_run, 'USER_DIR', self.root / 'user'),
                   mock.patch.object(gr2_run, 'OUT_DIR', port / 'out'),
                   mock.patch.object(gr2_run, 'LOG_DIR', port / 'out' / 'logs'),
                   mock.patch.object(gr2_run, 'probe_env', return_value={}),
                   mock.patch.object(gr2_run, 'raise_open_file_limit'),
                   mock.patch.object(gr2_run.subprocess, 'Popen')]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        process, log = gr2_run.launch(settings, detached=True)
        return process, log, gr2_run.subprocess.Popen.call_args

    def test_no_pipe_the_log_file_is_the_output(self):
        process, log, call = self.launch()
        self.assertIs(process, gr2_run.subprocess.Popen.return_value)
        kwargs = call.kwargs
        self.assertNotEqual(gr2_run.subprocess.PIPE, kwargs['stdout'])
        self.assertTrue(hasattr(kwargs['stdout'], 'write'))
        self.assertEqual(str(log), kwargs['stdout'].name)
        self.assertEqual(gr2_run.subprocess.STDOUT, kwargs['stderr'])
        self.assertNotIn('text', kwargs)
        self.assertTrue(Path(log).is_file())

    def test_linux_has_its_own_session(self):
        _, _, call = self.launch()
        self.assertIs(True, call.kwargs['start_new_session'])
        self.assertNotIn('creationflags', call.kwargs)

    def test_windows_has_its_own_group_and_no_console(self):
        with mock.patch.object(gr2_run.os, 'name', 'nt'), \
                mock.patch.object(gr2_run.subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x200, create=True), \
                mock.patch.object(gr2_run.subprocess, 'DETACHED_PROCESS', 0x8, create=True):
            options = gr2_run.detach_options()
        self.assertEqual({'creationflags': 0x200 | 0x8}, options)

    def test_real_child_survives_and_writes_the_log(self):
        # A real process (not the game): output reaches the file with no reader attached.
        log = self.root / 'real.log'
        with open(log, 'wb') as out:
            process = gr2_run.subprocess.Popen(
                [sys.executable, '-c', 'import sys; print("out"); print("err", file=sys.stderr)'],
                stdout=out, stderr=gr2_run.subprocess.STDOUT, **gr2_run.detach_options())
        self.assertEqual(0, process.wait(timeout=30))
        self.assertEqual({'out', 'err'}, set(log.read_text().split()))


@unittest.skipUnless(HAVE_QT, 'PySide6 not installed')
class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def make(self, **settings):
        probes = {'gpu': lambda: ('GPU', '1.4'), 'pad': lambda: None, 'problems': lambda: [], 'cache': lambda: 0,
                  'save': lambda: None, 'news': lambda: [], 'version': lambda: 'v1',
                  'saves': {'running': lambda: False, 'scan': lambda: [], 'open': lambda p: None}}
        data = {**gr2_run.DEFAULT_SETTINGS, 'ui_language': 'en_US', **settings}
        return Backend(settings=data, probes=probes)

    def test_shutdown_leaves_the_running_game_alone(self):
        backend = self.make()
        backend.process = mock.Mock()
        backend.shutdown()
        backend.process.terminate.assert_not_called()
        backend.process.kill.assert_not_called()

    def test_panel_is_rebuilt_once_per_tick(self):
        backend = self.make()
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'run.log'
            log.write_bytes(b'')
            backend._on_game_started(str(log))
            backend._tail_timer.stop()
            changes = []
            backend.logChanged.connect(lambda: changes.append(1))
            log.write_bytes(''.join(f'line {i}\n' for i in range(2000)).encode() + b'partial')
            backend._poll_log()
            self.assertEqual(1, len(changes))
            self.assertEqual(backend_module.LOG_LINES, len(backend._log))
            self.assertEqual('line 1999', backend.logText.splitlines()[-1])
            backend._poll_log()
            self.assertEqual(1, len(changes))     # nothing new: no rebuild
            backend._on_finished(0)               # the last, unfinished line is kept at the end
            self.assertIn('partial', backend._log)

    def test_option_is_on_by_default(self):
        self.assertIs(True, gr2_run.DEFAULT_SETTINGS['close_on_play'])
        self.assertEqual('Close the launcher when the game starts', self.make().t_('close_on_play'))
        self.assertEqual('Fechar o launcher ao abrir o jogo', self.make(ui_language='pt_BR').t_('close_on_play'))

    def started(self, **settings):
        backend = self.make(**settings)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(backend_module, 'QTimer') as timer:
            backend._on_game_started(str(Path(tmp) / 'run.log'))
            backend._tail_timer.stop()
        return backend, timer

    def test_option_off_keeps_the_launcher_open(self):
        _, timer = self.started(close_on_play=False)
        timer.singleShot.assert_not_called()

    def test_option_on_closes_the_launcher_after_about_two_seconds(self):
        backend, timer = self.started(close_on_play=True)
        delay, callback = timer.singleShot.call_args.args
        self.assertEqual(2000, delay)
        with mock.patch.object(self.app, 'quit') as quit_:
            callback()
        quit_.assert_called_once()

    def test_quit_starts_the_reopen_watcher_only_while_the_game_runs(self):
        for setting, running, expected in ((True, True, 1), (False, True, 0), (True, False, 0)):
            backend = self.make(reopen_launcher=setting)
            backend.process = mock.Mock()
            backend.process.poll.return_value = None if running else 0
            backend.process.pid = 4321
            with mock.patch.object(gr2_run, 'reopen_after') as reopen, mock.patch.object(self.app, 'quit'):
                backend._quit_app()
            self.assertEqual(expected, reopen.call_count, (setting, running))


class ReopenTests(unittest.TestCase):
    def test_reopen_watcher_is_detached_and_points_at_the_qt_launcher(self):
        with mock.patch.object(gr2_run.subprocess, 'Popen') as popen, mock.patch.object(gr2_run, 'FROZEN', False):
            self.assertTrue(gr2_run.reopen_after(1234))
        cmd = popen.call_args.args[0]
        self.assertTrue(cmd[1].endswith('gr2_launcher_qt.py'))
        self.assertEqual(['--reopen-after', '1234'], cmd[2:])
        self.assertIs(True, popen.call_args.kwargs['start_new_session'])

    def test_frozen_watcher_reruns_the_executable(self):
        with mock.patch.object(gr2_run.subprocess, 'Popen') as popen, mock.patch.object(gr2_run, 'FROZEN', True):
            gr2_run.reopen_after(77)
        self.assertEqual([sys.executable, '--reopen-after', '77'], popen.call_args.args[0])

    def test_wait_for_exit_returns_when_the_process_is_gone(self):
        child = gr2_run.subprocess.Popen([sys.executable, '-c', 'pass'])
        child.wait(timeout=30)
        gr2_run.wait_for_exit(child.pid)   # reaped: returns at once

    def test_defaults_close_and_reopen(self):
        self.assertIs(True, gr2_run.DEFAULT_SETTINGS['close_on_play'])
        self.assertIs(True, gr2_run.DEFAULT_SETTINGS['reopen_launcher'])


@unittest.skipIf(os.name == 'nt', 'Linux only')
class OpenFileLimitTests(unittest.TestCase):
    def test_soft_limit_goes_up_to_the_hard_one(self):
        import resource
        with mock.patch.object(resource, 'getrlimit', return_value=(1024, 524288)), \
                mock.patch.object(resource, 'setrlimit') as setrlimit:
            gr2_run.raise_open_file_limit()
        setrlimit.assert_called_once_with(resource.RLIMIT_NOFILE, (524288, 524288))

    def test_unlimited_hard_limit_is_left_alone(self):
        import resource
        with mock.patch.object(resource, 'getrlimit', return_value=(1024, resource.RLIM_INFINITY)), \
                mock.patch.object(resource, 'setrlimit') as setrlimit:
            gr2_run.raise_open_file_limit()
        setrlimit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
