# SPDX-License-Identifier: GPL-2.0-or-later
"""The QObject behind the Updates screen. One HTTPS GET to the GitHub releases API when the player
clicks "Check for updates" (or opens the launcher with the option on, off by default); it sends no
data of the player. Nothing is downloaded or installed: "Download" opens the release page."""
import datetime
import threading
import webbrowser

from PySide6.QtCore import Property, QObject, Signal, Slot

from . import releases, report
from .logic import tlg_run


class Updates(QObject):
    changed = Signal()
    fetched = Signal(object)

    def __init__(self, backend, probes=None):
        """probes (tests, screenshots): 'fetch' -> f(version) returning the release dict or raising
        UpdateError, 'version' -> the installed version, 'open_url' -> f(url), 'save' -> f(settings)."""
        super().__init__(backend)
        self.backend = backend
        self.probes = probes or {}
        self._checking = False
        self._error = ''
        seen = backend.settings.get('update_seen')
        self.release = dict(seen) if isinstance(seen, dict) and seen.get('tag') else None
        self.fetched.connect(self._on_fetched)

    def t(self, key, **fmt):
        return self.backend.t_(key, **fmt)

    # -- state ---------------------------------------------------------------------------------------
    def installed(self):
        if 'version' in self.probes:
            return self.probes['version']()
        return report.current_version((tlg_run.PORT_DIR, tlg_run.REPO_DIR), tlg_run.LOG_DIR)

    def status(self):
        if not self.release:
            return 'none'
        return releases.compare(self.installed(), self.release.get('tag', ''))

    @Property(bool, notify=changed)
    def available(self):
        """A newer version is known (the dot on the rail)."""
        return bool(self.release) and self.status() in ('newer', 'different')

    @Property(str, notify=changed)
    def current(self):
        return self.installed() or self.t('rep_unknown')

    @Property(str, notify=changed)
    def latest(self):
        return self.release['tag'] if self.release else '—'

    @Property(str, notify=changed)
    def published(self):
        return (self.release or {}).get('published', '')

    @Property(bool, notify=changed)
    def checking(self):
        return self._checking

    @Property(bool, notify=changed)
    def canDownload(self):
        return True     # without a known release it opens the releases page

    @Property(str, notify=changed)
    def statusText(self):
        if self._checking:
            return self.t('upd_checking')
        if self._error:
            return self._error
        status = self.status()
        tag = self.latest
        if status == 'none':
            return self.t('upd_never')
        return self.t('upd_' + status, tag=tag, current=self.installed())

    @Property(str, notify=changed)
    def tone(self):
        if self._error:
            return 'bad'
        return {'newer': 'warn', 'different': 'warn', 'same': 'good'}.get(self.status(), 'info') \
            if not self._checking else 'info'

    @Property(str, notify=changed)
    def notes(self):
        if not self.release:
            return ''
        notes = releases.extract_notes(self.release.get('body', ''), self.backend.t_.pt())
        return notes or self.t('upd_no_notes')

    @Property(bool, notify=changed)
    def checkOnOpen(self):
        return bool(self.backend.settings.get('check_updates_on_open', False))

    @Slot(bool)
    def setCheckOnOpen(self, value):
        self.backend.settings['check_updates_on_open'] = bool(value)
        self._save()
        self.changed.emit()

    def _save(self):
        if 'save' in self.probes:
            self.probes['save'](self.backend.settings)
        else:
            tlg_run.save_settings(self.backend.settings)

    # -- the check -----------------------------------------------------------------------------------
    @Slot()
    def check(self):
        if self._checking:
            return
        self._checking, self._error = True, ''
        self.changed.emit()
        version = self.installed()

        def work():
            fetch = self.probes.get('fetch') or (lambda v: releases.fetch_latest(v))
            try:
                self.fetched.emit(fetch(version))
            except releases.UpdateError as error:
                self.fetched.emit(error)
            except Exception as error:    # never let a surprise leave the screen stuck on "checking"
                self.fetched.emit(releases.UpdateError('http', str(error)))
        threading.Thread(target=work, daemon=True).start()

    def _on_fetched(self, result):
        self._checking = False
        if isinstance(result, releases.UpdateError):
            self._error = self.t('upd_err_' + result.kind, detail=result.detail)
        else:
            self.release = {'tag': result['tag'], 'url': result['url'], 'body': result['body'][:20000],
                            'published': result['published'],
                            'checked': datetime.date.today().isoformat()}
            self.backend.settings['update_seen'] = self.release
            self._save()
        self.changed.emit()

    @Slot()
    def download(self):
        url = (self.release or {}).get('url') or releases.RELEASES_URL
        if not url.startswith(releases.RELEASE_PREFIX):
            url = releases.RELEASES_URL
        if 'open_url' in self.probes:
            self.probes['open_url'](url)
        else:
            webbrowser.open(url)
