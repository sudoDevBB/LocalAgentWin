# Soundroom

Soundroom is a Windows 10 local server for YouTube playback on the server PC, Windows output volume, and room bells. Each room has its own distinct bell tune. Other devices on the same trusted home network can control it from a browser.

## Windows setup

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/) and enable the Python launcher.
2. Install Google Chrome and open it using the Windows account that will run Soundroom.
3. Double-click `install.bat`. It creates a virtual environment, installs the server dependencies, and registers Soundroom to start when you sign in to Windows.
4. In server Chrome, open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**, and select the project's `extension` folder. Allow its YouTube access; it needs this to close old YouTube tabs and control the new video. Leave it enabled.
5. Sign in to YouTube in this regular Chrome profile. Then open Soundroom on the Windows PC at the printed address; other devices on the same Wi-Fi can use that address too. Keep Chrome open while using playback.

The initial PIN is **223344**. Change it in **Server setup**. On a client device, select **Remember this device for 30 days** to avoid entering it on every visit. Changing the PIN invalidates remembered sign-ins.

## YouTube and server audio

Paste a YouTube link and choose **Play on server**. Soundroom closes existing YouTube tabs, then opens the selected video in a new tab in the server's regular, signed-in Chrome profile. The client browser only sends the control request; video and sound come from Chrome on the Windows server. The server's Chrome extension must be enabled and connected.

Set the Bluetooth speaker as the Windows default output. Use **Enable Bluetooth** or **Disable Bluetooth** in Soundroom to control the server radio. Open Windows Bluetooth settings to pair a speaker. Pairing and connection happen in Windows; the browser button cannot pair Bluetooth devices itself. If you clicked from another device, operate the Settings window at the server PC or connect to it with Windows Remote Desktop. Then select the Bluetooth speaker in Windows Sound settings. Soundroom reduces the server Chrome audio while a room bell plays, then restores it.

If the video gets stuck paused or will not resume, choose **Reset server player**. This closes Soundroom's YouTube tab in Chrome; then submit the YouTube link again.

## Room bells

Each room has 5 and 10 second controls for Receptionist and Housekeeping. The server alert shows the selected recipient; the room sound is the same for both. The selected control becomes **Stop bell** while the bell is playing. Room names and sounds are editable under **Sound settings**; removing a room also cancels its scheduled bells. Scheduled one-shot bells remain available in the schedule below the console. Room sounds are six distinct built-in WAV patterns; custom sounds must be uncompressed 16-bit PCM WAV files.

Every triggered bell opens a centered, topmost server-display alert that reads **“Please attend to Room &lt;room name&gt;”**. It wakes the display and interrupts the screen saver, then stays until acknowledged or for 60 seconds. Scheduled bells register Windows wake tasks; for those to wake the PC from sleep, the device must support wake timers and **Allow wake timers** must be enabled under Windows advanced power settings (Sleep → Allow wake timers). Windows may wake the PC while leaving its display off, depending on the device. A manual bell request cannot reach a PC while it is asleep; wake the PC first. The alert cannot appear over the Windows lock screen, so keep the server user signed in.

## Keep the server address stable

Soundroom shows the Windows PC’s current home-network address under **Server setup**. To keep it from changing, reserve that address for the Windows PC in your Airtel router’s LAN/DHCP settings. The router admin address and menu vary by model; Airtel’s [router login guide](https://www.airtel.in/blog/broadband/how-to-login-to-your-wi-fi-router/) explains how to find the router page and notes that settings differ across models. Look for **DHCP reservation**, **Address Reservation**, or a similar LAN option, then reserve the address shown by Soundroom for this PC. Do not change the router’s WAN/public IP. If you do not see a reservation option, contact Airtel support with your router model.

## Network and limitations

The server is reachable on the local network and requires the PIN. Keep the PC and clients on a trusted private Wi-Fi network; do not forward port 8765 from the internet. If Windows Firewall blocks other devices, allow Python on a private network. While Soundroom is running, it requests that Windows keep the PC awake. This does not prevent manual sleep or shutdown. Startup is configured for Windows sign-in because browser playback and Bluetooth audio need the interactive desktop session.
