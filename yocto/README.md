# Yocto Integrator Guide (meta-hmi)

Comprehensive integration guide for building the BYOA HMI stack into the native Toradex Yocto Reference Multimedia Image for the **Toradex Verdin i.MX8M Plus** System on Module (SoM).

---

## 1. Overview and Architecture

The `meta-hmi` layer integrates the three BYOA layers directly into the native root filesystem of the Toradex Reference Multimedia Image:

* **Layer 1 (`hmi-core`):** Hardware daemon (`hmi_hwd.py`), pin mapping (`hwd.json`), atomic installer (`hmi-install`), launcher wrappers (`hmi-gui-launch`, `hmi-hwd-launch`), systemd units (`hmi-hwd.service`, `hmi-gui.service`), and tmpfiles configuration.
* **Layer 2 (`hmi-gui`):** Python/PySide6 Qt6 GUI application loader and top-level QML shell.
* **Layer 3 (`hmi-ui-kit`):** Standalone Shadcn-derived QML component library, token definitions, and Tabler icon registry.
* **Packagegroup (`packagegroup-hmi`):** Aggregates all HMI components plus deployment utilities (`openssh-sftp-server`, `util-linux` for `flock`, `coreutils`, `weston`).
* **Image Append (`tdx-reference-multimedia-image.bbappend`):** Automatically injects `packagegroup-hmi` into the multimedia image.

> [!IMPORTANT]
> This integration targets the **native Toradex Yocto Reference Multimedia Image** (Wayland/Weston display server, systemd, running on bare metal). It is **not** for Torizon OS, Docker, or containerized runtime environments.

---

## 2. Prerequisite Layers and Branch Setup

### 2.1 Required Layer Stack

Ensure your Yocto build environment includes the following layers in `bblayers.conf`:

| Layer | Repository URL | Purpose |
|---|---|---|
| `openembedded-core` / `poky` | `git://git.openembedded.org/openembedded-core` | Core Yocto build system and base recipes. |
| `meta-openembedded/meta-oe` | `git://git.openembedded.org/meta-openembedded` | General utilities, development tools, and Python libraries. |
| `meta-freescale` | `git://git.yoctoproject.org/meta-freescale` | NXP i.MX8M Plus BSP and hardware acceleration support. |
| `meta-toradex-bsp-common` | `git://git.toradex.com/meta-toradex-bsp-common.git` | Toradex base hardware abstraction layer. |
| `meta-toradex-nxp` | `git://git.toradex.com/meta-toradex-nxp.git` | Toradex NXP-specific machine definitions and kernel recipes. |
| `meta-qt6` | `git://code.qt.io/yocto/meta-qt6.git` | Qt 6 and PySide6 bindings (required for `hmi-gui`). |
| `meta-hmi` | *(this repository)*: `yocto/meta-hmi` | BYOA HMI recipes, packagegroups, and image appends. |

### 2.2 Branch Compatibility and the PySide6 / meta-qt6 Caveat

The `meta-hmi` layer supports the following Yocto release codenames (mapped to Toradex BSP releases):

* **Yocto 5.0 (`scarthgap`):** Primary target for **Toradex BSP 7.x LTS**.
* **Yocto 4.2 / 4.3 (`mickledore` / `nanbield`):** Toradex BSP 6.x.
* **Yocto 4.0 (`kirkstone`):** Toradex BSP 5.x LTS.

#### The PySide6 Branch Caveat
`hmi-gui_1.0.bb` depends on `python3-pyside6` provided by `meta-qt6`.
1. Clone `meta-qt6` matching your exact Yocto branch:
   ```bash
   git clone -b scarthgap git://code.qt.io/yocto/meta-qt6.git layers/meta-qt6
   ```
2. **Alternative for C++ Integrators:** If your organization cannot deploy Python/PySide6 due to image footprint or licensing constraints, you can replace `/usr/lib/hmi/gui/main.py` with a compiled C++ Qt Quick executable (`QQmlApplicationEngine`). The install paths and `import Shadcn 1.0` QML interface remain identical.

---

## 3. Adding the Layer (`bitbake-layers`)

Add the required layers to your active build environment:

```bash
# Initialize the build environment
source setup-environment build

# Add meta-oe, meta-qt6, and meta-hmi
bitbake-layers add-layer ../layers/meta-openembedded/meta-oe
bitbake-layers add-layer ../layers/meta-qt6
bitbake-layers add-layer /path/to/EmbeddedDisplay/yocto/meta-hmi

# Verify that all layers are registered
bitbake-layers show-layers
```

---

## 4. Source Mapping for Local Workspace Development (`file://` URIs)

During local development and testing, recipes fetch files directly from their local `files/` subdirectories via `file://` URIs.

Below are the exact shell commands to populate the `files/` directories from the repository source trees (`daemon/`, `target/`, `gui/`, `ui/`):

### 4.1 Recipe: `hmi-core`
```bash
# Path to hmi-core recipe files directory
CORE_FILES="yocto/meta-hmi/recipes-hmi/hmi-core/files"
mkdir -p "${CORE_FILES}"

# Link or copy Layer 1 daemon and config
cp daemon/hmi_hwd.py            "${CORE_FILES}/hmi_hwd.py"
cp schema/manifest.py           "${CORE_FILES}/manifest.py"
cp daemon/hwd.json              "${CORE_FILES}/hwd.json"

# Link or copy Layer 3 target scripts and units
cp target/bin/hmi-install       "${CORE_FILES}/hmi-install"
cp target/bin/hmi-gui-launch    "${CORE_FILES}/hmi-gui-launch"
cp target/bin/hmi-hwd-launch    "${CORE_FILES}/hmi-hwd-launch"
cp target/etc/default/hmi-gui   "${CORE_FILES}/hmi-gui.default"
cp target/tmpfiles/hmi.conf     "${CORE_FILES}/hmi.conf"
cp target/systemd/hmi-hwd.service "${CORE_FILES}/hmi-hwd.service"
cp target/systemd/hmi-gui.service "${CORE_FILES}/hmi-gui.service"
```

### 4.2 Recipe: hmi-gui
```bash
# Path to hmi-gui recipe files directory
GUI_FILES="yocto/meta-hmi/recipes-hmi/hmi-gui/files"
mkdir -p "${GUI_FILES}"

# Copy GUI loader, tag engine, and shell QML screens
cp gui/hmi_loader/main.py       "${GUI_FILES}/main.py"
cp gui/hmi_loader/tagengine.py  "${GUI_FILES}/tagengine.py"
cp gui/shell/Shell.qml          "${GUI_FILES}/Shell.qml"
cp gui/shell/Fallback.qml       "${GUI_FILES}/Fallback.qml"
```

### 4.3 Recipe: hmi-ui-kit
```bash
# Path to hmi-ui-kit recipe files directory
UI_FILES="yocto/meta-hmi/recipes-hmi/hmi-ui-kit/files"
mkdir -p "${UI_FILES}"

# Copy the Shadcn QML component directory
cp -r ui/qml/Shadcn "${UI_FILES}/Shadcn"

# Copy tokens.json
cp ui/tokens.json "${UI_FILES}/tokens.json"

# Copy Tabler icon license
cp ui/icons/LICENSE.tabler "${UI_FILES}/LICENSE.tabler"
```

---

## 5. Production Configuration: Git Source Fetch (`git://` URIs)

For automated CI/CD and release builds, replace the `file://` entries in recipes with remote `git://` URIs locked to a specific commit hash (`SRCREV`):

### Example Production `hmi-core_1.0.bb` Recipe Header:
```bitbake
SRC_URI = "git://github.com/example-org/embedded-display.git;protocol=https;branch=main"
SRCREV = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"

S = "${WORKDIR}/git"

do_install() {
    install -d ${D}${libdir}/hmi
    install -m 0644 ${S}/daemon/hmi_hwd.py ${D}${libdir}/hmi/hmi_hwd.py

    install -d ${D}${sysconfdir}/hmi
    install -m 0640 ${S}/daemon/hwd.json ${D}${sysconfdir}/hmi/hwd.json

    install -d ${D}${bindir}
    install -m 0755 ${S}/target/bin/hmi-install     ${D}${bindir}/hmi-install
    install -m 0755 ${S}/target/bin/hmi-gui-launch  ${D}${bindir}/hmi-gui-launch
    install -m 0755 ${S}/target/bin/hmi-hwd-launch  ${D}${bindir}/hmi-hwd-launch

    install -d ${D}${sysconfdir}/default
    install -m 0644 ${S}/target/etc/default/hmi-gui ${D}${sysconfdir}/default/hmi-gui

    install -d ${D}${nonarch_libdir}/tmpfiles.d
    install -m 0644 ${S}/target/tmpfiles/hmi.conf   ${D}${nonarch_libdir}/tmpfiles.d/hmi.conf

    install -d ${D}${systemd_unitdir}/system
    install -m 0644 ${S}/target/systemd/hmi-hwd.service ${D}${systemd_unitdir}/system/hmi-hwd.service
    install -m 0644 ${S}/target/systemd/hmi-gui.service ${D}${systemd_unitdir}/system/hmi-gui.service

    install -d ${D}/opt/hmi_apps
    install -d ${D}/opt/hmi_apps/releases
}
```

---

## 6. Required `conf/local.conf` Configuration

Add the following settings to your `build/conf/local.conf`:

```bitbake
# 1. Target Machine Architecture
MACHINE = "verdin-imx8mp"

# 2. Systemd and Wayland Distro Features
DISTRO_FEATURES:append = " systemd wayland pam"
DISTRO_FEATURES_BACKFILL_CONSIDERED += "sysvinit"
VIRTUAL-RUNTIME_init_manager = "systemd"
VIRTUAL-RUNTIME_initscripts = "systemd-compat-units"

# 3. Enable OpenSSH Server for Deployment Pipeline
# OpenSSH provides SFTP subsystem and ControlMaster support required by deploy_to_hmi.sh
EXTRA_IMAGE_FEATURES:append = " ssh-server-openssh"

# 4. GPIO Bindings Selection (BSP 6/7 default is python3-libgpiod; BSP 5 is libgpiod-python)
HMI_GPIOD_PYTHON = "python3-libgpiod"

# 5. LAB BRING-UP ONLY - never build a shipping image with these.
#    They permit root login with no password over SSH, which on a machine
#    control panel means anyone on the network can deploy arbitrary code and
#    actuate outputs. Delete these two features before any image leaves the
#    bench, and deploy with an SSH key plus the forced-command hardening
#    described in deploy/README.md instead.
EXTRA_IMAGE_FEATURES:append = " allow-empty-password empty-root-password"
```

---

## 7. Building the Image with BitBake

Build the full reference multimedia image containing the HMI stack:

```bash
# Build the complete target image
bitbake tdx-reference-multimedia-image

# Alternatively, build only the HMI packagegroup or individual components
bitbake packagegroup-hmi
bitbake hmi-core
bitbake hmi-gui
bitbake hmi-ui-kit
```

The resulting image artifacts (`.wic.gz` or `.tezi.tar` for Toradex Easy Installer) will be located in:
`build/deploy/images/verdin-imx8mp/`

---

## 8. Target Verification Checklist

Once the image is flashed onto the Toradex Verdin i.MX8M Plus, verify the subsystem on the target console:

### 8.1 Service Status Verification
```bash
# Verify Layer 1 Hardware Daemon
systemctl status hmi-hwd.service

# Verify Layer 2 GUI Launcher
systemctl status hmi-gui.service
```

### 8.2 Live Journal Logging
```bash
# Follow logs for both units
journalctl -u hmi-hwd -u hmi-gui -f
```

### 8.3 Application Directory and Symlink Verification
```bash
# Check application root and permissions
ls -ld /opt/hmi_apps /opt/hmi_apps/releases

# Check installer status
/usr/bin/hmi-install status
```

### 8.4 Loopback Hardware Daemon Test
```bash
# Send a ping command to the hardware daemon on UDP 5000
python3 -c '
import socket, json
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2.0)
s.sendto(json.dumps({"id":"test-1", "cmd":"ping"}).encode("utf-8"), ("127.0.0.1", 5000))
print("Ack:", s.recvfrom(1024)[0].decode("utf-8"))
'
```
