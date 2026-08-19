"""
tools/hmi_deployer/deployer.py
Layer: 3 (Host Deployer)
Purpose: Handles the app bundle validation, packaging, and the sequential install
flow (CONTRACT section 4, 6).
"""
import json
import os
import tarfile
import hashlib
from typing import Tuple, List, Dict, Any
import datetime

def validate_bundle(bundle_dir: str) -> Tuple[bool, List[str]]:
    """
    Validates a raw app directory against CONTRACT section 4.
    
    Args:
        bundle_dir: Path to the app folder.
        
    Returns:
        (passed, list_of_error_strings_or_success_message).
    """
    errors = []
    manifest_path = os.path.join(bundle_dir, "manifest.json")
    
    if not os.path.isfile(manifest_path):
        return False, ["manifest.json is missing from the bundle root."]
        
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return False, [f"manifest.json is not valid JSON: {e}"]
        
    if manifest.get("schema") != 1:
        errors.append("manifest.json: 'schema' must be exactly 1.")
        
    name = manifest.get("name", "")
    if not isinstance(name, str) or not name:
        errors.append("manifest.json: 'name' is missing or not a string.")
    else:
        import re
        if not re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", name):
            errors.append("manifest.json: 'name' must be lowercase alphanumeric, dash, dot, or underscore (up to 64 chars).")
            
    entry = manifest.get("entry", "")
    if not isinstance(entry, str) or not entry:
        errors.append("manifest.json: 'entry' is missing or not a string.")
    elif ".." in entry:
        errors.append("manifest.json: 'entry' must not contain '..'.")
    else:
        entry_path = os.path.join(bundle_dir, entry)
        if not os.path.isfile(entry_path):
            errors.append(f"manifest.json: 'entry' file '{entry}' does not exist in the bundle.")
            
    screen = manifest.get("screen")
    if not isinstance(screen, dict) or "width" not in screen or "height" not in screen:
        errors.append("manifest.json: 'screen' must be an object with 'width' and 'height'.")
        
    tags = manifest.get("tags_required")
    if not isinstance(tags, list):
        errors.append("manifest.json: 'tags_required' must be a list of strings.")
        
    qt_ver = manifest.get("qt")
    if not isinstance(qt_ver, str):
        errors.append("manifest.json: 'qt' must be a string (e.g., '>=6.5').")
        
    if errors:
        return False, errors
    return True, ["Bundle is valid."]

def package_bundle(bundle_dir: str, output_dir: str) -> Tuple[str, str]:
    """
    Creates a gzip tarball of the bundle and its SHA256 checksum.
    
    Args:
        bundle_dir: Path to the app folder to pack.
        output_dir: Path where the .tar.gz and .sha256 should be placed.
        
    Returns:
        (tar_path, sha256_path)
    """
    with open(os.path.join(bundle_dir, "manifest.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    name = manifest.get("name", "app")
    
    # Release id: <name>-<UTC yyyymmddTHHMMSSZ>
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    release_id = f"{name}-{timestamp}"
    
    tar_name = f"{release_id}.tar.gz"
    tar_path = os.path.join(output_dir, tar_name)
    
    with tarfile.open(tar_path, "w:gz") as tar:
        for item in os.listdir(bundle_dir):
            item_path = os.path.join(bundle_dir, item)
            tar.add(item_path, arcname=item)
            
    # Compute SHA256
    sha256_hash = hashlib.sha256()
    with open(tar_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    checksum = sha256_hash.hexdigest()
    
    sha256_path = tar_path + ".sha256"
    with open(sha256_path, "w", encoding="utf-8") as f:
        f.write(f"{checksum}  {tar_name}\n")
        
    return tar_path, sha256_path
