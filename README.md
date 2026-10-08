<div align="center">

<img src="docs/assets/banner.jpg" alt="EmbeddedDisplay Studio" width="900" />

### Describe it. Design it. Wire it. Ship it to the glass.

A desktop studio for embedded Linux HMI panels — an AI designer, a canvas the size of the panel,<br />
a coding agent that wires your PLC, and one-click deploys to a 1.4 MB C + LVGL runtime that rolls itself back.

[![Release](https://img.shields.io/github/v/release/Hitheshkaranth/EmbeddedDisplayStudio?style=for-the-badge&label=Release&color=006FEE)](../../releases/latest)
[![CI](https://img.shields.io/github/actions/workflow/status/Hitheshkaranth/EmbeddedDisplayStudio/ci.yml?branch=main&style=for-the-badge&label=CI)](https://github.com/Hitheshkaranth/EmbeddedDisplayStudio/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-555555?style=for-the-badge)](LICENSE)
[![Presented at the Berkeley x DeepMind Hackathon](https://img.shields.io/badge/Presented%20at-Berkeley%20%C3%97%20DeepMind%20Hackathon-003262?style=for-the-badge&labelColor=FDB515)](#hackathon)

[![Python](https://img.shields.io/badge/Studio-Python%203.12%20%C2%B7%20PySide6-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Runtime](https://img.shields.io/badge/Panel-C11%20%C2%B7%20LVGL%209.3%20%C2%B7%20DRM%2FKMS-1A5FB4?style=flat-square)](native/hmi-ui/)
[![AI](https://img.shields.io/badge/AI-vLLM%20%C2%B7%20Ollama%20%C2%B7%20OpenAI%20%C2%B7%20Anthropic%20%C2%B7%20Gemini-FF6F00?style=flat-square)](docs/GUIDE.md#ai-design)
[![Yocto](https://img.shields.io/badge/Yocto-meta--hmi-1A5FB4?style=flat-square&logo=yocto&logoColor=white)](yocto/)

**[Quick start](#quick-start)** &nbsp;·&nbsp; **[Features](#features)** &nbsp;·&nbsp; **[How it works](#how-it-works)** &nbsp;·&nbsp; **[Guide](docs/GUIDE.md)** &nbsp;·&nbsp; **[Changelog](CHANGELOG.md)**

<br />

<img src="docs/assets/metro/metro-overview.gif" alt="One brief to a running metro cab display: AI design, Designer finish, Modbus wiring by the agent, deploy, and the live panel" width="900" />

<sub>One sentence to a running <strong>Namma Metro Purple Line</strong> cab display on a real Toradex panel — every step inside the Studio.</sub>

</div>

<br />

<a id="hackathon"></a>

> [!NOTE]
> #### Presented at the Berkeley × DeepMind Hackathon
> EmbeddedDisplay Studio was presented at the **Berkeley × DeepMind Hackathon**: a brief described in plain words, designed by AI, wired to the hardware and deployed to a real embedded panel — live, from one desktop app.

<br />

## Features

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/assets/metro/metro-describe.gif" alt="AI Design generating a cab display from a brief" />
<h4>AI generates the UI</h4>
<sub>Describe the screen in plain words. The model plans the content; a deterministic compiler lays it out for the panel's glass — including a full train cab display from one brief.</sub>
</td>
<td width="50%" valign="top">
<img src="docs/assets/metro/metro-design.gif" alt="Finishing the AI's screen in the Designer" />
<h4>Edit it in the Designer</h4>
<sub>The AI's screen is an ordinary design. Edit text, drop in logos, bind tags, set alarms and actions — then <strong>Tidy up</strong> re-lays the page.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/assets/metro/metro-agent.gif" alt="The coding agent mapping every tag to a Modbus register" />
<h4>A coding agent wires the hardware</h4>
<sub>The IDE's agent maps every value to a Modbus register on your PLC, rebinds the design and proves it with the hardware daemon's self-test.</sub>
</td>
<td width="50%" valign="top">
<img src="docs/assets/metro/metro-deploy.gif" alt="Deploying to the panel and mirroring it live" />
<h4>Deploy with rollback</h4>
<sub>Validate, upload, checksum, atomic swap. If the screen does not render within 25 s the panel rolls itself back. Mirror the live glass in the Studio.</sub>
</td>
</tr>
</table>

<div align="center">
<img src="docs/assets/metro/metro-panel.gif" alt="The real 10.1-inch panel running the cab display" width="560" />
<br /><sub>The deployed design on the real 10.1" panel, driven by the bench simulator.</sub>
</div>

<br />

**Also in the box**

- **The panel's own renderer, everywhere** — canvas and previews are drawn by the same C runtime that runs on the glass, so what you see is what ships.
- **51 widgets** — industrial, avionics, automotive and rail (speed arc, station line, train consist…), each in QML and in C. Save any group as a **custom widget**.
- **Simulate without hardware** — Tag Lab waveforms, and `tagsim` flies a whole aircraft or runs a train between stations so every reading agrees.
- **Operator runtime** — expression bindings, action lists with confirm, alarm priorities, latching and shelving, history, keypad, screen idle.
- **Bring your own Qt app** — PySide6 and PySide2 applications deploy too; the Studio installs their runtime on demand.

## How it works

<div align="center">
<img src="docs/assets/architecture.svg" alt="The Studio edits and previews a design and deploys it over SSH; on the panel, hmi-ui draws it and hmi-hwd owns the hardware" width="860" />
</div>

| | Layer | Owns |
|:-:|---|---|
| **1** | `hmi-hwd` — hardware daemon (C) | GPIO, ADC, serial, Modbus TCP/RTU, CAN, USB/HID, I2C/SPI sensors, history, safe states |
| **2** | `hmi-ui` — panel runtime (C + LVGL, DRM/KMS) | the design file, bindings, alarms, pixels |
| **3** | deployment | atomic install, health check, rollback |

Widgets never touch hardware: they bind to **tags** that arrive over a loopback socket ([the contract](docs/CONTRACT.md)).

## Quick start

> [!TIP]
> No hardware needed: the daemon simulates its I/O and Tag Lab drives any tag a design invents.

**Packaged** — download the Windows or Linux build from the [latest release](../../releases/latest). Nothing to install.

**From source** (Python 3.12):

```bash
python -m pip install -r requirements.txt
python main.py
```

**A panel** (once, over SSH, no reflash):

```bash
ssh-copy-id root@<panel-ip>
python deploy/provision_panel.py --host <panel-ip>
```

Then: **Design → AI Design**, describe the screen → **Simulate** → connect the panel from the device chip → **Deploy**.

## Documentation

| | |
|---|---|
| **[The guide](docs/GUIDE.md)** | The Studio's modes, AI Design, Code, deploying, the runtime, bundles, architecture, hardware |
| **[Contract](docs/CONTRACT.md)** | Wire protocol, bundle format, filesystem layout, reliability rules |
| **[AI layout compiler](docs/AI_LAYOUT_COMPILER.md)** | How a brief becomes a screen |
| **[Code IDE and agent](docs/CODE_SECTION.md)** | The Code mode and its opencode agent |
| **[Hardware daemon and tagsim](daemon/README.md)** | `hmi-hwd`, Modbus, the historian and the bench simulator |
| **[Changelog](CHANGELOG.md)** | Every release |

<details>
<summary><strong>Screenshots</strong></summary>
<br />
<table>
<tr>
<td width="50%"><img src="docs/assets/screens/design.png" alt="Design mode" /><p align="center"><sub>Design</sub></p></td>
<td width="50%"><img src="docs/assets/screens/simulate.png" alt="Simulate mode" /><p align="center"><sub>Simulate</sub></p></td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/screens/code.png" alt="Code mode" /><p align="center"><sub>Code</sub></p></td>
<td width="50%"><img src="docs/assets/screens/deploy.png" alt="Deploy mode" /><p align="center"><sub>Deploy</sub></p></td>
</tr>
</table>
</details>

## What's new

<table>
<tr>
<td width="33%" valign="top"><strong>A hardware daemon in C</strong><br /><sub><code>hmi-hwd</code> drops Python: GPIO, ADC, serial, Modbus TCP/RTU, CAN, USB and HID devices, I2C/SPI sensors and the historian, same wire protocol.</sub></td>
<td width="33%" valign="top"><strong>Connections and a Modbus map</strong><br /><sub>One list of model endpoints for AI Design and the agent; a design's tags become PLC registers in one click, tested against a simulated PLC.</sub></td>
<td width="33%" valign="top"><strong>Find, watch, simulate</strong><br /><sub>Find panels on the network, a link that recovers by itself, clock sync, drop-in images and brand, and Tag Lab simulating the open design.</sub></td>
</tr>
</table>

<br />

<div align="center">

**MIT licensed** — see [`LICENSE`](LICENSE). LVGL and Tabler Icons are MIT; the packaged Studio carries PySide6 and Qt, unmodified, under the LGPL-3.0.

<sub>FLYVI TECHNOLOGIES · EMBEDDED DISPLAY ENGINEERING</sub>

</div>
