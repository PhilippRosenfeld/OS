# horus

[![Tests](https://github.com/PhilippRosenfeld/OS/actions/workflows/tests.yml/badge.svg)](https://github.com/PhilippRosenfeld/OS/actions/workflows/tests.yml)

A retro terminal-style OS simulator/emulator, built with Python, pyglet, and moderngl — complete with a CRT shader, BIOS-style boot sequence, a virtual filesystem, and a small shell with its own set of commands.

## Running

```bash
uv sync
uv run horus
```

## Status

Early development (`v0.4.0`). See the [Releases](../../releases) page for changelogs.

## Roadmap

Planned work lives in the [milestones](../../milestones) and their issues:

- **v0.5.0**: Network & netman (hosts, services, remote login, firewall, file transfer, LAN, wiki)
- **v0.6.0**: Packages & apps (package installer, audio player)
- **v0.7.0**: Multiple computers & hardware upgrades
- **v0.8.0**: Communication & threats (mail, malware)
- **v0.9.0**: Media & surveillance (video, remote surveillance)
