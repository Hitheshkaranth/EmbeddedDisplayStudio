"""
tests/test_step_rendering.py
Layer: Test (W11)

Pins the one thing deploy_to_hmi.sh does with the installer's output: turn
STEP lines into something an operator reads.

The bug these were written for: render_installer_output matched
"STEP <n>/<total> <desc>", a numbered progress format that hmi-install has
never emitted. The real grammar is "STEP <tag> <ok|fail> [detail]"
(target/README.md section 2). Every STEP line therefore missed the banner
branch and fell through to the raw pass-through -- so no step was ever
rendered as progress, and, worse, a failing step printed in the same plain
text as the successes on either side of it.

The step that made that cost something is enable-boot. Its failure means the
application is running now and will be gone after the next power cycle, and it
scrolled past between "restart-gui ok" and "deployment successful".

Requires bash; skipped elsewhere.
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_SH = REPO_ROOT / "deploy" / "deploy_to_hmi.sh"
INSTALLER = REPO_ROOT / "target" / "bin" / "hmi-install"

RED = "<<RED>>"
GREEN = "<<GREEN>>"


def _bash_can_read_lines():
    """Whether this bash hands `read` the lines it is given.

    Git Bash for Windows, spawned from a Windows process rather than from a
    shell, runs the script and prints its own output correctly but gives the
    `read` builtin a zero-length line for every line of input -- `cat` on the
    same input shows the text. render_installer_output is a read loop, so
    under that bash every assertion here would pass or fail for reasons that
    have nothing to do with the function. Detected rather than assumed: the
    suite runs on Windows, in WSL, and on the panel.
    """
    if shutil.which("bash") is None:
        return False
    probe = subprocess.run(
        ["bash", "-c", "while IFS= read -r l; do echo \"[$l]\"; done <<'EOT'\nxy\nEOT"],
        capture_output=True, text=True,
    )
    return probe.stdout.strip() == "[xy]"


CAN_READ = _bash_can_read_lines()


@unittest.skipUnless(CAN_READ, "needs a bash whose `read` receives its input")
class StepRendering(unittest.TestCase):
    """Drives render_installer_output on its own, with the colours made visible."""

    def _render(self, *lines, verbose=0):
        """Feed STEP lines through the real function and return what it printed.

        The function is lifted out of deploy_to_hmi.sh rather than sourced:
        the script runs main "$@" at the bottom, so sourcing it would execute a
        deployment. The colour globals are substituted with markers so an
        assertion can tell red from green without matching escape codes.

        The input is a here-document inside the driver rather than a pipe or a
        redirect from a temp file. Both of those are wrong on Windows for
        different reasons: `bash` on PATH there is WSL's, which cannot open a
        C:/ path, and a piped stdin arrives as a single empty line -- which
        would satisfy the returncode check and quietly assert nothing.
        """
        body = self._extract("render_installer_output", DEPLOY_SH)
        driver = "\n".join([
            "C_CYAN=''", "C_BOLD=''", "C_RESET=''",
            f"C_RED='{RED}'", f"C_GREEN='{GREEN}'",
            f"OPT_VERBOSE={verbose}",
            body,
            "render_installer_output <<'INSTALLER_STDOUT'",
            *lines,
            "INSTALLER_STDOUT",
        ])
        result = subprocess.run(
            ["bash", "-c", driver], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(
            result.stdout.strip(), "",
            "the function produced nothing; the harness is not feeding it input",
        )
        return result.stdout

    @staticmethod
    def _extract(name, path):
        """Return the source of one shell function, brace to closing brace."""
        text = path.read_text(encoding="utf-8")
        start = text.index(f"{name}() {{")
        end = text.index("\n}\n", start) + len("\n}\n")
        return text[start:end]

    # -- tests -----------------------------------------------------------

    def test_a_step_line_is_rendered_rather_than_passed_through(self):
        """The whole point of the function: STEP lines become progress.

        Under the numbered pattern this branch was unreachable, so the check is
        that the tag and status appear formatted -- not that the raw line
        survived, which it did all along.
        """
        out = self._render("STEP verify-sha256 ok deadbeef")
        self.assertIn("[verify-sha256]", out)
        self.assertNotIn("STEP verify-sha256", out)

    def test_a_failing_step_is_the_one_that_is_coloured_red(self):
        """A failure that reads like a success is the failure that gets missed."""
        out = self._render(
            "STEP restart-gui ok GUI ready after 3s",
            "STEP enable-boot fail could not enable hmi-gui.service",
        )
        self.assertIn(RED, out, "a failed step rendered in the same colour as the rest")
        self.assertIn(GREEN, out)
        red_line = next(ln for ln in out.splitlines() if RED in ln)
        self.assertIn("enable-boot", red_line)

    def test_the_detail_text_survives_rendering(self):
        """The detail is where enable-boot says what an operator has to do."""
        out = self._render(
            "STEP enable-boot fail could not enable hmi-gui.service; "
            "the app runs now but will NOT start after a reboot"
        )
        self.assertIn("will NOT start after a reboot", out)

    def test_a_step_line_with_no_detail_does_not_gain_a_trailing_space(self):
        """save-previous and rollback-start both emit an empty detail."""
        out = self._render("STEP rollback-start ok ").rstrip("\n")
        self.assertEqual(out, out.rstrip(), f"trailing whitespace in {out!r}")

    def test_a_non_step_line_is_still_passed_through_untouched(self):
        """Installer stdout is the ground truth; nothing may be swallowed."""
        out = self._render("plain installer chatter", "STEP prune ok removed 1")
        self.assertIn("plain installer chatter", out)

    def test_verbose_keeps_the_raw_line_as_well(self):
        """--verbose is what a bug report is built from."""
        out = self._render("STEP swap-symlink ok /opt/hmi_apps/releases/x", verbose=1)
        self.assertIn("[RAW]", out)
        self.assertIn("STEP swap-symlink ok", out)

    def test_the_renderer_matches_the_grammar_the_installer_emits(self):
        """The two files have to agree, and once did not.

        hmi-install's step() is the only producer of these lines. Reading its
        printf format keeps this honest if either side is reworded, instead of
        pinning a hand-copied sample that can drift with neither test failing.
        """
        installer = INSTALLER.read_text(encoding="utf-8")
        fmt = re.search(r"printf '(STEP[^']*)'", installer)
        self.assertIsNotNone(fmt, "hmi-install's step() no longer printf's a STEP line")
        self.assertEqual(
            fmt.group(1), "STEP %s %s %s\\n",
            "the installer's STEP format changed; render_installer_output must follow",
        )

        rendered = self._render("STEP install-complete ok deployment successful: /opt/x")
        self.assertIn("[install-complete]", rendered)
        self.assertIn("deployment successful: /opt/x", rendered)


if __name__ == "__main__":
    unittest.main()
