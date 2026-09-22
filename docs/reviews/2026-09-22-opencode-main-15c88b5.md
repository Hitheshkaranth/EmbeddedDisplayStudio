# Code Review -- EmbeddedDisplay Studio, 15c88b5

## Summary

Overall quality is **high**. This repository is well-structured, thoroughly
documented, and shows clear evidence of experienced engineering. The C runtime
(native/hmi-ui) has a clean separation between model, binding engine, widget
layer, and display backend. The deployment pipeline (hmi-install, deploy_to_hmi.sh,
provision_panel.py) is robust with atomic symlink swaps, SHA-256 verification,
pre-extraction archive scanning, and auto-rollback on GUI failure. The recent
commit (15c88b5) -- migrating from Qt to a native C/LVGL panel runtime -- is
thoughtfully designed and backwards-compatible with existing bundles.

**Top risks:**
1. `drain()` in tags.c has an unbounded loop on the UDP socket that could
   starve the main loop under sustained malformed traffic.
2. `hmi_alarms_active()` in alarms.c returns a static buffer that is silently
   overwritten by the next call.
3. `provision_remote.sh` uses `rm -rf` paths that include the interpreter's
   site-packages under a glob; a shell-glob mismatch on the Python version
   could leave stale PySide6 packages.
4. Yocto recipes reference files via `file://` symlinks but have no
   `SRC_URI` checksums -- a file dropped in files/ won't trigger a rebuild.

---

## Findings

### Critical

#### 1. `native/hmi-ui/src/tags.c:157` -- unbounded recvfrom loop in `drain()`
**What:** The `drain()` function calls `recvfrom()` in a `for(;;)` loop until
`EAGAIN/EWOULDBLOCK`. Each iteration parses JSON with cJSON. An attacker (or a
mishapling daemon) flooding the UDP port with valid-but-payload-heavy JSON
frames will pin a CPU core, block all LVGL timers, starve the watchdog, and
hang the panel.

**Why it matters:** This is the panel's network-facing entry point. Even on
localhost, the hardware daemon could have a memory leak or bug that causes
it to send oversized frames. A single ~8 KB datagram parsed every 4 ms is
manageable; 100/second would eat CPU.

**Suggested fix:** Limit the loop to a fixed number of iterations (e.g. 32)
or add a time budget (process no more than 1 ms of parse time per poll).

```c
static void drain(hmi_tags_t *t)
{
    static char buf[MAX_DATAGRAM + 1];
    int max_iter = 64;   // cap to protect the main loop
    for (int i = 0; i < max_iter; ++i) {
        ssize_t n = recvfrom(t->fd, buf, sizeof buf, 0, NULL, NULL);
        if (n < 0) { ... }
        if (n > MAX_DATAGRAM) { ++t->rx_errors; continue; }
        ...
    }
}
```

#### 2. `native/hmi-ui/src/alarms.c:287` -- static buffer in `hmi_alarms_active()`
**What:** `hmi_alarms_active()` returns a pointer to a `static hmi_alarm_t *packed`
buffer. The function comment in `alarms.h` says "the array is valid until the
next evaluate/acknowledge", but the C code actually packs into static memory
each call, so **any** caller holding the pointer across another `evaluate()` or
`hmi_alarms_acknowledge()` call gets dangling data. Worse, `alarms.c:295` copies
the `alarm` struct but the `value` field inside is a shallow `hmi_value_t`
copy that borrows memory -- `hmi_value_free()` on the packed copy is unsafe
because the packed array is static and the value pointer is borrowed.

**Why it matters:** The runtime (runtime.c:40) calls `hmi_page_visit(rt->page,
deliver_alarms_cb, rt)` which calls `hmi_alarms_active_value()`, then the
caller (set_prop callback) may later trigger an alarm acknowledge, invalidating
the pointer.

**Suggested fix:** Either allocate per-call with the caller responsible for
freeing, or document that `hmi_alarms_active_value()` must be used (which does
a deep copy) and `hmi_alarms_active()` is strictly for read-only transient use
during the same evaluation pass.

### High

#### 3. `native/hmi-ui/src/bind.c:416` -- `snprintf` truncation in format string
**What:** `bind.c:416` uses `snprintf(formatted, sizeof formatted, "%.0f", display)`
in a 256-byte buffer, then copies the formatted value into `result[512]` via
`strcat`. The `result` buffer is 512 bytes, but the format string prefix
(`before`) can be up to 511 characters and `pct + 2` can add more, with
`strcat` silently truncating. The resulting string may be silently truncated
without the widget knowing.

**Why it matters:** A designer who creates a label with a very long format
string (e.g. from an AI prompt "Temperature of Main Engine Coolant at
High-Pressure Stage: %1 °C") will get a truncated display on the panel with
no indication of the truncation.

**Suggested fix:** Add a bounds check: if `strlen(result) + strlen(pct + 2) >=
sizeof(result)`, either truncate at `before` and append `...` or use
`snprintf` for the final concatenation.

#### 4. `native/hmi-ui/src/tags.c:256-269` -- `hmi_tags_history()` returns heap-allocated value via stack
**What:** `hmi_tags_history()` on line 256-269 returns an `hmi_value_t` on the
stack whose `items` pointer is heap-allocated (calloc). The caller must call
`hmi_value_free()` on the returned value. This is fine in C, but the function
signature makes it easy for callers to forget (it looks like a simple read
accessor, not a creator).

**Why it matters:** A bug where a caller does not free this value would leak
`count * sizeof(hmi_value_t)` bytes every call. Under continuous telemetry
this could exhaust memory over months.

**Suggested fix:** Add a comment in the header `// Caller must hmi_value_free().`
and add a test in test_alarms.c (or a new tests/test_tags.c) that verifies
freeing the return value doesn't crash and the history is correct after.

#### 5. `deploy/provision_remote.sh:204-206` -- aggressive `rm -rf` of Qt paths
**What:** Lines 204-206 delete a list of Qt loader paths including
`/usr/lib/hmi/qt6` and `/opt/hmi-python-qt5`. If a panel was provisioned by
a different tool or manually modified, one of these paths might point to
something important (e.g. an unrelated python installation).

**Why it matters:** `rm -rf /usr/lib/hmi/qt6` without checking ownership or
contents could delete a third-party package managed by the image builder.
The `--keep-qt` flag mitigates this but only under the default flow.

**Suggested fix:** Guard the removal with a marker file check: only delete
paths that contain a known `.hmi-qt-loader-marker` file, proving they were
installed by this platform's earlier provisioning.

#### 6. `deploy/provision_remote.sh:211` -- glob-based Python package removal
**What:** Line 211 uses `rm -rf /opt/hmi-python/lib/python3*/site-packages/PySide6*`
to strip PySide6 packages from the provisioned interpreter. The `python3*/`
part is a shell glob that depends on the Python minor version. If the installed
interpreter has an unexpected structure (e.g. a vendored layout from
python-build-standalone that does not include `python3.X` in the path), the
glob fails silently and stale packages remain.

**Why it matters:** A panel that kept stale PySide6 packages after Qt removal
will import the wrong binding when the daemon starts, causing a silent import
failure.

**Suggested fix:** Use `python3 -c "import sysconfig; ..."` to find the actual
site-packages path instead of relying on a glob pattern.

#### 7. `schema/manifest.py:446` -- `screen.height` boolean check
**What:** `manifest.py:446` checks `isinstance(value, bool)` which is correct
because `bool` is a subclass of `int` in Python. However, the same check is
missing for the `alarms[].critical.value` and `alarms[].warning.value` fields
at line 536 where `isinstance(value, bool)` IS checked. The screen check at
line 446 is fine but inconsistent with the rest of the file which has the
bool guard only in some places.

**Why it matters:** Not a bug -- this is a style nit, but the inconsistency
between lines 446-447 (which guards `bool`) and other value checks could lead
to a future edit introducing the same vulnerability elsewhere.

### Medium

#### 8. `native/hmi-ui/src/alarms.c:293` -- static buffer not thread-safe
**What:** `hmi_alarms_active()` uses `static hmi_alarm_t *packed; static size_t
packed_cap;` in alarms.c:287-288. If the alarm engine is called from two
threads (e.g. a tag-change callback and a UI thread), both will see the
buffer being modified. LVGL is generally single-threaded, but the `hmi_tags_poll`
callback (`on_tag` -> `hmi_runtime_on_tag`) runs from the main loop which is
single-threaded. So this is safe in practice but the `static` is fragile to
future changes.

**Why it matters:** If a future change calls alarms from a non-LVGL thread (e.g.
a separate telemetry worker), the static buffer causes data races.

**Suggested fix:** Add `// single-threaded; do not call from other threads` to
the header declaration, or allocate the buffer inside the call site's stack
frame if the alarm count is bounded.

#### 9. `native/hmi-ui/src/model.c:136-137` -- `ftell` size assumption
**What:** `model.c:136-137` reads the file size via `ftell`, then allocates
`(size_t)n + 1` bytes. If the file is extremely large (> 2 GB), `ftell`
returns `long` which is 32-bit on 32-bit systems, and the allocation would
fail silently or overflow.

**Why it matters:** The `.edsui` project files are typically small (under 1 MB),
but the model loader doesn't have an explicit size guard. A corrupted or
malicious `.edsui` file with truncated content would allocate too little
memory.

**Suggested fix:** Add a maximum file size check (e.g. 10 MB) and verify that
`fread` read exactly `n` bytes (it does at line 137, but the size check helps
before allocation).

#### 10. `target/bin/hmi-install:992` -- `prune_releases` subshell cleanup
**What:** `hmi-install:992` pipes `_pruned` output into `while IFS= read -r`
in a pipe, which runs the loop body in a subshell. The `_prune_count` variable
incremented inside the loop is lost when the subshell exits, so the log line
"removed X old release(s)" will always report 0 if there's no `echo` from
inside the subshell.

**Why it matters:** The summary line at the end of prune is misleading.
`_prune_count` at line 996 is set from `echo "$_pruned" | wc -l` which is
outside the subshell, but only if `_pruned` is non-empty. If the pipe from
`echo "$_pruned"` to `while` is a subshell and the variable is inside it,
the count is lost.

**Suggested fix:** Use a process substitution (`while ... done < <(echo
"$_pruned")`) or write the count to a temp file.

#### 11. `deploy/provision_panel.py:102` -- preflight inline shell is fragile
**What:** The PREFLIGHT string at line 99-118 runs an inline shell script over
SSH. The line at 102 that checks `python3_stdlib` uses a nested `echo` inside
a command substitution, and the quoting is complex enough that a panel with
unusual `$` characters in its `PRETTY_NAME` (unlikely but possible) could
break the output parsing in `parse_preflight()`.

**Why it matters:** A preflight that fails silently would report incorrect
board facts, potentially allowing a provisioning run that later fails.

**Suggested fix:** Each fact should be printed on its own line with a simple
`key=value` format rather than trying to parse complex output lines.

#### 12. `yocto/meta-hmi/recipes-hmi/hmi-core/hmi-core_1.0.bb:44` -- `SRC_URI` has no checksums
**What:** The `file://` entries in `SRC_URI` reference symlinks into the repo.
Without `file://...#md5=...` or `file://...#sha256sum=...`, if someone changes
a file in the `files/` directory, bitbake may not rebuild the package because
the `.bb` file's hash hasn't changed and the `file://` sources are resolved
at unpack time without checksumming.

**Why it matters:** An integrator who updates `hwd.json` but forgets to update
the recipe could end up with a stale package on the target.

**Suggested fix:** Add checksums to each `SRC_URI` entry or use a tarball
source that bitbake can hash.

### Low

#### 13. `native/hmi-ui/src/widgets/w_shalarmtable.c:48` -- row index from `lv_obj_get_index`
**What:** `w_shalarmtable.c:48` uses `lv_obj_get_index(row)` to determine which
alarm row was clicked, assuming child 0 is the empty-state label. This is
fragile if LVGL ever adds internal children or if the row layout changes.

**Suggested fix:** Store the alarm index in user data on the row element.

#### 14. `native/hmi-ui/src/runtime.c:47` -- global owner map is unbounded (hard-coded)
**What:** `runtime.c:47` has `static owner_t g_owners[2048]`. If a page has
more than 2048 widgets (unlikely but possible with generated designs), excess
widgets silently lose their owner mapping and `hmi_runtime_of()` returns NULL.

**Suggested fix:** Dynamic allocation with growth, or an assert/log on overflow.

#### 15. `schema/manifest.py:64` -- `deployable_name` regex length
**What:** `deployable_name()` at line 64 truncates to 64 characters after
normalization, but the NAME_RE at line 64 requires the name to match
`^[a-z0-9][a-z0-9._-]{0,63}$`. If the truncated name ends in a `.` or `-`,
the `rstrip` at line 75 fixes it, but a name like "a...." (4+ dots) collapses
to just "a" via the `-{2,}` -> `-` reduction, losing the original intent.

**Suggested fix:** Document that very noisy names are reduced aggressively.

#### 16. `deploy/provision_ui.sh:38` -- `install -d` on remote does not check success
**What:** `provision_ui.sh:38` runs `install -d` on the remote side without
checking its exit code. If the directory creation fails (e.g. no disk space,
read-only filesystem), subsequent scp commands will fail with an unhelpful
error.

**Suggested fix:** Check the exit code of each remote `install -d` command.

#### 17. `deploy/deploy_to_hmi.sh:934` -- quoting in ssh_run mkdir command
**What:** `deploy_to_hmi.sh:934` uses `ssh_run "mkdir -p '${REMOTE_UPLOAD_DIR}' && chmod 0700 '${REMOTE_UPLOAD_DIR}'"`.
The single quotes inside double quotes are literal, so the remote shell
receces the literal `$REMOTE_UPLOAD_DIR` which is not expanded on the remote
side unless `REMOTE_UPLOAD_DIR` is exported.

**Why it matters:** This is actually fine because `REMOTE_UPLOAD_DIR` is a
local variable that gets expanded by the local shell before `ssh` is called.
The remote command is `mkdir -p '/tmp/hmi_upload' && chmod 0700
'/tmp/hmi_upload'` -- a literal string. This is correct. **False positive.**

### Nit

#### 18. `native/hmi-ui/src/value.c:146` -- `hmi_value_debug` static buffer
**What:** `value.c:146` uses a static buffer. This is documented but the
function name `hmi_value_debug` (vs `hmi_value_debug_to_buf`) makes it
easy to misuse in multi-context logging.

#### 19. `native/hmi-ui/src/tags.c:44` -- `last_id` buffer overflow potential
**What:** `tags.c:44` has `char last_id[32]` which is used by `next_id()` at
line 92 with `snprintf(t->last_id, sizeof t->last_id, "gui-%u", ...)`. A 32-
byte buffer is more than enough for "gui-4294967295" (14 chars), but if the
counter overflows from `unsigned` to 0 and the daemon runs for years, the
counter wrapping is correct but the id string stays "gui-0".

**Suggested fix:** Log a warning when `next_id` wraps.

#### 20. `native/hmi-ui/src/main.c:44` -- ready file path from `--ready-file` is unsanitized
**What:** `main.c:44` uses `--ready-file F` directly in `fopen()` without
validating the path. An attacker who can control the command-line (e.g.
injection via the service file) could create any file on the filesystem.

**Suggested fix:** Validate that the path is under `/run/hmi/` before creating.

#### 21. `deploy/provision_panel.py:53` -- `TEXT_SUFFIXES` includes empty string
**What:** `TEXT_SUFFIXES` includes `""` which means every file (including
binaries like the hmi-ui binary) is treated as text and line-ending normalised.
The code at line 183 checks `if rel not in BINARY_SOURCES` which correctly
excludes the hmi-ui binary, but the empty string suffix catches files without
extensions that are still binary (e.g. `hmi-install`, `hmi-hwd-launch`).

**Suggested fix:** Remove `""` from TEXT_SUFFIXES and add explicit exceptions
for known text files without extensions.

---

## Things done well

- **Atomic symlink swaps** in hmi-install (using python3 `os.replace()`) -- correct,
  well-documented, and the only safe approach for cross-platform compatibility.
- **Pre-extraction archive scanning** (`prescan_bundle()`) catches path traversal
  before any files touch disk, which is critical for a service exposed over SSH.
- **Auto-rollback on GUI failure** with the `gui-ready` sentinel mechanism -- the
  central safety guarantee of the deployment pipeline, properly implemented.
- **Single source of truth for manifest validation** (`schema/manifest.py`) -- the
  desktop tool, host CLI, and target installer all call the same file, eliminating
  the previous "three copies of a rule" problem.
- **Deterministic bundle packing** (`schema/bundle.py`) with SHA-256 sidecar --
  byte-identical archives from the same directory, enabling reliable checksum
  verification on the target.
- **LVGL widget parity with QML** -- each C widget file references its QML spec
  in the comment header, making visual regression easy to spot.
- **Alarm engine tests** (`test_alarms.c`) cover all 19 edge cases from the
  original C++ engine, plus per-tag delivery.
- **`hmi-install` exit code 4** (deployed but not boot-default) -- a nuanced
  outcome that correctly distinguishes "working now but dark at reboot" from
  "not working."

---

## Test gaps

1. **No test for `tags.c` `drain()` under malformed input.** `test_bind.c` tests
   the binding engine but there is no `test_tags.c` that feeds malformed JSON,
   oversized datagrams, or rapid datagram bursts to `drain()`.

2. **No test for `bind.c` format string edge cases.** The `bind.c:416` snprintf
   path (format string with long prefix + value) is untested. A test with a
   400-character format string would verify truncation behavior.

3. **No test for `alarms.c` `hmi_alarms_active()` vs `hmi_alarms_acknowledge()`
   interaction.** The static buffer returned by `hmi_alarms_active()` is never
   held across an `acknowledge()` call in tests, so the potential invalidation
   is untested.

4. **No test for `model.c` with > 2 GB file or corrupted JSON.** Error paths
   exist but the size overflow and JSON-parsing near-end-of-file edge cases
   are untested.

5. **No test for `provision_remote.sh` with `HMI_KEEP_QT=1` on a panel that
   has stale PySide6 packages alongside an empty `python3*/` glob.** The
   `rm -rf` on line 211 silently fails if the glob doesn't match.

6. **No test for `deploy_to_hmi.sh` with a bundle whose name contains
   special characters (spaces, quotes).** The script uses `$*` and variable
   expansion in ways that could break with unusual bundle names.

7. **No test for `hmi-ui` widget `set_prop()` called after `destroy()`.** If
   the tag engine fires a value change for a widget during navigation, the
   set_prop callback may execute on a destroyed widget state pointer.

8. **No test for `schema/manifest.py` `preview_entry()` with an `edsui` bundle
   that has no `preview` key.** The function returns `"generated/App.qml"`
   as a fallback, but that file may not exist in the bundle.