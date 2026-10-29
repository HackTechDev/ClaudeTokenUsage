#!/usr/bin/env python3
"""Interface Qt affichant l'utilisation des limites Claude, rafraîchie chaque minute."""
import sys
from datetime import datetime

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from claude_usage import BUCKETS, fetch_usage

REFRESH_MS = 60_000


class FetchThread(QThread):
    """Interroge l'API hors du thread graphique pour ne pas figer la fenêtre."""
    done = pyqtSignal(list)
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

        self.grid = QGridLayout()
        self.rows = {}
        for i, (_, label) in enumerate(BUCKETS):
            name, bar, reset = QLabel(label), QProgressBar(), QLabel()
            bar.setRange(0, 100)
            bar.setFormat("%v %")
            for col, w in enumerate((name, bar, reset)):
                self.grid.addWidget(w, i, col)
            self.rows[label] = (name, bar, reset)

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

    def show_usage(self, usage):
        active = {label: (percent, reset) for label, percent, reset in usage}
        for label, (name, bar, reset_label) in self.rows.items():
            visible = label in active
            for w in (name, bar, reset_label):
                w.setVisible(visible)
            if visible:
                percent, reset = active[label]
                bar.setValue(round(percent))
                bar.setStyleSheet(f"QProgressBar::chunk {{ background: {bar_color(percent)}; }}")
                reset_label.setText(f"réinit. {reset:%d/%m %H:%M}")
        self.status.setText(f"Mis à jour à {datetime.now():%H:%M:%S}")

    def show_error(self, message):
        self.status.setText(f"Erreur à {datetime.now():%H:%M:%S} : {message}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = UsageWindow()
    window.show()
    sys.exit(app.exec())
