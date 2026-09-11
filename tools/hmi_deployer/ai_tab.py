"""
tools/hmi_deployer/ai_tab.py -- AI Design tab widget

Chat interface with model picker, brief input, and live preview.
Wired to OpenDesign connector and generator.
"""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QTextEdit, QVBoxLayout, QWidget, QMessageBox, QProgressBar,
)


class MessageItem(QWidget):
    """Single chat message widget."""

    def __init__(self, role: str, content: str, parent=None):
        super().__init__(parent)
        self.role = role
        self.is_user = role == "user"
        self.setLayout(QVBoxLayout(self))
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().setSpacing(4)

        bubble = QFrame()
        bubble.setObjectName("messageBubble")
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        text = QTextEdit()
        text.setPlainText(content)
        text.setReadOnly(True)
        text.setMaximumHeight(300)
        font = QFont()
        font.setPixelSize(13)
        text.setFont(font)

        if self.is_user:
            bubble.setStyleSheet("""
                QFrame#messageBubble {
                    background-color: #27272a;
                    border-radius: 12px;
                }
                QTextEdit {
                    background-color: transparent;
                    border: none;
                    color: #f4f4f5;
                }
            """)
        else:
            bubble.setStyleSheet("""
                QFrame#messageBubble {
                    background-color: #1d4ed8;
                    border-radius: 12px;
                }
                QTextEdit {
                    background-color: transparent;
                    border: none;
                    color: #ffffff;
                }
            """)

        bubble_layout.addWidget(text)
        self.layout().addWidget(bubble, alignment=Qt.AlignRight if self.is_user else Qt.AlignLeft)

    def append_delta(self, delta: str):
        """Append text delta to streaming response."""
        text = self.layout().itemAt(0).widget().findChild(QTextEdit)
        if text:
            text.moveCursor(text.textCursor().End)
            text.insertPlainText(delta)
            text.moveCursor(text.textCursor().End)


class AIDesignTab(QWidget):
    """AI-powered design tab.

    Provides:
    - Chat interface with model picker
    - Brief input and generation
    - Live preview on canvas
    """

    generateRequested = Signal(object)  # DesignerProject
    statusMessage = Signal(str)

    def __init__(self, connector=None, generator=None, parent=None):
        super().__init__(parent)
        self.connector = connector
        self.generator = generator
        self.streaming = False
        self.last_project = None

        self._build_ui()
        self._load_defaults()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top bar: model picker + connect button
        top_bar = QFrame()
        top_bar.setObjectName("aiTopBar")
        top_bar.setStyleSheet("""
            QFrame#aiTopBar {
                background-color: #18181b;
                border-bottom: 1px solid #27272a;
            }
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(8)

        # Model selector
        model_label = QLabel("Model:")
        model_label.setObjectName("aiLabel")
        model_label.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        top_layout.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)
        self.model_combo.setObjectName("modelSelector")
        self.model_combo.setStyleSheet("""
            QComboBox {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 4px 8px;
                color: #f4f4f5;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: none; }
        """)
        top_layout.addWidget(self.model_combo)

        # Provider selector
        prov_label = QLabel("Provider:")
        prov_label.setObjectName("aiLabel")
        prov_label.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        top_layout.addWidget(prov_label)

        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(120)
        self.provider_combo.setObjectName("providerSelector")
        self.provider_combo.setStyleSheet("""
            QComboBox {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 6px;
                padding: 4px 8px;
                color: #f4f4f5;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: none; }
        """)
        top_layout.addWidget(self.provider_combo)

        top_layout.addStretch()

        # Connection status
        self.status_lbl = QLabel("● Connected")
        self.status_lbl.setObjectName("connectionStatus")
        self.status_lbl.setStyleSheet("""
            #connectionStatus { color: #22c55e; font-size: 12px; }
        """)
        top_layout.addWidget(self.status_lbl)

        layout.addWidget(top_bar)

        # Chat area (scrollable)
        chat_area = QScrollArea()
        chat_area.setWidgetResizable(True)
        chat_area.setObjectName("chatArea")
        chat_area.setStyleSheet("""
            QScrollArea#chatArea {
                border: none;
                background-color: #09090b;
            }
        """)
        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setContentsMargins(16, 16, 16, 16)
        self.chat_layout.setSpacing(12)
        chat_area.setWidget(self.chat_widget)
        layout.addWidget(chat_area)

        # Input area (brief + send button)
        input_bar = QFrame()
        input_bar.setObjectName("aiInputBar")
        input_bar.setStyleSheet("""
            QFrame#aiInputBar {
                background-color: #18181b;
                border-top: 1px solid #27272a;
            }
        """)
        input_layout = QHBoxLayout(input_bar)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(8)

        # Brief text input
        self.brief_input = QPlainTextEdit()
        self.brief_input.setPlaceholderText("Describe the UI you want to generate...")
        self.brief_input.setObjectName("briefInput")
        self.brief_input.setStyleSheet("""
            QPlainTextEdit {
                background-color: #27272a;
                border: 1px solid #3f3f46;
                border-radius: 8px;
                padding: 8px;
                color: #f4f4f5;
                font-size: 13px;
            }
        """)
        self.brief_input.setMaximumHeight(80)
        input_layout.addWidget(self.brief_input, 1)

        # Send button
        self.send_btn = QPushButton("Generate")
        self.send_btn.setObjectName("primaryAction")
        self.send_btn.setStyleSheet("""
            QPushButton#primaryAction {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 13px;
            }
            QPushButton#primaryAction:hover { background-color: #1d4ed8; }
            QPushButton#primaryAction:disabled { background-color: #3f3f46; }
        """)
        self.send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(self.send_btn)

        layout.addWidget(input_bar)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setObjectName("generationProgress")
        self.progress_bar.setStyleSheet("""
            QProgressBar#generationProgress {
                background-color: #27272a;
                border: none;
                border-radius: 2px;
            }
            QProgressBar#generationProgress::chunk {
                background-color: #2563eb;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Populate provider/model defaults
        self._populate_providers()

    def _load_defaults(self):
        """Load default model/provider from settings."""
        self.statusMessage.emit("AI Design tab ready")

    def _populate_providers(self):
        """Populate provider/model selectors from connector presets."""
        if self.connector:
            presets = self.connector.get_provider_presets()
            self.provider_combo.clear()
            for preset in presets:
                self.provider_combo.addItem(preset["label"], preset["key"])
            self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)

    def _on_provider_changed(self, index: int):
        """Switch provider and update model list."""
        key = self.provider_combo.itemData(index)
        if not self.connector:
            return

        # Update connector mode and config
        self.connector.mode = "byok"
        from tools.hmi_deployer.ai_design import BYOK_PRESETS, ProviderConfig
        preset = dict(BYOK_PRESETS.get(key, {}))
        preset["provider"] = key
        self.connector.byok = ProviderConfig.from_dict(preset)

        # Update model list
        self.model_combo.clear()
        models = self.connector.discover_models()
        for model in models:
            self.model_combo.addItem(model.label, model.id)

    def add_message(self, role: str, content: str):
        """Add a chat message."""
        item = MessageItem(role, content)
        self.chat_layout.addWidget(item)
        # Auto-scroll to bottom
        QTimer.singleShot(0, self._scroll_to_bottom)
        return item

    def _scroll_to_bottom(self):
        try:
            scrollbar = self.chat_widget.findChild(object, "QAbstractScrollArea")
            if not scrollbar:
                from PySide6.QtWidgets import QScrollArea
                scrollbar = self.findChild(QScrollArea)
            if scrollbar:
                scrollbar.setValue(scrollbar.verticalScrollBar().maximum())
        except Exception:
            pass

    def _on_send(self):
        """Handle send button click."""
        brief = self.brief_input.toPlainText().strip()
        if not brief:
            return

        self.brief_input.setPlainText("")
        self.add_message("user", brief)
        self.send_btn.setEnabled(False)
        self.progress_bar.setVisible(True)

        if self.streaming:
            return

        self.streaming = True

        # Start generation in a separate timer to avoid blocking UI
        QTimer.singleShot(0, lambda: self._run_generation(brief))

    def _run_generation(self, brief: str):
        """Run generation cycle and update UI."""
        from PySide6.QtCore import QThread

        if not self.connector:
            self.add_message("assistant", "No connector configured. Check provider settings.")
            self.streaming = False
            self.send_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
            return

        # Create assistant message for streaming
        assistant_msg = self.add_message("assistant", "")

        try:
            if self.connector.is_running():
                status = f"Generating with {self.connector.mode} mode..."
                self.progress_bar.setFormat(status)
                self.progress_bar.setValue(10)

                for delta in self.connector.generate(brief):
                    if delta:
                        assistant_msg.append_delta(delta)
                        self._scroll_to_bottom()
                        self.progress_bar.setValue(50)

                self.progress_bar.setValue(80)
                self.add_message("system", "Generation complete. Click 'Apply to Canvas' to view the design.")
                self.progress_bar.setValue(100)
                QTimer.singleShot(500, lambda: self.progress_bar.setVisible(False))

            else:
                self.add_message("system", "Connector not available. Check daemon or provider settings.")
                self.progress_bar.setVisible(False)

        except Exception as exc:
            self.add_message("system", f"Error: {exc}")
            self.progress_bar.setVisible(False)

        self.streaming = False
        self.send_btn.setEnabled(True)
        self.statusMessage.emit("Generation complete")

    def apply_to_canvas(self, designer_workspace=None):
        """Apply the current design to the canvas."""
        if not self.last_project:
            QMessageBox.information(self, "No Design", "Generate a design first.")
            return
        if designer_workspace:
            designer_workspace.load_project(self.last_project)

    def set_last_project(self, project):
        """Store the last generated project."""
        self.last_project = project