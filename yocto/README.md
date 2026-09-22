# Yocto Integrator Guide (meta-hmi)

Comprehensive integration guide for building the HMI stack into the native Toradex Yocto Reference Multimedia Image for the **Toradex Verdin i.MX8M Plus** System on Module (SoM). The stack is Qt-free: the panel GUI is `native/hmi-ui` (C + LVGL) drawing to DRM/KMS with no compositor.

---

## 1. Overview and Architecture

The `meta-hmi` layer integrates the HMI layers directly into the native root filesystem of the Toradex Reference Multimedia Image:

* **Layer 1 (`hmi-core`):** Hardware daemon (`hmi_hwd.py`), pin mapping (`hwd.json`), atomic installer (`hmi-install`), the daemon launcher (`hmi-hwd-launch`), systemd units (`hmi-hwd.service`, `hmi-ui.service`), `/etc/default/hmi-ui` and tmpfiles configuration.
* **Layer 2 (`hmi-ui`):** The panel GUI runtime — `native/hmi-ui`, C11 + LVGL 9.3, drawing straight to DRM/KMS. It interprets the deployed bundle's `project.edsui`; no QML, no Qt, no compositor on the panel.
* **Kit (`hmi-ui-kit`):** The Inter fonts and the Tabler icons rasterised to PNG, installed to `/usr/lib/hmi/kit`.
* **Packagegroup (`packagegroup-hmi`):** Aggregates the packages above plus deployment utilities (`openssh-sftp-server`, `util-linux` for `flock`, `coreutils`) and `libdrm`.
* **Image Append (`tdx-reference-multimedia-image.bbappend`):** Automatically injects `packagegroup-hmi` into the multimedia image.

> [!IMPORTANT]
> This integration targets the **native Toradex Yocto Reference Multimedia Image** (systemd, running on bare metal). The image's Weston is not used: `hmi-ui.service` declares `Conflicts=weston.service` and owns the display. It is **not** for Torizon OS, Docker, or containerized runtime environments.

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
| `meta-hmi` | *(this repository)*: `yocto/meta-hmi` | BYOA HMI recipes, packagegroups, and image appends. |

### 2.2 Branch Compatibility

The `meta-hmi` layer supports the following Yocto release codenames (mapped to Toradex BSP releases):

* **Yocto 5.0 (`scarthgap`):** Primary target for **Toradex BSP 7.x LTS**.
* **Yocto 4.2 / 4.3 (`mickledore` / `nanbield`):** Toradex BSP 6.x.
* **Yocto 4.0 (`kirkstone`):** Toradex BSP 5.x LTS.

`hmi-ui` needs only `libdrm` (in every Toradex reference image) and a C11 toolchain; there is no Qt layer to match to a branch.

---

## 3. Adding the Layer (`bitbake-layers`)

Add the required layers to your active build environment:

```bash
# Initialize the build environment
source setup-environment build

# Add meta-oe and meta-hmi
bitbake-layers add-layer ../layers/meta-openembedded/meta-oe
bitbake-layers add-layer /path/to/EmbeddedDisplay/yocto/meta-hmi

# Verify that all layers are registered
bitbake-layers show-layers
```

---

## 4. Source Mapping for Local Workspace Development (`file://` URIs)

During local development and testing, recipes fetch files directly from their local `files/` subdirectories via `file://` URIs.

Below are the exact shell commands to populate the `files/` directories from the repository source trees (`daemon/`, `target/`, `native/hmi-ui/`, `ui/`):

### 4.1 Recipe: `hmi-core`
```bash
# Path to hmi-core recipe files directory
CORE_FILES="yocto/meta-hmi/recipes-hmi/hmi-core/files"
mkdir -p "${CORE_FILES}"

# Link or copy Layer 1 daemon and config
cp daemon/hmi_hwd.py            "${CORE_FILES}/hmi_hwd.py"
cp daemon/modbus.py             "${CORE_FILES}/modbus.py"
cp schema/manifest.py           "${CORE_FILES}/manifest.py"
cp daemon/hwd.json              "${CORE_FILES}/hwd.json"

# Link or copy Layer 3 target scripts and units
cp target/bin/hmi-install       "${CORE_FILES}/hmi-install"
cp target/bin/hmi-hwd-launch    "${CORE_FILES}/hmi-hwd-launch"
cp target/etc/default/hmi-ui    "${CORE_FILES}/hmi-ui.default"
cp target/tmpfiles/hmi.conf     "${CORE_FILES}/hmi.conf"
cp target/systemd/hmi-hwd.service "${CORE_FILES}/hmi-hwd.service"
cp target/systemd/hmi-ui.service  "${CORE_FILES}/hmi-ui.service"
```

### 4.2 Recipe: hmi-ui
```bash
# Path to hmi-ui recipe files directory
UI_SRC="yocto/meta-hmi/recipes-hmi/hmi-ui/files"
mkdir -p "${UI_SRC}"

# The runtime's source tree, with its pinned LVGL submodule checked out.
git submodule update --init native/hmi-ui/lvgl
rsync -a --exclude out --exclude '.cache' native/hmi-ui/ "${UI_SRC}/hmi-ui/"
```

### 4.3 Recipe: hmi-ui-kit
```bash
# Path to hmi-ui-kit recipe files directory
KIT_FILES="yocto/meta-hmi/recipes-hmi/hmi-ui-kit/files"
mkdir -p "${KIT_FILES}"

# The fonts and the rasterised icons (regenerate with
# python native/hmi-ui/schema/gen_icons.py when TablerIcons.js changes)
cp -r ui/qml/Shadcn/fonts "${KIT_FILES}/fonts"
cp -r ui/qml/Shadcn/icons "${KIT_FILES}/icons"
cp ui/icons/LICENSE.tabler "${KIT_FILES}/LICENSE.tabler"
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
    install -m 0755 ${S}/target/bin/hmi-hwd-launch  ${D}${bindir}/hmi-hwd-launch

    install -d ${D}${sysconfdir}/default
    install -m 0644 ${S}/target/etc/default/hmi-ui  ${D}${sysconfdir}/default/hmi-ui

    install -d ${D}${nonarch_libdir}/tmpfiles.d
    install -m 0644 ${S}/target/tmpfiles/hmi.conf   ${D}${nonarch_libdir}/tmpfiles.d/hmi.conf

    install -d ${D}${systemd_unitdir}/system
    install -m 0644 ${S}/target/systemd/hmi-hwd.service ${D}${systemd_unitdir}/system/hmi-hwd.service
    install -m 0644 ${S}/target/systemd/hmi-ui.service  ${D}${systemd_unitdir}/system/hmi-ui.service

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

# 2. Systemd Distro Features (the reference image also has wayland; harmless)
DISTRO_FEATURES:append = " systemd pam"
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
bitbake hmi-ui
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

# Verify Layer 2 GUI runtime
systemctl status hmi-ui.service
```

### 8.2 Live Journal Logging
```bash
# Follow logs for both units
journalctl -u hmi-hwd -u hmi-ui -f
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
