from __future__ import annotations

import subprocess
import time
from pathlib import Path

from ..models import CommandResult


def run_command(command: str, cwd: Path, timeout_seconds: int) -> CommandResult:
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        duration = time.time() - started
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            combined=f"$ {command}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}",
            duration_seconds=duration,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.time() - started
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(
            returncode=124,
            stdout=stdout,
            stderr=stderr,
            combined=f"$ {command}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}",
            duration_seconds=duration,
            timed_out=True,
        )
