import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_quota.auth_sync import sync_refreshed_auth, write_auth_bytes


class AuthSyncTests(unittest.TestCase):
    def test_write_auth_bytes_creates_private_auth_file(self):
        with TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "nested" / "auth.json"

            write_auth_bytes(target, b'{"account":"work"}')

            self.assertEqual(target.read_bytes(), b'{"account":"work"}')
            self.assertEqual(oct(target.stat().st_mode & 0o777), "0o600")

    def test_sync_refreshed_auth_requires_source_token_fields(self):
        for omitted_field in ("access_token", "refresh_token"):
            with self.subTest(omitted_field=omitted_field):
                with TemporaryDirectory() as tempdir:
                    root = Path(tempdir)
                    source = root / "source.json"
                    target = root / "target.json"
                    _write_auth(
                        source,
                        marker="refreshed",
                        omitted_field=omitted_field,
                    )
                    _write_auth(target, marker="original")

                    synced = sync_refreshed_auth(source=source, target=target)

                    self.assertFalse(synced)
                    self.assertEqual(_auth_marker(target), "original")


def _write_auth(path, *, marker, omitted_field=None):
    tokens = {
        "account_id": "acct-main",
        "access_token": "dummy-access",
        "refresh_token": "dummy-refresh",
    }
    if omitted_field is not None:
        tokens.pop(omitted_field)
    path.write_text(
        json.dumps(
            {
                "marker": marker,
                "tokens": tokens,
            },
            sort_keys=True,
        )
    )
    os.chmod(path, 0o600)


def _auth_marker(path):
    return json.loads(path.read_text())["marker"]


if __name__ == "__main__":
    unittest.main()
