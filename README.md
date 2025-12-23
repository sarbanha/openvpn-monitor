# OpenVPN Monitor

A monitoring script for OpenVPN that detects frozen/stuck services, automatically restarts them, and sends email notifications to administrators.

## Features

- **Status Monitoring**: MD5 hash comparison of OpenVPN status output
- **Automatic Recovery**: Restarts frozen services automatically
- **Email Alerts**: Multi-recipient notifications on failures
- **File Locking**: Prevents race conditions
- **.env Support**: Auto-loads configuration (no external dependencies)
- **Production Ready**: Type hints, robust error handling, comprehensive logging

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure** (optional) - Edit `.env`:
   ```bash
   # OpenVPN Settings
   OPENVPN_NC_HOST=127.0.0.1
   OPENVPN_NC_PORT=7505
   OPENVPN_SERVICE=openvpn-server@myconfig
   
   # Email Settings
   OPENVPN_EMAIL_ENABLED=true
   OPENVPN_SMTP_HOST=smtp.gmail.com
   OPENVPN_SMTP_PORT=587
   OPENVPN_SMTP_SECURITY=starttls
   OPENVPN_SMTP_USERNAME=your-email@gmail.com
   OPENVPN_SMTP_PASSWORD=your-app-password
   OPENVPN_EMAIL_FROM=monitor@yourdomain.com
   OPENVPN_EMAIL_TO=admin1@example.com,admin2@example.com
   ```

2. **Run**:
   ```bash
   python3 openvpn-monitor.py
   ```

## How It Works

1. Connects to OpenVPN management interface (`nc 127.0.0.1:7505`)
2. Calculates MD5 hash of status output
3. Compares with previous run's hash
4. If unchanged → service frozen:
   - Gathers diagnostics (systemctl status, load-stats)
   - Restarts service (`systemctl restart openvpn-server@myconfig`)
   - Sends email alerts (if enabled)
   - Logs everything to `/var/log/openvpn-monitor.log`

## Configuration

**Two methods** (Environment variables override `.env` file):

### Method 1: .env File (Recommended)

Edit `.env` in the script directory:
```bash
# OpenVPN Settings
OPENVPN_NC_HOST=127.0.0.1
OPENVPN_NC_PORT=7505
OPENVPN_SERVICE=openvpn-server@myconfig

# Email Settings
OPENVPN_EMAIL_ENABLED=true
OPENVPN_SMTP_HOST=smtp.gmail.com
OPENVPN_SMTP_PORT=587
OPENVPN_SMTP_SECURITY=starttls
OPENVPN_SMTP_USERNAME=your-email@gmail.com
OPENVPN_SMTP_PASSWORD=your-app-password
OPENVPN_EMAIL_FROM=monitor@yourdomain.com
OPENVPN_EMAIL_TO=admin@example.com,ops@example.com
```

### Method 2: Environment Variables

```bash
# OpenVPN Settings
export OPENVPN_NC_HOST=127.0.0.1
export OPENVPN_NC_PORT=38248
export OPENVPN_SERVICE=openvpn-server@myconfig

# Email Settings
export OPENVPN_EMAIL_ENABLED=true
export OPENVPN_SMTP_HOST=smtp.gmail.com
# ... (same email variables as .env)
python3 openvpn-monitor.py
```

### Configuration Variables

**OpenVPN Connection:**
- `OPENVPN_NC_HOST` - Management interface host (default: 127.0.0.1)
- `OPENVPN_NC_PORT` - Management interface port (default: 7505)
- `OPENVPN_SERVICE` - Systemd service name (default: openvpn-server@myconfig)

**Email Notification:**
- `OPENVPN_EMAIL_ENABLED` - Enable/disable emails (default: false)
- `OPENVPN_SMTP_HOST` - SMTP server (default: localhost)
- `OPENVPN_SMTP_PORT` - SMTP port (default: 25)
- `OPENVPN_SMTP_SECURITY` - Connection security: `none`, `starttls`, or `tls` (default: none)
- `OPENVPN_SMTP_USERNAME` - SMTP username (optional, only if server supports AUTH)
- `OPENVPN_SMTP_PASSWORD` - SMTP password (optional, only if server supports AUTH)
- `OPENVPN_EMAIL_FROM` - Sender address
- `OPENVPN_EMAIL_TO` - Comma-separated recipients

**Connection Security Options:**
- `none` - Plain connection, no encryption (port 25, local servers)
- `starttls` - Upgrade connection with STARTTLS (port 587 or 25)
- `tls` - Direct SSL/TLS connection (port 465)

**Note**: Authentication is automatically skipped if the SMTP server doesn't support it.

**Gmail** (STARTTLS on port 587, requires App Password):
```bash
OPENVPN_SMTP_HOST=smtp.gmail.com
OPENVPN_SMTP_PORT=587
OPENVPN_SMTP_SECURITY=starttls
```

**Office 365** (STARTTLS on port 587):
```bash
OPENVPN_SMTP_HOST=smtp.office365.com
OPENVPN_SMTP_PORT=587
OPENVPN_SMTP_SECURITY=starttls
```

**Local Server** (no encryption):
```bash
OPENVPN_SMTP_HOST=localhost
OPENVPN_SMTP_PORT=25
OPENVPN_SMTP_SECURITY=none
```

**Direct SSL/TLS** (port 465):
```bash
OPENVPN_SMTP_HOST=smtp.example.com
OPENVPN_SMTP_PORT=465
OPENVPN_SMTP_SECURITY=tls
```
OPENVPN_SMTP_SECURITY=tls
```

## Systemd Integration

### Quick Installation

Use the provided installation script:

```bash
sudo ./install-systemd.sh
```

This automatically:
- Copies service and timer files to `/etc/systemd/system/`
- Updates paths to match your installation directory
- Enables and starts the timer
- Configures monitoring to run every **10 seconds**

### Manual Installation

**Service** (`/etc/systemd/system/openvpn-monitor.service`):
```ini
[Unit]
Description=OpenVPN Monitor Service
After=network.target openvpn-server@myconfig.service

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/openvpn-monitor.py
WorkingDirectory=/path/to/OpenVPNMonitor
EnvironmentFile=/path/to/OpenVPNMonitor/.env
User=root
StandardOutput=journal
StandardError=journal
TimeoutStartSec=45s

[Install]
WantedBy=multi-user.target
```

**Timer** (`/etc/systemd/system/openvpn-monitor.timer`):
```ini
[Unit]
Description=Run OpenVPN Monitor every 10 seconds

[Timer]
OnBootSec=10s
OnUnitActiveSec=10s
AccuracySec=1s

[Install]
WantedBy=timers.target
```

**Manual Install**:
```bash
# Update paths in files, then:
sudo cp openvpn-monitor.service /etc/systemd/system/
sudo cp openvpn-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openvpn-monitor.timer
```

### Management

```bash
# Status
systemctl status openvpn-monitor.timer
systemctl list-timers openvpn-monitor.timer

# Logs
journalctl -u openvpn-monitor.service -f
tail -f /var/log/openvpn-monitor.log

# Control
sudo systemctl stop openvpn-monitor.timer
sudo systemctl start openvpn-monitor.timer
sudo systemctl disable openvpn-monitor.timer
```

## Email Alerts

**Subject**: `[ALERT] OpenVPN Service Failure on {hostname}`

**Body includes**:
- Hostname, service name, timestamp
- Condition (MD5 unchanged = frozen)
- Restart action and exit code
- Full diagnostics (systemctl status, load-stats, status output)

## Logs

Location: `/var/log/openvpn-monitor.log`

**Success**:
```
2025-12-23T10:30:45+00:00 SUCCESS probe md5_changed md5=abc123...
```

**Failure**:
```
================================================================================
Timestamp: 2025-12-23T10:30:45+00:00
Condition: status MD5 unchanged (md5=abc123...)
[... full diagnostics ...]
Action: systemctl restart openvpn-server@myconfig
Restart return code: 0
================================================================================
```

**View logs**:
```bash
tail -f /var/log/openvpn-monitor.log
```

## Security

- **Credentials**: Store in `.env` with `chmod 600 .env` (already in `.gitignore`)
- **Gmail**: Use App Passwords (not regular password)
- **TLS**: Always enable for remote SMTP servers
- **Permissions**: State directory (0o750), state file (0o640)

## Troubleshooting

### Email Not Sending

```bash
# Check configuration
echo $OPENVPN_EMAIL_ENABLED  # Should be: true
echo $OPENVPN_EMAIL_TO       # Should have recipients

# Check logs
tail -f /var/log/openvpn-monitor.log

# Test SMTP
telnet smtp.gmail.com 587
```

**Common Issues**:
- **Authentication failed** → Check credentials, use App Password for Gmail
- **Connection refused** → Verify SMTP host/port
- **TLS errors** → Ensure `SMTP_USE_TLS` matches server requirements
- **No recipients** → Check `EMAIL_TO` has valid addresses

### .env Not Loading

```bash
# Check file exists
ls -la .env

# Check syntax: KEY=VALUE, comments with #, quotes optional

# Verify loaded
echo $OPENVPN_SMTP_HOST
```

## Requirements

- **Python**: 3.6+
- **Dependencies**: `python-dotenv` (install via `pip install -r requirements.txt`)
- **Tools**: `nc` (netcat), `systemctl`
- **Access**: OpenVPN management interface (127.0.0.1:7505), systemctl

## Files

```
OpenVPNMonitor/
├── openvpn-monitor.py          # Main script
├── openvpn-monitor.service     # Systemd service unit
├── openvpn-monitor.timer       # Systemd timer unit (runs every 10s)
├── install-systemd.sh          # Automated systemd installation
├── requirements.txt            # Python dependencies
├── .env                        # Configuration (auto-loaded)
├── .env.example                # Template
├── .gitignore                  # Protects .env
└── README.md                   # This file
```

## License

Provided as-is for monitoring OpenVPN services.

