import plistlib
import subprocess

import pytest

import shakespeare_wallpaper as sw

INSTALL = sw.PROJECT_DIR / "install.sh"


def run_install(*args):
    return subprocess.run([str(INSTALL), *args], capture_output=True, text=True)


def test_dry_run_generates_plists_for_this_checkout(tmp_path):
    result = run_install("--dry-run", str(tmp_path), "--hour", "7")
    assert result.returncode == 0, result.stderr

    project = str(sw.PROJECT_DIR)
    for label, script in [("com.shakespeare.wallpaper", "shakespeare_wallpaper.py"),
                          ("com.shakespeare.menubar", "menubar.py")]:
        with open(tmp_path / f"{label}.plist", "rb") as f:
            plist = plistlib.load(f)
        assert plist["Label"] == label
        assert plist["ProgramArguments"] == [f"{project}/.venv/bin/python", f"{project}/{script}"]
        assert plist["WorkingDirectory"] == project
        assert plist["StandardErrorPath"].startswith(f"{project}/logs/")

    with open(tmp_path / "com.shakespeare.wallpaper.plist", "rb") as f:
        assert plistlib.load(f)["StartCalendarInterval"] == {"Hour": 7, "Minute": 0}


@pytest.mark.parametrize("args", [["--hour", "24"], ["--hour", "x"], ["--bogus"]])
def test_rejects_bad_options(args, tmp_path):
    result = run_install(*args, "--dry-run", str(tmp_path))
    assert result.returncode != 0
    assert not list(tmp_path.iterdir())
