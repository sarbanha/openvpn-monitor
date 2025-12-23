#!/usr/bin/env python3
import hashlib
import os
import subprocess
import fcntl
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

NC_HOST = "127.0.0.1"
NC_PORT = 38248
SERVICE = "openvpn-server@hd"

LOG_PATH = Path("/var/log/openvpn-monitor.log")
STATE_PATH = Path("/var/lib/openvpn-monitor/last_status_md5.txt")

# Seconds: keep conservative to avoid hanging if nc/systemctl blocks
CMD_TIMEOUT = 15
STATE_DIR_PERMS = 0o750
STATE_FILE_PERMS = 0o640
SEPARATOR_WIDTH = 80


class CommandResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


@contextmanager
def file_lock(path: Path):
    """Context manager for file locking to prevent race conditions."""
    lock_file = path.parent / f".{path.name}.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    with open(lock_file, 'w') as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def run_cmd(cmd: str, timeout: int = CMD_TIMEOUT) -> CommandResult:
    """
    Run a shell command and return CommandResult with returncode, stdout, stderr.
    """
    p = subprocess.run(
        cmd,
        shell=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return CommandResult(p.returncode, p.stdout, p.stderr)


def md5_hex(data: str) -> str:
    return hashlib.md5(data.encode("utf-8", errors="replace")).hexdigest()


def ensure_state_dir() -> None:
    # /var/lib is appropriate for state; create a dedicated directory.
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Restrictive permissions on directory and state file (best effort).
    try:
        os.chmod(STATE_PATH.parent, STATE_DIR_PERMS)
    except PermissionError:
        pass


def read_last_md5() -> Optional[str]:
    if not STATE_PATH.exists():
        return None

    with file_lock(STATE_PATH):
        try:
            return STATE_PATH.read_text(encoding="utf-8").strip()
        except Exception:
            # If state is unreadable for any reason, treat as no prior value.
            return None


def write_last_md5(value: str) -> None:
    with file_lock(STATE_PATH):
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(value + "\n", encoding="utf-8")
        os.replace(tmp, STATE_PATH)
        try:
            os.chmod(STATE_PATH, STATE_FILE_PERMS)
        except PermissionError:
            pass


def append_log(text: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def log_success(md5: str) -> None:
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    append_log(f"{ts} SUCCESS probe md5_changed md5={md5}")


def main() -> int:
    ensure_state_dir()

    # 1) Get current "status" output
    status_cmd = f"echo status | nc {NC_HOST} {NC_PORT}"
    status_result = run_cmd(status_cmd)

    # Compute md5 of stdout only (as requested: md5sum of the output)
    current_md5 = md5_hex(status_result.stdout)
    last_md5 = read_last_md5()

    # First run (no last_md5) - just store and exit
    if last_md5 is None:
        write_last_md5(current_md5)
        return 0

    # MD5 changed -> successful probe (one line)
    if current_md5 != last_md5:
        write_last_md5(current_md5)
        log_success(current_md5)
        return 0

    # MD5 unchanged -> full diagnostics + restart
    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    svc_status_cmd = f"systemctl status {SERVICE} --no-pager -l"
    load_stats_cmd = f"echo load-stats | nc {NC_HOST} {NC_PORT}"

    svc_result = run_cmd(svc_status_cmd)
    load_result = run_cmd(load_stats_cmd)

    # Build diagnostic block more efficiently
    block = []
    block.append("=" * SEPARATOR_WIDTH)
    block.append(f"Timestamp: {ts}")
    block.append(f"Condition: status MD5 unchanged (md5={current_md5})")
    block.append("")

    # Helper function to add command output
    def add_command_output(cmd: str, result: CommandResult):
        block.append(f"Command: {cmd}")
        block.append(f"Return code: {result.returncode}")
        if result.stderr.strip():
            block.append("STDERR:")
            block.append(result.stderr.rstrip("\n"))
        block.append("STDOUT:")
        block.append(result.stdout.rstrip("\n"))
        block.append("")

    add_command_output(svc_status_cmd, svc_result)
    add_command_output(load_stats_cmd, load_result)
    add_command_output(status_cmd, status_result)

    block.append(f"Action: systemctl restart {SERVICE}")

    restart_cmd = f"systemctl restart {SERVICE}"
    restart_result = run_cmd(restart_cmd)

    block.append(f"Restart return code: {restart_result.returncode}")
    if restart_result.stderr.strip():
        block.append("Restart STDERR:")
        block.append(restart_result.stderr.rstrip("\n"))
    if restart_result.stdout.strip():
        block.append("Restart STDOUT:")
        block.append(restart_result.stdout.rstrip("\n"))

    block.append("=" * SEPARATOR_WIDTH)
    block.append("")

    append_log("\n".join(block))

    # Update MD5 after restart
    write_last_md5(current_md5)

    return restart_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
