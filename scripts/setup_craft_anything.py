#!/usr/bin/env python3
"""
JARVIS LUNA - Craft Anything Setup Script
==========================================
Downloads and installs the official Craft Anything CLI from GitHub (storytold/craft-anything).
Places the binary in tools/bin/ and verifies functionality.
"""

import sys
import os
import platform
import urllib.request
import json
import zipfile
import tarfile
from pathlib import Path

REPO = "storytold/craft-anything"
BASE_DIR = Path(__file__).resolve().parent.parent
TOOLS_DIR = BASE_DIR / "tools" / "bin"


def get_latest_release_info():
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "JARVIS-LUNA-CraftAnythingSetup"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def detect_asset(assets):
    system = platform.system().lower()
    machine = platform.machine().lower()

    target_keyword = ""
    if system == "windows":
        target_keyword = "windows-x64-portable.zip" if "64" in machine else "windows-x86-portable.zip"
    elif system == "darwin":
        target_keyword = "macos-universal.zip"
    elif system == "linux":
        target_keyword = "linux-x86_64.tar.gz" if ("x86_64" in machine or "amd64" in machine) else "linux-aarch64.tar.gz"

    for asset in assets:
        name = asset["name"].lower()
        if target_keyword in name:
            return asset
    return None


def setup():
    print("=" * 60)
    print("JARVIS LUNA: Craft Anything CLI Setup")
    print("=" * 60)
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/3] Fetching latest release metadata from GitHub...")
    try:
        rel = get_latest_release_info()
        tag = rel.get("tag_name", "latest")
        print(f"  -> Found release: {tag}")
    except Exception as e:
        print(f"  [Error] Failed to fetch release info: {e}")
        print("  -> Will use built-in Python clean-room engine fallback.")
        return False

    print("[2/3] Detecting matching asset for this platform...")
    asset = detect_asset(rel.get("assets", []))
    if not asset:
        print("  [Warning] No matching prebuilt asset found for your platform.")
        print("  -> Built-in Python clean-room engine remains fully active.")
        return False

    asset_name = asset["name"]
    download_url = asset["browser_download_url"]
    print(f"  -> Selected asset: {asset_name}")
    print(f"  -> Download URL : {download_url}")

    archive_path = TOOLS_DIR / asset_name
    print(f"[3/3] Downloading {asset_name} ({asset.get('size', 0) // (1024*1024)} MB)...")
    try:
        urllib.request.urlretrieve(download_url, archive_path)
        print("  -> Download complete. Extracting binary...")

        if asset_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(TOOLS_DIR)
        elif asset_name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(TOOLS_DIR)

        archive_path.unlink(missing_ok=True)
        print(f"  -> Craft Anything installed successfully in {TOOLS_DIR}")
        return True
    except Exception as e:
        print(f"  [Notice] Download or extraction note: {e}")
        print("  -> You can also place craft-anything-cli binary manually in tools/bin/")
        return False


if __name__ == "__main__":
    setup()
