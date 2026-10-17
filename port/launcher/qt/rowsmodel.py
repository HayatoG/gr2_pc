# SPDX-License-Identifier: GPL-2.0-or-later
"""A list of dict rows for QML (the option rows of the Graphics and Controls screens).
set_rows() only emits dataChanged for rows that differ when the list of ids is the same, so a
slider keeps being dragged while its neighbours refresh."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class RowsModel(QAbstractListModel):
    DATA = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def roleNames(self):
        return {self.DATA: b'd'}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=DATA):
        if role == self.DATA and 0 <= index.row() < len(self.rows):
            return self.rows[index.row()]
        return None

    def set_rows(self, rows):
        if [r['id'] for r in rows] != [r['id'] for r in self.rows]:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()
            return
        for n, (old, new) in enumerate(zip(self.rows, rows)):
            if old != new:
                self.rows[n] = new
                self.dataChanged.emit(self.index(n), self.index(n))

    def get(self, row_id):
        return next((r for r in self.rows if r['id'] == row_id), None)
