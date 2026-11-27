"""Exercise publication against an IPA fixture without network or credentials."""

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import zipfile


MODULE_PATH = Path(__file__).resolve().parents[1] / "publish-altstore-source.py"
SPEC = importlib.util.spec_from_file_location("publish_altstore_source", MODULE_PATH)
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class PublishSourceTest(unittest.TestCase):
    def test_feed_matches_the_ipa_and_classic_date_format(self):
        with tempfile.TemporaryDirectory() as directory:
            ipa = Path(directory) / "PocketPal-unsigned.ipa"
            info = {
                "CFBundleShortVersionString": "1.24.0",
                "CFBundleVersion": "42",
                "CFBundleIdentifier": "ai.pocketpal.fixture",
                "MinimumOSVersion": "18.0",
                "NSLocalNetworkUsageDescription": "Serve the local model.",
            }
            with zipfile.ZipFile(ipa, "w") as archive:
                archive.writestr("Payload/PocketPal.app/Info.plist", plistlib.dumps(info))
            api_calls = []

            def github(path, method="GET", payload=None, missing=False):
                api_calls.append((path, method, payload))
                return None

            environment = {
                "GH_REPO": "fixture/pocketpal-ai",
                "GITHUB_SHA": "abcdef1234567890",
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "1",
            }
            with patch.dict(os.environ, environment), patch.object(publisher, "github", github), \
                    patch.object(publisher.subprocess, "run") as release, \
                    patch("sys.argv", ["publish-altstore-source.py", "--ipa", str(ipa)]):
                publisher.main()

            upload = next(payload for path, method, payload in api_calls if method == "PUT")
            feed = json.loads(base64.b64decode(upload["content"]))
            self.assertEqual(feed, json.loads((Path(directory) / "source.json").read_text()))
            app = feed["apps"][0]
            version = app["versions"][0]
            self.assertEqual(app["bundleIdentifier"], info["CFBundleIdentifier"])
            self.assertEqual(version["version"], "1.24.0")
            self.assertEqual(version["buildVersion"], "42")
            self.assertEqual(version["size"], ipa.stat().st_size)
            self.assertEqual(version["sha256"], hashlib.sha256(ipa.read_bytes()).hexdigest())
            # Classic's formatter enables full date/time/timezone, not fractional seconds.
            self.assertRegex(version["date"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")
            self.assertEqual(app["appPermissions"]["privacy"], {
                "NSLocalNetworkUsageDescription": info["NSLocalNetworkUsageDescription"],
            })
            self.assertEqual(app["appPermissions"]["entitlements"], [])
            release.assert_called_once()
            self.assertIn("--target", release.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
