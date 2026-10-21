# SPDX-License-Identifier: GPL-2.0-or-later
"""Light reader for the game's log file (no Qt, no Tk). The game writes straight to the file;
the launcher only looks at the new bytes now and then, so showing the log costs the game nothing."""
import collections

MAX_CHUNK = 1 << 20      # most bytes read per poll; a flood skips ahead to the newest ones
MAX_PARTIAL = 1 << 16    # a "line" longer than this is shown as it is instead of waiting for the \n


class LogTail:
    def __init__(self, path, max_lines=500):
        self.path = path
        self.offset = 0                  # bytes of the file already consumed
        self.partial = b''               # the unfinished last line, waiting for its \n
        self.lines = collections.deque(maxlen=max_lines)

    def poll(self, final=False):
        """Reads only what was appended since the last call; returns the new complete lines
        (the last max_lines at most). final=True also returns an unfinished last line."""
        try:
            with open(self.path, 'rb') as handle:
                size = handle.seek(0, 2)
                if size < self.offset:               # file replaced or truncated: start over
                    self.offset, self.partial = 0, b''
                start = self.offset
                if size - start > MAX_CHUNK:         # far behind: keep only the tail of the file
                    start, self.partial = size - MAX_CHUNK, b''
                    skipping = True
                else:
                    skipping = False
                handle.seek(start)
                data = handle.read(size - start)
        except OSError:
            return []
        self.offset = start + len(data)
        data = self.partial + data
        parts = data.split(b'\n')
        self.partial = parts.pop()
        if skipping and parts:
            parts.pop(0)                             # cut in the middle of a line
        if len(self.partial) > MAX_PARTIAL or (final and self.partial):
            parts.append(self.partial)
            self.partial = b''
        new = [p.rstrip(b'\r').decode('utf-8', 'replace') for p in parts][-self.lines.maxlen:]
        self.lines.extend(new)
        return new
