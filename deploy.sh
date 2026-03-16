#!/bin/bash
# Deploy PetFeedr to Raspberry Pi
# Usage: ./deploy.sh

set -e  # Exit on error

PI_HOST="${PI_HOST:-pi@petfeedr.local}"
PI_PATH="${PI_PATH:-/home/pi/PetFeedr}"
LOCAL_PATH="$(cd "$(dirname "$0")" && pwd)"  # Get absolute path
BACKUP_DIR="${BACKUP_DIR:-$HOME/PetFeedr-backups}"

# SSH multiplexing - reuse one connection for all commands (one password prompt!)
SSH_CONTROL_PATH="/tmp/petfeedr-deploy-$$"
SSH_OPTS="-o ControlMaster=auto -o ControlPath=$SSH_CONTROL_PATH -o ControlPersist=60"

# Cleanup function to close SSH connection on exit
cleanup() {
    ssh -O exit -o ControlPath="$SSH_CONTROL_PATH" "$PI_HOST" 2>/dev/null || true
}
trap cleanup EXIT

echo "🐱 PetFeedr Deploy Script"
echo "========================="

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Start SSH master connection (this is the only password prompt)
echo "🔐 Connecting to Pi..."
ssh $SSH_OPTS -o ControlMaster=yes -fN "$PI_HOST"

# Backup existing Pi folder before deploying
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_PATH="$BACKUP_DIR/petfeedr_backup_$TIMESTAMP"
echo "💾 Backing up current Pi installation..."
if rsync -az -e "ssh $SSH_OPTS" --exclude 'venv/' "$PI_HOST:$PI_PATH/" "$BACKUP_PATH/" 2>/dev/null; then
    echo "   Backup saved to: $BACKUP_PATH"
    
    # Keep only the last 10 backups (use subshell to avoid changing directory)
    (cd "$BACKUP_DIR" && ls -1td */ | tail -n +11 | while read dir; do rm -rf "$dir"; done)
    echo "   (Keeping last 10 backups)"
else
    echo "   ⚠️  No existing installation to backup (first deploy?)"
fi

# Stop the service
echo "⏹️  Stopping PetFeedr service..."
ssh $SSH_OPTS "$PI_HOST" "sudo systemctl stop petfeedr.service" 2>/dev/null || true

# Sync files (excludes venv, __pycache__, logs, and git)
echo "📦 Syncing files to Pi..."
rsync -avz --delete \
    -e "ssh $SSH_OPTS" \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    --exclude 'feeding_log.txt' \
    --exclude 'feeding_schedules.txt' \
    --exclude 'settings.json' \
    --exclude 'todays_schedule.json' \
    "$LOCAL_PATH/" "$PI_HOST:$PI_PATH/"

# Check if venv exists, create if not
echo "🔍 Checking Python environment..."
ssh $SSH_OPTS "$PI_HOST" "cd $PI_PATH && if [ ! -d 'venv' ]; then echo '📦 Creating venv...'; python3 -m venv venv; fi"

# Install/update dependencies
echo "📚 Updating dependencies..."
ssh $SSH_OPTS "$PI_HOST" "cd $PI_PATH && source venv/bin/activate && pip install -q -r requirements-pi.txt"

# Start the service
echo "▶️  Starting PetFeedr service..."
ssh $SSH_OPTS "$PI_HOST" "sudo systemctl start petfeedr.service"

# Check status
echo "✅ Checking service status..."
ssh $SSH_OPTS "$PI_HOST" "sudo systemctl is-active petfeedr.service" && echo "🐱 PetFeedr is running!" || echo "❌ Service failed to start"

echo ""
echo "🌐 Web interface: http://petfeedr.local:5000"
echo "📋 View logs: ssh $PI_HOST 'sudo journalctl -u petfeedr.service -f'"
