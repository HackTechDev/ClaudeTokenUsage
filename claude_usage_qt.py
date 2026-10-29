#!/usr/bin/env python3
"""Interface Qt affichant l'utilisation des limites Claude, rafraîchie chaque minute."""
import sys
from datetime import datetime

from PyQt6.QtCore import QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from claude_usage import fetch_usage, format_pace, format_remaining, retry_delay

REFRESH_S = 60


class FetchThread(QThread):
    """Interroge l'API hors du thread graphique pour ne pas figer la fenêtre."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, max_age):
        super().__init__()
        self.max_age = max_age

    def run(self):
        try:
            self.done.emit(fetch_usage(max_age=self.max_age))
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
        self.failures = 0  # échecs consécutifs, pour espacer les appels
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

        self.refresh_button = QPushButton("Rafraîchir")
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))

        layout = QVBoxLayout(self)
        layout.addLayout(self.grid)
        layout.addWidget(self.extra)
        layout.addWidget(self.breakdown)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_S * 1000)
        self.refresh()

    def refresh(self, force=False):
        if self.thread and self.thread.isRunning():
            return
        # Réutilise une réponse récente (CLI, status line) sauf rafraîchissement manuel
        self.thread = FetchThread(0 if force else REFRESH_S - 5)
        self.thread.done.connect(self.on_success)
        self.thread.failed.connect(self.on_error)
        self.thread.finished.connect(self.on_finished)
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Chargement…")
        self.thread.start()

    def on_finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Rafraîchir")

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

    def on_success(self, usage):
        self.failures = 0
        self.timer.setInterval(REFRESH_S * 1000)
        self.show_usage(usage)

    def on_error(self, message):
        self.failures += 1
        delay = retry_delay(REFRESH_S, self.failures)
        self.timer.setInterval(delay * 1000)
        self.show_error(f"{message} Nouvel essai dans {delay // 60} min.")

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
