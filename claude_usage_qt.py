#!/usr/bin/env python3
"""Interface Qt affichant l'utilisation des limites Claude, rafraîchie chaque minute."""
import sys
from datetime import datetime

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from claude_usage import fetch_usage, format_pace, format_remaining

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

        self.extra = QLabel()
        self.breakdown = QLabel()
        for label in (self.extra, self.breakdown):
            label.setWordWrap(True)
            label.hide()

        self.status = QLabel("Chargement…")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status.setStyleSheet("color: gray;")

        refresh = QPushButton("Rafraîchir")
        refresh.clicked.connect(self.refresh)

        layout = QVBoxLayout(self)
        layout.addLayout(self.grid)
        layout.addWidget(self.extra)
        layout.addWidget(self.breakdown)
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
            name, bar, reset, pace = QLabel(limit.label), QProgressBar(), QLabel(), QLabel()
            bar.setRange(0, 100)
            bar.setFormat("%v %")
            line = self.grid.rowCount()
            for col, w in enumerate((name, bar, reset)):
                self.grid.addWidget(w, line, col)
            self.grid.addWidget(pace, line + 1, 1, 1, 2)
            self.rows[limit.kind] = (name, bar, reset, pace)
        return self.rows[limit.kind]

    def show_usage(self, usage):
        self.last_usage = usage
        active = {l.kind for l in usage.limits}
        for kind, widgets in self.rows.items():
            for w in widgets:
                w.setVisible(kind in active)
        for limit in usage.limits:
            name, bar, reset_label, pace_label = self.row(limit)
            for w in (name, bar, reset_label):
                w.setVisible(True)
            pace = format_pace(limit)
            pace_label.setVisible(bool(pace))
            pace_label.setText(pace)
            pace_label.setStyleSheet(f"color: {'#e67e22' if limit.exhaustion() else 'gray'};")
            bar.setValue(round(limit.percent))
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {bar_color(limit.percent)}; }}")
            reset_label.setText(f"réinit. {limit.resets_at:%d/%m %H:%M}"
                                f" (dans {format_remaining(limit.remaining())})")
        self.extra.setVisible(usage.extra is not None)
        if usage.extra:
            self.extra.setText(f"Crédits supplémentaires : {usage.extra.describe()}")
        self.breakdown.setVisible(bool(usage.describe_breakdown()))
        self.breakdown.setText(f"Répartition sur 7 jours : {usage.describe_breakdown()}")
        self.status.setText(f"Mis à jour à {datetime.now():%H:%M:%S}")
        self.resize(self.size().expandedTo(self.sizeHint()))

    def show_error(self, message):
        if self.last_usage:  # garde les dernières valeurs, avec un compte à rebours à jour
            self.show_usage(self.last_usage)
        self.status.setText(f"Erreur à {datetime.now():%H:%M:%S} : {message}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = UsageWindow()
    window.show()
    sys.exit(app.exec())
