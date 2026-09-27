#!/usr/bin/env python3
"""Install the app and create a clickable launcher for this user."""

import argparse
import os
from pathlib import Path
import shutil


APP_NAME = "Emerald Glass Snapshots"
APP_ID = "io.github.SimoDod.EmeraldGlassSnapshots"
SOURCE = Path(__file__).resolve().with_name("emerald_glass_snapshots.py")


def desktop_quote(value: str) -> str:
    """Quote one argument using Desktop Entry Exec field escaping."""
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'"{value}"'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", action="store_true", help="Also create a Desktop shortcut")
    args = parser.parse_args()

    home = Path.home()
    desktop = home / "Desktop"
    if args.desktop and not desktop.is_dir():
        parser.error(f"Desktop folder not found: {desktop}")
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")).expanduser()
    executable = home / ".local/bin/emerald-glass-snapshots"
    executable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, executable)
    executable.chmod(0o755)

    launcher_text = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Save and restore desktop appearance snapshots\n"
        f"Exec={desktop_quote(str(executable))} gui\n"
        "Icon=preferences-desktop-theme\n"
        "Terminal=false\n"
        "Categories=Settings;DesktopSettings;\n"
        "StartupNotify=true\n"
    )
    applications = data_home / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    launcher = applications / f"{APP_ID}.desktop"
    launcher.write_text(launcher_text)
    launcher.chmod(0o755)
    print(f"Installed {APP_NAME} and its application menu launcher: {launcher}")

    if args.desktop:
        shortcut = desktop / f"{APP_NAME}.desktop"
        if shortcut.exists():
            print(f"Desktop shortcut already exists; left it unchanged: {shortcut}")
        else:
            shortcut.write_text(launcher_text)
            shortcut.chmod(0o755)
            print(f"Created Desktop shortcut: {shortcut}")


if __name__ == "__main__":
    main()
