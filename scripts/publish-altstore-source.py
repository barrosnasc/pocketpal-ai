#!/usr/bin/env python3
"""Publish a checked unsigned IPA and update the personal AltStore feed.

Only GitHub credentials are used. Apple credentials never enter CI.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
from datetime import datetime, timezone
import zipfile


def github(path, method="GET", payload=None, missing=False):
    command = ["gh", "api", "--method", method, path]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        if missing and "404" in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ipa", type=Path, required=True)
    args = parser.parse_args()
    repository = os.environ["GH_REPO"]
    commit = os.environ["GITHUB_SHA"]
    tag = f"ios-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
    with zipfile.ZipFile(args.ipa) as archive:
        roots = [
            name for name in archive.namelist()
            if name.startswith("Payload/") and name.count("/") == 2
            and name.endswith(".app/Info.plist")
        ]
        if len(roots) != 1:
            raise RuntimeError("Expected exactly one main app Info.plist")
        info = plistlib.loads(archive.read(roots[0]))
    version = info["CFBundleShortVersionString"]
    build = info["CFBundleVersion"]
    digest = hashlib.file_digest(args.ipa.open("rb"), "sha256").hexdigest()
    notes = args.ipa.parent / "release-notes.txt"
    notes.write_text(
        f"Build pessoal do PocketPal AI {version} ({build}).\n\n"
        f"Commit: {commit}\nSHA-256: {digest}\n\n"
        "IPA sem assinatura Apple, destinado ao AltStore Classic. "
        "Plus incluído pelo mecanismo oficial dos builds de código-fonte. "
        "Nenhuma credencial Apple é utilizada no GitHub Actions.\n"
    )
    subprocess.run([
        "gh", "release", "create", tag, str(args.ipa),
        "--repo", repository, "--target", commit,
        "--title", f"PocketPal pessoal {version} ({build})",
        "--notes-file", str(notes), "--latest=false",
    ], check=True)
    branch = "altstore-feed"
    if github(f"repos/{repository}/git/ref/heads/{branch}", missing=True) is None:
        github(f"repos/{repository}/git/refs", "POST", {
            "ref": f"refs/heads/{branch}", "sha": commit,
        })
    previous = github(f"repos/{repository}/contents/source.json?ref={branch}", missing=True)
    old_versions = []
    if previous:
        source = json.loads(base64.b64decode(previous["content"]))
        old_versions = source.get("apps", [{}])[0].get("versions", [])
    entry = {
        "version": version,
        "buildVersion": build,
        "marketingVersion": f"{version} · build pessoal {build}",
        # AltStore's ISO8601DateFormatter does not enable fractional seconds.
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "localizedDescription": f"Build pessoal do commit {commit[:12]}. Plus incluído.",
        "downloadURL": f"https://github.com/{repository}/releases/download/{tag}/{args.ipa.name}",
        "size": args.ipa.stat().st_size,
        "sha256": digest,
        "minOSVersion": info.get("MinimumOSVersion", "18.0"),
    }
    versions = [entry] + [
        item for item in old_versions
        if (item["version"], item.get("buildVersion")) != (version, build)
    ]
    source = {
        "name": "PocketPal pessoal",
        "subtitle": "Builds próprios para inferência local no iPhone",
        "identifier": f"dev.{repository.split('/')[0]}.pocketpal-source",
        "website": f"https://github.com/{repository}",
        "apps": [{
            "name": "PocketPal AI — build pessoal",
            "bundleIdentifier": info["CFBundleIdentifier"],
            "developerName": "PocketPal contributors · build pessoal",
            "localizedDescription": "PocketPal AI compilado do código-fonte MIT, com Plus incluído pelo projeto. Inferência local com Metal e API de chat na LAN. Build pessoal; sem vínculo oficial com os mantenedores.",
            "iconURL": f"https://raw.githubusercontent.com/{repository}/ios-server/src/assets/pocketpal-dark-v2.png",
            "category": "developer",
            "versions": versions[:10],
            "appPermissions": {
                # This artifact has no code signature / signed entitlements.
                "entitlements": [],
                "privacy": {key: value for key, value in info.items() if key.endswith("UsageDescription")},
            },
        }],
        "news": [],
    }
    encoded = base64.b64encode((json.dumps(source, ensure_ascii=False, indent=2) + "\n").encode()).decode()
    payload = {
        "message": f"chore: publish PocketPal {version} ({build})",
        "content": encoded,
        "branch": branch,
    }
    if previous:
        payload["sha"] = previous["sha"]
    github(f"repos/{repository}/contents/source.json", "PUT", payload)
    (args.ipa.parent / "source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n")
    print(f"Fonte AltStore: https://raw.githubusercontent.com/{repository}/{branch}/source.json")


if __name__ == "__main__":
    main()
