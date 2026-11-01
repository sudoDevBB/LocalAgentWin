# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python local server with a browser interface, reachable on the local network. The user chose a working local prototype and approved this recommended stack.

## Users

The primary user operates a Windows 10 computer connected to Bluetooth speakers and wants to play YouTube music and schedule room bells from a browser. People elsewhere in the home should recognize which room triggered a bell by its sound.

## Product Purpose

The local server provides one place to control music playback, system volume, and room bells. Success means music can be started from a YouTube link, each room has its own recognizable bell sound, bells can be scheduled, and a bell can temporarily lower the music before restoring it.

## Positioning

The product combines a local music control surface with room-based bell scheduling, a distinct sound assigned to each room, and audio ducking on the Windows machine that is playing the sound.

## Operating Context

The server runs on Windows 10, which is connected to Bluetooth audio. A browser interface accepts a YouTube link and provides music and room-bell controls. The interface is reachable by other devices on the local network. YouTube streaming requires internet access on the client browser.

## Capabilities and Constraints

- Play and change YouTube videos from the browser interface.
- Pause the product's current embedded YouTube video when another video is selected within the product.
- Provide system volume control and gradually reduce music volume while a room bell plays, then restore the music volume.
- Create scheduled bells for named rooms. Each room has one unique tune; bells use the assigned room tune, and the same tune cannot be assigned to another room. Built-in sounds are generated locally; custom tunes use 16-bit PCM WAV.
- Preview each room's bell through the Windows audio output and upload additional 16-bit PCM WAV tunes.
- Include a room-bell management portal and instructions for controlling the local server.
- Assumption: use YouTube's embedded player. Browser security prevents this page from controlling playback in unrelated tabs or applications.
- The Windows setup script creates a virtual environment and installs dependencies; Python 3.11 or later must already be installed.
- Initial scheduling is one-shot and uses the Windows computer local time; recurrence and daylight-saving behavior remain future decisions.
- LAN access uses a six-digit PIN generated locally at first run.
- The first build is a working local prototype.

## Evidence on Hand

The user-provided brief is the only product evidence. No product name, logo, audio files, or existing implementation was supplied. Do not present illustrative room schedules or audio as real user data.

## Product Principles

- Keep music and room-bell controls understandable from a browser.
- Give each room a distinct, previewable bell sound so listeners can recognize its source.
- Let the local Windows machine own audio playback and volume changes.
- Make setup suitable for Windows 10 and install required dependencies.
- Keep the limits of browser-controlled YouTube playback clear.
