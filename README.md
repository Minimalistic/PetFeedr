# PetFeedr

PetFeedr is a project that aims to automate the feeding process for pets. It provides a convenient way for pet owners to schedule and control the feeding of their pets.

## Features (Intended)

- Schedule feeding times for your pets
- Control the amount of food dispensed
- Monitor feeding history and patterns
- Receive notifications for feeding events

## Installation

1. Clone the repository: `git clone https://github.com/your-username/PetFeedr.git`
2. Navigate to repository folder in terminal
3. Type `python3 -m venv venv`
4. Type `source venv/bin/activate`
5. Install dependencies:
   - **On Raspberry Pi:** `pip install -r requirements-pi.txt`
   - **On Mac/PC (development):** `pip install -r requirements.txt`


## Configuring the Service

1. Create a new service file:
`sudo nano /etc/systemd/system/petfeedr.service`
2. Add the following content to the service file:
```
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
Replace `<your-user>` with your Raspberry Pi username and `/path/to/PetFeedr` with the actual path to the project directory.

3. Save the file and exit the editor.
4. Reload the systemd daemon:
`sudo systemctl daemon-reload`
5. Start the PetFeedr service:
`sudo systemctl start petfeedr.service`
6. Check the status of the service:
`sudo systemctl status petfeedr.service`

## Usage

1. Access the PetFeedr web interface at `http://localhost:5000`
2. Create an account or log in with your existing credentials
3. Set up feeding schedules and portion sizes for your pets
4. Monitor feeding events and adjust settings as needed

## Development / Simulation Mode

PetFeedr can run in simulation mode for development and testing without needing actual hardware. This is useful for:
- Developing on a laptop/desktop without GPIO access
- Testing schedule changes without affecting the live pet feeder
- Debugging the web interface

### Running in Simulation Mode

**Automatic:** If `RPi.GPIO` is not installed (e.g., on a Mac or PC), simulation mode is enabled automatically.

**Manual:** Force simulation mode by setting an environment variable:
```bash
PETFEEDR_SIMULATE=true python3 PetFeedr.py
```

In simulation mode:
- 🔧 No GPIO/hardware is touched
- 🔄 Motor movements are logged but not executed
- 📱 Pushover notifications are simulated (logged, not sent)
- ✅ The web interface works normally

### Configuration

Copy `SecretKeys.py.example` to `SecretKeys.py` and configure:
- `PETFEEDR_USER_ID` / `PETFEEDR_PASSWORD` - Web login credentials
- `PETFEEDR_SECRET_KEY` - Flask session secret (generate a random string)
- `PUSHOVER_ENABLED` - Set to `True` to enable push notifications
- `PUSHOVER_API_TOKEN` / `PUSHOVER_USER_KEY` - From pushover.net (optional)

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