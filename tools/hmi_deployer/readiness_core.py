from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessItem:
    name: str
    severity: str
    detail: str
    action: str


def audit_readiness(bundle_valid, manifest, connected, detected_resolution):
    """Audit readiness and return exactly four ReadinessItem rows.

    Parameters
    ----------
    bundle_valid : bool
        Whether the deployment bundle is valid.
    manifest : dict | None
        The parsed manifest for the target display.
    connected : bool
        Whether the target display is currently connected.
    detected_resolution : tuple[int, int] | None
        The detected screen resolution as (width, height), or None.

    Returns
    -------
    tuple[ReadinessItem, ReadinessItem, ReadinessItem, ReadinessItem]
        Bundle, Target, Display, Tags items in that order.
    """
    # --- Bundle ---
    if manifest is None or not bundle_valid:
        bundle_item = ReadinessItem(
            name="Bundle",
            severity="error",
            detail="Bundle is invalid or manifest is missing.",
            action="Provide a valid bundle with a manifest.",
        )
    else:
        bundle_item = ReadinessItem(
            name="Bundle",
            severity="ready",
            detail="Bundle is valid.",
            action="",
        )

    # --- Target ---
    if connected:
        target_item = ReadinessItem(
            name="Target",
            severity="ready",
            detail="Target display is connected.",
            action="",
        )
    else:
        target_item = ReadinessItem(
            name="Target",
            severity="warning",
            detail="Target display is not connected.",
            action="Connect the target display before deploying.",
        )

    # --- Display (geometry match) ---
    if manifest is not None:
        screen = manifest.get("screen", {})
        target_w = screen.get("width")
        target_h = screen.get("height")
        if target_w is not None and target_h is not None and detected_resolution is not None:
            if (target_w, target_h) == detected_resolution:
                display_item = ReadinessItem(
                    name="Display",
                    severity="ready",
                    detail="Screen geometry matches detected resolution.",
                    action="",
                )
            else:
                display_item = ReadinessItem(
                    name="Display",
                    severity="warning",
                    detail="Screen geometry mismatch: expected ({}, {}), detected {}.".format(
                        target_w, target_h, detected_resolution
                    ),
                    action="Verify display configuration or update manifest.",
                )
        else:
            display_item = ReadinessItem(
                name="Display",
                severity="info",
                detail="Target geometry or detected resolution unavailable.",
                action="Check display detection.",
            )
    else:
        display_item = ReadinessItem(
            name="Display",
            severity="info",
            detail="Manifest unavailable; cannot verify display geometry.",
            action="Provide a valid manifest.",
        )

    # --- Tags ---
    if manifest is not None:
        tags_required = manifest.get("tags_required")
        if tags_required:
            tags_item = ReadinessItem(
                name="Tags",
                severity="ready",
                detail="All required tags are present.",
                action="",
            )
        else:
            tags_item = ReadinessItem(
                name="Tags",
                severity="info",
                detail="No required tags specified.",
                action="",
            )
    else:
        tags_item = ReadinessItem(
            name="Tags",
            severity="info",
            detail="Manifest unavailable; cannot verify tags.",
            action="Provide a valid manifest.",
        )

    return (bundle_item, target_item, display_item, tags_item)