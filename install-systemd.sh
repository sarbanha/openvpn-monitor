#!/bin/bash
# Installation script for OpenVPN Monitor systemd units

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="openvpn-monitor.service"
TIMER_FILE="openvpn-monitor.timer"

echo "OpenVPN Monitor - Systemd Installation"
echo "======================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)"
    exit 1
fi

# Update paths in service file and install directly
echo "1. Installing systemd service file..."
echo "   Installation directory: ${SCRIPT_DIR}"
sed "s|INSTALL_DIR|${SCRIPT_DIR}|g" \
    "${SCRIPT_DIR}/${SERVICE_FILE}" > "/etc/systemd/system/${SERVICE_FILE}"
echo "   ✓ Installed to /etc/systemd/system/${SERVICE_FILE}"

echo ""
echo "2. Installing systemd timer file..."
cp "${SCRIPT_DIR}/${TIMER_FILE}" "/etc/systemd/system/${TIMER_FILE}"
echo "   ✓ Installed to /etc/systemd/system/${TIMER_FILE}"

echo ""
echo "3. Reloading systemd daemon..."
systemctl daemon-reload
echo "   ✓ Daemon reloaded"

echo ""
echo "4. Enabling timer to start on boot..."
systemctl enable openvpn-monitor.timer
echo "   ✓ Timer enabled"

echo ""
echo "5. Starting timer..."
systemctl start openvpn-monitor.timer
echo "   ✓ Timer started"

echo ""
echo "======================================="
echo "Installation complete!"
echo ""
echo "Useful commands:"
echo "  - Check timer status:    systemctl status openvpn-monitor.timer"
echo "  - Check service status:  systemctl status openvpn-monitor.service"
echo "  - View logs:             journalctl -u openvpn-monitor.service -f"
echo "  - List timers:           systemctl list-timers openvpn-monitor.timer"
echo "  - Stop timer:            sudo systemctl stop openvpn-monitor.timer"
echo "  - Disable timer:         sudo systemctl disable openvpn-monitor.timer"
echo ""
echo "The monitor will run every 30 seconds."
echo "Check logs: tail -f /var/log/openvpn-monitor.log"

