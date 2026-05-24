import sys
import random
import json
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QAction, QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSpinBox, QPushButton, QCheckBox, QProgressBar, 
    QSystemTrayIcon, QMenu, QGraphicsDropShadowEffect
)

# --- CONFIGURATION STORAGE ---
CONFIG_FILE = Path.home() / ".breakly_config.json"

DEFAULT_CONFIG = {
    "work_duration_min": 25,
    "break_duration_sec": 20,
    "snooze_duration_min": 5,
    "is_paused": False
}

def load_config():
    if CONFIG_FILE.exists():
        try:
            return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text())}
        except Exception:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(config):
    try:
        CONFIG_FILE.write_text(json.dumps(config, indent=4))
    except Exception as e:
        print(f"Error saving config: {e}")

# --- PREMIUM LIGHT MODE STYLE SHEET (QSS) ---
PREMIUM_LIGHT_STYLE = """
QMainWindow, QWidget#CentralWidget {
    background-color: #F9F9FB;
}

QWidget#OverlayContent {
    background-color: #FFFFFF;
    border: 1px solid #E4E4E9;
    border-radius: 16px;
}

QLabel {
    color: #2D3142;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
}

QLabel#MainTitle {
    font-size: 24px;
    font-weight: 700;
    color: #1A1C23;
}

QLabel#OverlayTitle {
    font-size: 28px;
    font-weight: 700;
    color: #1A1C23;
}

QLabel#InstructionLabel {
    font-size: 18px;
    color: #4F546A;
}

QLabel#TimerLabel {
    font-size: 14px;
    font-weight: 600;
    color: #717791;
}

QSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #DCDCE2;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 14px;
    color: #2D3142;
    min-width: 70px;
}

QSpinBox:focus {
    border: 1px solid #7EA172;
}

QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #DCDCE2;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 14px;
    font-weight: 600;
    color: #4F546A;
}

QPushButton:hover {
    background-color: #F3F3F7;
    border-color: #C8C8D1;
}

QPushButton#PrimaryButton {
    background-color: #7EA172;
    border: 1px solid #6C8E61;
    color: #FFFFFF;
}

QPushButton#PrimaryButton:hover {
    background-color: #8EB382;
}

QPushButton#DangerButton {
    background-color: #FFF0F0;
    border: 1px solid #FCAEAE;
    color: #D93838;
}

QPushButton#DangerButton:hover {
    background-color: #FFE5E5;
}

QCheckBox {
    font-size: 14px;
    color: #2D3142;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 1px solid #DCDCE2;
    border-radius: 4px;
    background-color: #FFFFFF;
}

QCheckBox::indicator:checked {
    background-color: #7EA172;
    border-color: #6C8E61;
}

QProgressBar {
    border: none;
    background-color: #EAEAEF;
    height: 8px;
    text-align: center;
    border-radius: 4px;
}

QProgressBar::chunk {
    background-color: #7EA172;
    border-radius: 4px;
}
"""

MINDFUL_INSTRUCTIONS = [
    "Look 20 feet away to relax your eye muscles.",
    "Drop your shoulders and stretch your lower back.",
    "Stand up and take three deep, slow breaths.",
    "Hydrate time—grab a quick glass of water.",
    "Roll your wrists and rest your hands off the keyboard."
]

def create_fallback_icon():
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#7EA172"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(12, 12, 8, 8)
    painter.end()
    return QIcon(pm)


class BreakPopup(QWidget):
    """
    A safe, un-ignorable fullscreen overlay. Uses clean window structures
    to block external app interaction without using disruptive low-level system traps.
    """
    def __init__(self, duration_sec, cancel_callback, snooze_callback, resume_next_cycle_callback):
        super().__init__()
        self.total_seconds = duration_sec
        self.seconds_remaining = duration_sec
        
        self.cancel_callback = cancel_callback
        self.snooze_callback = snooze_callback
        self.resume_next_cycle_callback = resume_next_cycle_callback

        # Native Window Config: Frameless, Sticky On Top, Application Level Modal Focus
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        
        # solid background mapping block via paintEvent
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setGeometry(QApplication.primaryScreen().geometry())
        
        self.init_ui()

        # Core Animation Clock Loop
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

        # Anti-Focus Theft Watchdog
        self.watchdog = QTimer(self)
        self.watchdog.timeout.connect(self.enforce_absolute_focus)
        self.watchdog.start(200)

    def paintEvent(self, event):
        """Draws a full protective visual shield that naturally captures mouse inputs cleanly."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Soft off-white mask with high density opacity (235/255)
        painter.setBrush(QColor(243, 243, 247, 235))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(self.rect())
        painter.end()

    def init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Centered Interactive Card Base
        self.container = QWidget(self)
        self.container.setObjectName("OverlayContent")
        self.container.setFixedWidth(540)
        
        shadow = QGraphicsDropShadowEffect(self.container)
        shadow.setBlurRadius(32)
        shadow.setColor(QColor(0, 0, 0, 30))
        shadow.setOffset(0, 12)
        self.container.setGraphicsEffect(shadow)

        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(40, 40, 40, 40)
        self.container_layout.setSpacing(28)

        # Text Header Elements
        header_layout = QHBoxLayout()
        self.title_lbl = QLabel("Time to step away", self.container)
        self.title_lbl.setObjectName("OverlayTitle")
        header_layout.addWidget(self.title_lbl)
        header_layout.addStretch()
        
        self.time_lbl = QLabel(self.format_time(self.seconds_remaining), self.container)
        self.time_lbl.setObjectName("TimerLabel")
        header_layout.addWidget(self.time_lbl)
        self.container_layout.addLayout(header_layout)

        # Description Content Label
        self.instruction_lbl = QLabel(random.choice(MINDFUL_INSTRUCTIONS), self.container)
        self.instruction_lbl.setObjectName("InstructionLabel")
        self.instruction_lbl.setWordWrap(True)
        self.container_layout.addWidget(self.instruction_lbl)

        # Visual Progress Tracking Gauge
        self.progress = QProgressBar(self.container)
        self.progress.setMaximum(self.total_seconds)
        self.progress.setValue(self.total_seconds)
        self.progress.setTextVisible(False)
        self.container_layout.addWidget(self.progress)

        # Button Wrapper Module
        self.btn_row_widget = QWidget(self.container)
        btn_layout = QHBoxLayout(self.btn_row_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        
        self.snooze_btn = QPushButton("Snooze Break", self.btn_row_widget)
        self.snooze_btn.clicked.connect(self.handle_snooze)
        
        self.skip_btn = QPushButton("Skip Break", self.btn_row_widget)
        self.skip_btn.setObjectName("DangerButton")
        self.skip_btn.clicked.connect(self.handle_cancel)

        btn_layout.addWidget(self.snooze_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.skip_btn)
        self.container_layout.addWidget(self.btn_row_widget)

        root_layout.addWidget(self.container)

    def format_time(self, total_seconds):
        mins, secs = divmod(total_seconds, 60)
        return f"{mins:02d}:{secs:02d}"

    def tick(self):
        if self.seconds_remaining > 0:
            self.seconds_remaining -= 1
            self.progress.setValue(self.seconds_remaining)
            self.time_lbl.setText(self.format_time(self.seconds_remaining))
            
            if self.seconds_remaining == 0:
                self.timer.stop()
                self.transition_to_presence_check()

    def transition_to_presence_check(self):
        """Hides countdown layouts and instantiates a fully responsive verification button."""
        self.title_lbl.setText("Break Completed")
        self.time_lbl.setText("00:00")
        self.instruction_lbl.setText("Welcome back! Whenever you are ready to resume focus, click the button below.")
        
        # Hide the layout gracefully instead of hard deleteLater to preserve layout sizing geometry safely
        self.btn_row_widget.hide()

        # Inject the active resolution return action button
        self.return_btn = QPushButton("I am back", self.container)
        self.return_btn.setObjectName("PrimaryButton")
        self.return_btn.setMinimumHeight(48)
        self.return_btn.setStyleSheet("font-size: 16px; border-radius: 10px; font-weight: bold;")
        
        # Bind verification click action slot directly
        self.return_btn.clicked.connect(self.handle_presence_confirmed)
        self.container_layout.addWidget(self.return_btn)
        
        # Force parent canvas to redraw button context bounding layout area
        self.return_btn.show()
        self.return_btn.raise_()

    def enforce_absolute_focus(self):
        if not self.isActiveWindow():
            self.raise_()
            self.activateWindow()

    def cleanup_and_close(self, callback_target):
        self.timer.stop()
        self.watchdog.stop()
        self.close()
        callback_target()

    def handle_snooze(self):
        self.cleanup_and_close(self.snooze_callback)

    def handle_cancel(self):
        self.cleanup_and_close(self.cancel_callback)

    def handle_presence_confirmed(self):
        self.cleanup_and_close(self.resume_next_cycle_callback)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Alt):
            event.accept()
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange:
            if self.isMinimized():
                event.ignore()
                self.setWindowState(Qt.WindowState.WindowActive)
                self.raise_()
        super().changeEvent(event)


class MainWindow(QMainWindow):
    """
    Main State Machine & Preference Configuration panel.
    Runs completely decoupled from physical screen-blocking hooks.
    """
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.popup_window = None

        self.setWindowTitle("Breakly Setup")
        self.setFixedSize(380, 420)

        # Main Setup Engine Initialization
        self.master_timer = QTimer(self)
        self.master_timer.timeout.connect(self.trigger_break_sequence)
        
        # Track actual countdown progress independently
        self.time_to_trigger = 0

        self.init_ui()
        self.apply_stored_logic()

    def init_ui(self):
        central_widget = QWidget(self)
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # App Heading Brand Identity Banner
        title = QLabel("Breakly", central_widget)
        title.setObjectName("MainTitle")
        subtitle = QLabel("Work enough and live more.", central_widget)
        subtitle.setStyleSheet("color: #717791; font-size: 13px; font-style: italic;")
        
        header_block = QVBoxLayout()
        header_block.addWidget(title)
        header_block.addWidget(subtitle)
        layout.addLayout(header_block)

        # Configuration Forms Input Wrapper Grid Elements
        form_layout = QVBoxLayout()
        form_layout.setSpacing(14)

        # X Value: Work Window Selector
        work_box = QHBoxLayout()
        work_lbl = QLabel("Work Duration (Minutes):", central_widget)
        self.work_input = QSpinBox(central_widget)
        self.work_input.setRange(1, 180)
        self.work_input.setValue(self.config["work_duration_min"])
        work_box.addWidget(work_lbl)
        work_box.addStretch()
        work_box.addWidget(self.work_input)
        form_layout.addLayout(work_box)

        # Y Value: Break Interval Selector
        break_box = QHBoxLayout()
        break_lbl = QLabel("Break Duration (Seconds):", central_widget)
        self.break_input = QSpinBox(central_widget)
        self.break_input.setRange(5, 3600)
        self.break_input.setValue(self.config["break_duration_sec"])
        break_box.addWidget(break_lbl)
        break_box.addStretch()
        break_box.addWidget(self.break_input)
        form_layout.addLayout(break_box)

        # Z Value: Snooze Intermission Delay Selector
        snooze_box = QHBoxLayout()
        snooze_lbl = QLabel("Snooze Intermission (Minutes):", central_widget)
        self.snooze_input = QSpinBox(central_widget)
        self.snooze_input.setRange(1, 60)
        self.snooze_input.setValue(self.config["snooze_duration_min"])
        snooze_box.addWidget(snooze_lbl)
        snooze_box.addStretch()
        snooze_box.addWidget(self.snooze_input)
        form_layout.addLayout(snooze_box)

        layout.addLayout(form_layout)

        # Master Safe-Guard Toggle Switch
        self.pause_checkbox = QCheckBox("Pause App Loops (Meeting Safe Mode)", central_widget)
        self.pause_checkbox.setChecked(self.config["is_paused"])
        self.pause_checkbox.toggled.connect(self.handle_pause_toggle)
        layout.addWidget(self.pause_checkbox)

        # Live Status Track Readout Frame
        self.status_lbl = QLabel("State: Calculating window entry...", central_widget)
        self.status_lbl.setStyleSheet("color: #717791; font-size: 12px; background: #F3F3F7; padding: 8px; border-radius: 6px;")
        layout.addWidget(self.status_lbl)

        # State Control Interactive Action Row
        action_layout = QHBoxLayout()
        save_btn = QPushButton("Save Preferences", central_widget)
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self.save_preferences)
        
        action_layout.addStretch()
        action_layout.addWidget(save_btn)
        layout.addLayout(action_layout)

        # Secondary Tick Engine to poll remaining status labels dynamically
        self.status_refresh_timer = QTimer(self)
        self.status_refresh_timer.timeout.connect(self.update_live_status_label)
        self.status_refresh_timer.start(1000)

    def apply_stored_logic(self):
        if self.config["is_paused"]:
            self.master_timer.stop()
            self.status_lbl.setText("State: Engine Paused.")
        else:
            self.time_to_trigger = self.config["work_duration_min"] * 60
            self.master_timer.start(1000)

    def handle_pause_toggle(self, is_checked):
        self.config["is_paused"] = is_checked
        save_config(self.config)
        if is_checked:
            self.master_timer.stop()
            if self.popup_window:
                self.popup_window.close()
                self.popup_window = None
        else:
            self.apply_stored_logic()

    def save_preferences(self):
        self.config["work_duration_min"] = self.work_input.value()
        self.config["break_duration_sec"] = self.break_input.value()
        self.config["snooze_duration_min"] = self.snooze_input.value()
        save_config(self.config)
        self.apply_stored_logic()

    def update_live_status_label(self):
        if self.config["is_paused"]:
            self.status_lbl.setText("State: Idle (App Paused)")
            return
        
        if self.time_to_trigger > 0:
            self.time_to_trigger -= 1
            mins, secs = divmod(self.time_to_trigger, 60)
            self.status_lbl.setText(f"Next Break In: {mins:02d}m {secs:02d}s")

    def trigger_break_sequence(self):
        if self.time_to_trigger <= 0 and not self.popup_window:
            self.master_timer.stop()
            self.status_refresh_timer.stop()
            self.status_lbl.setText("State: Break currently active...")
            
            self.popup_window = BreakPopup(
                duration_sec=self.config["break_duration_sec"],
                cancel_callback=self.post_break_reset,
                snooze_callback=self.post_snooze_reset,
                resume_next_cycle_callback=self.post_break_reset
            )
            self.popup_window.show()

    def post_break_reset(self):
        self.popup_window = None
        self.status_refresh_timer.start(1000)
        self.apply_stored_logic()

    def post_snooze_reset(self):
        self.popup_window = None
        self.status_refresh_timer.start(1000)
        self.time_to_trigger = self.config["snooze_duration_min"] * 60
        self.master_timer.start(1000)

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self.hide)
            event.accept()
        else:
            super().changeEvent(event)


class BreaklyApplication:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setStyleSheet(PREMIUM_LIGHT_STYLE)
        self.app.setQuitOnLastWindowClosed(False)

        self.main_window = MainWindow()
        self.app_icon = create_fallback_icon()
        
        self.init_tray()
        self.main_window.show()

    def init_tray(self):
        self.tray = QSystemTrayIcon(self.app_icon, self.app)
        self.tray.setToolTip("Breakly — Work enough & live more")

        menu = QMenu()
        open_action = QAction("Open Setup Panel", self.app)
        open_action.triggered.connect(self.show_window)
        
        exit_action = QAction("Quit Entirely", self.app)
        exit_action.triggered.connect(self.quit_app)

        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        
        self.tray.activated.connect(self.handle_tray_activation)
        self.tray.show()

    def handle_tray_activation(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()

    def show_window(self):
        self.main_window.showNormal()
        self.main_window.activateWindow()

    def quit_app(self):
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec())


if __name__ == "__main__":
    app_engine = BreaklyApplication()
    app_engine.run()