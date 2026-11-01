# Soundroom

Soundroom is a Windows 10 local server for an embedded YouTube player, system volume, and scheduled room bells. Every room uses a different assigned sound so listeners can identify where a bell came from.

## Windows setup

1. Install Python 3.11 or newer if it is not already installed. During installation, enable the Python launcher.
2. Double-click `install.bat`. It creates a private virtual environment and installs the required Python packages.
3. Double-click `start.bat`. The server prints a six-digit access PIN and its local address.
4. Open `http://127.0.0.1:8765` on the Windows computer. Other devices on the same trusted network can use `http://<windows-computer-ip>:8765`.
5. If Windows Firewall blocks other devices, allow Python on a private network in Windows Security. Keep the port off public networks and do not forward it from your router.

The browser interface uses a PIN generated on first launch. Keep the PIN private. App state and uploaded WAV tunes stay in the local `data` folder.

## Playback and audio

YouTube runs in the product's embedded player. Starting a different link replaces the current embedded video. Browser security does not let a local web page control YouTube videos playing in unrelated tabs or other applications.

The volume control uses the Windows default output endpoint. Set the Bluetooth speaker as the default Windows output before starting Soundroom. When a room bell rings, Soundroom gradually lowers browser audio sessions, plays the room's distinct tune, then gradually restores the previous browser volume. Six distinct built-in bell patterns are assigned to rooms automatically. Every room must use a different tune; preview the sound from the Windows speaker before relying on it. Custom bell tunes must be uncompressed 16-bit PCM WAV files with one or two channels. The embedded YouTube player requires an internet connection.

## Prototype scope

This is a local-network prototype. The server binds to all network interfaces so trusted devices can connect; the PIN is required for the interface and its API. Do not expose port 8765 to the internet. The server must stay running for bells to ring. Bell times use the Windows computer's local time and are one-shot. The setup script installs Python packages, but Python itself must be installed first.
