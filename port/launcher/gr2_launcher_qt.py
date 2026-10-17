#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Gravity Rush 2 launcher, Qt Quick edition (PySide6). The default launcher of the packages; the classic
Tk launcher (infamous_launcher.py) ships next to it as "<name> (classic)". Same settings file, same game start
path (gr2_run.prepare/launch), same tlg.ini as the Tk launcher.

    python3 infamous_launcher_qt.py            # needs: pip install PySide6-Essentials
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gr2_run as tlg_run  # noqa: E402


def main():
    args = sys.argv[1:]
    # Same packaged roles as the Tk launcher: preparation scripts and a window-less --play.
    if args[:1] == ['--script'] and len(args) > 1:
        sys.exit(tlg_run.run_script(args[1:]))
    if args[:1] == ['--clear-shader-cache']:
        sys.exit(tlg_run.main(args))
    if args[:1] == ['--play']:
        sys.exit(tlg_run.main(args[1:]))
    if args[:1] == ['--selftest']:  # CI smoke test of the frozen launcher: opens offscreen, touches nothing
        try:
            from qt import selftest
            code = selftest.run()
        except Exception as error:  # never let a windowed exe open an error dialog in CI
            code = 3
            if os.environ.get('GR2_SELFTEST_OUT'):
                Path(os.environ['GR2_SELFTEST_OUT']).write_text(f'selftest FAILED: {error!r}\n', encoding='utf-8')
        sys.exit(code)
    os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')  # we style the controls ourselves
    try:
        from qt.app import App
    except ImportError as error:
        sys.exit(f'PySide6 is missing ({error}). Install it with: pip install PySide6-Essentials\n'
                 f'PySide6 não encontrado. Instale com: pip install PySide6-Essentials')
    sys.exit(App().run())


if __name__ == '__main__':
    main()
