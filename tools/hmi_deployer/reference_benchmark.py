"""Reproduce an image-only AI Designer run without deploying to a device.

python -m tools.hmi_deployer.reference_benchmark --help
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New evidence directory")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider", default="custom")
    parser.add_argument("--api-key-env", default="HMI_AI_API_KEY")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=768)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Use a new output directory so evidence from different runs is never mixed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from tools.hmi_deployer.ai_design import ODConnector, ProviderConfig, load_brief_image
    from tools.hmi_deployer.reference_workflow import prepare_reference_images
    from tools.hmi_deployer.reference_pipeline import generate_reference
    app = QApplication.instance() or QApplication([])
    connector = ODConnector(mode="byok", byok=ProviderConfig(
        args.provider, args.model, baseUrl=args.base_url,
        apiKey=os.environ.get(args.api_key_env, "")))
    images = prepare_reference_images([load_brief_image(str(args.image))])
    last = [time.monotonic()]
    def emit(event):
        if event.get("type") == "status":
            print(event.get("label", event.get("message", "")), flush=True)
        elif time.monotonic() - last[0] > 20:
            print("Classifying measured elements…", flush=True)
            last[0] = time.monotonic()
    result = generate_reference(connector, "Reconstruct this image as an editable HMI with simulated readings.",
                                args.model, images, args.width, args.height, emit, args.output)
    report = result["report"]
    print(json.dumps({key: report.get(key) for key in (
        "passed", "gates", "source_text_count", "simulation_tag_count", "rendered_text_needs_review",
        "visual_match_verified", "runtime_verified", "elapsed_seconds")}, indent=2))
    print("Evidence:", args.output.resolve())
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
