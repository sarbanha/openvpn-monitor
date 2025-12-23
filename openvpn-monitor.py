#!/usr/bin/env python3
import hashlib
import os
import subprocess
import fcntl
import smtplib
from contextlib import contextmanager
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import NamedTuple, Optional, List
from dotenv import load_dotenv

# Load .env file before reading configuration
load_dotenv()

# OpenVPN configuration
NC_HOST = os.getenv("OPENVPN_NC_HOST", "127.0.0.1")
NC_PORT = int(os.getenv("OPENVPN_NC_PORT", "7505"))
SERVICE = os.getenv("OPENVPN_SERVICE", "openvpn-server@myconfig")

LOG_PATH = Path("/var/log/openvpn-monitor.log")
STATE_PATH = Path("/var/lib/openvpn-monitor/last_status_md5.txt")

# Seconds: keep conservative to avoid hanging if nc/systemctl blocks
CMD_TIMEOUT = 15
STATE_DIR_PERMS = 0o750
STATE_FILE_PERMS = 0o640
SEPARATOR_WIDTH = 80

# Email configuration
SMTP_HOST = os.getenv("OPENVPN_SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("OPENVPN_SMTP_PORT", "25"))
SMTP_SECURITY = os.getenv("OPENVPN_SMTP_SECURITY", "none").lower()  # Options: none, starttls, tls
SMTP_USERNAME = os.getenv("OPENVPN_SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("OPENVPN_SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("OPENVPN_EMAIL_FROM", "openvpn-monitor@localhost")
EMAIL_TO = os.getenv("OPENVPN_EMAIL_TO", "").split(",")  # Comma-separated list
EMAIL_ENABLED = os.getenv("OPENVPN_EMAIL_ENABLED", "false").lower() == "true"


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


def send_email_alert(subject: str, body: str, recipients: List[str]) -> bool:
    """
    Send email alert to multiple administrators.
    Returns True if successful, False otherwise.
    """
    if not EMAIL_ENABLED:
        return False

    if not recipients or not any(r.strip() for r in recipients):
        append_log("Email alert skipped: No recipients configured")
        return False

    # Filter out empty recipients
    recipients = [r.strip() for r in recipients if r.strip()]

    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = ", ".join(recipients)
        msg['Subject'] = subject
        msg['Date'] = datetime.now(timezone.utc).astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")

        msg.attach(MIMEText(body, 'plain'))

        # Connect to SMTP server with proper security handling
        if SMTP_SECURITY == "tls":
            # Direct SSL/TLS connection (port 465)
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        elif SMTP_SECURITY == "starttls":
            # Plain connection with STARTTLS upgrade (port 587 or 25)
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            server.starttls()
        else:
            # Plain connection, no encryption (port 25, local servers)
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)

        # Login only if credentials provided AND server supports AUTH
        if SMTP_USERNAME and SMTP_PASSWORD:
            try:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            except smtplib.SMTPNotSupportedError:
                # Server doesn't support AUTH - continue without authentication
                append_log("Warning: SMTP server does not support authentication, sending without login")
            except smtplib.SMTPAuthenticationError as auth_err:
                append_log(f"Warning: SMTP authentication failed: {auth_err}, attempting to send anyway")

        # Send email
        server.sendmail(EMAIL_FROM, recipients, msg.as_string())
        server.quit()

        append_log(f"Email alert sent successfully to: {', '.join(recipients)}")
        return True

    except Exception as e:
        append_log(f"Failed to send email alert: {type(e).__name__}: {e}")
        return False


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

    diagnostic_text = "\n".join(block)
    append_log(diagnostic_text)

    # Send email alert to administrators
    hostname = os.uname().nodename
    email_subject = f"[ALERT] OpenVPN Service Failure on {hostname}"
    email_body = f"""OpenVPN Monitor has detected a service failure and initiated a restart.

Hostname: {hostname}
Service: {SERVICE}
Timestamp: {ts}
Condition: Status MD5 unchanged (service appears frozen)

Restart Action: systemctl restart {SERVICE}
Restart Result: Exit code {restart_result.returncode}

Full Diagnostic Details:
{diagnostic_text}

This is an automated alert from the OpenVPN monitoring system.
"""

    send_email_alert(email_subject, email_body, EMAIL_TO)

    # Update MD5 after restart
    write_last_md5(current_md5)

    return restart_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
