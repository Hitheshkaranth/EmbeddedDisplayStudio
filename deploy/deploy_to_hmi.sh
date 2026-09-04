#!/usr/bin/env bash
# deploy_to_hmi.sh — BYOA HMI host-side deployment CLI
#
# CONTRACT reference: sections 3 (manifest schema), 4 (bundle format),
#   6 (deployment pipeline), 7 (tooling requirements), 7.1 (code standards).
#
# Supported actions:
#   deploy   (default) — validate, package, upload, install an application bundle
#   rollback           — revert to the previous generation on the target
#   list               — list installed applications and their generations
#   status             — show the currently running application
#   logs               — tail hmi-gui and hmi-hwd journal entries
#   check              — verify target readiness (sshd, hmi-install, units)
#
# Portability: runs under bash 4+ on Linux, macOS, and Git Bash for Windows.
#   Platform-specific paths are detected at runtime; comments mark each branch.
#
# Copyright (c) 2026 — BYOA HMI Swarm W4

set -euo pipefail

# ---------------------------------------------------------------------------
# SECTION 1 — GLOBAL CONSTANTS AND COLOUR SETUP
# ---------------------------------------------------------------------------

# Script identity — used in log prefixes and help text.
SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_NAME
readonly SCRIPT_VERSION="1.0.0"

# Maximum bundle size that triggers a warning (100 MiB).  Larger bundles are
# still accepted; this is advisory only (CONTRACT section 6).
readonly BUNDLE_WARN_BYTES=104857600

# Remote directory into which tarballs are staged before installation.
# The installer (hmi-install) expects files here (CONTRACT section 6).
readonly REMOTE_UPLOAD_DIR="/tmp/hmi_upload"

# Remote path of the target-side installer binary (CONTRACT section 6).
readonly REMOTE_INSTALLER="/usr/bin/hmi-install"

# hmi-install's exit status for "installed, running and verified, but the unit
# could not be enabled" -- the release is live and was deliberately not rolled
# back, but the panel will not come up with it after a power cycle.  We
# propagate it unchanged so a caller of this script sees the same distinction
# the installer drew; it is neither a success nor a failed deploy.
readonly EXIT_NOT_BOOT_DEFAULT=4

# Journald units whose logs are retrieved by the "logs" action.
readonly LOG_UNITS=("hmi-gui" "hmi-hwd")

# Number of journal lines fetched before following (CONTRACT section 6).
readonly LOG_LINES=200

# Path to the single implementation of CONTRACT section 4.
#
# The manifest rules are NOT duplicated in this script any more. They lived
# here as a name regex, a version regex, a required-field list and a schema
# constant, and that copy disagreed with the desktop tool and the target
# installer in both directions -- so the same bundle deployed or not depending
# on which tool you used. schema/manifest.py is now called by all three.
# Assigned before it is made readonly: `readonly x="$(cmd)"` returns the
# status of readonly, not of cmd, so a failed cd here would have been
# silently accepted and every path below resolved against the wrong root.
REPO_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT_DIR
readonly SCHEMA_VALIDATOR="${REPO_ROOT_DIR}/schema/manifest.py"

# Path to the shared bundle packer (exclusion rules + deterministic tar).
readonly SCHEMA_PACKER="${REPO_ROOT_DIR}/schema/bundle.py"


# SSH ControlMaster socket is placed inside TMPDIR; the variable is populated
# during setup_temp_dir() and referenced by all ssh/scp helper functions.
SSH_CTL_SOCKET=""   # path to ControlMaster socket, set in setup_temp_dir()
TMPWORK=""          # mktemp working directory, cleaned up via trap

# ---------------------------------------------------------------------------
# SECTION 2 — COLOUR AND OUTPUT HELPERS
# ---------------------------------------------------------------------------

# Colour codes are only emitted when stdout is a terminal AND the NO_COLOR
# environment variable is unset (https://no-color.org/).
# ANSI codes are stored in plain variables so they can be embedded in printf
# format strings without subshell overhead.

_setup_colours() {
    # Purpose: initialise colour variables for the current terminal context.
    # Args:    none
    # Returns: sets module-level colour variables; never fails.
    # Side effects: exports no variables.
    if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
        C_RED=$'\033[0;31m'
        C_GREEN=$'\033[0;32m'
        C_YELLOW=$'\033[0;33m'
        C_CYAN=$'\033[0;36m'
        C_BOLD=$'\033[1m'
        C_RESET=$'\033[0m'
    else
        # No colour: assign empty strings so format strings remain valid.
        C_RED=""
        C_GREEN=""
        C_YELLOW=""
        C_CYAN=""
        C_BOLD=""
        C_RESET=""
    fi
}

# Initialise colours immediately so every function that follows can use them.
_setup_colours

log_info() {
    # Purpose: print an informational message to stderr (stdout is reserved for
    #          function return values, which callers capture with $( ); a log
    #          line on stdout would be captured into the caller's variable).
    # Args:    $@ — message tokens (joined by spaces).
    # Returns: 0
    printf '%s\n' "$*" >&2
}

log_step() {
    # Purpose: print a highlighted step banner to stderr (stdout is reserved for
    #          function return values, which callers capture with $( ); a log
    #          line on stdout would be captured into the caller's variable).
    # Args:    $@ — message tokens.
    # Returns: 0
    printf '%s==> %s%s\n' "${C_CYAN}${C_BOLD}" "$*" "${C_RESET}" >&2
}

log_ok() {
    # Purpose: print a success message to stderr (stdout is reserved for
    #          function return values, which callers capture with $( ); a log
    #          line on stdout would be captured into the caller's variable).
    # Args:    $@ — message tokens.
    # Returns: 0
    printf '%s[OK]%s %s\n' "${C_GREEN}" "${C_RESET}" "$*" >&2
}

log_warn() {
    # Purpose: print a non-fatal warning to stderr.
    # Args:    $@ — message tokens.
    # Returns: 0
    printf '%s[WARN]%s %s\n' "${C_YELLOW}" "${C_RESET}" "$*" >&2
}

log_error() {
    # Purpose: print a fatal error message to stderr.
    # Args:    $@ — message tokens.
    # Returns: 0
    printf '%s[ERROR]%s %s\n' "${C_RED}" "${C_RESET}" "$*" >&2
}

log_verbose() {
    # Purpose: print a debug message to stdout when --verbose is active.
    # Args:    $@ — message tokens.
    # Returns: 0
    # Side effects: nothing when OPT_VERBOSE is 0.
    if [[ "${OPT_VERBOSE}" -eq 1 ]]; then
        printf '%s[DBG]%s %s\n' "${C_CYAN}" "${C_RESET}" "$*"
    fi
}

die() {
    # Purpose: emit a fatal error message and exit with a non-zero status.
    # Args:    $1 — exit code (integer); $2..N — message tokens.
    # Returns: does not return (exits).
    # Exits:   with the status code supplied as $1.
    local code="$1"; shift
    log_error "$*"
    exit "${code}"
}

# ---------------------------------------------------------------------------
# SECTION 3 — PORTABILITY HELPERS
# ---------------------------------------------------------------------------

# Detect the host environment once at startup.  The detection result drives
# platform-specific branches throughout the script.
#
# PLATFORM values:
#   linux  — Linux (including WSL)
#   darwin — macOS
#   gitbash — Git Bash / MSYS2 on Windows
HOST_PLATFORM=""

_detect_platform() {
    # Purpose: identify the host OS so that platform branches can be taken.
    # Args:    none
    # Returns: sets HOST_PLATFORM; exits 1 on unrecognised platform.
    case "$(uname -s)" in
        Linux*)  HOST_PLATFORM="linux" ;;
        Darwin*) HOST_PLATFORM="darwin" ;;
        MINGW*|MSYS*|CYGWIN*) HOST_PLATFORM="gitbash" ;;
        *)
            die 1 "Unrecognised platform: $(uname -s). Supported: Linux, macOS, Git Bash."
            ;;
    esac
    log_verbose "Detected platform: ${HOST_PLATFORM}"
}

realpath_portable() {
    # Purpose: resolve a path to its canonical absolute form portably.
    #          'readlink -f' is GNU-only; macOS/BSD readlink does not support -f.
    #          Git Bash has neither reliably.  We fall back to Python (available
    #          per contract as python3 or python) or pwd -P if Python is absent.
    # Args:    $1 — path to resolve (string, need not exist yet).
    # Returns: writes canonical path to stdout; exits non-zero on failure.
    local path="$1"
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$path"
    elif command -v python >/dev/null 2>&1; then
        python -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "$path"
    elif [[ "${HOST_PLATFORM}" == "linux" ]]; then
        # GNU coreutils readlink -f is safe on Linux.
        readlink -f -- "$path"
    else
        # Last resort: use pwd -P on the parent directory and append the basename.
        local dir file
        dir="$(cd "$(dirname "$path")" 2>/dev/null && pwd -P)" || return 1
        file="$(basename "$path")"
        printf '%s/%s\n' "${dir}" "${file}"
    fi
}

mktemp_dir() {
    # Purpose: create a private temporary directory portably.
    #          GNU mktemp accepts a trailing XXXXXX template; BSD/macOS mktemp
    #          also accepts it; Git Bash (MinGW) mktemp accepts it too but the
    #          -d flag placement matters.
    # Args:    none
    # Returns: writes the path of the created directory to stdout.
    # Exits:   non-zero if the directory cannot be created.
    mktemp -d 2>/dev/null || mktemp -d -t hmi_deploy
}

# ---------------------------------------------------------------------------
# SECTION 4 — TEMP DIRECTORY AND CLEANUP
# ---------------------------------------------------------------------------

setup_temp_dir() {
    # Purpose: create the private working directory used for this run.
    #          All intermediate files (staged bundle, sha256 sidecar, SSH
    #          ControlMaster socket, extracted-manifest copy) live here.
    #          The directory is deleted via cleanup() on every exit path.
    # Args:    none
    # Returns: sets global TMPWORK and SSH_CTL_SOCKET.
    # Exits:   1 if the directory cannot be created.
    TMPWORK="$(mktemp_dir)"
    # ControlMaster socket: OpenSSH requires the path to be short (< 104 chars
    # on some systems) and MUST NOT contain spaces (Git Bash concern).
    SSH_CTL_SOCKET="${TMPWORK}/ssh_ctl.sock"
    log_verbose "Working directory: ${TMPWORK}"
    log_verbose "SSH ControlMaster socket: ${SSH_CTL_SOCKET}"
}

cleanup() {
    # Purpose: unconditional cleanup handler registered with trap.
    #          Closes the SSH ControlMaster connection if one was opened,
    #          then removes the temp working directory.
    # Args:    none
    # Returns: 0 (errors are suppressed so the original exit code is preserved).
    # Side effects: closes the SSH master connection; deletes TMPWORK.
    if [[ -S "${SSH_CTL_SOCKET:-}" ]]; then
        # Request a graceful master exit; ignore errors (target may be gone).
        ssh_ctl -O exit 2>/dev/null || true
    fi
    if [[ -n "${TMPWORK:-}" && -d "${TMPWORK}" ]]; then
        rm -rf -- "${TMPWORK}"
    fi
}

# Register cleanup for all exit paths: normal exit, signals, and errexit.
trap cleanup EXIT INT TERM HUP

# ---------------------------------------------------------------------------
# SECTION 5 — ARGUMENT PARSING
# ---------------------------------------------------------------------------

# Option variables — defaults listed here; overridden by flag parsing below.
OPT_ACTION="deploy"     # primary action (deploy|rollback|list|status|logs|check)
OPT_HOST=""             # -H/--host (required for all network actions)
OPT_USER="root"         # -u/--user
OPT_PORT="22"           # -p/--port
OPT_IDENTITY=""         # -i/--identity (path to SSH private key, optional)
OPT_BUNDLE=""           # -b/--bundle (directory or .tar.gz, required for deploy)
OPT_NAME_OVERRIDE=""    # --name (overrides manifest name)
OPT_NO_RESTART=0        # --no-restart: skip hmi-gui restart after install
OPT_KEEP=""             # --keep <n>: number of generations to retain
OPT_DRY_RUN=0           # --dry-run: print commands, do not execute
OPT_INSECURE=0          # --insecure: skip host-key verification (with warning)
OPT_VERBOSE=0           # -v/--verbose: emit debug messages and raw target output

usage() {
    # Purpose: print the command synopsis and exit with the given code.
    # Args:    $1 — exit code (default 0).
    # Returns: does not return (exits).
    local code="${1:-0}"
    printf 'deploy_to_hmi.sh %s

' "${SCRIPT_VERSION}"
    cat <<'EOF'
Usage: deploy_to_hmi.sh [ACTION] -H HOST [OPTIONS] [-b BUNDLE]

ACTIONS (default: deploy)
  deploy     Validate, package, upload and install a BYOA bundle.
  rollback   Revert to the previous installed generation on the target.
  list       List installed applications and available generations.
  status     Show the name and generation of the currently running application.
  logs       Tail hmi-gui and hmi-hwd journal entries (Ctrl-C to stop).
  check      Verify target readiness and print a readiness report.

CONNECTION FLAGS (required for all network actions)
  -H, --host HOST       Target hostname or IP address.
  -u, --user USER       SSH login user (default: root).
  -p, --port PORT       SSH port (default: 22).
  -i, --identity FILE   Path to the SSH private key file.
      --insecure        Disable StrictHostKeyChecking.  WARNING: MITM risk.
                        Uses a throwaway known_hosts file for this run only.

BUNDLE FLAGS (deploy only)
  -b, --bundle PATH     Path to the application bundle.  Either a directory
                        containing manifest.json, or a .tar.gz archive.
      --name NAME       Override the application name from manifest.json.
      --no-restart      Do not restart hmi-gui after successful installation.
      --keep N          Retain the N most recent generations; prune older ones.

GENERAL FLAGS
      --dry-run         Print every command that would be run; do not execute.
  -v, --verbose         Enable debug output; pass raw target stdout through.
  -h, --help            Show this help text and exit.

EXIT CODES
  0  Success.
  1  Local validation, packaging or usage error.
  4  Deployed and running, but not made the boot default.  The release was
     verified and deliberately left live; it will not start after a reboot
     until `systemctl enable hmi-gui.service` is run on the panel.
  *  Any other code is passed through from hmi-install on the target.

EXAMPLES
  # First deployment
  deploy_to_hmi.sh -H 192.168.1.50 -b ./myapp

  # Iterate and redeploy
  deploy_to_hmi.sh -H 192.168.1.50 -b ./myapp --keep 3

  # Emergency rollback
  deploy_to_hmi.sh rollback -H 192.168.1.50

  # Check target readiness
  deploy_to_hmi.sh check -H 192.168.1.50
EOF
    exit "${code}"
}

parse_args() {
    # Purpose: parse command-line arguments into option variables.
    #          Handles both long (--flag) and short (-f) forms.  The first
    #          non-flag token that matches a known action name is taken as the
    #          action; subsequent non-flag tokens are errors.
    # Args:    $@ — the raw command-line arguments.
    # Returns: populates OPT_* globals; calls die() on unrecognised tokens.
    # Exits:   1 on parse error; 0 via usage() on --help.

    local positional_seen=0   # guard against multiple positional arguments

    while [[ $# -gt 0 ]]; do
        case "$1" in
            deploy|rollback|list|status|logs|check)
                if [[ "${positional_seen}" -eq 1 ]]; then
                    die 1 "Unexpected positional argument: $1"
                fi
                OPT_ACTION="$1"
                positional_seen=1
                ;;
            -H|--host)
                [[ $# -ge 2 ]] || die 1 "Flag $1 requires an argument."
                OPT_HOST="$2"; shift
                ;;
            --host=*)
                OPT_HOST="${1#--host=}"
                ;;
            -u|--user)
                [[ $# -ge 2 ]] || die 1 "Flag $1 requires an argument."
                OPT_USER="$2"; shift
                ;;
            --user=*)
                OPT_USER="${1#--user=}"
                ;;
            -p|--port)
                [[ $# -ge 2 ]] || die 1 "Flag $1 requires an argument."
                OPT_PORT="$2"; shift
                ;;
            --port=*)
                OPT_PORT="${1#--port=}"
                ;;
            -i|--identity)
                [[ $# -ge 2 ]] || die 1 "Flag $1 requires an argument."
                OPT_IDENTITY="$2"; shift
                ;;
            --identity=*)
                OPT_IDENTITY="${1#--identity=}"
                ;;
            -b|--bundle)
                [[ $# -ge 2 ]] || die 1 "Flag $1 requires an argument."
                OPT_BUNDLE="$2"; shift
                ;;
            --bundle=*)
                OPT_BUNDLE="${1#--bundle=}"
                ;;
            --name)
                [[ $# -ge 2 ]] || die 1 "Flag $1 requires an argument."
                OPT_NAME_OVERRIDE="$2"; shift
                ;;
            --name=*)
                OPT_NAME_OVERRIDE="${1#--name=}"
                ;;
            --no-restart)
                OPT_NO_RESTART=1
                ;;
            --keep)
                [[ $# -ge 2 ]] || die 1 "Flag $1 requires an argument."
                OPT_KEEP="$2"; shift
                ;;
            --keep=*)
                OPT_KEEP="${1#--keep=}"
                ;;
            --dry-run)
                OPT_DRY_RUN=1
                ;;
            --insecure)
                OPT_INSECURE=1
                ;;
            -v|--verbose)
                OPT_VERBOSE=1
                ;;
            -h|--help)
                usage 0
                ;;
            -*)
                die 1 "Unknown flag: $1.  Run '$SCRIPT_NAME --help' for usage."
                ;;
            *)
                # Any other positional argument is unexpected.
                die 1 "Unexpected argument: $1.  Run '$SCRIPT_NAME --help' for usage."
                ;;
        esac
        shift
    done
}

validate_common_opts() {
    # Purpose: enforce that mandatory options are present and that numeric
    #          options are well-formed.  Called after parse_args().
    # Args:    none
    # Returns: 0 on success; calls die() on validation failure.
    # Exits:   1 on any violation.

    # --host is required for all actions except --help (already handled).
    if [[ -z "${OPT_HOST}" ]]; then
        die 1 "Flag --host (-H) is required.  Run '$SCRIPT_NAME --help' for usage."
    fi

    # --port must be a positive integer in 1–65535.
    if ! [[ "${OPT_PORT}" =~ ^[0-9]+$ ]] || \
       [[ "${OPT_PORT}" -lt 1 || "${OPT_PORT}" -gt 65535 ]]; then
        die 1 "Invalid port value '${OPT_PORT}': must be an integer in 1–65535."
    fi

    # --keep must be a positive integer when supplied.
    if [[ -n "${OPT_KEEP}" ]]; then
        if ! [[ "${OPT_KEEP}" =~ ^[0-9]+$ ]] || [[ "${OPT_KEEP}" -lt 1 ]]; then
            die 1 "Invalid --keep value '${OPT_KEEP}': must be a positive integer."
        fi
    fi

    # --identity file must exist and be readable when supplied.
    if [[ -n "${OPT_IDENTITY}" && ! -f "${OPT_IDENTITY}" ]]; then
        die 1 "Identity file not found: ${OPT_IDENTITY}"
    fi

    # --insecure deserves a loud warning: the operator is knowingly accepting
    # a man-in-the-middle risk.
    if [[ "${OPT_INSECURE}" -eq 1 ]]; then
        log_warn "--------------------------------------------------------------"
        log_warn "--insecure: StrictHostKeyChecking disabled.  A throwaway"
        log_warn "known_hosts file will be used.  Susceptible to MITM attacks."
        log_warn "Use only on isolated lab networks — NEVER in production."
        log_warn "--------------------------------------------------------------"
    fi
}

# ---------------------------------------------------------------------------
# SECTION 6 — SSH / TRANSPORT HELPERS
# ---------------------------------------------------------------------------

_ssh_base_args() {
    # Purpose: build the ssh argument array that is shared by every ssh and scp
    #          invocation in this script.  ControlMaster=auto causes the first
    #          call to open the master; subsequent calls reuse it — the user is
    #          only prompted for credentials once.
    # Args:    none
    # Returns: writes space-separated ssh flags to stdout.  Caller should use
    #          eval or read into an array.
    # Side effects: references global SSH_CTL_SOCKET, OPT_PORT, OPT_USER,
    #               OPT_IDENTITY, OPT_INSECURE, TMPWORK.
    local -a args=(
        -o "ControlMaster=auto"
        -o "ControlPath=${SSH_CTL_SOCKET}"
        -o "ControlPersist=60s"
        -o "BatchMode=no"
        -o "ConnectTimeout=15"
        -p "${OPT_PORT}"
    )

    if [[ -n "${OPT_IDENTITY}" ]]; then
        args+=(-i "${OPT_IDENTITY}")
    fi

    if [[ "${OPT_INSECURE}" -eq 1 ]]; then
        # Use a throwaway empty known_hosts so we never pollute the user's
        # real ~/.ssh/known_hosts with an untrusted key.
        local fake_kh="${TMPWORK}/known_hosts_throwaway"
        touch "${fake_kh}"
        args+=(
            -o "StrictHostKeyChecking=no"
            -o "UserKnownHostsFile=${fake_kh}"
        )
    fi

    # Print each argument token on its own line so the caller can read it
    # into an array safely (spaces in paths are preserved).
    printf '%s\n' "${args[@]}"
}

# Shared SSH argument array; populated by build_ssh_args() once the temp dir
# exists and options are parsed.
SSH_ARGS=()  # SSH base arguments shared across all ssh/scp calls

build_ssh_args() {
    # Purpose: populate the global SSH_ARGS array from _ssh_base_args().
    #          Must be called after setup_temp_dir() and parse_args().
    # Args:    none
    # Returns: sets SSH_ARGS global.
    local line
    while IFS= read -r line; do
        SSH_ARGS+=("${line}")
    done < <(_ssh_base_args)
}

_remote_target() {
    # Purpose: return the SSH user@host string for the current run.
    # Args:    none
    # Returns: writes "user@host" to stdout.
    printf '%s@%s' "${OPT_USER}" "${OPT_HOST}"
}

ssh_run() {
    # Purpose: run a command on the remote target over the ControlMaster
    #          connection.  In --dry-run mode, prints the command instead.
    # Args:    $@ — the remote command tokens (passed as a single quoted arg
    #               or as individual tokens joined by the shell).
    # Returns: exit status of the remote command, or 0 in dry-run mode.
    # Exits:   propagates remote exit status.
    local -a cmd=(ssh "${SSH_ARGS[@]}" "$(_remote_target)" "$@")
    if [[ "${OPT_DRY_RUN}" -eq 1 ]]; then
        printf '%s[DRY-RUN]%s ssh %s@%s %s\n' \
            "${C_YELLOW}" "${C_RESET}" \
            "${OPT_USER}" "${OPT_HOST}" \
            "$*"
        return 0
    fi
    log_verbose "ssh_run: ${cmd[*]}"
    "${cmd[@]}"
}

ssh_ctl() {
    # Purpose: send a ControlMaster control command (-O flag) to manage the
    #          master connection (check, exit, stop).
    # Args:    $@ — passed verbatim to ssh -O (e.g. "exit", "check").
    # Returns: exit status of the ssh control command.
    # Side effects: may close the master connection.
    ssh "${SSH_ARGS[@]}" -O "$@" "$(_remote_target)" 2>/dev/null
}

scp_to_remote() {
    # Purpose: copy a local file to a path on the remote target using the
    #          existing ControlMaster connection so no second authentication
    #          prompt is issued.
    # Args:    $1 — local source path.
    #          $2 — remote destination path (absolute).
    # Returns: 0 on success; scp exit status on failure.
    # Exits:   scp exit status (non-zero on transfer error).
    local src="$1"
    local dst="$2"
    # scp uses -P (uppercase) for the port; otherwise inherits ControlMaster.
    local -a cmd=(
        scp
        -P "${OPT_PORT}"
        -o "ControlMaster=auto"
        -o "ControlPath=${SSH_CTL_SOCKET}"
    )
    if [[ -n "${OPT_IDENTITY}" ]]; then
        cmd+=(-i "${OPT_IDENTITY}")
    fi
    if [[ "${OPT_INSECURE}" -eq 1 ]]; then
        local fake_kh="${TMPWORK}/known_hosts_throwaway"
        cmd+=(
            -o "StrictHostKeyChecking=no"
            -o "UserKnownHostsFile=${fake_kh}"
        )
    fi
    cmd+=("${src}" "$(_remote_target):${dst}")

    if [[ "${OPT_DRY_RUN}" -eq 1 ]]; then
        printf '%s[DRY-RUN]%s scp %s -> %s:%s\n' \
            "${C_YELLOW}" "${C_RESET}" \
            "${src}" "$(_remote_target)" "${dst}"
        return 0
    fi
    log_verbose "scp_to_remote: ${cmd[*]}"
    "${cmd[@]}"
}

open_master_connection() {
    # Purpose: open the SSH ControlMaster connection that will be reused for
    #          all subsequent ssh_run() and scp_to_remote() calls.  The -N
    #          flag means no command is executed on the remote side; -f puts
    #          the master in the background.  We check for an already-open
    #          socket first so this is safe to call multiple times.
    # Args:    none
    # Returns: 0 on success; calls die() on connection failure.
    # Exits:   1 on SSH failure.
    # Side effects: establishes a background SSH process writing to SSH_CTL_SOCKET.

    if [[ "${OPT_DRY_RUN}" -eq 1 ]]; then
        printf '%s[DRY-RUN]%s Open SSH ControlMaster to %s@%s:%s\n' \
            "${C_YELLOW}" "${C_RESET}" \
            "${OPT_USER}" "${OPT_HOST}" "${OPT_PORT}"
        return 0
    fi

    # If a socket already exists and the master is alive, reuse it.
    if [[ -S "${SSH_CTL_SOCKET}" ]]; then
        if ssh_ctl check 2>/dev/null; then
            log_verbose "Reusing existing ControlMaster socket."
            return 0
        fi
    fi

    log_step "Opening SSH connection to ${OPT_USER}@${OPT_HOST}:${OPT_PORT}"
    ssh "${SSH_ARGS[@]}" -fN "$(_remote_target)" \
        || die 1 "Cannot connect to ${OPT_HOST}:${OPT_PORT} as ${OPT_USER}."
    log_ok "SSH connection established."
}

# ---------------------------------------------------------------------------
# SECTION 7 — BUNDLE VALIDATION  (CONTRACT section 4)
# ---------------------------------------------------------------------------

MANIFEST_NAME=""    # app name extracted from manifest.json
MANIFEST_VERSION="" # app version extracted from manifest.json
MANIFEST_ENTRY=""   # app entry file path extracted from manifest.json
MANIFEST_SCHEMA=""  # schema version extracted from manifest.json

validate_bundle_dir() {
    # Purpose: validate a directory-form bundle against CONTRACT section 4 by
    #          calling the single shared implementation in schema/manifest.py,
    #          then extract the MANIFEST_* globals the rest of this script
    #          needs.
    #
    #          The rules used to be reimplemented here in bash + python
    #          one-liners.  That third copy disagreed with the other two in
    #          both directions -- it demanded a 'version' the desktop tool
    #          never checked, and ignored the 'runtime'/'entry' agreement that
    #          CONTRACT 4.1 requires everywhere -- so whether a bundle deployed
    #          depended on which tool you reached for.
    #
    # Args:    $1 — path to the bundle directory.
    # Returns: populates MANIFEST_* globals; calls die() on any violation.
    # Exits:   1 on any validation failure.

    local bdir="$1"

    [[ -d "${bdir}" ]]         || die 1 "Bundle path is not a directory: ${bdir}"

    # Run the shared validator.  Its stdout is either "OK" or one error per
    # line, so the whole report reaches the user rather than the first problem.
    local report=""
    local rc=0
    report="$(python3 "${SCHEMA_VALIDATOR}" "${bdir}" 2>&1)" || rc=$?
    if [[ "${rc}" -ne 0 ]]; then
        log_error "Bundle validation failed for ${bdir}:"
        printf '%s
' "${report}" >&2
        exit 1
    fi

    # Pull the fields this script uses for naming and reporting.  Safe now:
    # the validator has already confirmed each is present and well-formed.
    local fields
    fields="$(python3 -c "
import json, sys
with open(sys.argv[1] + '/manifest.json') as f:
    m = json.load(f)
print(m['name'])
print(m['version'])
print(m['entry'])
print(m['schema'])
" "${bdir}")" || die 1 "Could not read manifest fields from ${bdir}"

    MANIFEST_NAME="$(printf '%s
' "${fields}" | sed -n '1p')"
    MANIFEST_VERSION="$(printf '%s
' "${fields}" | sed -n '2p')"
    MANIFEST_ENTRY="$(printf '%s
' "${fields}" | sed -n '3p')"
    MANIFEST_SCHEMA="$(printf '%s
' "${fields}" | sed -n '4p')"

    # Size advisory.  `du -sb` is GNU-only; BSD/macOS du has no -b, so fall
    # back to summing the file sizes with find+awk rather than silently
    # skipping the check on the platforms this script claims to support.
    local bundle_bytes
    if bundle_bytes="$(du -sb "${bdir}" 2>/dev/null | awk '{print $1}')"        && [[ -n "${bundle_bytes}" ]]; then
        :
    else
        bundle_bytes="$(find "${bdir}" -type f -exec wc -c {} + 2>/dev/null             | awk '{ total += $1 } END { print total + 0 }')"
    fi
    if [[ "${bundle_bytes:-0}" -gt "${BUNDLE_WARN_BYTES}" ]]; then
        log_warn "Bundle size is $(( bundle_bytes / 1048576 )) MiB, which exceeds the advisory limit of $(( BUNDLE_WARN_BYTES / 1048576 )) MiB. Consider splitting large assets."
    fi

    log_ok "Bundle validated: name=${MANIFEST_NAME}, version=${MANIFEST_VERSION}, entry=${MANIFEST_ENTRY}, schema=${MANIFEST_SCHEMA}"
}

validate_bundle_archive() {
    # Purpose: validate a .tar.gz bundle archive by extracting it into a
    #          temporary subdirectory and delegating to validate_bundle_dir().
    # Args:    $1 — path to the .tar.gz archive.
    # Returns: populates MANIFEST_* globals (via validate_bundle_dir);
    #          writes the extraction directory path to stdout.
    # Exits:   1 on any validation failure.

    local archive="$1"

    [[ -f "${archive}" ]] \
        || die 1 "Bundle archive not found: ${archive}"

    local extract_dir="${TMPWORK}/bundle_extracted"
    mkdir -p "${extract_dir}"

    tar --extract --gzip --file="${archive}" --directory="${extract_dir}" \
        2>/dev/null \
        || die 1 "Cannot extract bundle archive: ${archive}"

    # The archive may have a top-level directory or may be flat; detect which.
    local top_count
    top_count="$(find "${extract_dir}" -mindepth 1 -maxdepth 1 | wc -l)"
    if [[ "${top_count}" -eq 1 ]]; then
        local top_entry
        top_entry="$(find "${extract_dir}" -mindepth 1 -maxdepth 1)"
        if [[ -d "${top_entry}" ]]; then
            # Archive wraps a single top-level directory; use it as bundle root.
            extract_dir="${top_entry}"
        fi
    fi

    validate_bundle_dir "${extract_dir}"
    printf '%s\n' "${extract_dir}"
}

# ---------------------------------------------------------------------------
# SECTION 8 — BUNDLE PACKAGING  (CONTRACT section 6)
# ---------------------------------------------------------------------------

package_bundle() {
    # Purpose: build the bundle tarball and its SHA-256 sidecar by calling the
    #          shared packer in schema/bundle.py -- the same code the desktop
    #          tool uses, so both produce byte-identical archives from the same
    #          directory and the digest the target verifies does not depend on
    #          which tool built it.
    #
    #          That sharing is the point. Build outputs, caches, VCS metadata
    #          and anything listed in the bundle's .hmiignore are excluded;
    #          this script used to tar the directory as it found it, so the
    #          README's "left out of the bundle automatically" was true of the
    #          GUI and false here, and a CLI deploy shipped .git/ and build/
    #          over a field link into panel flash.
    #
    # Args:    $1 - validated bundle directory path.
    # Returns: writes <tarball_path> to stdout.
    # Exits:   1 if packing fails (oversized bundle, unreadable file).
    # Side effects: creates files under TMPWORK.

    local bdir="$1"

    log_step "Packaging bundle"

    local tarball=""
    local rc=0
    tarball="$(python3 "${SCHEMA_PACKER}" pack "${bdir}" "${TMPWORK}")" || rc=$?
    if [[ "${rc}" -ne 0 || -z "${tarball}" ]]; then
        die 1 "Could not package ${bdir}."
    fi

    local digest_only
    digest_only="$(awk '{print $1}' "${tarball}.sha256")"

    log_ok "Tarball: ${tarball}"
    log_ok "SHA-256: ${digest_only}"
    printf '%s
' "${tarball}"
}

# ---------------------------------------------------------------------------
# SECTION 9 — PROGRESS RENDERING  (CONTRACT section 6)
# ---------------------------------------------------------------------------

render_installer_output() {
    # Purpose: read the installer's stdout line by line, rendering STEP tags
    #          as visual progress banners while always passing through every
    #          raw line in --verbose mode.  Non-STEP lines are printed as-is.
    #          STEP tag format (target/README.md section 2, as emitted by
    #          hmi-install's step()): "STEP <tag> <ok|fail> [detail]".
    #
    #          This used to match "STEP <n>/<total> <desc>", a numbered form
    #          the installer has never emitted.  Every STEP line therefore fell
    #          through to the raw branch: nothing was ever rendered as a
    #          banner, and a failing step scrolled past uncoloured, reading
    #          exactly like the successes around it.  The step that made that
    #          matter is enable-boot, whose failure leaves an application that
    #          runs now and is gone after the next power cycle.
    # Args:    stdin - the remote installer's stdout stream.
    # Returns: 0 (line-processing; exit status comes from the calling context).
    # Side effects: writes formatted progress to stdout.

    local line step_tag step_status step_detail status_colour

    while IFS= read -r line; do
        if [[ "${line}" =~ ^STEP[[:space:]]+([^[:space:]]+)[[:space:]]+([^[:space:]]+)[[:space:]]*(.*) ]]; then
            step_tag="${BASH_REMATCH[1]}"
            step_status="${BASH_REMATCH[2]}"
            step_detail="${BASH_REMATCH[3]}"

            # A failing step is the one line in this stream the operator must
            # not miss, so it is the one line that gets red.
            if [[ "${step_status}" == "fail" ]]; then
                status_colour="${C_RED}"
            else
                status_colour="${C_GREEN}"
            fi

            printf '%s[%s]%s %s%s%s%s\n' \
                "${C_CYAN}${C_BOLD}" "${step_tag}" "${C_RESET}" \
                "${status_colour}" "${step_status}" "${C_RESET}" \
                "${step_detail:+ ${step_detail}}"

            # Always also pass the raw STEP line through in verbose mode.
            if [[ "${OPT_VERBOSE}" -eq 1 ]]; then
                printf '%s[RAW]%s %s\n' "${C_CYAN}" "${C_RESET}" "${line}"
            fi
        else
            # Non-STEP line: in verbose mode always print; otherwise print too
            # (installer output is the ground truth for the user).
            printf '%s\n' "${line}"
        fi
    done
}

# ---------------------------------------------------------------------------
# SECTION 10 — DEPLOY ACTION  (CONTRACT section 6)
# ---------------------------------------------------------------------------

action_deploy() {
    # Purpose: implement the "deploy" action end-to-end:
    #            1. Validate the bundle (client-side, before any network I/O).
    #            2. Package it into a deterministic tarball with SHA-256 sidecar.
    #            3. Open the SSH ControlMaster connection (authenticates once).
    #            4. Create the remote staging directory (/tmp/hmi_upload, 0700).
    #            5. Upload the tarball and sidecar via scp.
    #            6. Invoke hmi-install on the target, streaming output live.
    #            7. Optionally pass --no-restart and --keep flags.
    #            8. Exit with the installer's exit status.
    # Args:    none (uses OPT_* globals).
    # Returns: exits with hmi-install's exit status (CONTRACT section 6).
    # Exits:   1 on local validation/packaging failure; remote exit code otherwise.

    # ----- Local validation (before any network I/O) -----

    if [[ -z "${OPT_BUNDLE}" ]]; then
        die 1 "The deploy action requires --bundle (-b).  \
Run '$SCRIPT_NAME --help' for usage."
    fi

    local bundle_dir=""

    # Both helpers below call die on failure, and die's exit only ends the
    # command substitution's subshell -- the parent shell reads an empty result
    # and carries on. That is how a bundle that failed to pack still opened the
    # SSH connection, scp'd "" to the panel, and ran the remote installer with
    # an empty argument: the error was printed, then contradicted by four steps
    # of apparent progress. Every substitution here has to re-raise it.
    if [[ "${OPT_BUNDLE}" == *.tar.gz || "${OPT_BUNDLE}" == *.tgz ]]; then
        log_step "Validating bundle archive: ${OPT_BUNDLE}"
        bundle_dir="$(validate_bundle_archive "${OPT_BUNDLE}")" \
            || die 1 "Could not unpack or validate ${OPT_BUNDLE}."
    elif [[ -d "${OPT_BUNDLE}" ]]; then
        log_step "Validating bundle directory: ${OPT_BUNDLE}"
        validate_bundle_dir "${OPT_BUNDLE}"
        bundle_dir="$(realpath_portable "${OPT_BUNDLE}")"
    else
        die 1 "Bundle path '${OPT_BUNDLE}' is neither a directory nor a .tar.gz archive."
    fi

    # ----- Packaging -----

    local tarball
    tarball="$(package_bundle "${bundle_dir}")" \
        || die 1 "Could not package ${bundle_dir}."
    [[ -n "${tarball}" ]] || die 1 "Packaging produced no tarball for ${bundle_dir}."
    local sidecar="${tarball}.sha256"

    # ----- Transport -----

    open_master_connection

    local remote_tarball remote_sidecar
    remote_tarball="${REMOTE_UPLOAD_DIR}/$(basename "${tarball}")"
    remote_sidecar="${REMOTE_UPLOAD_DIR}/$(basename "${sidecar}")"

    log_step "Preparing remote staging directory"
    ssh_run "mkdir -p '${REMOTE_UPLOAD_DIR}' && chmod 0700 '${REMOTE_UPLOAD_DIR}'"

    log_step "Uploading $(basename "${tarball}")"
    scp_to_remote "${tarball}" "${remote_tarball}"

    log_step "Uploading SHA-256 sidecar"
    scp_to_remote "${sidecar}" "${remote_sidecar}"

    # ----- Remote install -----

    # Build the hmi-install command line.
    local -a install_cmd=("${REMOTE_INSTALLER}" install "${remote_tarball}")
    [[ "${OPT_NO_RESTART}" -eq 1 ]] && install_cmd+=(--no-restart)
    [[ -n "${OPT_KEEP}" ]]          && install_cmd+=(--keep "${OPT_KEEP}")
    [[ -n "${OPT_NAME_OVERRIDE}" ]] && install_cmd+=(--name "${OPT_NAME_OVERRIDE}")

    log_step "Installing on target: ${install_cmd[*]}"

    if [[ "${OPT_DRY_RUN}" -eq 1 ]]; then
        printf '%s[DRY-RUN]%s Remote: %s\n' \
            "${C_YELLOW}" "${C_RESET}" "${install_cmd[*]}"
        return 0
    fi

    # Stream installer output live; parse STEP tags for progress display.
    # We capture the exit status from ssh (which propagates the remote exit code).
    local install_rc=0
    ssh "${SSH_ARGS[@]}" "$(_remote_target)" "${install_cmd[@]}" \
        | render_installer_output \
        || install_rc=${PIPESTATUS[0]}

    return "${install_rc}"
}

# ---------------------------------------------------------------------------
# SECTION 11 — ROLLBACK ACTION
# ---------------------------------------------------------------------------

action_rollback() {
    # Purpose: revert the target to its previous installed generation by
    #          invoking `hmi-install rollback` over the SSH ControlMaster
    #          connection.  The installer handles the atomic swap and service
    #          restart on the target side.
    # Args:    none (uses OPT_* globals).
    # Returns: exits with hmi-install's exit status.
    # Exits:   hmi-install exit code.

    open_master_connection
    log_step "Rolling back to previous generation on ${OPT_HOST}"
    local rc=0
    ssh_run "${REMOTE_INSTALLER}" rollback || rc=$?
    return "${rc}"
}

# ---------------------------------------------------------------------------
# SECTION 12 — LIST ACTION
# ---------------------------------------------------------------------------

action_list() {
    # Purpose: list all installed applications and available generations by
    #          invoking `hmi-install list` on the target and printing its output.
    # Args:    none (uses OPT_* globals).
    # Returns: exits with hmi-install's exit status.
    # Exits:   hmi-install exit code.

    open_master_connection
    log_step "Listing installed applications on ${OPT_HOST}"
    local rc=0
    ssh_run "${REMOTE_INSTALLER}" list || rc=$?
    return "${rc}"
}

# ---------------------------------------------------------------------------
# SECTION 13 — STATUS ACTION
# ---------------------------------------------------------------------------

action_status() {
    # Purpose: show the name and active generation of the running application
    #          by invoking `hmi-install status` on the target.
    # Args:    none (uses OPT_* globals).
    # Returns: exits with hmi-install's exit status.
    # Exits:   hmi-install exit code.

    open_master_connection
    log_step "Querying status on ${OPT_HOST}"
    local rc=0
    ssh_run "${REMOTE_INSTALLER}" status || rc=$?
    return "${rc}"
}

# ---------------------------------------------------------------------------
# SECTION 14 — LOGS ACTION
# ---------------------------------------------------------------------------

action_logs() {
    # Purpose: tail the hmi-gui and hmi-hwd journal entries on the target
    #          by running `journalctl -u hmi-gui -u hmi-hwd -n <n> -f`
    #          over SSH.  Follows the log in real time until Ctrl-C.
    # Args:    none (uses OPT_* globals).
    # Returns: 0 on Ctrl-C (SIGINT); journalctl exit code otherwise.
    # Exits:   SIGINT from user is treated as a clean exit.

    open_master_connection
    log_step "Tailing journal logs on ${OPT_HOST} (Ctrl-C to stop)"

    # Build the unit flags from LOG_UNITS.
    local -a unit_flags=()
    for u in "${LOG_UNITS[@]}"; do
        unit_flags+=(-u "${u}")
    done

    if [[ "${OPT_DRY_RUN}" -eq 1 ]]; then
        printf '%s[DRY-RUN]%s journalctl %s -n %s -f\n' \
            "${C_YELLOW}" "${C_RESET}" \
            "${unit_flags[*]}" "${LOG_LINES}"
        return 0
    fi

    # Run journalctl over SSH; allow SIGINT to propagate cleanly.
    local rc=0
    ssh "${SSH_ARGS[@]}" "$(_remote_target)" \
        journalctl "${unit_flags[@]}" -n "${LOG_LINES}" -f \
        || rc=$?

    # Exit code 130 means interrupted by SIGINT; treat that as clean.
    [[ "${rc}" -eq 130 ]] && return 0
    return "${rc}"
}

# ---------------------------------------------------------------------------
# SECTION 15 — CHECK ACTION
# ---------------------------------------------------------------------------

action_check() {
    # Purpose: verify target readiness without deploying anything.
    #          Checks performed:
    #            1. TCP reachability of the SSH port.
    #            2. SSH login succeeds (sshd is accepting connections).
    #            3. hmi-install is present at REMOTE_INSTALLER and is executable.
    #            4. hmi-gui.service unit file exists.
    #            5. hmi-hwd.service unit file exists.
    #          Prints a short readiness table summarising all results.
    # Args:    none (uses OPT_* globals).
    # Returns: 0 if all checks pass; 1 if any check fails.
    # Exits:   1 if any check fails (allows scripting: deploy only if check ok).

    local all_ok=1   # set to 0 if any check fails; final exit code

    log_step "Checking target readiness: ${OPT_HOST}:${OPT_PORT}"

    # 1. TCP reachability — use bash's /dev/tcp if available, else nc.
    local tcp_ok=0
    if [[ "${OPT_DRY_RUN}" -eq 1 ]]; then
        printf '%s[DRY-RUN]%s Check TCP %s:%s\n' \
            "${C_YELLOW}" "${C_RESET}" "${OPT_HOST}" "${OPT_PORT}"
        tcp_ok=1
    else
        (echo > /dev/tcp/"${OPT_HOST}"/"${OPT_PORT}") 2>/dev/null \
            && tcp_ok=1 \
            || true
        if [[ "${tcp_ok}" -eq 0 ]] && command -v nc >/dev/null 2>&1; then
            nc -z -w5 "${OPT_HOST}" "${OPT_PORT}" 2>/dev/null && tcp_ok=1 || true
        fi
    fi

    _check_print "TCP port ${OPT_PORT} reachable" "${tcp_ok}"
    [[ "${tcp_ok}" -eq 0 ]] && all_ok=0

    # 2. SSH login.
    local ssh_ok=0
    if [[ "${OPT_DRY_RUN}" -eq 1 ]]; then
        printf '%s[DRY-RUN]%s Check SSH login %s@%s\n' \
            "${C_YELLOW}" "${C_RESET}" "${OPT_USER}" "${OPT_HOST}"
        ssh_ok=1
    elif [[ "${tcp_ok}" -eq 1 ]]; then
        open_master_connection 2>/dev/null && ssh_ok=1 || true
    fi

    _check_print "SSH login as ${OPT_USER}" "${ssh_ok}"
    [[ "${ssh_ok}" -eq 0 ]] && all_ok=0

    # 3–5. Remote checks (only if SSH is up).
    if [[ "${ssh_ok}" -eq 1 && "${OPT_DRY_RUN}" -eq 0 ]]; then
        local installer_ok=0 gui_unit_ok=0 hwd_unit_ok=0

        # Check installer executable.
        ssh_run "test -x '${REMOTE_INSTALLER}'" 2>/dev/null && installer_ok=1 || true
        _check_print "hmi-install at ${REMOTE_INSTALLER}" "${installer_ok}"
        [[ "${installer_ok}" -eq 0 ]] && all_ok=0

        # Check hmi-gui unit.
        ssh_run "systemctl cat hmi-gui.service >/dev/null 2>&1" 2>/dev/null \
            && gui_unit_ok=1 || true
        _check_print "hmi-gui.service unit" "${gui_unit_ok}"
        [[ "${gui_unit_ok}" -eq 0 ]] && all_ok=0

        # Check hmi-hwd unit.
        ssh_run "systemctl cat hmi-hwd.service >/dev/null 2>&1" 2>/dev/null \
            && hwd_unit_ok=1 || true
        _check_print "hmi-hwd.service unit" "${hwd_unit_ok}"
        [[ "${hwd_unit_ok}" -eq 0 ]] && all_ok=0
    elif [[ "${OPT_DRY_RUN}" -eq 1 ]]; then
        # Dry-run mode: print what we would check.
        printf '%s[DRY-RUN]%s Check hmi-install executable\n' \
            "${C_YELLOW}" "${C_RESET}"
        printf '%s[DRY-RUN]%s Check hmi-gui.service unit\n' \
            "${C_YELLOW}" "${C_RESET}"
        printf '%s[DRY-RUN]%s Check hmi-hwd.service unit\n' \
            "${C_YELLOW}" "${C_RESET}"
    fi

    if [[ "${all_ok}" -eq 1 ]]; then
        log_ok "Target is ready for deployment."
    else
        log_error "One or more readiness checks failed.  See above."
    fi

    return $(( 1 - all_ok ))
}

_check_print() {
    # Purpose: print a single line of the readiness report table.
    # Args:    $1 — check label (string).
    #          $2 — result: 1 = pass, 0 = fail.
    # Returns: 0
    local label="$1"
    local ok="$2"
    if [[ "${ok}" -eq 1 ]]; then
        printf '  %s[PASS]%s %s\n' "${C_GREEN}" "${C_RESET}" "${label}"
    else
        printf '  %s[FAIL]%s %s\n' "${C_RED}" "${C_RESET}" "${label}"
    fi
}

# ---------------------------------------------------------------------------
# SECTION 16 — SUMMARY FOOTER
# ---------------------------------------------------------------------------

print_summary() {
    # Purpose: print a one-line summary of the completed run.  Printed on every
    #          exit path (including failure) via the main function's trap or
    #          direct call before exit.
    # Args:    $1 — action name (string).
    #          $2 — release id / app name (string; empty for non-deploy actions).
    #          $3 — start epoch seconds (integer).
    #          $4 — exit code (integer).
    # Returns: 0
    local action="$1"
    local release_id="$2"
    local start_ts="$3"
    local exit_code="$4"

    local end_ts
    end_ts="$(date +%s 2>/dev/null || echo "${start_ts}")"
    local duration=$(( end_ts - start_ts ))

    local result_str result_colour
    if [[ "${exit_code}" -eq 0 ]]; then
        result_str="SUCCESS"
        result_colour="${C_GREEN}"
    elif [[ "${exit_code}" -eq "${EXIT_NOT_BOOT_DEFAULT}" ]]; then
        # hmi-install's exit 4: the release is installed, running and verified,
        # and was deliberately not rolled back.  Calling that FAILED would push
        # an operator toward undoing a deploy that is working; calling it
        # SUCCESS is how the panel came up blank the next morning with nothing
        # in the log to explain it.  It is its own outcome and reads as one.
        result_str="PARTIAL (exit ${exit_code}: running, not the boot default)"
        result_colour="${C_YELLOW}"
    else
        result_str="FAILED (exit ${exit_code})"
        result_colour="${C_RED}"
    fi

    local id_part=""
    [[ -n "${release_id}" ]] && id_part=" release=${release_id}"

    printf '\n%s--- %s%s action=%s duration=%ds result=%s%s ---%s\n' \
        "${result_colour}${C_BOLD}" \
        "${SCRIPT_NAME}" \
        "${id_part}" \
        "${action}" \
        "${duration}" \
        "${result_str}" \
        "${C_RESET}" \
        "${C_RESET}"
}

# ---------------------------------------------------------------------------
# SECTION 17 — MAIN ENTRY POINT
# ---------------------------------------------------------------------------

main() {
    # Purpose: orchestrate the full run — argument parsing, option validation,
    #          temp-dir setup, action dispatch, summary, and exit.
    # Args:    $@ — raw command-line arguments (forwarded from the shell).
    # Returns: exits with the action's exit code.
    # Exits:   1 on usage/validation errors; action exit code otherwise.

    # Record start time for the summary line.
    local start_ts
    start_ts="$(date +%s 2>/dev/null || echo 0)"

    # Platform detection must come first; other helpers depend on it.
    _detect_platform

    # Temp dir must be ready before SSH args are built.
    setup_temp_dir

    # Parse and validate flags.
    parse_args "$@"
    validate_common_opts

    # Build the SSH argument array now that OPT_* and TMPWORK are final.
    build_ssh_args

    local exit_code=0
    local release_id=""

    case "${OPT_ACTION}" in
        deploy)
            action_deploy   || exit_code=$?
            release_id="${OPT_NAME_OVERRIDE:-${MANIFEST_NAME}}-${MANIFEST_VERSION}"
            # The one outcome an operator can act on immediately and would
            # otherwise only discover at the next power cycle.  Says what to
            # run, on which host, rather than only that something went wrong.
            if [[ "${exit_code}" -eq "${EXIT_NOT_BOOT_DEFAULT}" ]]; then
                log_warn "The application is installed and running on ${OPT_HOST}, but it \
was NOT made the boot default and will not start after a reboot."
                log_warn "Run this on the panel to fix it: \
systemctl enable hmi-gui.service"
            fi
            ;;
        rollback)
            action_rollback || exit_code=$?
            ;;
        list)
            action_list     || exit_code=$?
            ;;
        status)
            action_status   || exit_code=$?
            ;;
        logs)
            action_logs     || exit_code=$?
            ;;
        check)
            action_check    || exit_code=$?
            ;;
        *)
            # Should not be reached: parse_args only accepts known actions.
            die 1 "Unknown action: ${OPT_ACTION}"
            ;;
    esac

    print_summary "${OPT_ACTION}" "${release_id}" "${start_ts}" "${exit_code}"
    exit "${exit_code}"
}

# ---------------------------------------------------------------------------
# ENTRY
# ---------------------------------------------------------------------------

main "$@"
