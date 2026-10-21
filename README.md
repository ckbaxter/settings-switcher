# Settings Switcher

Switches a setting in a web interface on or off from a script. Built for turning a port forwarding on a Fritzbox router on and off, where the router's TR-064 interface is not an option.

*Deutsche Version: [README.de.md](README.de.md)*

## How it works

You click through the change once in a built-in browser, and the tool writes your steps down as a **profile**: a short list of simple actions. From then on, one command repeats them in a fresh, throw-away container with a headless browser:

```
./run.sh port-forward-on
./run.sh port-forward-off
```

The exit code tells you whether it worked, so you can call it from a scheduler or a home automation system.

- **Profiles** are small JSON files with fixed actions (open a page, click, fill in, tick a box, check a result). There is no free scripting.
- **Recorder:** a small web page with a live browser. You click through the web interface as usual and every action turns into a step.
- **Runner:** `run.sh` starts a locked-down container, plays the profile and removes the container again.

## Features

- Record a profile by clicking, also on a tablet (touch scrolling); continue recording from any step
- Checks after the change, so a run only counts as successful when the setting really is in the expected state
- Optional automatic retry of the whole run if it fails now and then
- Passwords are never stored in a profile; the browser can only visit the addresses you allow
- Ready-made Docker images, built by a GitHub workflow

## Requirements

- A Linux host with Docker (Compose v2) and Bash
- A web interface that the Docker host can reach (for example the router)
- Developed and tested with a Fritzbox 7590 running FRITZ!OS 8.25 only. Other devices or versions may need changes to the profile.

## Quick start

1. **Router access:** `cp runner.env.example runner.env && chmod 600 runner.env`, then enter the address of the router and a login. Use a separate router user with minimal rights.
2. **Editor settings:** `cp .env.example .env && chmod 600 .env`, then set an editor token (for example `openssl rand -hex 24`) and the same router address.
3. **Record:** `docker compose --profile record up -d --build`, open `http://127.0.0.1:8080`, click through the change and save the profile. Stop the editor with `docker compose --profile record down`.
4. **Run:** `./run.sh <profile>`

More: [docs/konfiguration.md](docs/konfiguration.md) · [docs/profile.md](docs/profile.md) · [docs/betrieb.md](docs/betrieb.md) · [docs/fehlersuche.md](docs/fehlersuche.md) · [docs/sicherheit-und-grenzen.md](docs/sicherheit-und-grenzen.md) (the detailed documentation is currently in German; the web interface is German as well).

## Versioning

[Semantic Versioning](https://semver.org). The single source of truth is the [`VERSION`](VERSION) file. Changes are listed in [CHANGELOG.md](CHANGELOG.md); releases are Git tags `vX.Y.Z`, and the matching Docker images are published to the GitHub Container Registry.

## Security notice

The runner can log in to your router, so treat it like a key. Keep the login only in `runner.env`, never in a profile. Do not expose the editor to the internet; it is bound to the local machine by default and protected by a token. Profiles contain addresses and element names of your own devices, so the `.gitignore` keeps your own profiles out of the repository. Details: [docs/sicherheit-und-grenzen.md](docs/sicherheit-und-grenzen.md).

## Limitations (short)

Recorded steps can break after a firmware update and then need to be recorded again. A run without a check does not prove that the setting changed. The live view is a series of screenshots, not a video.

## Disclaimer

Settings Switcher is an independent project and is not affiliated with or endorsed by AVM GmbH or any other device manufacturer. Fritzbox and FRITZ!OS are trademarks of their respective owners.
