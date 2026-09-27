# Emerald Glass Snapshots

A small GTK app for saving and restoring KDE Plasma appearance settings. It is
designed for **CachyOS with KDE Plasma on Wayland**. It saves the supported files
that exist on your machine, so a particular Emerald Glass theme is not required.

## Requirements

- CachyOS, KDE Plasma, and a Wayland session
- Python 3, PyGObject, and GTK 4 for the window
- Kvantum and Qogir icons if your desktop uses them

On CachyOS, install the packages with:

```bash
sudo pacman -S --needed python python-gobject gtk4 kvantum qogir-icon-theme kwin plasma-workspace
```

The app also has terminal commands. They use Python's standard library and do
not need GTK. The Better Blur DX KWin plugin is needed for a restore only if it
was installed when that snapshot was made; the app does not install it.

## Run the app

```bash
git clone https://github.com/SimoDod/emerald-glass-snapshots.git
cd emerald-glass-snapshots
python3 emerald_glass_snapshots.py
```

Click **Save current state** to create a snapshot. To restore one, select it and
click **Restore selected**. The confirmation dialog lets you choose whether to
save your current settings as an additional snapshot first. You can also rename
snapshots or move them to Trash from the window.

Snapshots are stored outside the repository in
`~/.local/share/emerald-glass-snapshots/` by default. If `XDG_DATA_HOME` is set,
the app uses that location instead. You can set `EMERALD_GLASS_SNAPSHOTS_DIR` to
choose a different folder.

## Terminal commands

```bash
python3 emerald_glass_snapshots.py save
python3 emerald_glass_snapshots.py verify
python3 emerald_glass_snapshots.py restore --dry-run
python3 emerald_glass_snapshots.py restore
python3 emerald_glass_snapshots.py restore /path/to/snapshot.tar.gz
```

An interactive restore asks whether to make a snapshot of the current settings.
For an unattended restore, `--yes` skips both questions and makes no new
snapshot unless you also pass `--save-current`.

## What a snapshot contains

The app records supported KDE, KWin, Kvantum, GTK, and Konsole configuration,
plus local theme, icon, wallpaper, and Better Blur DX source files when present.
It does not collect browser profiles, documents, display geometry, or open
windows. It is an appearance backup, not a full system backup.

Restores work for the same home directory recorded in the snapshot. The app
checks the archive before replacing files, pauses Plasma briefly if needed,
and keeps the replaced files in a `restore-backups/` folder next to the
snapshots. Some applications need to be reopened to show restored colors.

**Keep snapshot archives private.** Desktop settings can contain usernames,
paths, panel launch commands, and other personal data. The repository ignores
archives, but you should still check what you stage before pushing changes.

## License

MIT. See [LICENSE](LICENSE).
