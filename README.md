# PetFeedr

PetFeedr is a project that aims to automate the feeding process for pets. It provides a convenient way for pet owners to schedule and control the feeding of their pets.

## Features (Intended)

- Schedule feeding times for your pets
- Control the amount of food dispensed
- Monitor feeding history and patterns
- Receive notifications for feeding events

## Quick Start (Raspberry Pi)

### First-Time Setup

1. Clone the repository on your Mac/PC:
   ```bash
   git clone https://github.com/your-username/PetFeedr.git
   cd PetFeedr
   ```

2. Edit `deploy.sh` and `setup-pi.sh` to match your Pi's username and hostname if different from defaults.

3. Deploy to your Pi:
   ```bash
   ./deploy.sh
   ```

4. SSH into your Pi and run the one-time setup:
   ```bash
   ssh your-user@your-pi.local
   cd ~/PetFeedr
   ./setup-pi.sh
   ```

5. Access the web interface at `http://your-pi.local:5000`

### Deploying Updates

After making code changes, simply run:
```bash
./deploy.sh
```

This will:
- 💾 Backup the current Pi installation to your Mac
- ⏹️ Stop the service
- 📦 Sync changed files
- 📚 Update dependencies if needed
- ▶️ Restart the service

Backups are stored in `~/Documents/Homelab/PetFeedr/backups/` (last 10 kept).

## Manual Installation

If you prefer manual setup:

1. Copy files to your Pi
2. Create a virtual environment:
   ```bash
   cd ~/PetFeedr
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements-pi.txt
   ```

3. Create the systemd service file:
   ```bash
   sudo nano /etc/systemd/system/petfeedr.service
   ```
   
   Add:
   ```ini
   [Unit]
   Description=PetFeedr Service
   After=multi-user.target

   [Service]
   Type=simple
   User=<your-user>
   WorkingDirectory=/path/to/PetFeedr
   ExecStart=/bin/bash -c 'source /path/to/PetFeedr/venv/bin/activate && python /path/to/PetFeedr/PetFeedr.py'
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   Replace `<your-user>` and `/path/to/PetFeedr` with your values.

4. Enable and start the service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable petfeedr.service
   sudo systemctl start petfeedr.service
   ```

## Development (Mac/PC)

For local development without a Pi:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 PetFeedr.py
```

Simulation mode is enabled automatically when `RPi.GPIO` is not available.

## Usage

1. Access the PetFeedr web interface at `http://localhost:5000` (or `http://<pi-ip-address>:5000` from another device on your network)
2. Set up feeding schedules using the web interface
3. Monitor feeding events and adjust settings as needed
4. Use the manual feed button to trigger feedings on demand

## Simulation Mode

PetFeedr can run in simulation mode for development and testing without needing actual hardware. This is useful for:
- Developing on a laptop/desktop without GPIO access
- Testing schedule changes without affecting the live pet feeder
- Debugging the web interface

**Automatic:** If `RPi.GPIO` is not installed (e.g., on a Mac or PC), simulation mode is enabled automatically.

**Manual:** Force simulation mode by setting an environment variable:
```bash
PETFEEDR_SIMULATE=true python3 PetFeedr.py
```

In simulation mode:
- 🔧 No GPIO/hardware is touched
- 🔄 Motor movements are logged but not executed
- ✅ The web interface works normally

## Maintaining the Raspberry Pi

To ensure a smooth update process and minimize the risk of data loss, it's recommended to create a backup of the Raspberry Pi's SD card before applying any updates.

### Creating a Backup Image

1. Power down your Raspberry Pi gracefully.

2. Remove the SD card from your Raspberry Pi and connect it to your laptop using an SD card reader.

3. Create an image of the SD card using a tool like Win32 Disk Imager (Windows) or by using the `dd` command (macOS/Linux).

4. Store the backup image in a safe location, such as an external hard drive or a cloud storage service.

### Updating the Raspberry Pi

1. Power on your Raspberry Pi and SSH into it.

2. Update the system and installed packages:
`sudo apt update`
`sudo apt upgrade`

3. Review the list of available updates and proceed with the installation if you're comfortable with the changes.

4. Reboot your Raspberry Pi after the update process is complete:
`sudo reboot`

5. Verify that the PetFeedr script and other critical functionalities are working as expected.

Note: If any issues arise during the update process, you can flash the backup image back to the SD card to restore your system to its previous state.

## License

This project is licensed under the...