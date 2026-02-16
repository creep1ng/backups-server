"""Hook execution helpers for backup commands.

This module provides utilities to run configured shell commands for
backup_commands.pre and backup_commands.post hooks.

Functions
- run_command: execute a single shell command and return (rc, stdout, stderr)
- run_hooks: execute a list of commands for a given phase (pre/post)
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Dict, List, Tuple

DEFAULT_TIMEOUT_SECONDS = 300

logger = logging.getLogger(__name__)


def run_command(
    command: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    env: Dict[str, str] | None = None,
) -> Tuple[int, str, str]:
    """Execute a single shell command.

    The command is executed with ``shell=True`` because commands come from
    user configuration. stdout and stderr are captured and returned as
    decoded strings.

    Args:
        command: Shell command to execute.
        timeout: Timeout in seconds for the subprocess call. Defaults to
            ``DEFAULT_TIMEOUT_SECONDS``.

    Returns:
        A tuple of (return_code, stdout, stderr). On exception the return
        code will be -1 and stderr will contain the exception message.
    """
    try:
        logger.debug("Running command (shell): %s", command)
        env_vars = os.environ.copy()
        if env:
            env_vars.update(env)
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env_vars,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (
        subprocess.TimeoutExpired
    ) as exc:  # pragma: no cover - hard to trigger reliably
        # Include any captured output for diagnostics
        stdout = getattr(exc, "stdout", "") or ""
        stderr = getattr(exc, "stderr", "") or f"TimeoutExpired: {str(exc)}"
        logger.error("Command timed out after %s seconds: %s", timeout, command)
        logger.debug("Timeout stdout: %s", stdout)
        logger.debug("Timeout stderr: %s", stderr)
        return -1, stdout, stderr
    except subprocess.SubprocessError as exc:
        logger.exception("Subprocess failed while running command: %s", command)
        return -1, "", str(exc)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error running command: %s", command)
        return -1, "", str(exc)


def _apply_substitutions(command: str, substitutions: Dict[str, str] | None) -> str:
    if not substitutions:
        return command

    result = command
    for key, value in substitutions.items():
        placeholder = f"${{{key}}}"
        if placeholder in result:
            result = result.replace(placeholder, value)
    return result


def run_hooks(
    commands: List[str],
    phase: str,
    substitutions: Dict[str, str] | None = None,
    env: Dict[str, str] | None = None,
) -> bool:
    """Run a sequence of shell commands for a hook phase.

    This will execute commands sequentially and stop at the first
    failure (fail-fast). All command executions and outputs are logged for
    audit purposes.

    Args:
        commands: List of shell command strings to execute.
        phase: Either "pre" or "post" - used in log messages.

    Returns:
        True if all commands ran and returned exit code 0, False otherwise.

    Notes:
        - Never raises; exceptions are handled and result in a False return
          value so callers can continue or abort as appropriate.
    """
    if phase not in ("pre", "post"):
        logger.warning("run_hooks called with unexpected phase: %s", phase)

    if not commands:
        logger.debug("No %s-hook commands to run", phase)
        return True

    logger.info("Running %s-hook commands: count=%d", phase, len(commands))

    for idx, cmd in enumerate(commands, start=1):
        resolved_cmd = _apply_substitutions(cmd, substitutions)
        logger.info(
            "[%s-hook][%d/%d] Executing command: %s",
            phase,
            idx,
            len(commands),
            resolved_cmd,
        )
        rc, out, err = run_command(resolved_cmd, env=env)
        # Log outputs at debug level for audit/diagnostics
        if out:
            logger.debug("Command stdout (phase=%s): %s", phase, out)
        if err:
            logger.debug("Command stderr (phase=%s): %s", phase, err)

        if rc != 0:
            logger.error(
                "Command failed (exit=%d) during %s-hook: %s",
                rc,
                phase,
                cmd,
            )
            # Ensure we return False on first failure (fail-fast)
            return False

    logger.info("All %s-hook commands completed successfully", phase)
    return True
