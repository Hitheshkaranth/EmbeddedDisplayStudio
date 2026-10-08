"""tools/hmi_deployer/connections.py -- the model endpoints a design uses.

One list of AI model connections, shared by the AI Design tab and the Code
agent (agent_panel.py): AI Design picks one for its provider, the Code agent
picks one per role (the "design" role, and the default the Code agent uses).
Each connection names an endpoint (provider, base url, model) and whether it
is a thinking model; the list is persisted in QSettings so it survives a
restart. Saving a connection also writes its opencode provider entry
(connections.opencode_provider_entry) into ~/.config/opencode/opencode.jsonc,
the model's own provider config, so the agent runtime knows where to send
requests.

Connection(name, kind, base_url, api_key, model, thinking):
    kind  -- "vllm" | "openai" | "ollama" | "anthropic" | "google" | "byok"
             (which OpenAI-compatible shape the endpoint speaks).
    model -- the model id the endpoint serves (or "" for ollama, where the
             tag list is authoritative).
    thinking -- this model is asked to reason before it answers.

ConnectionStore(settings): a thin layer over QSettings key "connections/list"
(JSON) plus "connections/default/<role>". It does not touch the network; the
caller fetches the model list (fetch_models).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

# The opencode "provider" block key for a connection: namespaced "studio-" so
# it never collides with a provider the user added themselves.
_PREFIX = "studio-"
_OPENVEND = "~/.config/opencode/opencode.jsonc"

# Roles the UI offers a connection to be the pick for. The agent one also
# writes the opencode provider entry, since the agent runtime reads it.
_ROLES = ("design", "agent")


@dataclass
class Connection:
    """One model endpoint. kind selects the OpenAI-compatible flavor; model
    is the id to request (empty for ollama, whose tags are fetched)."""

    name: str
    kind: str
    base_url: str
    api_key: str = ""
    model: str = ""
    thinking: bool = False


# Provider kinds in the order the UI shows them; "byok" (bring-your-own-key)
# sits last: it is the generic fallback, not a specific provider.
_KINDS = ("vllm", "openai", "ollama", "anthropic", "google", "byok")


class ConnectionStore:
    """Persisted list of Connection plus one default per role, in QSettings.

    The list lives under "connections/list" (a JSON array of the connection
    fields); each role keeps one name under "connections/default/<role>". The
    set default is the pick a role uses when the user has not chosen one
    (default_for: the set one, else the first of the list, else None).
    """

    def __init__(self, settings: QSettings | None = None) -> None:
        self._owns = settings is None
        self._settings: QSettings = settings or QSettings("MIL-HMI", "Deployer")

    # -- the list ---------------------------------------------------------

    def list(self) -> list[Connection]:
        """Every stored connection, in stored order."""
        try:
            raw = self._settings.value("connections/list", "[]")
            items = json.loads(raw if isinstance(raw, str) else json.dumps(raw))
        except (TypeError, ValueError):
            items = []
        out = []
        for row in items:
            try:
                out.append(Connection(**row))
            except (TypeError, ValueError):
                continue
        return out

    def _save_list(self, conns: list[Connection]) -> None:
        self._settings.setValue("connections/list", json.dumps([asdict(c) for c in conns]))

    def _check_name(self, name: str) -> None:
        if any(c.name == name for c in self.list()):
            raise ValueError(f"A connection named '{name}' already exists")

    def add(self, conn: Connection) -> None:
        """Store a new connection; a duplicate name is rejected."""
        self._check_name(conn.name)
        conns = self.list()
        conns.append(conn)
        self._save_list(conns)

    def update(self, conn: Connection) -> None:
        """Replace the connection with the same name, or add it when absent."""
        self._check_name(conn.name)
        conns = self.list()
        for i, c in enumerate(conns):
            if c.name == conn.name:
                conns[i] = conn
                self._save_list(conns)
                return
        conns.append(conn)
        self._save_list(conns)

    def remove(self, name: str) -> None:
        """Drop the connection named `name`; the default for a role pointing
        at it is left (the role then falls back to default_for)."""
        conns = [c for c in self.list() if c.name != name]
        self._save_list(conns)

    def get(self, name: str) -> Connection | None:
        """The connection named `name`, or None."""
        for c in self.list():
            if c.name == name:
                return c
        return None

    # -- the default per role --------------------------------------------

    def set_default(self, role: str, name: str) -> None:
        """Make `name` the pick for `role` (recorded, not validated)."""
        self._settings.setValue(f"connections/default/{role}", name)

    def default_for(self, role: str) -> Connection | None:
        """The pick for `role`: the set one, else the first of the list, else
        None (the role can proceed by asking the user to choose)."""
        name = self._settings.value(f"connections/default/{role}", "", type=str)
        if name:
            conn = self.get(name)
            if conn is not None:
                return conn
        conns = self.list()
        return conns[0] if conns else None


# ---------------------------------------------------------------------------
# opencode provider entries
# ---------------------------------------------------------------------------

def _opencode_key(conn: Connection) -> str:
    """The provider block key: 'studio-' + the connection name."""
    return _PREFIX + conn.name


def opencode_provider_entry(conn: Connection):
    """The opencode `provider[<key>]` block for `conn` and its key.

    The model is told, via `chat_template_kwargs.enable_thinking`, whether to
    reason before answering; baseURL is the endpoint's /v1 (unless it already
    carries one, so a base that is already OpenAI-shaped is not doubled).
    Returns (key, entry).
    """
    key = _opencode_key(conn)
    base = conn.base_url
    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"
    model_name = conn.model or ""
    entry = {
        "npm": "@ai-sdk/openai-compatible",
        "options": {
            "baseURL": base,
            "apiKey": conn.api_key,
        },
        # A model carries its options: think, or not.
        "models": {
            model_name: {
                "options": {
                    "chat_template_kwargs": {"enable_thinking": bool(conn.thinking)},
                }
            }
        },
    }
    return key, entry


def _backup_path(path: str) -> str:
    """The backup file name for `path`: the same file, suffixed with the
    write time, so the user's previous config is recoverable."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{path}.before-{stamp}"


def _read_lenient(path: str) -> dict:
    """The config at `path` as a dict, or {} when absent or unparseable
    (a missing or half-written file must not block saving the provider)."""
    if not os.path.isfile(path):
        return {}
    try:
        from designer.layout.intake import loads_lenient
        data = loads_lenient(open(path, encoding="utf-8").read())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(path: str, data: dict) -> None:
    """Write `data` to `path` as plain JSON (opencode.jsonc is read as JSON
    here; the file is valid JSON, only the editor adds comments)."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def write_opencode_config(conns: list[Connection], path: str | None = None):
    """Merge `conns` into the opencode config at `path`, returning
    'key/model' for the first connection (or '' when there are none).

    Each connection's provider block is written under "provider"; the user's
    own providers are kept, and opencode's own default model (top-level
    "model") is not taken over. A backup of the pre-merge file is written
    first as `<path>.before-<stamp>`.

    Args:
        conns: the connections whose provider entries to write.
        path: destination file; defaults to ~/.config/opencode/opencode.jsonc.

    Returns:
        'studio-<name>/<model>' for conns[0], or '' when conns is empty.
    """
    path = (path or _OPENVEND).replace("~", os.path.expanduser("~"))

    ref = ""
    if conns:
        ref = f"{_opencode_key(conns[0])}/{conns[0].model or ''}"

    # Back up the file before the merge, so a bad edit is reversible.
    if os.path.isfile(path):
        try:
            open(_backup_path(path), "w", encoding="utf-8").write(
                open(path, encoding="utf-8").read())
        except OSError:
            pass

    data = _read_lenient(path)
    providers = data.get("provider")
    if not isinstance(providers, dict):
        providers = {}

    for conn in conns:
        key, entry = opencode_provider_entry(conn)
        providers[key] = entry

    data["provider"] = providers
    _write(path, data)
    return ref


# ---------------------------------------------------------------------------
# Live model listing
# ---------------------------------------------------------------------------

def fetch_models(conn: Connection, timeout: float = 5.0) -> list[str]:
    """The model ids an endpoint offers, fetched from its models list.

    OpenAI-compatible endpoints serve /v1/models; ollama serves
    /api/tags. A request that fails or times out yields no models (the caller
    shows the failure, not a traceback).

    Args:
        conn:    the connection to list models for.
        timeout: per-request timeout in seconds.

    Returns:
        Model ids, in the endpoint's order; empty on any failure.
    """
    if conn is None or not conn.base_url:
        return []
    import urllib.request
    base = conn.base_url
    try:
        if conn.kind == "ollama":
            url = base.rstrip("/") + "/api/tags"
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", ""))
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        url = base.rstrip("/") + ("/v1/models" if not base.endswith("/v1") else "/models")
        req = urllib.request.Request(url)
        if conn.api_key:
            req.add_header("Authorization", "Bearer " + conn.api_key)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", ""))
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------

class ConnectionsDialog(QWidget):
    """The "Manage connections" editor: the list, the fields for one, and the
    actions (Test / Save / Remove / Use for AI Design / Use for the Code
    agent).

    Attributes tests may rely on: `list_widget` (QListWidget), the text fields
    `name_edit`, `base_url_edit`, `api_key_edit`, `model_edit`, the
    `kind_combo` (QComboBox), the `thinking_check` (QCheckBox), and
    `save_button`. `saved` is emitted when Save succeeds, so the caller can
    refresh its provider list.
    """

    # Emitted when Save succeeds (the caller refreshes its provider list).
    saved = Signal()
    # Emitted after any mutation, carrying the current store.
    changed = Signal(ConnectionStore)

    def __init__(self, store: ConnectionStore, parent=None):
        super().__init__(parent)
        self.setObjectName("connectionsDialog")
        self._store = store
        self.resize(640, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # -- the saved list ----------------------------------------------
        self.list_widget = QListWidget()
        self.list_widget.setCurrentRow(-1)
        self.list_widget.currentRowChanged.connect(self._selection_changed)
        self.list_widget.itemClicked.connect(self._selection_changed)
        layout.addWidget(self.list_widget, 1)

        # -- the fields --------------------------------------------------
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name")
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(list(_KINDS))
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://host:port")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("API key")
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Model id (empty to fetch)")
        self.thinking_check = QCheckBox("Thinking model")
        self.thinking_check.setCursor(Qt.PointingHandCursor)
        for edit in (self.name_edit, self.base_url_edit, self.api_key_edit, self.model_edit):
            edit.setCursor(Qt.PointingHandCursor)
        form.addRow("Name", self.name_edit)
        form.addRow("Kind", self.kind_combo)
        form.addRow("Base URL", self.base_url_edit)
        form.addRow("API key", self.api_key_edit)
        form.addRow("Model", self.model_edit)
        form.addRow(self.thinking_check)
        group = QGroupBox("Connection")
        group.setLayout(form)
        layout.addWidget(group)

        # -- test --------------------------------------------------------
        test_row = QHBoxLayout()
        self.test_button = QPushButton("Test")
        self.test_button.setCursor(Qt.PointingHandCursor)
        self.test_button.clicked.connect(self._test)
        test_row.addWidget(self.test_button)
        self.test_label = QLabel()
        self.test_label.setObjectName("connectionsTest")
        test_row.addWidget(self.test_label)
        test_row.addStretch(1)
        layout.addLayout(test_row)

        # -- save / remove -----------------------------------------------
        button_row = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.clicked.connect(self._save)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setCursor(Qt.PointingHandCursor)
        self.remove_button.clicked.connect(self._remove)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.remove_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        # -- the per-role pick -------------------------------------------
        role_row = QHBoxLayout()
        role_row.addWidget(QLabel("Use for"))
        self.role_buttons = {}
        for role in _ROLES:
            button = QPushButton(f"Use for {role.title()}")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, r=role: self._use_for(r))
            role_row.addWidget(button)
            self.role_buttons[role] = button
        role_row.addStretch(1)
        layout.addLayout(role_row)

        self._refresh_list()
        self.changed.emit(store)

    # -- the actions ------------------------------------------------------

    def _refresh_list(self) -> None:
        self.list_widget.clear()
        for conn in self._store.list():
            self.list_widget.addItem(QListWidgetItem(f"{conn.name}  ({conn.kind})"))
        self._refresh_enabled()

    def _selection_changed(self, row: int) -> None:
        self._load_into_fields(row)
        self._refresh_enabled()

    def _load_into_fields(self, row: int) -> None:
        conns = self._store.list()
        if 0 <= row < len(conns):
            conn = conns[row]
            self.name_edit.setText(conn.name)
            self.kind_combo.setCurrentText(conn.kind)
            self.base_url_edit.setText(conn.base_url)
            self.api_key_edit.setText(conn.api_key)
            self.model_edit.setText(conn.model)
            self.thinking_check.setChecked(conn.thinking)
        else:
            self._clear_fields()

    def _clear_fields(self) -> None:
        self.name_edit.clear()
        self.base_url_edit.clear()
        self.api_key_edit.clear()
        self.model_edit.clear()
        self.thinking_check.setChecked(False)

    def _refresh_enabled(self) -> None:
        self.remove_button.setEnabled(self.list_widget.currentRow() >= 0)

    def _current_connection(self) -> Connection:
        """What the fields name now, or None when the name is blank."""
        name = self.name_edit.text().strip()
        if not name:
            return None
        return Connection(
            name=name,
            kind=self.kind_combo.currentText() or "byok",
            base_url=self.base_url_edit.text().strip(),
            api_key=self.api_key_edit.text().strip(),
            model=self.model_edit.text().strip(),
            thinking=self.thinking_check.isChecked(),
        )

    def _test(self) -> None:
        conn = self._current_connection()
        if conn is None or not conn.base_url:
            self.test_label.setText("Enter a name and base URL to test.")
            return
        models = fetch_models(conn)
        self.test_label.setText(
            f"Found {len(models)} model(s)." if models else "No models returned.")

    def _save(self) -> None:
        conn = self._current_connection()
        if conn is None or not conn.base_url:
            QMessageBox.warning(self, "Connection", "Name and base URL are required.")
            return
        try:
            self._store.update(conn)
        except ValueError as exc:
            QMessageBox.warning(self, "Connection", str(exc))
            return
        self._refresh_list()
        self.list_widget.setCurrentRow(self.list_widget.count() - 1)
        self._load_into_fields(self.list_widget.currentRow())
        self.changed.emit(self._store)

    def _remove(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        conns = self._store.list()
        if row >= len(conns):
            return
        self._store.remove(conns[row].name)
        self.list_widget.setCurrentRow(-1)
        self._clear_fields()
        self._refresh_list()
        self.changed.emit(self._store)

    def _use_for(self, role: str) -> None:
        row = self.list_widget.currentRow()
        if row < 0:
            return
        conns = self._store.list()
        if row >= len(conns):
            return
        conn = conns[row]
        self._store.set_default(role, conn.name)
        if role == "agent":
            # The Code agent reads this config, so write it: the new
            # connection is usable without a separate step.
            try:
                write_opencode_config(conns)
            except OSError:
                pass
        self.test_label.setText(f"Used for {role}.")


__all__ = ["Connection", "ConnectionStore", "fetch_models",
           "opencode_provider_entry", "write_opencode_config", "ConnectionsDialog"]