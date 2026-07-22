#!/bin/bash
# One-time setup for PetFeedr on Raspberry Pi
# Run this ON THE PI after first deploy: ./setup-pi.sh

set -e

PI_USER="${PI_USER:-$(whoami)}"
PI_PATH="${PI_PATH:-/home/$PI_USER/PetFeedr}"
SERVICE_FILE="/etc/systemd/system/petfeedr.service"

echo "🐱 PetFeedr Pi Setup"
echo "===================="

# Feedings fire on the system clock — a wrong timezone shifts every meal
# (learned the hard way: OS image defaulted to Eastern, cat ate an hour early)
echo "🕐 Setting timezone..."
sudo timedatectl set-timezone America/Chicago

# Create the systemd service file
echo "📝 Creating systemd service..."
sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=PetFeedr Service
After=multi-user.target

[Service]
Type=simple
User=$PI_USER
WorkingDirectory=$PI_PATH
ExecStart=/bin/bash -c 'source $PI_PATH/venv/bin/activate && python $PI_PATH/PetFeedr.py'
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable service
echo "🔄 Enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable petfeedr.service

# Start the service
echo "▶️  Starting service..."
sudo systemctl start petfeedr.service

# Check status
echo ""
echo "✅ Setup complete!"
sudo systemctl status petfeedr.service --no-pager

echo ""
echo "🌐 Web interface: http://petfeedr.local:5000"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status petfeedr.service   # Check status"
echo "  sudo systemctl restart petfeedr.service  # Restart"
echo "  sudo journalctl -u petfeedr.service -f   # View logs"
