# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python local server with a browser interface, reachable on the local network. The user chose a working local prototype and approved this recommended stack.

## Users

The primary user operates a Windows 10 computer connected to Bluetooth speakers and wants to play YouTube music and ring room bells from a browser. People elsewhere in the home should recognize which room triggered a bell by its sound.

## Product Purpose

The local server provides one place to control server-side YouTube playback, Windows output volume, and room bells. Success means music plays on the Windows PC, each room has its own recognizable bell sound, room bells can be rung and stopped from a console or scheduled, and a bell can temporarily lower the music before restoring it.

## Positioning

The product combines a local music control surface with immediate room bell controls, optional scheduling, a distinct sound assigned to each room, and audio ducking on the Windows machine that plays both.

## Operating Context

The server runs on Windows 10, which is connected to Bluetooth audio. A browser interface accepts a YouTube link and provides music, room-bell, Bluetooth settings, access PIN, and network setup controls. The interface is reachable by other devices on the local network. YouTube streaming requires internet access on the Windows server.

## Capabilities and Constraints

- Play and change YouTube videos in a visible, Soundroom-controlled Chromium window on the Windows server; client browsers only send control requests.
- Reset the managed server-side browser session from the client interface if playback becomes stuck.
- Close YouTube tabs in the server's regular Chrome windows when a new video is requested; use a separate persistent Chromium profile for the controlled video session.
- Provide system volume control and gradually reduce music volume while a room bell plays, then restore the music volume.
- Provide immediate 5-second and 10-second room bell controls, with a stop action while a bell is playing, alongside scheduled one-shot bells.
- Allow room names and assigned sounds to be edited, and allow rooms to be removed with their scheduled bells cancelled.
- Show a centered, topmost Windows server-display alert for every bell trigger with the room name; wake the display and interrupt the screen saver.
- Register wake-enabled Windows Task Scheduler entries for scheduled bells so compatible PCs can wake from sleep.
- Provide a button that opens Bluetooth settings on the server so the user can pair/connect a speaker and select it as the Windows default output.
- Explain that Bluetooth pairing is completed on the server PC or through Remote Desktop; the browser control only opens Windows Settings on the server.
- Start the server at Windows sign-in through Task Scheduler.
- Use an initial access PIN of `223344`, allow changing it from server settings, and offer a 30-day remembered browser session.
- Display the current Windows LAN address and document DHCP reservation on the user's Airtel router to keep the address stable.
- Create scheduled bells for named rooms. Each room has one unique tune; bells use the assigned room tune, and the same tune cannot be assigned to another room. Built-in sounds are generated locally; custom tunes use 16-bit PCM WAV.
- Preview each room's bell through the Windows audio output and upload additional 16-bit PCM WAV tunes.
- Include a room-bell management portal and instructions for controlling the local server.
- Use YouTube's normal watch page in Soundroom-managed Chromium. Existing YouTube tabs in regular Chrome are closed when a new video is requested.
- The Windows setup script creates a virtual environment, installs Python dependencies and Chromium, and registers a sign-in startup task. Python 3.11 or later must already be installed.
- Scheduled wake behavior depends on Windows wake timers and device support. A sleeping PC cannot receive an immediate network bell request, and a desktop application alert cannot appear above the Windows lock screen.
- Bluetooth pairing and device selection remain Windows actions launched from the Soundroom interface; the user chooses the Bluetooth output in Windows settings.
- Initial scheduling is one-shot and uses the Windows computer local time; recurrence and daylight-saving behavior remain future decisions.
- LAN access uses a six-digit PIN. First-run default is `223344`; the owner can change it from Server setup.
- Remembered access uses an HTTP-only signed session cookie with a 30-day lifetime; PIN changes rotate the signing secret and invalidate those sessions.
- LAN address stability is configured in the router using a DHCP reservation; the server does not change the router or assign a static public IP.
- Startup runs when the Windows user signs in, not before sign-in, so Bluetooth and the browser player can use the interactive desktop.
- The first build is a working local prototype.

## Evidence on Hand

The user-provided brief is the only product evidence. No product name, logo, audio files, or existing implementation was supplied. Do not present illustrative room schedules or audio as real user data.

## Product Principles

- Keep music and room-bell controls understandable from a browser.
- Give each room a distinct, previewable bell sound so listeners can recognize its source.
- Let the local Windows machine own audio playback and volume changes.
- Make setup suitable for Windows 10 and install required dependencies.
- Keep the limits of browser-controlled YouTube playback clear.
