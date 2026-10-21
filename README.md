# Settings Switcher

Switches a setting in a web interface on or off from a script. You record a click-through once, and the tool replays it later in a headless browser, for devices and services whose web interface is the only way in. A typical use case is turning a port forwarding on a Fritzbox router on and off when its TR-064 interface is not an option.

*Deutsche Version: [README.de.md](README.de.md)*

## How it works

You click through the change once in a built-in browser, and the tool writes your steps down as a **profile**: a short list of simple actions. From then on, one command repeats them in a fresh, throw-away container with a headless browser:

```
./run.sh setting-on
./run.sh setting-off
```

The exit code tells you whether it worked, so you can call it from a scheduler or a home automation system.

- **Profiles** are small JSON files with fixed actions (open a page, click, fill in, tick a box, check a result). There is no free scripting.
- **Recorder:** a small web page with a live browser. You click through the web interface as usual and every action turns into a step.
- **Runner:** `run.sh` starts a locked-down container, plays the profile and removes the container again.

## Features

- Works with any web interface the Docker host can reach; nothing in it is tied to a specific device
- Record a profile by clicking, also on a tablet (touch scrolling); continue recording from any step
- Checks after the change, so a run only counts as successful when the setting really is in the expected state
- Optional automatic retry of the whole run if it fails now and then
- Passwords are never stored in a profile; the browser can only visit the addresses you allow
- Ready-made Docker images to download (GitHub Container Registry)

## Requirements

- A Linux host with Docker (Compose v2) and Bash
- A web interface that the Docker host can reach, with a login that works from a plain form
- Developed and tested with a Fritzbox 7590 running FRITZ!OS 8.25 only (turning a port forwarding on and off). Other devices and web interfaces should work in principle but are untested and may need adjustments to the profile.

## Quick start

1. **Access:** `cp runner.env.example runner.env && chmod 600 runner.env`, then enter the address of the web interface and a login. Use a separate user with minimal rights.
2. **Editor settings:** `cp .env.example .env && chmod 600 .env`, then set an editor token (for example `openssl rand -hex 24`) and the same address.
3. **Record:** `docker compose --profile record up -d --build`, open `http://127.0.0.1:8080`, click through the change and save the profile. Stop the editor with `docker compose --profile record down`.
4. **Run:** `./run.sh <profile>`

The example files and the documentation use a Fritzbox as the running example (address `192.168.178.1`); replace it with your own.

A more detailed walkthrough: [docs/erste-schritte.md](docs/erste-schritte.md)

More: [docs/konfiguration.md](docs/konfiguration.md) · [docs/profile.md](docs/profile.md) · [docs/betrieb.md](docs/betrieb.md) · [docs/fehlersuche.md](docs/fehlersuche.md) · [docs/sicherheit-und-grenzen.md](docs/sicherheit-und-grenzen.md) (the detailed documentation is currently in German; the web interface is German as well).

## Versions and contributing

Versions follow [Semantic Versioning](https://semver.org), and changes are listed in [CHANGELOG.md](CHANGELOG.md). If you want to contribute or create releases, see [docs/entwicklung.md](docs/entwicklung.md) (in German). License: MIT.

## Security notice

The runner can log in to the web interface, so treat it like a key. Keep the login only in `runner.env`, never in a profile. Do not expose the editor to the internet; it is bound to the local machine by default and protected by a token. Profiles contain addresses and element names of your own devices, so the `.gitignore` keeps your own profiles out of the repository. Details: [docs/sicherheit-und-grenzen.md](docs/sicherheit-und-grenzen.md).

## Limitations (short)

Recorded steps can break after a firmware or software update and then need to be recorded again. A run without a check does not prove that the setting changed. A profile has only fixed steps and one login from `runner.env`, so pages that need a CAPTCHA or a one-time code cannot be automated. The live view is a series of screenshots, not a video.

## Disclaimer

Settings Switcher is an independent project and is not affiliated with or endorsed by AVM GmbH or any other device or software manufacturer. Fritzbox and FRITZ!OS, like all other product names mentioned, are trademarks of their respective owners.
