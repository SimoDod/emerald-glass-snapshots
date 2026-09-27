#!/usr/bin/env python3
"""Save and restore desktop appearance snapshots."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from datetime import datetime


PROFILE_PATHS = (
    ".config/kdeglobals",
    ".config/plasmarc",
    ".config/plasmashellrc",
    ".config/plasma-org.kde.plasma.desktop-appletsrc",
    ".config/kwinrc",
    ".config/kwinrulesrc",
    ".config/konsolerc",
    ".config/Kvantum/kvantum.kvconfig",
    ".config/Kvantum/EmeraldGlassDark",
    ".config/gtk-3.0/settings.ini",
    ".config/gtk-3.0/gtk.css",
    ".config/gtk-3.0/colors.css",
    ".config/gtk-4.0/settings.ini",
    ".config/gtk-4.0/gtk.css",
    ".config/gtk-4.0/colors.css",
    ".local/share/color-schemes/EmeraldGlass.colors",
    ".local/share/plasma/desktoptheme/cachyos-emerald-glass-dark",
    ".local/share/icons/Qogir-Emerald",
    ".local/share/konsole/Emerald Glass.profile",
    ".local/share/konsole/EmeraldGlass.colorscheme",
    ".local/share/cachyos-glass/wallpapers",
    ".local/src/kwin-effects-better-blur-dx",
)
EFFECT_PLUGIN = Path("/usr/lib/qt6/plugins/kwin/effects/plugins/better_blur_dx.so")
REQUIRED_PACKAGES = ("kvantum", "qogir-icon-theme", "kwin", "plasma-workspace")
HOME = Path.home().resolve()
STORE = Path(
    os.environ.get(
        "EMERALD_GLASS_SNAPSHOTS_DIR",
        Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "emerald-glass-snapshots",
    )
).expanduser()


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def run(command: list[str], *, timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=check)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    if not shutil.which("pacman"):
        return result
    for name in REQUIRED_PACKAGES:
        query = run(["pacman", "-Q", name], timeout=10)
        result[name] = query.stdout.strip() if query.returncode == 0 else None
    return result


def make_manifest(require_complete: bool) -> dict:
    present = [path for path in PROFILE_PATHS if (HOME / path).exists()]
    missing = [path for path in PROFILE_PATHS if path not in present]
    if missing and require_complete:
        raise RuntimeError("Cannot save; missing profile components: " + ", ".join(missing))
    applets_file = HOME / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    applets = applets_file.read_text() if applets_file.exists() else ""
    panels = [line for line in applets.splitlines() if line.startswith("plugin=org.kde.panel")]
    return {
        "format": 1,
        "saved_at": datetime.now().astimezone().isoformat(),
        "source_home": str(HOME),
        "paths": present,
        "missing_paths": missing,
        "active_panel_count": len(panels),
        "packages": package_versions(),
        "better_blur_plugin_sha256": file_hash(EFFECT_PLUGIN) if EFFECT_PLUGIN.is_file() else None,
        "note": "Appearance profile only; no display geometry, windows, browser data or personal documents.",
    }


def save(prefix: str = "emerald-glass", *, require_complete: bool = False) -> Path:
    STORE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STORE, 0o700)
    manifest = make_manifest(require_complete)
    if not manifest["paths"]:
        raise RuntimeError("No supported desktop settings found to save")
    destination = STORE / f"{prefix}-{stamp()}.tar.gz"
    temporary = destination.with_name(destination.name + ".part")
    try:
        with tarfile.open(temporary, "w:gz", dereference=False) as archive:
            payload = json.dumps(manifest, indent=2, sort_keys=True).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(payload)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(payload))
            for relative in manifest["paths"]:
                archive.add(HOME / relative, arcname=relative, recursive=True)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def latest_snapshot() -> Path:
    snapshots = list(STORE.glob("*.tar.gz"))
    if not snapshots:
        raise RuntimeError("No saved profile found. Run 'save' first.")
    return max(snapshots, key=lambda path: (path.stat().st_mtime_ns, path.name))


def rename_destination(snapshot: Path, title: str) -> Path:
    title = title.strip()
    if title.lower().endswith(".tar.gz"):
        title = title[:-7].rstrip()
    if (not title or title in (".", "..") or title.startswith(".")
            or any(character in title for character in "/\\")
            or any(ord(character) < 32 or ord(character) == 127 for character in title)):
        raise ValueError("Enter a name without slashes, leading dots or control characters")
    filename = title + ".tar.gz"
    if len(filename.encode("utf-8")) > 240:
        raise ValueError("Snapshot name is too long")
    destination = STORE / filename
    if destination == snapshot:
        raise ValueError("The new name is the same as the current name")
    return destination


def rename_snapshot(snapshot: Path, title: str) -> Path:
    if snapshot.is_symlink() or snapshot.resolve().parent != STORE.resolve() or not snapshot.name.endswith(".tar.gz"):
        raise RuntimeError("Refusing to rename a file outside the snapshots folder")
    if not snapshot.is_file():
        raise RuntimeError("The selected snapshot no longer exists")
    destination = rename_destination(snapshot, title)
    try:
        # A hard link fails if the name exists, so another snapshot is never overwritten.
        os.link(snapshot, destination)
    except FileExistsError as error:
        raise ValueError(f"A snapshot named {destination.name} already exists") from error
    try:
        snapshot.unlink()
    except OSError:
        destination.unlink()
        raise
    return destination


def valid_member_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or name in ("", "."):
        return False
    return name == "manifest.json" or any(
        name == root or name.startswith(root + "/") for root in PROFILE_PATHS
    )


def verify(snapshot: Path) -> tuple[dict, int]:
    if not snapshot.is_file():
        raise RuntimeError(f"Snapshot not found: {snapshot}")
    count = 0
    seen: set[str] = set()
    with tarfile.open(snapshot, "r:gz") as archive:
        members = archive.getmembers()
        manifest_member = archive.getmember("manifest.json")
        source = archive.extractfile(manifest_member)
        if source is None:
            raise RuntimeError("Snapshot has no readable manifest")
        manifest = json.load(source)
        included_paths = tuple(manifest.get("paths", []))
        if (manifest.get("format") != 1 or not included_paths
                or len(included_paths) != len(set(included_paths))
                or any(path not in PROFILE_PATHS for path in included_paths)):
            raise RuntimeError("Unrecognized or incomplete snapshot")
        for member in members:
            if member.name in seen or not valid_member_path(member.name):
                raise RuntimeError(f"Unsafe or duplicate archive entry: {member.name}")
            if member.name != "manifest.json" and not any(
                member.name == root or member.name.startswith(root + "/") for root in included_paths
            ):
                raise RuntimeError(f"Archive entry is outside its manifest: {member.name}")
            seen.add(member.name)
            if not (member.isfile() or member.isdir() or member.issym()):
                raise RuntimeError(f"Unsupported archive entry: {member.name}")
            if member.isfile():
                handle = archive.extractfile(member)
                if handle is None:
                    raise RuntimeError(f"Cannot read archive entry: {member.name}")
                for _ in iter(lambda: handle.read(1024 * 1024), b""):
                    pass
                count += 1
        if any(root not in seen for root in included_paths):
            raise RuntimeError("Snapshot is missing a required profile component")
    return manifest, count


def check_restore_requirements(manifest: dict) -> None:
    if manifest["source_home"] != str(HOME):
        raise RuntimeError(
            "This profile contains absolute wallpaper paths for "
            f"{manifest['source_home']}; restore it as that user."
        )
    if manifest.get("better_blur_plugin_sha256") and not EFFECT_PLUGIN.is_file():
        raise RuntimeError(
            "The Better Blur DX KWin plugin is missing. Its source is in the snapshot, "
            "but a user-level restore cannot install a system KWin plugin. Install it first."
        )
    installed = package_versions()
    missing = [name for name, version in manifest.get("packages", {}).items()
               if version is not None and installed.get(name) is None]
    if missing:
        raise RuntimeError("Required packages are missing: " + ", ".join(missing))


def unpack(snapshot: Path, staging: Path) -> None:
    with tarfile.open(snapshot, "r:gz") as archive:
        for member in archive:
            if member.name == "manifest.json":
                continue
            target = staging.joinpath(*PurePosixPath(member.name).parts)
            if any(parent.is_symlink() for parent in target.parents if parent != staging):
                raise RuntimeError(f"Archive entry is nested under a symlink: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(exist_ok=True)
            elif member.issym():
                target.symlink_to(member.linkname)
            else:
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(f"Cannot unpack {member.name}")
                with target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)


def restore(snapshot: Path, yes: bool, dry_run: bool, save_current: bool | None = None) -> None:
    manifest, count = verify(snapshot)
    check_restore_requirements(manifest)
    print(f"Verified {snapshot.name}: {count} files, {manifest['active_panel_count']} panel(s).")
    if dry_run:
        print("Dry run complete; nothing changed.")
        return
    if not yes:
        if not sys.stdin.isatty():
            raise RuntimeError("Interactive confirmation required; run from a terminal or add --yes.")
        answer = input("Restore this snapshot? [y/N]: ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled; nothing changed.")
            return
        if save_current is None:
            answer = input("Save a snapshot of current settings before restoring? [y/N]: ")
            save_current = answer.strip().lower() in ("y", "yes")

    if save_current:
        previous = save("before-restore", require_complete=False)
        print(f"Current settings saved as {previous}")
    backup = STORE / "restore-backups" / stamp()
    backup.mkdir(mode=0o700, parents=True)
    service = "plasma-plasmashell.service"
    stopped = False
    moved: list[tuple[Path, Path | None]] = []
    with tempfile.TemporaryDirectory(prefix="emerald-stage-", dir=STORE) as scratch:
        staging = Path(scratch)
        unpack(snapshot, staging)
        try:
            if shutil.which("systemctl") and run(["systemctl", "--user", "is-active", "--quiet", service]).returncode == 0:
                print("Pausing Plasma briefly to restore its panel and wallpaper configuration...")
                run(["systemctl", "--user", "stop", service], check=True)
                stopped = True
            for relative in manifest["paths"]:
                source = staging / relative
                destination = HOME / relative
                old = backup / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                prior: Path | None = None
                if destination.exists() or destination.is_symlink():
                    old.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, old)
                    prior = old
                try:
                    os.replace(source, destination)
                except Exception:
                    if prior is not None:
                        os.replace(prior, destination)
                    raise
                moved.append((destination, prior))
        except Exception:
            for destination, prior in reversed(moved):
                rejected = staging / "rejected" / destination.relative_to(HOME)
                rejected.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() or destination.is_symlink():
                    os.replace(destination, rejected)
                if prior is not None:
                    os.replace(prior, destination)
            raise
        finally:
            if stopped:
                start = run(["systemctl", "--user", "start", service])
                if start.returncode != 0:
                    print("WARNING: Plasma did not restart automatically; run 'systemctl --user start plasma-plasmashell.service'.", file=sys.stderr)

    if shutil.which("qdbus6"):
        run(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"], timeout=15)
    if shutil.which("dbus-send"):
        run(["dbus-send", "--session", "--type=signal", "/KGlobalSettings", "org.kde.KGlobalSettings.notifyChange", "int32:0", "int32:0"], timeout=15)
    print("Snapshot restored. Reopen applications that cache their Kvantum or GTK appearance.")
    print(f"Pre-restore files remain in {backup}")


def launch_gui() -> None:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, GLib, Gtk
    except (ImportError, ValueError) as error:
        message = f"GTK 4 Python support is unavailable: {error}"
        if shutil.which("kdialog"):
            run(["kdialog", "--error", message])
        raise RuntimeError(message) from error

    class StateWindow(Gtk.ApplicationWindow):
        def __init__(self, application: Gtk.Application) -> None:
            super().__init__(application=application, title="Emerald Glass Snapshots")
            self.set_default_size(760, 500)
            self.busy = False
            self.row_paths: dict[Gtk.ListBoxRow, Path] = {}
            self.connect("close-request", self.on_close_request)

            layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
            layout.set_margin_top(22)
            layout.set_margin_bottom(22)
            layout.set_margin_start(24)
            layout.set_margin_end(24)
            self.set_child(layout)

            title = Gtk.Label(label="Emerald Glass Snapshots", xalign=0)
            title.add_css_class("title-1")
            layout.append(title)

            self.listbox = Gtk.ListBox()
            self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
            self.listbox.set_show_separators(True)
            self.listbox.connect("row-selected", self.on_row_selected)
            placeholder = Gtk.Label(label="No snapshots yet. Click Save current state to create one.")
            placeholder.set_margin_top(32)
            placeholder.set_margin_bottom(32)
            self.listbox.set_placeholder(placeholder)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_child(self.listbox)
            scrolled.set_vexpand(True)
            scrolled.set_min_content_height(245)
            layout.append(scrolled)

            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            layout.append(actions)
            self.save_button = Gtk.Button(label="Save current state")
            self.save_button.add_css_class("suggested-action")
            self.save_button.connect("clicked", self.on_save)
            actions.append(self.save_button)
            self.restore_button = Gtk.Button(label="Restore selected")
            self.restore_button.connect("clicked", self.on_restore)
            actions.append(self.restore_button)
            self.rename_button = Gtk.Button(label="Rename selected")
            self.rename_button.connect("clicked", self.on_rename)
            actions.append(self.rename_button)
            self.delete_button = Gtk.Button(label="Delete selected")
            self.delete_button.add_css_class("destructive-action")
            self.delete_button.connect("clicked", self.on_delete)
            actions.append(self.delete_button)
            self.refresh_button = Gtk.Button(label="Refresh list")
            self.refresh_button.connect("clicked", lambda _button: self.refresh_list())
            actions.append(self.refresh_button)

            status_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            layout.append(status_line)
            self.spinner = Gtk.Spinner()
            status_line.append(self.spinner)
            self.status = Gtk.Label(label="Ready. You can choose to save current settings when restoring.", xalign=0)
            self.status.set_wrap(True)
            self.status.set_selectable(True)
            status_line.append(self.status)
            self.refresh_list()

        def on_close_request(self, _window: Gtk.Window) -> bool:
            if self.busy:
                self.status.set_text("Please wait until the current operation finishes.")
                return True
            return False

        def on_row_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
            self.restore_button.set_sensitive(not self.busy and row is not None)
            self.rename_button.set_sensitive(not self.busy and row is not None)
            self.delete_button.set_sensitive(not self.busy and row is not None)

        def refresh_list(self, select: Path | None = None) -> None:
            self.row_paths.clear()
            self.listbox.remove_all()
            STORE.mkdir(mode=0o700, parents=True, exist_ok=True)
            snapshots = sorted(STORE.glob("*.tar.gz"), key=lambda path: path.stat().st_mtime, reverse=True)
            selected_row = None
            for snapshot in snapshots:
                try:
                    with tarfile.open(snapshot, "r:gz") as archive:
                        source = archive.extractfile("manifest.json")
                        if source is None:
                            raise ValueError("missing manifest")
                        metadata = json.load(source)
                    saved_at = datetime.fromisoformat(metadata["saved_at"]).astimezone()
                    date_label = saved_at.strftime("%d %b %Y, %H:%M:%S")
                    panel_label = f"{metadata.get('active_panel_count', '?')} panel(s)"
                except (OSError, ValueError, KeyError, tarfile.TarError):
                    date_label = "Unreadable snapshot"
                    panel_label = "Verification will fail"
                kind = "Pre-restore snapshot" if snapshot.name.startswith("before-restore-") else "Saved state"
                size_mb = snapshot.stat().st_size / (1024 * 1024)
                row = Gtk.ListBoxRow()
                labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                labels.set_margin_top(10)
                labels.set_margin_bottom(10)
                labels.set_margin_start(12)
                labels.set_margin_end(12)
                main_label = Gtk.Label(label=f"{date_label}  ·  {kind}", xalign=0)
                main_label.add_css_class("heading")
                labels.append(main_label)
                detail = Gtk.Label(label=f"{snapshot.name}  ·  {size_mb:.1f} MiB  ·  {panel_label}", xalign=0)
                detail.set_ellipsize(3)
                detail.add_css_class("dim-label")
                labels.append(detail)
                row.set_child(labels)
                self.listbox.append(row)
                self.row_paths[row] = snapshot
                if select is not None and snapshot == select:
                    selected_row = row
            if selected_row is None and self.row_paths:
                selected_row = next(iter(self.row_paths))
            if selected_row is not None:
                self.listbox.select_row(selected_row)
            self.restore_button.set_sensitive(not self.busy and selected_row is not None)
            self.rename_button.set_sensitive(not self.busy and selected_row is not None)
            self.delete_button.set_sensitive(not self.busy and selected_row is not None)

        def move_snapshot_to_trash(self, snapshot: Path) -> Path:
            if snapshot.resolve().parent != STORE.resolve() or not snapshot.name.endswith(".tar.gz"):
                raise RuntimeError("Refusing to delete a file outside the snapshots folder")
            if not snapshot.is_file():
                raise RuntimeError("The selected snapshot no longer exists")
            if not Gio.File.new_for_path(str(snapshot)).trash(None):
                raise RuntimeError("Could not move the selected snapshot to Trash")
            return snapshot

        def start_job(self, action: str, function, *args) -> None:
            if self.busy:
                return
            self.busy = True
            self.save_button.set_sensitive(False)
            self.restore_button.set_sensitive(False)
            self.rename_button.set_sensitive(False)
            self.delete_button.set_sensitive(False)
            self.refresh_button.set_sensitive(False)
            self.listbox.set_sensitive(False)
            self.spinner.start()
            self.status.set_text(action + "…")

            def worker() -> None:
                try:
                    result = function(*args)
                except Exception as error:
                    GLib.idle_add(self.finish_job, action, None, str(error))
                else:
                    GLib.idle_add(self.finish_job, action, result, None)

            threading.Thread(target=worker, daemon=False).start()

        def finish_job(self, action: str, result, error: str | None) -> bool:
            self.busy = False
            self.spinner.stop()
            self.save_button.set_sensitive(True)
            self.refresh_button.set_sensitive(True)
            self.listbox.set_sensitive(True)
            if error is None:
                self.refresh_list(select=result if action in ("Saving current state", "Renaming selected snapshot") else None)
                if action == "Saving current state":
                    self.status.set_text(f"Saved a new snapshot: {result.name}")
                elif action == "Renaming selected snapshot":
                    self.status.set_text(f"Renamed snapshot to {result.name}")
                elif action == "Deleting selected snapshot":
                    self.status.set_text(f"Moved {result.name} to Trash. It can be recovered there.")
                else:
                    self.status.set_text("Restore complete. Reopen apps that still show cached colors.")
            else:
                self.restore_button.set_sensitive(self.listbox.get_selected_row() is not None)
                self.rename_button.set_sensitive(self.listbox.get_selected_row() is not None)
                self.delete_button.set_sensitive(self.listbox.get_selected_row() is not None)
                self.status.set_text(f"{action} failed: {error}")
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.CLOSE,
                    text=f"{action} failed\n\n{error}",
                )
                dialog.connect("response", lambda window, _response: window.destroy())
                dialog.present()
            return False

        def on_save(self, _button: Gtk.Button) -> None:
            self.start_job("Saving current state", save)

        def on_rename(self, _button: Gtk.Button) -> None:
            row = self.listbox.get_selected_row()
            if row is None:
                return
            snapshot = self.row_paths[row]
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text="Rename this snapshot. Its saved desktop settings will not change.",
            )
            entry = Gtk.Entry()
            entry.set_text(snapshot.name[:-7])
            entry.set_activates_default(True)
            entry.set_margin_top(12)
            dialog.get_content_area().append(entry)
            error_label = Gtk.Label(xalign=0)
            error_label.add_css_class("error")
            error_label.set_wrap(True)
            dialog.get_content_area().append(error_label)
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dialog.add_button("Rename", Gtk.ResponseType.ACCEPT)
            dialog.set_default_response(Gtk.ResponseType.ACCEPT)

            def confirmed(window: Gtk.MessageDialog, response: int) -> None:
                if response != Gtk.ResponseType.ACCEPT:
                    window.destroy()
                    return
                title = entry.get_text()
                try:
                    destination = rename_destination(snapshot, title)
                    if destination.exists():
                        raise ValueError(f"A snapshot named {destination.name} already exists")
                except ValueError as error:
                    error_label.set_text(str(error))
                    entry.grab_focus()
                    return
                window.destroy()
                self.start_job("Renaming selected snapshot", rename_snapshot, snapshot, title)

            dialog.connect("response", confirmed)
            dialog.present()
            entry.grab_focus()
            entry.select_region(0, -1)

        def on_restore(self, _button: Gtk.Button) -> None:
            row = self.listbox.get_selected_row()
            if row is None:
                return
            snapshot = self.row_paths[row]
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text=(
                    "Restore this snapshot?\n\n"
                    f"{snapshot.name}\n\nThe desktop panel may disappear briefly while Plasma restarts. "
                    "Replaced files will be kept in restore-backups."
                ),
            )
            save_current = Gtk.CheckButton(label="Save current settings as a snapshot first")
            save_current.set_margin_top(12)
            dialog.get_message_area().append(save_current)
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dialog.add_button("Restore", Gtk.ResponseType.ACCEPT)

            def confirmed(window: Gtk.MessageDialog, response: int) -> None:
                create_snapshot = save_current.get_active()
                window.destroy()
                if response == Gtk.ResponseType.ACCEPT:
                    self.start_job("Restoring selected snapshot", restore, snapshot, True, False, create_snapshot)

            dialog.connect("response", confirmed)
            dialog.present()

        def on_delete(self, _button: Gtk.Button) -> None:
            row = self.listbox.get_selected_row()
            if row is None:
                return
            snapshot = self.row_paths[row]
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text=(
                    "Move this snapshot to Trash?\n\n"
                    f"{snapshot.name}\n\nYou can recover it from Trash if needed."
                ),
            )
            dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dialog.add_button("Move to Trash", Gtk.ResponseType.ACCEPT)

            def confirmed(window: Gtk.MessageDialog, response: int) -> None:
                window.destroy()
                if response == Gtk.ResponseType.ACCEPT:
                    self.start_job("Deleting selected snapshot", self.move_snapshot_to_trash, snapshot)

            dialog.connect("response", confirmed)
            dialog.present()

    application = Gtk.Application(application_id="io.github.SimoDod.EmeraldGlassSnapshots")

    def activate(app: Gtk.Application) -> None:
        existing = app.get_active_window()
        window = existing or StateWindow(app)
        window.present()

    application.connect("activate", activate)
    application.run([])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui", help="Open the save/restore window (default)")
    sub.add_parser("save", help="Capture the current desktop appearance settings and assets")
    verify_parser = sub.add_parser("verify", help="Check a snapshot without changing anything")
    verify_parser.add_argument("snapshot", nargs="?", type=Path)
    restore_parser = sub.add_parser("restore", help="Restore a snapshot (latest by default)")
    restore_parser.add_argument("snapshot", nargs="?", type=Path)
    restore_parser.add_argument("--dry-run", action="store_true")
    restore_parser.add_argument("--yes", action="store_true",
                                help="Restore without prompts; no new snapshot unless --save-current is set")
    restore_parser.add_argument("--save-current", action="store_true", default=None,
                                help="Save current settings as a snapshot before restoring")
    args = parser.parse_args()
    try:
        if args.command in (None, "gui"):
            launch_gui()
        elif args.command == "save":
            snapshot = save()
            print(f"Saved {snapshot}")
            print("Copy the script and snapshot archive together to another drive for safekeeping.")
        elif args.command == "verify":
            snapshot = args.snapshot or latest_snapshot()
            manifest, count = verify(snapshot)
            print(f"Verified {snapshot}: {count} files, {manifest['active_panel_count']} panel(s).")
        else:
            restore(args.snapshot or latest_snapshot(), args.yes, args.dry_run, args.save_current)
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
