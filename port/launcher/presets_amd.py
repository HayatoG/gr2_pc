# SPDX-License-Identifier: GPL-2.0-or-later
"""The "AMD cards" preset (see infamous_pc's presets_amd.py). No AMD-specific workarounds have
been cataloged for Gravity Rush 2 yet; this is a valid but empty preset, same as presets_current.py."""
from presets_current import CURRENT

AMD = {
    'id': 'amd',
    'exported': '',
    'names': {'en': 'AMD CARDS', 'pt': 'PLACAS AMD'},
    'what': {
        'en': 'No AMD-specific preset is cataloged for this port yet.',
        'pt': 'Nenhuma configuração específica para AMD foi catalogada para este port ainda.',
    },
    'settings': dict(CURRENT['settings']),
    'items': dict(CURRENT['items']),
}
