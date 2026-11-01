# Soundroom

Soundroom is a Windows 10 local server for YouTube playback on the server PC, Windows output volume, and room bells. Each room has its own distinct bell tune. Other devices on the same trusted home network can control it from a browser.

## Windows setup

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/) and enable the Python launcher.
2. Double-click `install.bat`. It creates a virtual environment, installs Python dependencies and its managed Chromium browser, and registers Soundroom to start when your Windows account signs in. Setup needs internet access.
3. Double-click `start.bat` to start it now. The server address and access PIN appear in the console. After future sign-ins it starts in the background; logs are written to `data/server.log`.
4. On the Windows PC, open the printed address. Other devices on the same Wi-Fi can open the same address.

The initial PIN is **223344**. Change it in **Server setup**. On a client device, select **Remember this device for 30 days** to avoid entering it on every visit. Changing the PIN invalidates remembered sign-ins.

## YouTube and server audio

Paste a YouTube link and choose **Play on server**. Soundroom closes YouTube tabs in regular Chrome on the Windows PC, then opens the video in its managed browser window on that PC. The client browser sends the control request; video and sound come from the server. The managed window has a separate profile, so sign in there if a video requires it. YouTube needs internet access on the Windows PC.

Set the Bluetooth speaker as the Windows default output. Use **Open Bluetooth settings** in Soundroom to open Settings on the server. Pairing and connection happen in Windows; the browser button cannot pair Bluetooth devices itself. If you clicked from another device, operate the Settings window at the server PC or connect to it with Windows Remote Desktop. Then select the Bluetooth speaker in Windows Sound settings. Soundroom reduces the managed browser audio while a room bell plays, then restores it.

If the video gets stuck paused or will not resume, choose **Reset server player**. This closes and relaunches Soundroom's managed browser session; then submit the YouTube link again.

## Room bells

Each room has a **Ring · 5 sec** and **Ring · 10 sec** control. The selected control becomes **Stop bell** while the bell is playing. Room names and sounds are editable under **Sound settings**; removing a room also cancels its scheduled bells. Scheduled one-shot bells remain available in the schedule below the console. Room sounds are six distinct built-in WAV patterns; custom sounds must be uncompressed 16-bit PCM WAV files.

Every triggered bell opens a centered, topmost server-display alert that reads **“Please attend to Room &lt;room name&gt;”**. It wakes the display and interrupts the screen saver, then stays until acknowledged or for 60 seconds. Scheduled bells register Windows wake tasks; for those to wake the PC from sleep, the device must support wake timers and **Allow wake timers** must be enabled under Windows advanced power settings (Sleep → Allow wake timers). Windows may wake the PC while leaving its display off, depending on the device. A manual bell request cannot reach a PC while it is asleep; wake the PC first. The alert cannot appear over the Windows lock screen, so keep the server user signed in.

## Keep the server address stable

Soundroom shows the Windows PC’s current home-network address under **Server setup**. To keep it from changing, reserve that address for the Windows PC in your Airtel router’s LAN/DHCP settings. The router admin address and menu vary by model; Airtel’s [router login guide](https://www.airtel.in/blog/broadband/how-to-login-to-your-wi-fi-router/) explains how to find the router page and notes that settings differ across models. Look for **DHCP reservation**, **Address Reservation**, or a similar LAN option, then reserve the address shown by Soundroom for this PC. Do not change the router’s WAN/public IP. If you do not see a reservation option, contact Airtel support with your router model.

## Network and limitations

The server is reachable on the local network and requires the PIN. Keep the PC and clients on a trusted private Wi-Fi network; do not forward port 8765 from the internet. If Windows Firewall blocks other devices, allow Python on a private network. The server must be running and the PC awake for bells and music controls to work. Startup is configured for Windows sign-in because browser playback and Bluetooth audio need the interactive desktop session.
