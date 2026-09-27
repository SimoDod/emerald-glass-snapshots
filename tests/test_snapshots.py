"""Small restore tests that use a temporary home directory."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import emerald_glass_snapshots as app


class SnapshotTests(unittest.TestCase):
    def test_restore_keeps_replaced_files_without_creating_a_new_snapshot(self):
        self.check_restore(save_current=False)

    def test_restore_can_save_current_state_first(self):
        self.check_restore(save_current=True)

    def check_restore(self, *, save_current: bool) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            settings = home / ".config/kdeglobals"
            settings.parent.mkdir(parents=True)
            settings.write_text("saved appearance")
            store = Path(directory) / "snapshots"

            with (patch.object(app, "HOME", home),
                  patch.object(app, "STORE", store),
                  patch.object(app, "PROFILE_PATHS", (".config/kdeglobals", ".config/missing")),
                  patch.object(app, "EFFECT_PLUGIN", Path(directory) / "missing-plugin"),
                  patch.object(app, "package_versions", return_value={}),
                  patch.object(app.shutil, "which", return_value=None)):
                snapshot = app.save()
                manifest, _ = app.verify(snapshot)
                self.assertEqual(manifest["paths"], [".config/kdeglobals"])

                settings.write_text("current appearance")
                app.restore(snapshot, yes=True, dry_run=False, save_current=save_current)

                self.assertEqual(settings.read_text(), "saved appearance")
                backups = list((store / "restore-backups").glob("*/.config/kdeglobals"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(), "current appearance")
                self.assertEqual(len(list(store.glob("before-restore-*.tar.gz"))), int(save_current))


if __name__ == "__main__":
    unittest.main()
