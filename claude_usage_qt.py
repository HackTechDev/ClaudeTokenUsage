#!/usr/bin/env python3
"""Interface Qt affichant l'utilisation des limites Claude, rafraîchie chaque minute."""
import shutil, subprocess, sys
from datetime import datetime

from PyQt6.QtCore import QSettings, QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QMenu, QProgressBar, QPushButton, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)

from claude_usage import (
    CONFIG, fetch_usage, format_pace, format_remaining, notifications, retry_delay, severity,
)

REFRESH_S = CONFIG["refresh_interval"]
BAR_COLORS = {"ok": "#5cb85c", "warn": "#f0ad4e", "crit": "#d9534f"}


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
    return BAR_COLORS[severity(percent)]


def tray_pixmap(percent):
    """Pastille colorée selon le niveau, avec le pourcentage (« ! » si atteint, « ? » si inconnu)."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#888888" if percent is None else bar_color(percent)))
    painter.drawRoundedRect(0, 0, 64, 64, 14, 14)
    text = "?" if percent is None else "!" if percent >= 100 else f"{int(percent)}"
    font = QFont()
    font.setBold(True)
    font.setPixelSize(40 if len(text) < 2 else 34)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


def dark_palette():
    p = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#2b2b2b", QPalette.ColorRole.WindowText: "#e6e6e6",
        QPalette.ColorRole.Base: "#1f1f1f", QPalette.ColorRole.AlternateBase: "#2b2b2b",
        QPalette.ColorRole.Text: "#e6e6e6", QPalette.ColorRole.Button: "#3a3a3a",
        QPalette.ColorRole.ButtonText: "#e6e6e6", QPalette.ColorRole.ToolTipBase: "#3a3a3a",
        QPalette.ColorRole.ToolTipText: "#e6e6e6", QPalette.ColorRole.Highlight: "#4a90d9",
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.PlaceholderText: "#8c8c8c",
    }
    for role, color in colors.items():
        p.setColor(role, QColor(color))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#7a7a7a"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#7a7a7a"))
    return p


def apply_theme(app, theme):
    """Applique le thème configuré ; en mode "auto", suit le mode clair/sombre du système."""
    if theme == "auto":
        dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        palette_is_dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128
        if dark == palette_is_dark:
            return  # le thème du système est déjà appliqué
    else:
        dark = theme == "dark"
    app.setStyle("Fusion")
    app.setPalette(dark_palette() if dark else app.style().standardPalette())


class UsageWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Claude Usage")
        self.setMinimumWidth(420)
        self.thread = None
        self.failures = 0  # échecs consécutifs, pour espacer les appels
        self.last_usage = None
        self.notify_state = None  # niveaux du relevé précédent, pour les notifications

        # Réglages mémorisés dans ~/.config/claude-usage/claude-usage-qt.conf
        self.settings = QSettings("claude-usage", "claude-usage-qt")
        self.compact = self.settings.value("compact", False, type=bool)

        self.compact_action = QAction("Mode compact", self, checkable=True, checked=self.compact)
        self.compact_action.toggled.connect(self.set_compact)
        self.on_top_action = QAction("Toujours au premier plan", self, checkable=True,
                                     checked=self.settings.value("on_top", False, type=bool))
        self.on_top_action.toggled.connect(self.set_on_top)
        # Clic droit dans la fenêtre : seul moyen d'en sortir en mode compact, sans barre de titre
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.addActions([self.compact_action, self.on_top_action])

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

        self.apply_window_flags()
        for w in (self.refresh_button, self.status):
            w.setVisible(not self.compact)
        if self.compact:
            self.setMinimumWidth(0)
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.setup_tray()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_S * 1000)
        self.refresh()

    def setup_tray(self):
        """Icône de la zone de notification : la fenêtre se ferme dans l'icône au lieu de quitter."""
        self.tray = QSystemTrayIcon(QIcon(tray_pixmap(None)), self)
        self.tray.setToolTip("Claude Usage : chargement…")
        menu = QMenu(self)
        menu.addAction("Afficher / masquer", self.toggle_visible)
        menu.addAction("Rafraîchir", lambda: self.refresh(force=True))
        menu.addSeparator()
        menu.addActions([self.compact_action, self.on_top_action])
        menu.addSeparator()
        menu.addAction("Quitter", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and self.toggle_visible())
        self.tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def apply_window_flags(self):
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, self.compact)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.on_top_action.isChecked())

    def set_on_top(self, on):
        self.settings.setValue("on_top", on)
        visible = self.isVisible()
        self.apply_window_flags()  # changer les drapeaux masque la fenêtre
        if visible:
            self.show()

    def set_compact(self, on):
        """Mode compact : sans bordure, seulement les barres et le temps restant."""
        self.compact = on
        self.settings.setValue("compact", on)
        visible = self.isVisible()
        self.apply_window_flags()
        for w in (self.refresh_button, self.status):
            w.setVisible(not on)
        if self.last_usage:
            self.show_usage(self.last_usage)
        else:
            self.extra.setVisible(False)
            self.breakdown.setVisible(False)
        self.setMinimumWidth(0 if on else 420)
        if visible:
            self.show()
        # Après le réaffichage, sinon le gestionnaire de fenêtres rétablit l'ancienne taille
        QTimer.singleShot(0, lambda: self.resize(self.sizeHint()))

    def mousePressEvent(self, event):
        # Sans barre de titre, la fenêtre compacte se déplace en la faisant glisser
        if self.compact and event.button() == Qt.MouseButton.LeftButton:
            self.windowHandle().startSystemMove()
        super().mousePressEvent(event)

    def toggle_visible(self):
        if self.isVisible():
            self.close()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def update_tray(self, usage):
        if not self.tray:
            return
        # Affiche la limite la plus utilisée ; le détail est dans l'infobulle
        top = max(usage.limits, key=lambda l: l.percent, default=None)
        self.tray.setIcon(QIcon(tray_pixmap(top.percent if top else None)))
        self.tray.setToolTip("\n".join(
            f"{l.label} : {l.percent:.0f} % (réinit. dans {format_remaining(l.remaining())})"
            for l in usage.limits) or "Claude Usage : aucune limite")

    def quit(self):
        self.settings.setValue("geometry", self.saveGeometry())
        QApplication.instance().quit()

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
        messages, self.notify_state = notifications(self.notify_state, usage)
        if CONFIG["notifications"]:
            for message in messages:
                self.notify(message)

    def notify(self, message):
        """Notification de bureau, via l'icône de notification ou à défaut notify-send."""
        if self.tray:
            self.tray.showMessage("Claude Usage", message, QSystemTrayIcon.MessageIcon.Information, 10_000)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "Claude Usage", message])

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
            pace_label.setVisible(bool(pace) and not self.compact)
            pace_label.setText(pace)
            pace_label.setStyleSheet(f"color: {'#e67e22' if limit.exhaustion() else 'gray'};")
            bar.setValue(round(limit.percent))
            bar.setStyleSheet(f"QProgressBar::chunk {{ background: {bar_color(limit.percent)}; }}")
            if self.compact:
                reset_label.setText(format_remaining(limit.remaining()))
            else:
                reset_label.setText(f"réinit. {limit.resets_at:%d/%m %H:%M}"
                                    f" (dans {format_remaining(limit.remaining())})")
        self.extra.setVisible(usage.extra is not None and not self.compact)
        if usage.extra:
            self.extra.setText(f"Crédits supplémentaires : {usage.extra.describe()}")
        self.breakdown.setVisible(bool(usage.describe_breakdown()) and not self.compact)
        self.breakdown.setText(f"Répartition sur 7 jours : {usage.describe_breakdown()}")
        self.status.setText(f"Mis à jour à {datetime.now():%H:%M:%S}")
        self.update_tray(usage)
        self.resize(self.size().expandedTo(self.sizeHint()))

    def show_error(self, message):
        if self.last_usage:  # garde les dernières valeurs, avec un compte à rebours à jour
            self.show_usage(self.last_usage)
        self.status.setText(f"Erreur à {datetime.now():%H:%M:%S} : {message}")
        if self.tray:
            self.tray.setToolTip(f"Claude Usage : erreur\n{message}")

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_theme(app, CONFIG["theme"])
    app.styleHints().colorSchemeChanged.connect(lambda: apply_theme(app, CONFIG["theme"]))
    window = UsageWindow()
    window.show()
    sys.exit(app.exec())
