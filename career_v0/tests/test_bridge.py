from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from career_v0.bridge import BridgeError, run, _upload_bytes
from career_v0.domain import DomainError
from career_v0.tests.test_m1 import SYNTHETIC_MASTER, preferences


class HostBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.master = self.state / "master.md"
        self.master.write_bytes(SYNTHETIC_MASTER)

    def tearDown(self):
        self.tmp.cleanup()

    def test_owner_action_requires_host_secret(self):
        created = run({"op": "create_campaign", "preferences": preferences()},
                      state_dir=self.state, master_path=self.master, owner_secret=None)["campaign"]
        with self.assertRaisesRegex(DomainError, "Owner action"):
            run({"op": "confirm_campaign", "campaign_id": created["campaign_id"]},
                state_dir=self.state, master_path=self.master, owner_secret=None)
        confirmed = run({"op": "confirm_campaign", "campaign_id": created["campaign_id"]},
                        state_dir=self.state, master_path=self.master, owner_secret="host-only-proof")["campaign"]
        self.assertEqual(confirmed["confirmed_by"], "OWNER")

    def test_upload_must_be_host_owned_and_bounded(self):
        external = self.state / "external.xlsx"
        external.write_bytes(b"bytes")
        with self.assertRaisesRegex(BridgeError, "Host-owned"):
            _upload_bytes(self.state, str(external))
        upload = self.state / "_uploads" / "request.xlsx"
        upload.parent.mkdir()
        upload.write_bytes(b"bytes")
        self.assertEqual(_upload_bytes(self.state, str(upload)), b"bytes")


if __name__ == "__main__":
    unittest.main()
