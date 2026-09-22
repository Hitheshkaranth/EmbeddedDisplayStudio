# recipes-images/tdx-reference-multimedia-image.bbappend
#
# Extends the native Toradex Yocto Reference Multimedia Image with the
# BYOA HMI stack for Toradex Verdin i.MX8M Plus.
#
# IMPORTANT ARCHITECTURE NOTE:
# This append targets ONLY the native Toradex Reference Multimedia Image
# (systemd init manager, direct hardware rootfs). The HMI draws to DRM/KMS
# itself: the image's Weston is not used and hmi-ui.service conflicts with
# it. It is NOT intended for Torizon OS, Docker, or containerized environments.
#
# INTEGRATION PREREQUISITE:
# The deployment pipeline (deploy_to_hmi.sh) uses OpenSSH features
# including ControlMaster multiplexing and SFTP file transfer.
# Ensure your build configuration (local.conf) enables the OpenSSH server:
#     EXTRA_IMAGE_FEATURES:append = " ssh-server-openssh"

# ---------------------------------------------------------------------------
# IMAGE_INSTALL:append
#
# Appends packagegroup-hmi to the root filesystem package list.
# packagegroup-hmi pulls in:
#   1. hmi-core (hardware abstraction daemon, hwd.json, hmi-install, systemd units)
#   2. hmi-ui (the Qt-free GUI runtime: C + LVGL on DRM/KMS)
#   3. hmi-ui-kit (Inter fonts and Tabler icon PNGs)
#   4. Required deployment utilities (openssh-sftp-server, util-linux flock, coreutils)
# ---------------------------------------------------------------------------
IMAGE_INSTALL:append = " packagegroup-hmi"
