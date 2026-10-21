#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Gravity Rush 2 launcher, Qt Quick edition (PySide6). The default launcher of the packages; the classic
Tk launcher (gr2_launcher.py) ships next to it as "<name> (classic)". Same settings file, same game start
path (gr2_run.prepare/launch), same tlg.ini as the Tk launcher.

    python3 gr2_launcher_qt.py            # needs: pip install PySide6-Essentials
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gr2_run as tlg_run  # noqa: E402


def main():
    args = sys.argv[1:]
    if args[:1] in (['--apply-update'], ['--rollback-update']) and len(args) == 3:
        import update_install
        sys.exit(update_install.helper(args[1], int(args[2]), rollback=args[0] == '--rollback-update'))
    # --reopen-after PID: the launcher closed on play waits (no window) for the game, then opens again.
    if args[:1] == ['--reopen-after'] and len(args) == 2 and args[1].isdigit():
        tlg_run.wait_for_exit(int(args[1]))
        args = []
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
    launch_lock = None
    if tlg_run.FROZEN and os.name == 'nt':
        import update_install
        try:
            launch_lock = update_install.install_lock(tlg_run.PORT_DIR, '.gr2-launcher.lock')
            launch_lock.__enter__()
            pending = update_install.pending(tlg_run.PORT_DIR)
            if pending and pending[1]['status'] in ('applying', 'recovering'):
                launch_lock.__exit__(None, None, None)
                launch_lock = None
                update_install.start_helper(pending[0], rollback=True)
                return 0
        except (update_install.InstallError, OSError) as error:
            import ctypes
            url = 'https://github.com/HayatoG/gr2_pc/releases/latest'  # same value as qt/releases.py RELEASES_URL
            if getattr(error, 'kind', '') == 'busy':   # another launcher window, or an update, holds the lock
                text = ('Outra janela do launcher ou uma atualização está em andamento. Aguarde e tente de novo.\n\n'
                        'Another launcher window or an update is in progress. Wait and try again.')
            else:
                text = ('Uma atualização anterior foi interrompida e não pode ser concluída automaticamente. '
                        'Mantenha a pasta de instalação como está, não apague a pasta user/ nem os saves, '
                        'e reinstale o pacote da release nesta mesma pasta:\n' + url + '\n\n'
                        'A previous update was interrupted and cannot be completed automatically. '
                        'Keep the install folder as it is, do not delete the user/ folder or your saves, '
                        'and reinstall the release package into this same folder from the release page:\n' + url)
            ctypes.windll.user32.MessageBoxW(None, f'{text}\n\n({error})', 'Gravity Rush 2 — Launcher / Atualização', 0x10)
            return 1
    try:
        app = App()
        if launch_lock:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: update_install.confirm(tlg_run.PORT_DIR))
        code = app.run()
    finally:
        if launch_lock:
            launch_lock.__exit__(None, None, None)
    # Settings are already saved and the game runs on its own: skip the interpreter teardown, where
    # PySide6/QML destructors and leftover threads could keep a closed launcher alive (Windows).
    for stream in (sys.stdout, sys.stderr):   # None in the windowed executable
        if stream is not None:
            stream.flush()
    os._exit(code if isinstance(code, int) else 0)


if __name__ == '__main__':
    main()
