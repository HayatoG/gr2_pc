# SPDX-License-Identifier: GPL-2.0-or-later
"""Every switch the launcher's "Experimental fixes" window and the Graphics screen's in-game-menu
rows offer. Only options this port's runtime really reads are listed: each MENU key and each ini A/B
key is parsed by gpu/shim/tlg_settings.cpp (tlg.ini), each env-only A/B switch is a getenv() of the
GPU core (GR2_X is copied to TLG_X by src/probe.c). tests/test_launcher_options.py checks that.
The BP01-BP12 shadPS4 backports and inFAMOUS's draw-distance/LDS/occlusion/AMD switches are not in
this port's core, so they are not offered. ADVANCED stays empty (inFAMOUS-specific tuning)."""
from collections import namedtuple
from pathlib import Path

import advanced_table

Item = namedtuple('Item', 'id group key env vtype default choices lo hi unit shader live store '
                          'pass_env risky broken name what source tab')
Item.__new__.__defaults__ = ()


def _make(id, group, key, env, vtype, default, name, what, *, choices=(), lo=0, hi=0, unit='',
          shader=False, live=False, store='ini', pass_env=False, risky=False, broken=False,
          source='', tab=''):
    return Item(id, group, key, env, vtype, default, choices, lo, hi, unit, shader, live, store,
                pass_env, risky, broken, name, what, source, tab)


def _bp(n, default, shader, live, name, what, source, risky=False):
    return _make(f'BP{n:02d}', 'bp', f'bp{n:02d}', f'GR2_BP{n:02d}', 'bool', '1' if default else '0',
                 name, what, shader=shader, live=live, pass_env=True, risky=risky, source=source)


def _ab(key, env, default, shader, live, name, what, store='ini', pass_env=True, broken=False):
    return _make(env, 'ab', key, env, 'bool', None if default is None else '1' if default else '0',
                 name, what, shader=shader, live=live, store=store, pass_env=pass_env, broken=broken)


def _ab_choice(key, env, default, choices, name, what, **kw):
    return _make(env, 'ab', key, env, 'choice', default, name, what, choices=choices, pass_env=True, **kw)


def _menu(tab, key, vtype, default, name, what, **kw):
    return _make('menu:' + key, 'menu', key, '', vtype, default, name, what, live=True, tab=tab, **kw)


_CORNERS = (('0', 'Top left', 'Superior esquerdo'), ('1', 'Top right', 'Superior direito'),
            ('2', 'Bottom left', 'Inferior esquerdo'), ('3', 'Bottom right', 'Inferior direito'))
MENU = [
    _menu('Image', 'fsr1', 'bool', '0', ('Upscale with FSR 1', 'Ampliar com FSR 1'),
          ('Enlarges the game image when it is smaller than the window (spatial filter, no shimmer).',
           'Amplia a imagem do jogo quando ela é menor que a janela (filtro espacial, sem tremor).')),
    _menu('Image', 'rcas', 'bool', '1', ('Sharpening (RCAS)', 'Nitidez (RCAS)'),
          ('Sharpens the final image. Needs FSR 1 when the game image is smaller than the window.',
           'Deixa a imagem final mais nítida. Precisa do FSR 1 quando a imagem do jogo é menor que a janela.')),
    _menu('Image', 'rcas_strength', 'int', '60', ('Sharpening strength', 'Intensidade da nitidez'),
          ('How strong the sharpening is.', 'Quão forte é a nitidez.'), lo=0, hi=100, unit='%'),
    _menu('Performance', 'fps_limit', 'choice', '0', ('Frame rate limit', 'Limite de FPS'),
          ('Caps the presented frames. The game runs at 30 FPS (as on PS4).',
           'Limita os quadros apresentados. O jogo roda a 30 FPS (como no PS4).'),
          choices=(('30', '30', '30'), ('60', '60', '60'), ('120', '120', '120'), ('240', '240', '240'),
                   ('0', 'Unlimited', 'Sem limite'))),
    _menu('Performance', 'frames_queued', 'choice', '1', ('Frames queued', 'Quadros na fila'),
          ('More frames queued: steadier FPS, slower response to input.',
           'Mais quadros na fila: FPS mais estável, resposta mais lenta.'),
          choices=(('1', '1 (lowest latency)', '1 (menor atraso)'), ('2', '2', '2'),
                   ('0', 'Unlimited', 'Sem limite'))),
    _menu('Overlay', 'overlay_fps', 'bool', '1', ('Overlay: FPS', 'Overlay: FPS'),
          ('Shows the frame rate in the performance overlay.', 'Mostra os quadros por segundo no overlay.')),
    _menu('Overlay', 'overlay_frametime', 'bool', '1', ('Overlay: frame time', 'Overlay: tempo de quadro'),
          ('Shows the time of each frame.', 'Mostra o tempo de cada quadro.')),
    _menu('Overlay', 'overlay_upscaler', 'bool', '0', ('Overlay: upscaler', 'Overlay: upscaler'),
          ('Shows the active upscaler.', 'Mostra o upscaler ativo.')),
    _menu('Overlay', 'overlay_gpu', 'bool', '1', ('Overlay: GPU', 'Overlay: GPU'),
          ('Shows the GPU name and use.', 'Mostra o nome e o uso da GPU.')),
    _menu('Overlay', 'overlay_cpu', 'bool', '0', ('Overlay: CPU', 'Overlay: CPU'),
          ('Shows the game\'s CPU use.', 'Mostra o uso de CPU do jogo.')),
    _menu('Overlay', 'overlay_ram', 'bool', '0', ('Overlay: RAM', 'Overlay: RAM'),
          ('Shows RAM used by the game and total.', 'Mostra a RAM usada pelo jogo e a total.')),
    _menu('Overlay', 'overlay_vram', 'bool', '1', ('Overlay: VRAM', 'Overlay: VRAM'),
          ('Shows video memory used and available.', 'Mostra a memória de vídeo usada e disponível.')),
    _menu('Overlay', 'overlay_scale', 'int', '100', ('Overlay font size', 'Tamanho da fonte do overlay'),
          ('Size of the overlay text.', 'Tamanho do texto do overlay.'), lo=50, hi=300, unit='%'),
    _menu('Overlay', 'overlay_corner', 'choice', '1', ('Overlay corner', 'Canto do overlay'),
          ('Where the overlay sits.', 'Onde o overlay fica.'), choices=_CORNERS),
    _menu('Overlay', 'overlay_opacity', 'int', '50', ('Overlay background opacity', 'Opacidade do fundo do overlay'),
          ('0% is no background.', '0% é sem fundo.'), lo=0, hi=100, unit='%'),
    _menu('Overlay', 'overlay_layout', 'choice', '0', ('Overlay layout', 'Disposição do overlay'),
          ('Items side by side or stacked.', 'Itens lado a lado ou empilhados.'),
          choices=(('0', 'One line', 'Uma linha'), ('1', 'One item per line', 'Um item por linha'))),
]

# The BP01-BP12 shadPS4 backports of infamous_pc are not in this port's GPU core yet (they come with
# the iss-backports PR), so the table has none: a switch here would change nothing in the game.
BACKPORTS = []

DIAGNOSTICS = [
    _ab('block1d', 'TLG_BLOCK1D', None, True, False, ('BC 1D textures as 2D', 'Texturas BC 1D como 2D'),
        ('Block-compressed 1D textures as 2D images. Automatic: on for drivers that refuse them, except NVIDIA.',
         'Texturas 1D comprimidas como imagens 2D. Automático: ligado nos drivers que as recusam, exceto NVIDIA.')),
    _ab('async_shaders', 'TLG_ASYNC_SHADERS', True, False, True, ('Asynchronous shader compile', 'Compilação assíncrona de shaders'),
        ('Compiles pipelines off the GPU thread (fewer hitches). Also in the in-game menu.',
         'Compila pipelines fora da thread da GPU (menos engasgos). Também no menu do jogo.'),
        pass_env=False),
    _ab('deferred_readback', 'TLG_DEFERRED_READBACK', True, False, False, ('Deferred GPU readbacks', 'Leituras da GPU adiadas'),
        ('Only the thread that reads GPU results waits, not the whole GPU.',
         'Só a thread que lê resultados da GPU espera, não a GPU inteira.'),
        pass_env=False),
    _ab('stale_readback', 'TLG_STALE_READBACK', False, False, False, ('Stale readbacks', 'Leituras da GPU com um quadro de atraso'),
        ('CPU reads see the last published GPU version instead of waiting (needs deferred readbacks).',
         'A CPU lê a última versão publicada pela GPU em vez de esperar (precisa das leituras adiadas).'),
        pass_env=False),
    _ab('background_warmup', 'TLG_BACKGROUND_WARMUP', True, False, False, ('Load pipelines while playing', 'Carregar pipelines durante o jogo'),
        ('The cached pipelines load in the background (a corner note shows progress); off blocks until all are loaded.',
         'Os pipelines em cache carregam em segundo plano (uma nota no canto mostra o progresso); desligado espera carregar tudo.')),
    _ab('pipeline_binaries', 'TLG_PIPELINE_BINARIES', False, False, False, ('Pipeline binaries (VK_KHR_pipeline_binary)', 'Pipeline binaries (VK_KHR_pipeline_binary)'),
        ('Still crashes the game on the NVIDIA 595 driver; off by default in this port.',
         'Ainda derruba o jogo no driver NVIDIA 595; desligado por padrão neste port.'),
        broken=True),
]

ADVANCED = advanced_table.build(_make)
ITEMS = MENU + BACKPORTS + DIAGNOSTICS + ADVANCED
PREFIX = 'GR2_'


def _from_launcher(item, settings):
    value = settings.get(item.key)
    return item.default if value is None else '1' if value else '0'


def read_states(ini, settings=None):
    """{item.id: value text or None}: the player's choice, None = the default applies.
    A value equal to the default is also None, so only real changes are kept."""
    settings = settings or {}
    states = {}
    for item in ITEMS:
        value = _from_launcher(item, settings) if item.store == 'launcher' else ini.get(item.key)
        states[item.id] = normalize(item, value)
    return states


def normalize(item, value):
    """The value if valid and different from the default, else None."""
    if value is None:
        return None
    value = str(value).strip()
    if item.vtype == 'bool':
        valid = value in ('0', '1')
    elif item.vtype == 'choice':
        valid = value in [c[0] for c in item.choices]
    elif item.vtype == 'float':
        try:
            number = float(value)
            valid = item.lo <= number <= item.hi
        except ValueError:
            valid = False
        if valid:
            if abs(number - float(item.default)) <= 1e-6 * max(1.0, abs(number)):
                return None
            value = f'{number:g}' if abs(number) < 1e6 else str(int(round(number)))
    else:
        try:
            valid = item.lo <= int(value) <= item.hi
        except ValueError:
            valid = False
        value = str(int(value)) if valid else value
    return value if valid and value != item.default else None


FLOAT_STEPS = {}


def effective(item, states):
    """The value the game will use; None for an automatic switch left on automatic."""
    value = states.get(item.id)
    return item.default if value is None else value


def ini_updates(states):
    """tlg.ini keys to write: the value for a change, None to remove the key (default again)."""
    return {item.key: states.get(item.id) for item in ITEMS if item.store == 'ini'}


def environment(states, environ=None):
    """GR2_<name>=0/1 for the BPnn and A/B switches the player changed; one already in the
    environment (GR2_ or TLG_) wins. Untouched switches add nothing, so the defaults hold."""
    environ = {} if environ is None else environ
    env = {}
    for item in ITEMS:
        value = states.get(item.id)
        if value is None or not item.pass_env:
            continue
        suffix = item.env[len('TLG_'):] if item.env.startswith('TLG_') else item.env[len(PREFIX):]
        if PREFIX + suffix in environ or item.env in environ:
            continue
        env[PREFIX + suffix] = value
    return env


def previous_release(states):
    """Every BPnn off, as the release before the backports (explicit, so the list shows it)."""
    states = dict(states)
    for item in BACKPORTS:
        states[item.id] = '0' if item.default == '1' else None
    return states


def defaults(states, group=None):
    """Forget every choice (of one group, or all)."""
    return {k: (None if group is None or _group(k) == group else v) for k, v in states.items()}


def is_recommended(item):
    """Rows that are part of the Recommended profile (the table's defaults): the fixes and
    switches that are on by default. Recommended = no choice stored; nothing here changes a default."""
    return item.group in ('bp', 'ab') and item.vtype == 'bool' and item.default == '1'


def changes(states):
    """How many fixes/switches (BPnn and A/B) differ from the Recommended profile. The game menu
    options (overlay corner, limits...) are preferences and do not count."""
    return sum(1 for item in BACKPORTS + DIAGNOSTICS if states.get(item.id) is not None)


def advanced_changes(states):
    """How many Advanced parameters the player changed."""
    return sum(1 for item in ADVANCED if states.get(item.id) is not None)


def notice_pending(settings):
    """The one-time notice about new fixes has not been shown yet (always False: there is
    nothing to notice about until ITEMS has real entries)."""
    return False


def mark_notice_seen(settings):
    settings['backports_notice_seen'] = True


def _group(item_id):
    return next(item.group for item in ITEMS if item.id == item_id)


def write_ini(path, updates):
    """Sets or removes keys in tlg.ini, keeping every other line (the game's own keys included)."""
    path = Path(path)
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        lines = ['# tlg settings']
    out, seen = [], set()
    for line in lines:
        key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else None
        if key in updates:
            seen.add(key)
            if updates[key] is not None:
                out.append(f'{key}={updates[key]}')
        else:
            out.append(line)
    out += [f'{k}={v}' for k, v in updates.items() if v is not None and k not in seen]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')
