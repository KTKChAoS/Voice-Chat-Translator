"""Translation display: a toggleable always-on-top overlay / normal window,
controlled from a system-tray icon so it works even in click-through mode.

Runs entirely as a separate window — it never draws into the game's render
pipeline, so it does not trip anti-cheat. For it to appear over Valorant, run
the game in *Windowed Fullscreen* (not exclusive fullscreen).
"""
from __future__ import annotations

import collections
import time

from PySide6 import QtCore, QtGui, QtWidgets


class Bridge(QtCore.QObject):
    """Thread-safe channel from worker threads to the Qt main thread."""
    result = QtCore.Signal(str, str, float, bool)  # text, lang, prob, is_partial
    status = QtCore.Signal(str)


def _make_icon() -> QtGui.QIcon:
    pix = QtGui.QPixmap(64, 64)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setBrush(QtGui.QColor(30, 144, 255))
    p.setPen(QtCore.Qt.NoPen)
    p.drawRoundedRect(6, 6, 52, 52, 14, 14)
    p.setPen(QtGui.QColor("white"))
    f = QtGui.QFont("Segoe UI", 30, QtGui.QFont.Bold)
    p.setFont(f)
    p.drawText(pix.rect(), QtCore.Qt.AlignCenter, "文")
    p.end()
    return QtGui.QIcon(pix)


class OverlayWindow(QtWidgets.QWidget):
    def __init__(self, cfg: dict, on_pause_toggle=None, on_quit=None):
        super().__init__()
        self.cfg = cfg["ui"]
        self.on_pause_toggle = on_pause_toggle
        self.on_quit = on_quit
        self.paused = False
        # Keep a generous scrollback; the window height decides what's visible,
        # and the view auto-scrolls to the newest line.
        self.lines = collections.deque(maxlen=max(self.cfg["max_lines"], 60))
        self.partial = ""
        self._drag_offset = None

        self.setWindowTitle("Valorant Voice Translator")
        self.resize(self.cfg["width"], self.cfg["height"])
        self.move(self.cfg["x"], self.cfg["y"])

        self.view = QtWidgets.QTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        # Let clicks/drags pass through to the window (for repositioning).
        self.view.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.view.viewport().setAutoFillBackground(False)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(self.view)

        self._apply_styles()
        self.set_mode(self.cfg["mode"])
        self.set_status("Loading…")
        self._build_tray()

    # ---- appearance -----------------------------------------------------
    def _apply_styles(self):
        fs = self.cfg["font_size"]
        self.view.setStyleSheet(
            f"QTextEdit {{ background: transparent; border: none; color: #FFFFFF; "
            f"font-family: 'Segoe UI'; font-size: {fs}px; }}"
        )
        self.view.viewport().setStyleSheet("background: transparent;")

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setBrush(QtGui.QColor(0, 0, 0, 180))
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 14, 14)

    def set_mode(self, mode: str):
        self.cfg["mode"] = mode
        ct = self.cfg["click_through"] and mode == "overlay"
        flags = QtCore.Qt.WindowStaysOnTopHint
        if mode == "overlay":
            flags |= QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool
        if ct:
            flags |= QtCore.Qt.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, mode == "overlay")
        self.setWindowOpacity(self.cfg["opacity"] if mode == "overlay" else 1.0)
        self.show()

    # ---- system tray ----------------------------------------------------
    def _build_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(_make_icon(), self)
        self.tray.setToolTip("Valorant Voice Translator")
        menu = QtWidgets.QMenu()

        self.act_pause = menu.addAction("Pause")
        self.act_pause.triggered.connect(self._toggle_pause)
        menu.addSeparator()

        act_mode = menu.addAction("Toggle overlay / window")
        act_mode.triggered.connect(self._toggle_mode)
        self.act_click = menu.addAction("Click-through")
        self.act_click.setCheckable(True)
        self.act_click.setChecked(self.cfg["click_through"])
        self.act_click.triggered.connect(self._toggle_click_through)

        menu.addAction("Opacity +", lambda: self._nudge_opacity(0.05))
        menu.addAction("Opacity −", lambda: self._nudge_opacity(-0.05))
        menu.addAction("Clear", self._clear)
        menu.addSeparator()
        menu.addAction("Quit", self._quit)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def _toggle_pause(self):
        self.paused = not self.paused
        self.act_pause.setText("Resume" if self.paused else "Pause")
        if self.on_pause_toggle:
            self.on_pause_toggle(self.paused)
        self.set_status("Paused" if self.paused else "Listening…")

    def _toggle_mode(self):
        self.set_mode("window" if self.cfg["mode"] == "overlay" else "overlay")
        self._render()

    def _toggle_click_through(self, checked):
        self.cfg["click_through"] = bool(checked)
        self.set_mode(self.cfg["mode"])

    def _nudge_opacity(self, delta):
        self.cfg["opacity"] = max(0.2, min(1.0, self.cfg["opacity"] + delta))
        if self.cfg["mode"] == "overlay":
            self.setWindowOpacity(self.cfg["opacity"])

    def _clear(self):
        self.lines.clear()
        self._render()

    def _quit(self):
        if self.on_quit:
            self.on_quit()
        QtWidgets.QApplication.quit()

    # ---- content --------------------------------------------------------
    @QtCore.Slot(str, str, float, bool)
    def add_result(self, text: str, lang: str, prob: float, is_partial: bool):
        if not text:
            if not is_partial:
                self.partial = ""
                self._render()
            return
        tag = ""
        if self.cfg["show_original_lang"] and lang:
            tag = f"<span style='color:#7ec8ff'>[{lang}]</span> "
        if is_partial:
            # Live, still-being-spoken line — shown dimmed; gets refined/committed.
            self.partial = f"<span style='color:#bfc6cf'>{tag}{text}…</span>"
        else:
            self.lines.append(f"{tag}{text}")
            self.partial = ""
        self._render()

    @QtCore.Slot(str)
    def set_status(self, msg: str):
        self._status = msg
        self._render()

    def _render(self):
        rows = list(self.lines)
        if self.partial:
            rows.append(self.partial)
        if rows:
            body = "<div style='line-height:128%'>" + "<br>".join(rows) + "</div>"
        else:
            body = f"<i style='color:#9aa'>{getattr(self, '_status', '')}</i>"
        self.view.setHtml(body)
        # Keep the newest line pinned to the bottom (auto-scroll).
        self.view.moveCursor(QtGui.QTextCursor.End)
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---- dragging (overlay mode, when not click-through) ----------------
    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None:
            self.move(e.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _e):
        self._drag_offset = None
