#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Gravity Rush 2 launcher (Tkinter, Linux and Windows), in pt_BR and en_US.

Game folder, game and interface language, display, FPS overlay, VRAM budget and native audio;
Play starts the game through gr2_run.py (the same code path as run_gr2.sh) and shows its log.
Settings live in ~/.config/tlg-launcher/settings.json (%APPDATA% on Windows).
"""
import locale
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gr2_run as tlg_run  # noqa: E402  (same API as the TLG core)

TEXT = {
    'title': ('Gravity Rush 2 — PC', 'Gravity Rush 2 — PC'),
    'gs_outline_off': ('Turn off the geometry-shader outline (fixes black streaks)', 'Desligar o contorno do geometry shader (corrige as linhas pretas)'),
    'game': ('Game', 'Jogo'),
    'game_dir': ('Game folder', 'Pasta do jogo'),
    'system_lib_dir': ('Console system modules', 'Módulos do sistema do console'),
    'browse': ('Browse…', 'Procurar…'),
    'language': ('Language', 'Idioma'),
    'game_language': ('Game language (voice and text)', 'Idioma do jogo (voz e texto)'),
    'ui_language': ('Interface language', 'Idioma da interface'),
    'auto': ('Automatic (system)', 'Automático (sistema)'),
    'video': ('Video', 'Vídeo'),
    'display_mode': ('Display mode', 'Modo de exibição'),
    'Windowed': ('Windowed', 'Janela'),
    'Borderless': ('Borderless window', 'Janela sem borda'),
    'Fullscreen': ('Fullscreen', 'Tela cheia'),
    'vsync': ('VSync', 'VSync'),
    'show_fps': ('Show FPS overlay at start (F10 toggles)', 'Mostrar overlay de FPS ao iniciar (F10 alterna)'),
    'vram': ('Texture cache budget (MB of VRAM)', 'Orçamento do cache de texturas (MB de VRAM)'),
    'vram_hint': ('6 GB card: 5600 · 8 GB: 7000 · 12 GB: 10500 · 16 GB: 14000 · 24 GB: 21500. This is video card memory (VRAM), not RAM; never above your card\'s VRAM.',
                  'Placa de 6 GB: 5600 · 8 GB: 7000 · 12 GB: 10500 · 16 GB: 14000 · 24 GB: 21500. É a memória da placa de vídeo (VRAM), não a RAM; nunca acima da VRAM da placa.'),
    'audio': ('Audio', 'Áudio'),
    'native_audio': ('Native audio (libSceNgs2.sprx from your console)', 'Áudio nativo (libSceNgs2.sprx do seu console)'),
    'play': ('Play', 'Jogar'),
    'saves': ('Saves folder', 'Pasta de saves'),
    'logs': ('Logs folder', 'Pasta de logs'),
    'clear_cache': ('Clear shader cache', 'Limpar cache de shaders'),
    'clear_cache_ask': ('This deletes the compiled shaders ({size}); the next start takes longer to load and '
                        'may stutter at first. Continue?',
                        'Isso apaga os shaders compilados ({size}); a próxima partida demora mais para carregar e '
                        'pode engasgar no começo. Continuar?'),
    'clear_cache_empty': ('The shader cache is already empty.', 'O cache de shaders já está vazio.'),
    'clear_cache_done': ('Shader cache cleared: {size} freed.', 'Cache de shaders limpo: {size} liberados.'),
    'clear_cache_failed': ('{size} freed, but {count} file(s) could not be deleted (in use? Close the game '
                           'and try again).',
                           '{size} liberados, mas {count} arquivo(s) não puderam ser apagados (em uso? Feche o '
                           'jogo e tente de novo).'),
    'mods': ('Mods / Cheats…', 'Mods / Cheats…'),
    'mods_title': ('Mods / Cheats', 'Mods / Cheats'),
    'mods_hint': ('Drop shadPS4/GoldHEN cheat XML files in the mods folder, then turn them on here. '
                  'Nothing here changes the game until you enable it.',
                  'Solte arquivos de cheat XML no formato shadPS4/GoldHEN na pasta de mods e ligue aqui. '
                  'Nada muda no jogo até você ativar.'),
    'mods_warning': ('A cheat can crash the game or behave oddly; if that happens, turn it off here.',
                     'Um cheat pode travar o jogo ou se comportar de forma estranha; se isso acontecer, desligue aqui.'),
    'mods_folder': ('Open mods folder', 'Abrir pasta de mods'),
    'mods_refresh': ('Refresh list', 'Atualizar lista'),
    'mods_empty': ('No cheat XML files found in the mods folder yet.',
                   'Nenhum arquivo de cheat XML encontrado na pasta de mods ainda.'),
    'close': ('Close', 'Fechar'),
    'quit': ('Quit', 'Sair'),
    'ready': ('Ready to play.', 'Pronto para jogar.'),
    'audio_native': ('Audio: native (console module found).', 'Áudio: nativo (módulo do console encontrado).'),
    'audio_builtin': ('Audio: built-in mixer, experimental (libSceNgs2.sprx not found or not selected).',
                      'Áudio: mixer próprio, experimental (libSceNgs2.sprx não encontrado ou desmarcado).'),
    'missing': ('Missing', 'Faltando'),
    'not_built': ('Port not built (run build.sh)', 'Port não compilado (rode o build.sh)'),
    'preparing': ('Preparing the game…', 'Preparando o jogo…'),
    'running': ('Playing — log:', 'Jogando — log:'),
    'ended': ('Game closed (exit code {code}).', 'Jogo fechado (código {code}).'),
    'crashed': ('The game closed with an error (code {code}). The log has the details.',
                'O jogo fechou com erro (código {code}). Os detalhes estão no log.'),
    'already': ('The game is already running.', 'O jogo já está rodando.'),
    'error': ('Error', 'Erro'),
    'port_by': ('PC port by HayatoG', 'Port para PC por HayatoG'),
    'channel': ('YouTube channel: @hayatog-dev', 'Canal no YouTube: @hayatog-dev'),
    'discord': ('Discord community', 'Comunidade no Discord'),
}
CHANNEL_URL = 'https://www.youtube.com/@hayatog-dev'
DISCORD_URL = 'https://discord.gg/UMkdMYZh9g'
GAME_LANGUAGE_NAMES = {'en': 'English', 'pt_BR': 'Português (Brasil)', 'es_LA': 'Español (Latinoamérica)',
                       'fr_CA': 'Français (Canada)'}
UI_LANGUAGES = ['auto', 'pt_BR', 'en_US']
UI_LANGUAGE_NAMES = {'pt_BR': 'Português (Brasil)', 'en_US': 'English (US)'}
DISPLAY_MODES = ['Windowed', 'Borderless', 'Fullscreen']


def art_path(settings, name):
    """Official art from the user's own dump (sce_sys); never shipped with the port."""
    for folder in (Path(settings['game_dir']) / 'sce_sys', tlg_run.REPO_DIR / 'dump' / 'sce_sys'):
        if (folder / name).is_file():
            return folder / name
    return None


def system_is_portuguese():
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        value = os.environ.get(name)
        if value:
            return value.lower().startswith('pt')
    try:
        return (locale.getlocale()[0] or '').lower().startswith('pt')
    except ValueError:
        return False


class Launcher:
    def __init__(self, root):
        self.root = root
        self.settings = tlg_run.load_settings()
        self.process = None
        self.lines = queue.Queue()
        self.build()
        self.root.after(100, self.pump)

    # -- language ---------------------------------------------------------------------------
    def pt(self):
        choice = self.settings.get('ui_language', 'auto')
        return system_is_portuguese() if choice == 'auto' else choice == 'pt_BR'

    def t(self, key, **fmt):
        en, pt = TEXT[key]
        return (pt if self.pt() else en).format(**fmt)

    # -- window -----------------------------------------------------------------------------
    def build(self):
        """Horizontal layout: banner on top; Game + Audio | Language + Video | game log; buttons below."""
        for child in self.root.winfo_children():
            child.destroy()
        root = self.root
        root.title(self.t('title'))
        root.minsize(1120, 640)
        pad = {'padx': 6, 'pady': 4}
        main = ttk.Frame(root, padding=12)
        main.pack(fill='both', expand=True)
        for column, weight in enumerate((3, 3, 4)):
            main.columnconfigure(column, weight=weight, uniform='cols' if column < 2 else '')
        main.rowconfigure(2, weight=1)

        header = ttk.Frame(main)
        header.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 8))
        self.load_art()
        if self.banner:
            ttk.Label(header, image=self.banner).pack(side='left', padx=(0, 14))
        titles = ttk.Frame(header)
        titles.pack(side='left', fill='y')
        ttk.Label(titles, text='Gravity Rush 2', font=('TkDefaultFont', 22, 'bold')).pack(anchor='w')
        ttk.Label(titles, text='PC — CUSA03694 v1.00', foreground='#777').pack(anchor='w')
        credits = ttk.Frame(header)
        credits.pack(side='right', anchor='ne')
        ttk.Label(credits, text=self.t('port_by'), foreground='#777').pack(anchor='e')
        for key, url in (('channel', CHANNEL_URL), ('discord', DISCORD_URL)):
            link = ttk.Label(credits, text=self.t(key), foreground='#2a6fdb', cursor='hand2',
                             font=('TkDefaultFont', 10, 'underline'))
            link.pack(anchor='e')
            link.bind('<Button-1>', lambda _, u=url: gr2_run.open_external(u))
        self.status = ttk.Label(titles, text='', foreground='#555', wraplength=420, justify='left')
        self.status.pack(anchor='w', pady=(10, 0))

        self.vars = {}
        left = ttk.Frame(main)
        left.grid(row=2, column=0, sticky='nsew', **pad)
        left.columnconfigure(0, weight=1)
        game = ttk.LabelFrame(left, text=self.t('game'), padding=8)
        game.grid(sticky='ew', pady=(0, 8))
        game.columnconfigure(0, weight=1)
        for row, key in enumerate(('game_dir', 'system_lib_dir')):
            ttk.Label(game, text=self.t(key)).grid(row=row * 2, column=0, columnspan=2, sticky='w')
            var = tk.StringVar(value=self.settings[key])
            var.trace_add('write', lambda *_: self.changed())
            self.vars[key] = var
            ttk.Entry(game, textvariable=var).grid(row=row * 2 + 1, column=0, sticky='ew', pady=(0, 6))
            ttk.Button(game, text=self.t('browse'), command=lambda k=key: self.browse(k)).grid(
                row=row * 2 + 1, column=1, padx=(6, 0), pady=(0, 6))
        audio = ttk.LabelFrame(left, text=self.t('audio'), padding=8)
        audio.grid(sticky='ew')
        self.check(audio, 0, 'native_audio')

        middle = ttk.Frame(main)
        middle.grid(row=2, column=1, sticky='nsew', **pad)
        middle.columnconfigure(0, weight=1)
        lang = ttk.LabelFrame(middle, text=self.t('language'), padding=8)
        lang.grid(sticky='ew', pady=(0, 8))
        lang.columnconfigure(1, weight=1)
        self.combo(lang, 0, 'game_language', list(tlg_run.GAME_LANGUAGES), lambda k: GAME_LANGUAGE_NAMES[k])
        self.combo(lang, 1, 'ui_language', UI_LANGUAGES,
                   lambda k: self.t('auto') if k == 'auto' else UI_LANGUAGE_NAMES[k], on_change=self.build)
        video = ttk.LabelFrame(middle, text=self.t('video'), padding=8)
        video.grid(sticky='ew')
        video.columnconfigure(1, weight=1)
        self.combo(video, 0, 'display_mode', DISPLAY_MODES, lambda k: self.t(k))
        self.check(video, 1, 'vsync')
        self.check(video, 2, 'show_fps')
        self.check(video, 5, 'gs_outline_off')
        ttk.Label(video, text=self.t('vram'), wraplength=220).grid(row=3, column=0, sticky='w', pady=(6, 0))
        vram = tk.IntVar(value=int(self.settings['vram_budget_mb']))
        self.vars['vram_budget_mb'] = vram
        spin = ttk.Spinbox(video, from_=2000, to=24000, increment=200, textvariable=vram, width=8,
                           command=self.changed)
        spin.grid(row=3, column=1, sticky='w', padx=6, pady=(6, 0))
        spin.bind('<FocusOut>', lambda _: self.changed())
        ttk.Label(video, text=self.t('vram_hint'), foreground='#777', wraplength=360).grid(row=4, column=0, columnspan=2, sticky='w')

        log_frame = ttk.LabelFrame(main, text='Log', padding=4)
        log_frame.grid(row=2, column=2, sticky='nsew', **pad)
        self.log = tk.Text(log_frame, wrap='none', font=('TkFixedFont', 9), state='disabled', width=60)
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        buttons = ttk.Frame(main)
        buttons.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        ttk.Button(buttons, text=self.t('quit'), command=self.quit).pack(side='left')
        style = ttk.Style()
        style.configure('Play.TButton', font=('TkDefaultFont', 13, 'bold'))
        self.play_button = ttk.Button(buttons, text=self.t('play'), style='Play.TButton', command=self.play)
        self.play_button.pack(side='right', ipadx=30, ipady=8)
        ttk.Button(buttons, text=self.t('logs'), command=lambda: self.open(tlg_run.LOG_DIR)).pack(side='right', padx=6)
        ttk.Button(buttons, text=self.t('saves'), command=lambda: self.open(tlg_run.USER_DIR / 'savedata')).pack(side='right')
        self.cache_button = ttk.Button(buttons, text=self.t('clear_cache'), command=self.clear_cache)
        self.cache_button.pack(side='right', padx=(0, 6))
        ttk.Button(buttons, text=self.t('mods'), command=self.mods_dialog).pack(side='right', padx=(0, 6))
        self.refresh_status()

    def load_art(self):
        """Window icon (the port's tlg.png) and a 480x135 banner (a band of pic1.png from the dump, when present)."""
        self.banner = getattr(self, 'banner', None)
        if getattr(self, 'art_loaded', False):
            return
        self.art_loaded = True
        try:
            icon = art_path(self.settings, 'icon0.png')  # the game's own icon, from the user's dump
            if icon and icon.is_file():
                self.icon = tk.PhotoImage(file=str(icon)).subsample(4)
                self.root.iconphoto(True, self.icon)
            elif (tlg_run.PORT_DIR / 'launcher' / 'gr2.png').is_file():  # the port's own icon
                self.icon = tk.PhotoImage(file=str(tlg_run.PORT_DIR / 'launcher' / 'gr2.png'))
                self.root.iconphoto(True, self.icon)
            picture = art_path(self.settings, 'pic1.png') or art_path(self.settings, 'pic0.png')
            if picture:
                full = tk.PhotoImage(file=str(picture))
                band = full.width() * 9 // 32           # a 32:9 band from the middle of the image
                top = (full.height() - band) // 2
                self.banner = tk.PhotoImage()
                self.banner.tk.call(self.banner, 'copy', full, '-from', 0, top, full.width(), top + band,
                                    '-subsample', 4, 4)  # Tk command: same on every Python version
        except tk.TclError:
            self.banner = None

    def combo(self, parent, row, key, values, label, on_change=None):
        ttk.Label(parent, text=self.t(key)).grid(row=row, column=0, sticky='w')
        names = [label(v) for v in values]
        box = ttk.Combobox(parent, values=names, state='readonly', width=28)
        current = self.settings.get(key, values[0])
        box.current(values.index(current) if current in values else 0)
        box.grid(row=row, column=1, sticky='w', padx=6, pady=2)

        def picked(_):
            self.settings[key] = values[box.current()]
            tlg_run.save_settings(self.settings)
            if on_change:
                on_change()
            else:
                self.refresh_status()
        box.bind('<<ComboboxSelected>>', picked)
        return box

    def mods_dialog(self):
        """Mods/cheats (shadPS4/GoldHEN XML in tlg_run.mods_dir()); toggles write mods.json
        through tlg_run.set_mod_enabled. Nothing here is on unless the player turns it on."""
        if getattr(self, 'mods_window', None) and self.mods_window.winfo_exists():
            self.mods_window.lift()
            return
        win = self.mods_window = tk.Toplevel(self.root)
        win.title(self.t('mods_title'))
        win.transient(self.root)
        win.minsize(560, 360)
        frame = ttk.Frame(win, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=self.t('mods_hint'), wraplength=520, justify='left').pack(anchor='w')
        ttk.Label(frame, text=self.t('mods_warning'), foreground='#a33', wraplength=520, justify='left').pack(
            anchor='w', pady=(4, 8))

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill='both', expand=True)
        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scroll = ttk.Scrollbar(list_frame, orient='vertical', command=canvas.yview)
        rows = ttk.Frame(canvas)
        rows.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=rows, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        def toggle(key, var):
            tlg_run.set_mod_enabled(key, var.get())

        def populate():
            for child in rows.winfo_children():
                child.destroy()
            try:
                mods = tlg_run.list_mods(self.settings)
            except Exception as error:  # a malformed XML file is reported, never crashes the launcher
                mods = []
                ttk.Label(rows, text=str(error), foreground='#a33').pack(anchor='w')
            if not mods:
                ttk.Label(rows, text=self.t('mods_empty'), foreground='#777').pack(anchor='w', pady=8)
            for key, name, note, enabled in mods:
                row = ttk.Frame(rows)
                row.pack(fill='x', anchor='w', pady=2)
                var = tk.BooleanVar(value=enabled)
                ttk.Checkbutton(row, text=name or key, variable=var,
                                command=lambda k=key, v=var: toggle(k, v)).pack(anchor='w')
                if note:
                    ttk.Label(row, text=note, foreground='#777', wraplength=480, justify='left').pack(
                        anchor='w', padx=(22, 0))
        populate()

        bottom = ttk.Frame(frame)
        bottom.pack(fill='x', pady=(10, 0))
        ttk.Button(bottom, text=self.t('mods_folder'), command=lambda: self.open(tlg_run.mods_dir())).pack(side='left')
        ttk.Button(bottom, text=self.t('mods_refresh'), command=populate).pack(side='left', padx=6)
        ttk.Button(bottom, text=self.t('close'), command=win.destroy).pack(side='right')

    def check(self, parent, row, key):
        var = tk.BooleanVar(value=bool(self.settings[key]))
        self.vars[key] = var
        ttk.Checkbutton(parent, text=self.t(key), variable=var, command=self.changed).grid(
            row=row, column=0, columnspan=3, sticky='w', pady=2)

    # -- actions ----------------------------------------------------------------------------
    def changed(self):
        for key, var in self.vars.items():
            try:
                self.settings[key] = var.get()
            except tk.TclError:
                pass  # spinbox while typing
        tlg_run.save_settings(self.settings)
        self.refresh_status()

    def refresh_status(self):
        problems = tlg_run.check_game(self.settings['game_dir'])
        if problems:
            text = '; '.join(self.t('not_built') if k == 'not_built' else f"{self.t('missing')}: {d}"
                             for k, d in problems)
        else:
            text = self.t('ready')
        audio = self.t('audio_native') if tlg_run.ngs2_module(self.settings) else self.t('audio_builtin')
        self.status.configure(text=f'{text}  {audio}')
        self.play_button.configure(state='disabled' if problems or self.process else 'normal')
        self.cache_button.configure(state='disabled' if self.process else 'normal')

    def browse(self, key):
        path = filedialog.askdirectory(initialdir=self.vars[key].get() or str(Path.home()))
        if path:
            self.vars[key].set(path)

    def open(self, path):
        Path(path).mkdir(parents=True, exist_ok=True)
        gr2_run.open_external(path)

    def clear_cache(self):
        """Clear shader cache: asks first, never while the game runs; shows how much was freed."""
        if self.process:
            messagebox.showinfo(self.t('title'), self.t('already'))
            return
        size = tlg_run.shader_cache_size(self.settings)
        if not size:
            messagebox.showinfo(self.t('clear_cache'), self.t('clear_cache_empty'))
            return
        if not messagebox.askyesno(self.t('clear_cache'),
                                   self.t('clear_cache_ask', size=tlg_run.shader_cache.human_size(size))):
            return
        try:
            freed, failures = tlg_run.clear_shader_cache(self.settings)
        except Exception as error:  # shown to the user, the launcher keeps running
            messagebox.showerror(self.t('error'), str(error))
            return
        freed = tlg_run.shader_cache.human_size(freed)
        if failures:
            message = self.t('clear_cache_failed', size=freed, count=len(failures))
            messagebox.showwarning(self.t('clear_cache'), message)
        else:
            message = self.t('clear_cache_done', size=freed)
            messagebox.showinfo(self.t('clear_cache'), message)
        self.append(message)

    def append(self, line):
        self.log.configure(state='normal')
        self.log.insert('end', line if line.endswith('\n') else line + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 2000:
            self.log.delete('1.0', '500.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def play(self):
        if self.process:
            messagebox.showinfo(self.t('title'), self.t('already'))
            return
        self.changed()
        self.append(self.t('preparing'))
        self.play_button.configure(state='disabled')
        self.cache_button.configure(state='disabled')
        threading.Thread(target=self.run_game, daemon=True).start()

    def run_game(self):
        try:
            tlg_run.prepare(self.settings, log=lambda line: self.lines.put(line))
            self.process, log = tlg_run.launch(self.settings)
        except Exception as error:  # shown to the user, the launcher keeps running
            self.lines.put(('error', str(error)))
            return
        self.lines.put(f"{self.t('running')} {log}")
        with open(log, 'w', encoding='utf-8') as out:
            for line in self.process.stdout:
                out.write(line)
                out.flush()
                self.lines.put(line.rstrip('\n'))
        code = self.process.wait()
        self.process = None
        self.lines.put(('ended', code))

    def pump(self):
        try:
            while True:
                item = self.lines.get_nowait()
                if isinstance(item, tuple):
                    kind, value = item
                    if kind == 'error':
                        messagebox.showerror(self.t('error'), value)
                    else:
                        message = self.t('ended' if value in (0, -15) else 'crashed', code=value)
                        self.append(message)
                        if value not in (0, -15):
                            messagebox.showwarning(self.t('title'), message)
                    self.refresh_status()
                else:
                    self.append(item)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def quit(self):
        if self.process:
            self.process.terminate()
        self.root.destroy()


def main():
    # Packaged executable roles: --script <file> runs a preparation script, --play starts the
    # game with the saved settings and no launcher window (shortcuts, Steam).
    args = sys.argv[1:]
    if args[:1] == ['--script'] and len(args) > 1:
        sys.exit(tlg_run.run_script(args[1:]))
    if args[:1] == ['--clear-shader-cache']:
        sys.exit(tlg_run.main(args))
    if args[:1] == ['--play']:
        sys.exit(tlg_run.main(args[1:]))
    root = tk.Tk(className='gr2-pc')  # matches StartupWMClass in the desktop entry
    try:
        ttk.Style().theme_use('clam')
    except tk.TclError:
        pass
    Launcher(root)
    root.mainloop()


if __name__ == '__main__':
    main()
