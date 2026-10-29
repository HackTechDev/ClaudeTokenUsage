#!/usr/bin/env python3
"""Interface Qt affichant l'utilisation des limites Claude, rafraîchie chaque minute."""
import sys
from datetime import datetime

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from claude_usage import fetch_usage, format_remaining

REFRESH_MS = 60_000


class FetchThread(QThread):
    """Interroge l'API hors du thread graphique pour ne pas figer la fenêtre."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        try:
            self.done.emit(fetch_usage())
        except Exception as e:
            self.failed.emit(str(e))


def bar_color(percent):
    if percent >= 90:
        return "#d9534f"
    if percent >= 75:
        return "#f0ad4e"
    return "#5cb85c"


class UsageWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Claude Usage")
        self.setMinimumWidth(420)
        self.thread = None
        self.last_usage = None

        self.grid = QGridLayout()
        self.rows = {}  # type de limite -> widgets de sa ligne

        self.status = QLabel("Chargement…")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status.setStyleSheet("color: gray;")

        refresh = QPushButton("Rafraîchir")
        refresh.clicked.connect(self.refresh)

        layout = QVBoxLayout(self)
        layout.addLayout(self.grid)
        layout.addWidget(refresh)
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)
        self.refresh()

    def refresh(self):
        if self.thread and self.thread.isRunning():
            return
        self.thread = FetchThread()
        self.thread.done.connect(self.show_usage)
        self.thread.failed.connect(self.show_error)
        self.thread.start()

    def row(self, limit):
        """Renvoie les widgets de la ligne d'une limite, en les créant au besoin."""
        if limit.kind not in self.rows:
            name, bar, reset = QLabel(limit.label), QProgressBar(), QLabel()
            bar.setRange(0, 100)
            bar.setFormat("%v %")
            line = self.grid.rowCount()
            for col, w in enumerate((name, bar, reset)):
                self.grid.addWidget(w, line, col)
            self.rows[limit.kind] = (name, bar, reset)
        return self.rows[limit.kind]

    def show_usage(self, usage):
        self.last_usage = usage
        active = {l.kind for l in usage.limits}
        for kind, widgets in self.rows.items():
            for w in widgets:
                w.setVisible(kind in active)
        for limit in usage.limits:
            name, bar, reset_label = self.row(limit)
            for w in (name, bar, reset_label):
                w.setVisible(True)
            bar.setValue(round(limit.percent))
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {bar_color(limit.percent)}; }}")
            reset_label.setText(f"réinit. {limit.resets_at:%d/%m %H:%M}"
                                f" (dans {format_remaining(limit.remaining())})")
        self.status.setText(f"Mis à jour à {datetime.now():%H:%M:%S}")

    def show_error(self, message):
        if self.last_usage:  # garde les dernières valeurs, avec un compte à rebours à jour
            self.show_usage(self.last_usage)
        self.status.setText(f"Erreur à {datetime.now():%H:%M:%S} : {message}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = UsageWindow()
    window.show()
    sys.exit(app.exec())
