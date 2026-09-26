# Code section: project editor and coding agent

The Studio's **Code** tab used to show one thing: the code of the design
(`.edsui` or the hmi-ui C of the selected widget). It is now a small IDE
for the project folder: a file tree, tabbed editors for any file in the
project, the old design view kept as a pinned tab, and a chat agent that
reads and writes the project's files. The agent is **opencode**, driven over
its HTTP server, so the Studio gets opencode's tools (read, edit, write,
grep, glob, bash) and its providers (the vLLM endpoints, OpenRouter) without
re-implementing any of it.

```
+-- Code -------------------------------------------------------------------------------+
| [Open folder...] ~/bundles/cockpit        [Save] [Save all]       [Files] [Agent]      |
+------------------+--------------------------------------------+-----------------------+
| filter [      ]  | Design | main.c | project.edsui* |          | Agent  [model v] [+]  |
| v src/           |--------------------------------------------| user: add a sub()...  |
|     main.c       |  1  #include "hmi.h"                        | > Thinking (collapsed)|
|     util.h       |  2                                          | [glob] *.c   done     |
| v assets/        |  3  int add(int a, int b) { ... }           | [edit] math.c  done   |
|   project.edsui  |  ...                                        | I added sub() to ...  |
|   manifest.json  |                                             |-----------------------|
|                  |                                             | [x] include open file |
|                  |                                             | [ message...     ][>] |
+------------------+--------------------------------------------+-----------------------+
```

## Components

| Module | Class | Depends on |
|---|---|---|
| `designer/ide/project_files.py` | file helpers, `ProjectTree` | PySide6, stdlib |
| `designer/ide/editor_tabs.py` | `EditorTabs` | `project_files` helpers, `designer/ui/code_editor.CodeEditor` |
| `designer/ui/code_editor.py` | `PythonHighlighter` | - |
| `designer/ide/opencode_client.py` | `OpencodeServer`, `OpencodeClient`, `EventNormalizer` | stdlib only (no Qt) |
| `designer/ide/agent_backend.py` | `AgentBackend` (base), `ScriptedBackend`, `OpencodeBackend` | `opencode_client`, QtCore |
| `designer/ide/agent_panel.py` | `AgentPanel` | `AgentBackend` interface only |
| `designer/ide/code_section.py` | `CodeSection` (composition) | all of the above |
| `tools/hmi_deployer/mainwindow.py` | hosts `CodeSection` as the Code tab | |

Dependency rule: arrows only point down the table. `AgentPanel` knows the
`AgentBackend` interface and nothing about opencode; `opencode_client` knows
nothing about Qt. So the panel is tested with `ScriptedBackend`, the client
with a recorded event stream and a fake HTTP server, and nothing in the test
suite needs opencode or a model.

## Data flow

```
ProjectTree --fileActivated(path)--------------------------> EditorTabs.open_file
EditorTabs  --selection_context() (on send)----------------> AgentPanel -> backend.send(text, model, context)
OpencodeBackend: HTTP POST /session/{id}/prompt_async  -> opencode serve (child process, cwd = project)
opencode    --SSE GET /event?directory=...  -> reader thread -> EventNormalizer -> backend.event(dict) [GUI thread]
AgentPanel  <-- event: text / reasoning / tool / permission / usage / busy / idle / error
AgentPanel  --fileEdited(path)--> EditorTabs.file_changed_on_disk (reload clean tabs; banner on dirty)
                                  ProjectTree.refresh (new files appear)
AgentPanel  --openFileRequested(path, line)--> EditorTabs.open_file
Designer    --designChanged--> CodeWindow (pinned "Design" tab, unchanged)
workspace.bundle_dir changes --> CodeSection.set_root -> tree root, backend.start(directory)
```

## The agent event vocabulary

`AgentBackend.event` carries one dict per event. `EventNormalizer` produces
exactly these from opencode's raw bus events; any other backend must too.

| type | fields | from opencode |
|---|---|---|
| `busy` | - | `session.status` status.type busy/retry (first one only) |
| `idle` | - | `session.idle`, or `session.status` idle (first one only) |
| `text` | `id`, `delta` | assistant `text` part: `message.part.delta` (field text); a `message.part.updated` whose text is longer than what was sent emits the missing suffix |
| `reasoning` | `id`, `delta` | same, for `reasoning` parts |
| `tool` | `id`, `tool`, `status`, `title`, `input`, `output`, `error` | `message.part.updated` part.type tool; one event per status change (pending, running, completed, error) |
| `file_edited` | `path` (absolute) | `file.edited` |
| `permission` | `id`, `permission`, `patterns`, `title` | `permission.asked` (`permission.updated` accepted too) |
| `usage` | `input`, `output`, `reasoning` | `step-finish` part tokens |
| `error` | `message` | `session.error` (error.data.message, else error.name) |

Filtering: events for another session are dropped; parts belonging to a
`user` message (opencode echoes the prompt) are dropped; `file.edited`
carries no session and always passes. Deltas for a part id seen before its
`message.part.updated` are buffered by type once known (text is the default).

## opencode integration

* Binary: `$OPENCODE_BIN`, else `opencode` on PATH (on Windows `opencode.cmd`
  from `%APPDATA%\npm`). Missing -> the panel says how to install it
  (`npm i -g opencode-ai`) and stays usable as a read-only transcript.
* One server per Studio: `opencode serve --hostname 127.0.0.1 --port 0`,
  base URL parsed from the line `opencode server listening on http://...`.
  `$OPENCODE_URL` attaches to an already running server instead. The child
  is stopped when the Studio exits (and when the section is destroyed).
* Every request carries `?directory=<project root>`, which is how opencode
  scopes sessions, file tools and the event stream to the project.
* Session: created lazily on first send (`POST /session`), "New chat"
  drops it. Prompt: `POST /session/{id}/prompt_async` with
  `{"parts":[{"type":"text","text":...}], "model":{providerID, modelID},
  "system": SYSTEM_PROMPT}`; returns 204 immediately, the answer arrives on
  the event stream. Stop: `POST /session/{id}/abort`. Permission:
  `POST /permission/{requestID}/reply {"reply": "once"|"always"|"reject"}`.
* Models: `GET /config/providers` -> providers[].models, `default` map. The
  panel's combo lists `provider/model`; the choice is kept in QSettings
  (`codeSection/agentModel`).
* All network I/O runs off the GUI thread (a `threading.Thread` per call
  for requests; one long-lived reader thread for SSE, reconnecting with
  back-off while the backend is started). Results reach Qt through queued
  signals.

## Editors and files

* Tree: synchronous model built from `os.scandir` (not QFileSystemModel, whose
  async loading makes tests and "reveal" flaky), folders first, names
  case-insensitive, ignored dirs hidden (`.git`, `__pycache__`, `build`, ...),
  a filter field, context menu New file / New folder / Rename / Delete /
  Copy path. A `QFileSystemWatcher` on expanded directories refreshes it.
* Files: UTF-8 (BOM kept) with a latin-1 fallback; newline style preserved;
  NUL bytes in the first 8 KiB or > 2 MiB -> not opened, message instead.
  Saves are atomic (temp file + `os.replace`). Paths outside the project root
  are refused.
* Tabs: title = file name, `*` suffix when dirty, tooltip = relative path.
  Ctrl+S / Ctrl+Shift+S / Ctrl+W. Closing a dirty tab asks Save / Discard /
  Cancel. A file changed on disk (the agent, git, another editor) reloads
  silently when the tab is clean; when dirty a banner offers Reload / Keep
  mine. Language from the extension: `.c .h .cpp .hpp .cc` C, `.py` Python,
  `.qml .js` QML, `.json .edsui` JSON, everything else plain.
* The design view (`CodeWindow`) is a pinned, non-closable first tab
  "Design"; the Designer's Code action (Ctrl+Shift+K) switches to it.

## Widget visibility and backend

The navigator on the left has four panes: **Files**, **Widgets** (the
current page, with thumbnails), **Outline** and **Backend**. The last two,
and the agent's design context, all read one `DesignIndex`
(`designer/ide/design_index.py`), which `CodeSection.rebuild_index()` builds
again on every `designChanged`. It covers the whole design (every page),
each widget's bindings and actions, every tag with the widgets that read and
write it, each widget's line in `project.edsui`, and the binding
diagnostics from `designer/model/binding_diagnostics.audit_bindings`.

```
Outline                                   Backend
2 pages, 10 widgets, 6 types, 6 tags...   Source: Simulator (online)
[filter] [All] [Bound] [Issues] [tag: x]  Tag        Access Used by   Value  Status
v Main (5)                                ai.fuel           -         --     unused
    rpm    ShGauge    ai.rpm              ai.oiltemp R      oil       52.1   not declared
  v panel  ShCard                         ai.rpm     R      rpm, rpm2 3120.5 ok
      pump ShToggle   do.pump (rw)        do.pump    RW     pump      true   ok
v Alarms (5)                              [Copy tags] [Generate backend...]
    oil    ShNumDisplay ai.oiltemp   1
```

| Module | Class | What |
|---|---|---|
| `designer/ide/design_index.py` | `DesignIndex`, `WidgetEntry`, `TagEntry` | the design as facts; no Qt |
| `designer/ide/widget_outline.py` | `WidgetOutline` | whole-design tree: tags, issue counts, filters (All / Bound / Issues / one tag). Click selects the widget, switching page if needed; double-click opens `project.edsui` at the widget |
| `designer/ide/tag_panel.py` | `TagPanel` | the Backend pane: one row per tag with access, users, live value and status; clicking a tag filters the Outline to its widgets; double-click on a writable tag writes a value; "Generate backend..." |
| `designer/ide/tag_source.py` | `TagSource`, `EngineTagSource`, `SimulatedTagSource` | where values come from: the Studio's TagEngine (UDP 5001) while it is online, else a time-driven simulator scaled to each widget's min/max |
| `designer/ide/agent_context.py` | `design_brief`, `quick_actions` | what the agent is told about the design (pages, the selected widget's JSON and bindable properties, tags, issues, CONTRACT rules), and one-click prompts |
| `designer/ide/backend_scaffold.py` | `write_scaffold` | writes `backend/` into the project: `backend.py` (a runnable CONTRACT 2 UDP backend with one `read_`/`write_` stub per tag), `tags.json`, `tags.h`, `README.md` |

**Values.** The pane polls its source every 250 ms, only while it is
visible. `CodeSection.set_engine_provider()` is given the device panel's
TagEngine (built lazily by the first preview); `EngineTagSource` never starts
or stops the engine, the Studio owns it. The simulator runs only while the
Code tab is on screen. Writes go to the engine (`Bus.write`, i.e. to the
daemon) or, on the simulator, override that tag until the design changes.

**Agent.** The panel's "Include design" option (on by default) adds
`design_brief()` to each message as `context["design"]`; `build_prompt`
appends it after the editor context. The brief is capped at 6000 characters
(tags are dropped first, the rules never). "Quick actions" offers prompts
for the selected widget (explain, bind, add alarm) and the design (fix
binding issues, write the backend, summarise).

**Generated backend.** `python3 backend/backend.py --listen 127.0.0.1:5010
--sink 127.0.0.1:5001` publishes a frame of every design tag each 100 ms and
answers `set`, `pulse`, `subscribe`, `list`, `ping` as `hmi-hwd` does. On a
panel, point hmi-ui at it with `HMI_UI_EXTRA_ARGS=--daemon-port 5010`, as for
tagsim. Files that already exist are kept unless the user agrees to
overwrite them.

## Security notes

The opencode server listens on 127.0.0.1 only. The agent can run shell
commands in the project directory with the user's rights, as opencode does in
a terminal; permission requests opencode raises are shown in the panel and
nothing is auto-approved by the Studio.

## Tests

* `tests/test_ide_project_files.py`
* `tests/test_ide_editor_tabs.py`
* `tests/test_ide_opencode.py` (recorded stream `tests/fixtures/opencode_events_edit.sse`, fake server)
* `tests/test_ide_agent_panel.py`
* `tests/test_ide_code_section.py` (composition; live opencode test when `OPENCODE_LIVE=1`)
* `tests/test_code_window.py`, `tests/test_code_editor.py`
* `tests/test_ide_design_index.py`, `tests/test_ide_widget_outline.py`, `tests/test_ide_tag_panel.py`,
  `tests/test_ide_tag_source.py`, `tests/test_ide_agent_context.py`, `tests/test_ide_backend_scaffold.py`
  (fixture `tests/ide_v2_fixture.py`; the scaffold test runs the generated backend over UDP)
