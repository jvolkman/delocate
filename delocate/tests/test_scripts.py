# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
""" Test scripts

If we appear to be running from the development directory, use the scripts in
the top-level folder ``scripts``.  Otherwise try and get the scripts from the
path
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from os.path import basename, exists, realpath, splitext
from os.path import join as pjoin
from pathlib import Path
from typing import Text

import pytest
from pytest_console_scripts import ScriptRunner

from ..tmpdirs import InGivenDirectory, InTemporaryDirectory
from ..tools import dir2zip, get_rpaths, set_install_name, zip2dir
from ..wheeltools import InWheel
from .test_delocating import _copy_to, _make_bare_depends, _make_libtree
from .test_fuse import assert_same_tree
from .test_install_names import EXT_LIBS
from .test_wheelies import (
    PLAT_WHEEL,
    PURE_WHEEL,
    RPATH_WHEEL,
    WHEEL_PATCH,
    WHEEL_PATCH_BAD,
    PlatWheel,
    _fixed_wheel,
    _rename_module,
    _thin_lib,
    _thin_mod,
)
from .test_wheeltools import (
    EXP_ITEMS,
    EXTRA_EXPS,
    EXTRA_PLATS,
    assert_winfo_similar,
)

DATA_PATH = (Path(__file__).parent / "data").resolve(strict=True)


def _proc_lines(in_str: str) -> list[str]:
    """Return input split across lines, striping whitespace, without blanks.

    Parameters
    ----------
    in_str : str
        Input for splitting, stripping

    Returns
    -------
    out_lines : list
        List of line ``str`` where each line has been stripped of leading and
        trailing whitespace and empty lines have been removed.
    """
    lines = in_str.splitlines()
    return [line.strip() for line in lines if line.strip() != ""]


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_listdeps(plat_wheel: PlatWheel, script_runner: ScriptRunner) -> None:
    # smokey tests of list dependencies command
    local_libs = {
        "liba.dylib",
        "libb.dylib",
        "libc.dylib",
        "libextfunc2_rpath.dylib",
    }
    # single path, with libs
    with InGivenDirectory(DATA_PATH):
        result = script_runner.run(
            "delocate-listdeps", str(DATA_PATH), check=True
        )
    assert set(_proc_lines(result.stdout)) == local_libs
    # single path, no libs
    with InTemporaryDirectory():
        zip2dir(PURE_WHEEL, "pure")
        result = script_runner.run(["delocate-listdeps", "pure"], check=True)
        assert result.stdout.strip() == ""

        # Multiple paths one with libs
        zip2dir(plat_wheel.whl, "plat")
        result = script_runner.run(
            ["delocate-listdeps", "pure", "plat"], check=True
        )
        assert _proc_lines(result.stdout) == [
            "pure:",
            "plat:",
            plat_wheel.stray_lib,
        ]

        # With -d flag, get list of dependending modules
        result = script_runner.run(
            ["delocate-listdeps", "-d", "pure", "plat"], check=True
        )
        assert _proc_lines(result.stdout) == [
            "pure:",
            "plat:",
            plat_wheel.stray_lib + ":",
            str(Path("plat", "fakepkg1", "subpkg", "module2.abi3.so")),
        ]

    # With --all flag, get all dependencies
    with InGivenDirectory(DATA_PATH):
        result = script_runner.run(
            ["delocate-listdeps", "--all", DATA_PATH], check=True
        )
    rp_ext_libs = set(realpath(L) for L in EXT_LIBS)
    assert set(_proc_lines(result.stdout)) == local_libs | rp_ext_libs

    # Works on wheels as well
    result = script_runner.run(["delocate-listdeps", PURE_WHEEL], check=True)
    assert result.stdout.strip() == ""
    result = script_runner.run(
        ["delocate-listdeps", PURE_WHEEL, plat_wheel.whl], check=True
    )
    assert _proc_lines(result.stdout) == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib,
    ]

    # -d flag (is also --dependency flag)
    m2 = pjoin("fakepkg1", "subpkg", "module2.abi3.so")
    result = script_runner.run(
        ["delocate-listdeps", "--depending", PURE_WHEEL, plat_wheel.whl],
        check=True,
    )
    assert _proc_lines(result.stdout) == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib + ":",
        m2,
    ]

    # Can be used with --all
    result = script_runner.run(
        [
            "delocate-listdeps",
            "--all",
            "--depending",
            PURE_WHEEL,
            plat_wheel.whl,
        ],
        check=True,
    )
    assert _proc_lines(result.stdout) == [
        PURE_WHEEL + ":",
        plat_wheel.whl + ":",
        plat_wheel.stray_lib + ":",
        m2,
        EXT_LIBS[1] + ":",
        m2,
        plat_wheel.stray_lib,
    ]


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Runs macOS executable."
)
def test_path(script_runner: ScriptRunner) -> None:
    # Test path cleaning
    with InTemporaryDirectory():
        # Make a tree; use realpath for OSX /private/var - /var
        liba, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath("subtree")
        )
        os.makedirs("fakelibs")
        # Make a fake external library to link to
        fake_lib = realpath(_copy_to(liba, "fakelibs", "libfake.dylib"))
        _, _, _, test_lib, slibc, stest_lib = _make_libtree(
            realpath("subtree2")
        )
        subprocess.run([test_lib], check=True)
        subprocess.run([stest_lib], check=True)
        set_install_name(slibc, EXT_LIBS[0], fake_lib)
        # Check it fixes up correctly
        script_runner.run(
            ["delocate-path", "subtree", "subtree2", "-L", "deplibs"],
            check=True,
        )
        assert len(os.listdir(Path("subtree", "deplibs"))) == 0
        # Check fake libary gets copied and delocated
        out_path = Path("subtree2", "deplibs")
        assert os.listdir(out_path) == ["libfake.dylib"]


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_path_dylibs(script_runner: ScriptRunner) -> None:
    # Test delocate-path with and without dylib extensions
    with InTemporaryDirectory():
        # With 'dylibs-only' - does not inspect non-dylib files
        liba, bare_b = _make_bare_depends()
        out_dypath = Path("subtree", "deplibs")
        script_runner.run(
            ["delocate-path", "subtree", "-L", "deplibs", "-d"], check=True
        )
        assert len(os.listdir(out_dypath)) == 0
        script_runner.run(
            ["delocate-path", "subtree", "-L", "deplibs", "--dylibs-only"],
            check=True,
        )
        assert len(os.listdir(Path("subtree", "deplibs"))) == 0
        # Default - does inspect non-dylib files
        script_runner.run(
            ["delocate-path", "subtree", "-L", "deplibs"], check=True
        )
        assert os.listdir(out_dypath) == ["liba.dylib"]


def _check_wheel(wheel_fname: str | Path, lib_sdir: str | Path) -> None:
    wheel_fname = Path(wheel_fname).resolve(strict=True)
    with InTemporaryDirectory():
        zip2dir(str(wheel_fname), "plat_pkg")
        dylibs = Path("plat_pkg", "fakepkg1", lib_sdir)
        assert dylibs.exists()
        assert os.listdir(dylibs) == ["libextfunc.dylib"]


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_wheel(script_runner: ScriptRunner) -> None:
    # Some tests for wheel fixing
    with InTemporaryDirectory() as tmpdir:
        # Default in-place fix
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        script_runner.run(["delocate-wheel", fixed_wheel], check=True)
        _check_wheel(fixed_wheel, ".dylibs")
        # Make another copy to test another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        script_runner.run(
            ["delocate-wheel", "-L", "dynlibs_dir", fixed_wheel], check=True
        )
        _check_wheel(fixed_wheel, "dynlibs_dir")
        # Another output directory
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        script_runner.run(
            ["delocate-wheel", "-w", "fixed", fixed_wheel], check=True
        )
        _check_wheel(Path("fixed", basename(fixed_wheel)), ".dylibs")
        # More than one wheel
        shutil.copy2(fixed_wheel, "wheel_copy.ext")
        result = script_runner.run(
            ["delocate-wheel", "-w", "fixed2", fixed_wheel, "wheel_copy.ext"],
            check=True,
        )
        assert _proc_lines(result.stdout) == [
            "Fixing: " + name for name in (fixed_wheel, "wheel_copy.ext")
        ]
        _check_wheel(Path("fixed2", basename(fixed_wheel)), ".dylibs")
        _check_wheel(Path("fixed2", "wheel_copy.ext"), ".dylibs")

        # Verbose - single wheel
        result = script_runner.run(
            ["delocate-wheel", "-w", "fixed3", fixed_wheel, "-v"], check=True
        )
        _check_wheel(Path("fixed3", basename(fixed_wheel)), ".dylibs")
        wheel_lines1 = [
            "Fixing: " + fixed_wheel,
            "Copied to package .dylibs directory:",
            stray_lib,
        ]
        assert _proc_lines(result.stdout) == wheel_lines1

        result = script_runner.run(
            [
                "delocate-wheel",
                "-v",
                "--wheel-dir",
                "fixed4",
                fixed_wheel,
                "wheel_copy.ext",
            ],
            check=True,
        )
        wheel_lines2 = [
            "Fixing: wheel_copy.ext",
            "Copied to package .dylibs directory:",
            stray_lib,
        ]
        assert _proc_lines(result.stdout) == wheel_lines1 + wheel_lines2


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_fix_wheel_dylibs(script_runner: ScriptRunner) -> None:
    # Check default and non-default search for dynamic libraries
    with InTemporaryDirectory() as tmpdir:
        # Default in-place fix
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        _rename_module(fixed_wheel, "module.other", "test.whl")
        shutil.copyfile("test.whl", "test2.whl")
        # Default is to look in all files and therefore fix
        script_runner.run(["delocate-wheel", "test.whl"], check=True)
        _check_wheel("test.whl", ".dylibs")
        # Can turn this off to only look in dynamic lib exts
        script_runner.run(["delocate-wheel", "test2.whl", "-d"], check=True)
        with InWheel("test2.whl"):  # No fix
            assert not Path("fakepkg1", ".dylibs").exists()


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_fix_wheel_archs(script_runner: ScriptRunner) -> None:
    # Some tests for wheel fixing
    with InTemporaryDirectory() as tmpdir:
        # Test check of architectures
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        # Fixed wheel, architectures are OK
        script_runner.run(["delocate-wheel", fixed_wheel, "-k"], check=True)
        _check_wheel(fixed_wheel, ".dylibs")
        # Broken with one architecture removed
        archs = set(("x86_64", "arm64"))

        def _fix_break(arch: Text) -> None:
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)

        def _fix_break_fix(arch: Text) -> None:
            _fixed_wheel(tmpdir)
            _thin_lib(stray_lib, arch)
            _thin_mod(fixed_wheel, arch)

        for arch in archs:
            # Not checked
            _fix_break(arch)
            script_runner.run(["delocate-wheel", fixed_wheel], check=True)
            _check_wheel(fixed_wheel, ".dylibs")
            # Checked
            _fix_break(arch)
            result = script_runner.run(
                ["delocate-wheel", fixed_wheel, "--check-archs"]
            )
            assert result.returncode != 0
            assert result.stderr.startswith("Traceback")
            assert (
                "DelocationError: Some missing architectures in wheel"
                in result.stderr
            )
            assert result.stdout.strip() == ""
            # Checked, verbose
            _fix_break(arch)
            result = script_runner.run(
                ["delocate-wheel", fixed_wheel, "--check-archs", "-v"]
            )
            assert result.returncode != 0
            assert "Traceback" in result.stderr
            assert result.stderr.endswith(
                "DelocationError: Some missing architectures in wheel"
                f"\n{'fakepkg1/subpkg/module2.abi3.so'}"
                f" needs arch {archs.difference([arch]).pop()}"
                f" missing from {stray_lib}\n"
            )
            assert result.stdout == f"Fixing: {fixed_wheel}\n"
            # Require particular architectures
        both_archs = "arm64,x86_64"
        for ok in ("universal2", "arm64", "x86_64", both_archs):
            _fixed_wheel(tmpdir)
            script_runner.run(
                ["delocate-wheel", fixed_wheel, "--require-archs=" + ok],
                check=True,
            )
        for arch in archs:
            other_arch = archs.difference([arch]).pop()
            for not_ok in ("intel", both_archs, other_arch):
                _fix_break_fix(arch)
                result = script_runner.run(
                    [
                        "delocate-wheel",
                        fixed_wheel,
                        "--require-archs=" + not_ok,
                    ],
                )
                assert result.returncode != 0


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform == "win32", reason="Can't run scripts."
)
def test_fuse_wheels(script_runner: ScriptRunner) -> None:
    # Some tests for wheel fusing
    with InTemporaryDirectory():
        zip2dir(PLAT_WHEEL, "to_wheel")
        zip2dir(PLAT_WHEEL, "from_wheel")
        dir2zip("to_wheel", "to_wheel.whl")
        dir2zip("from_wheel", "from_wheel.whl")
        script_runner.run(
            ["delocate-fuse", "to_wheel.whl", "from_wheel.whl"], check=True
        )
        zip2dir("to_wheel.whl", "to_wheel_fused")
        assert_same_tree("to_wheel_fused", "from_wheel")
        # Test output argument
        os.mkdir("wheels")
        script_runner.run(
            ["delocate-fuse", "to_wheel.whl", "from_wheel.whl", "-w", "wheels"],
            check=True,
        )
        zip2dir(pjoin("wheels", "to_wheel.whl"), "to_wheel_refused")
        assert_same_tree("to_wheel_refused", "from_wheel")


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform == "win32", reason="Can't run scripts."
)
def test_patch_wheel(script_runner: ScriptRunner) -> None:
    # Some tests for patching wheel
    with InTemporaryDirectory():
        shutil.copyfile(PURE_WHEEL, "example.whl")
        # Default is to overwrite input
        script_runner.run(
            ["delocate-patch", "-v", "example.whl", WHEEL_PATCH], check=True
        )
        zip2dir("example.whl", "wheel1")
        assert (
            Path("wheel1", "fakepkg2", "__init__.py").read_text()
            == 'print("Am in init")\n'
        )
        # Pass output directory
        shutil.copyfile(PURE_WHEEL, "example.whl")
        script_runner.run(
            ["delocate-patch", "example.whl", WHEEL_PATCH, "-w", "wheels"],
            check=True,
        )
        zip2dir(pjoin("wheels", "example.whl"), "wheel2")
        assert (
            Path("wheel2", "fakepkg2", "__init__.py").read_text()
            == 'print("Am in init")\n'
        )
        # Bad patch fails
        shutil.copyfile(PURE_WHEEL, "example.whl")
        result = script_runner.run(
            ["delocate-patch", "example.whl", WHEEL_PATCH_BAD]
        )
        assert result.returncode != 0


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform == "win32", reason="Can't run scripts."
)
def test_add_platforms(script_runner: ScriptRunner) -> None:
    # Check adding platform to wheel name and tag section
    assert_winfo_similar(PLAT_WHEEL, EXP_ITEMS, drop_version=False)
    with InTemporaryDirectory() as tmpdir:
        # First wheel needs proper wheel filename for later unpack test
        out_fname = basename(PURE_WHEEL)
        # Need to specify at least one platform
        with pytest.raises(subprocess.CalledProcessError):
            script_runner.run(
                ["delocate-addplat", PURE_WHEEL, "-w", tmpdir], check=True
            )
        plat_args = ("-p", EXTRA_PLATS[0], "--plat-tag", EXTRA_PLATS[1])
        # Can't add platforms to a pure wheel
        with pytest.raises(subprocess.CalledProcessError):
            script_runner.run(
                ["delocate-addplat", PURE_WHEEL, "-w", tmpdir, *plat_args],
                check=True,
            )
        assert not exists(out_fname)
        # Error raised (as above) unless ``--skip-error`` flag set
        script_runner.run(
            ["delocate-addplat", PURE_WHEEL, "-w", tmpdir, "-k", *plat_args],
            check=True,
        )
        # Still doesn't do anything though
        assert not exists(out_fname)
        # Works for plat_wheel
        out_fname = ".".join(
            (splitext(basename(PLAT_WHEEL))[0],) + EXTRA_PLATS + ("whl",)
        )
        script_runner.run(
            ["delocate-addplat", PLAT_WHEEL, "-w", tmpdir, *plat_args],
            check=True,
        )
        assert Path(out_fname).is_file()
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # If wheel exists (as it does) then fail
        with pytest.raises(subprocess.CalledProcessError):
            script_runner.run(
                ["delocate-addplat", PLAT_WHEEL, "-w", tmpdir, *plat_args],
                check=True,
            )
        # Unless clobber is set
        script_runner.run(
            ["delocate-addplat", PLAT_WHEEL, "-c", "-w", tmpdir, *plat_args],
            check=True,
        )
        # Can also specify platform tags via --osx-ver flags
        script_runner.run(
            ["delocate-addplat", PLAT_WHEEL, "-c", "-w", tmpdir, "-x", "10_9"],
            check=True,
        )
        assert_winfo_similar(out_fname, EXTRA_EXPS)
        # Can mix plat_tag and osx_ver
        extra_extra = ("macosx_10_12_universal2", "macosx_10_12_x86_64")
        out_big_fname = ".".join(
            (splitext(basename(PLAT_WHEEL))[0],)
            + EXTRA_PLATS
            + extra_extra
            + ("whl",)
        )
        extra_big_exp = EXTRA_EXPS + [
            ("Tag", "{pyver}-{abi}-" + plat) for plat in extra_extra
        ]
        script_runner.run(
            [
                "delocate-addplat",
                PLAT_WHEEL,
                "-w",
                tmpdir,
                "-x",
                "10_12",
                "-d",
                "universal2",
                *plat_args,
            ],
            check=True,
        )
        assert_winfo_similar(out_big_fname, extra_big_exp)
        # Default is to write into directory of wheel
        os.mkdir("wheels")
        shutil.copy2(PLAT_WHEEL, "wheels")
        local_plat = pjoin("wheels", basename(PLAT_WHEEL))
        local_out = pjoin("wheels", out_fname)
        script_runner.run(
            ["delocate-addplat", local_plat, *plat_args], check=True
        )
        assert exists(local_out)
        # With rm_orig flag, delete original unmodified wheel
        os.unlink(local_out)
        script_runner.run(
            ["delocate-addplat", "-r", local_plat, *plat_args], check=True
        )
        assert not exists(local_plat)
        assert exists(local_out)
        # Copy original back again
        shutil.copy2(PLAT_WHEEL, "wheels")
        # If platforms already present, don't write more
        res = sorted(os.listdir("wheels"))
        assert_winfo_similar(local_out, EXTRA_EXPS)
        script_runner.run(
            ["delocate-addplat", local_out, "--clobber", *plat_args], check=True
        )
        assert sorted(os.listdir("wheels")) == res
        assert_winfo_similar(local_out, EXTRA_EXPS)
        # The wheel doesn't get deleted output name same as input, as here
        script_runner.run(
            ["delocate-addplat", local_out, "-r", "--clobber", *plat_args],
            check=True,
        )
        assert sorted(os.listdir("wheels")) == res
        # But adds WHEEL tags if missing, even if file name is OK
        shutil.copy2(local_plat, local_out)
        with pytest.raises(AssertionError):
            assert_winfo_similar(local_out, EXTRA_EXPS)
        script_runner.run(
            ["delocate-addplat", local_out, "--clobber", *plat_args], check=True
        )
        assert sorted(os.listdir("wheels")) == res
        assert_winfo_similar(local_out, EXTRA_EXPS)
        assert_winfo_similar(local_out, EXTRA_EXPS)


@pytest.mark.xfail(sys.platform != "darwin", reason="Needs macOS linkage.")
def test_fix_wheel_with_excluded_dylibs(script_runner: ScriptRunner):
    with InTemporaryDirectory() as tmpdir:
        fixed_wheel, stray_lib = _fixed_wheel(tmpdir)
        _rename_module(fixed_wheel, "module.other", "test.whl")
        shutil.copyfile("test.whl", "test2.whl")
        # We exclude the stray library so it shouldn't be present in the wheel
        result = script_runner.run(
            ["delocate-wheel", "-vv", "-e", "extfunc", "test.whl"], check=True
        )
        assert "libextfunc.dylib excluded" in result.stderr
        with InWheel("test.whl"):
            assert not Path("plat_pkg/fakepkg1/.dylibs").exists()
        # We exclude a library that does not exist so we should behave normally
        script_runner.run(
            ["delocate-wheel", "-e", "doesnotexist", "test2.whl"], check=True
        )
        _check_wheel("test2.whl", ".dylibs")


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_sanitize_command(tmp_path: Path, script_runner: ScriptRunner) -> None:
    unpack_dir = tmp_path / "unpack"
    zip2dir(RPATH_WHEEL, unpack_dir)
    assert "libs/" in set(
        get_rpaths(str(unpack_dir / "fakepkg/subpkg/module2.abi3.so"))
    )

    rpath_wheel = tmp_path / "example.whl"
    shutil.copyfile(RPATH_WHEEL, rpath_wheel)
    libs_path = tmp_path / "libs"
    libs_path.mkdir()
    shutil.copy(DATA_PATH / "libextfunc_rpath.dylib", libs_path)
    shutil.copy(DATA_PATH / "libextfunc2_rpath.dylib", libs_path)
    result = script_runner.run(
        ["delocate-wheel", "-vv", "--sanitize-rpaths", rpath_wheel],
        check=True,
        cwd=tmp_path,
    )
    assert "Sanitize: Deleting rpath 'libs/' from" in result.stderr

    unpack_dir = tmp_path / "unpack"
    zip2dir(rpath_wheel, unpack_dir)
    assert "libs/" not in set(
        get_rpaths(str(unpack_dir / "fakepkg/subpkg/module2.abi3.so"))
    )


@pytest.mark.xfail(  # type: ignore[misc]
    sys.platform != "darwin", reason="Needs macOS linkage."
)
def test_glob(
    tmp_path: Path, plat_wheel: PlatWheel, script_runner: ScriptRunner
) -> None:
    # Test implicit globbing by passing "*.whl" without shell=True
    script_runner.run(["delocate-listdeps", "*.whl"], check=True, cwd=tmp_path)
    zip2dir(plat_wheel.whl, tmp_path / "plat")

    result = script_runner.run(
        ["delocate-wheel", "*.whl", "-v"], check=True, cwd=tmp_path
    )
    assert Path(plat_wheel.whl).name in result.stdout
    assert "*.whl" not in result.stdout
    assert not Path(tmp_path, "*.whl").exists()

    # Delocate literal file "*.whl" instead of expanding glob
    shutil.copyfile(plat_wheel.whl, tmp_path / "*.whl")
    result = script_runner.run(
        ["delocate-wheel", "*.whl", "-v"], check=True, cwd=tmp_path
    )
    assert Path(plat_wheel.whl).name not in result.stdout
    assert "*.whl" in result.stdout

    Path(plat_wheel.whl).unlink()
    Path(tmp_path, "*.whl").unlink()
    result = script_runner.run(["delocate-wheel", "*.whl"], cwd=tmp_path)
    assert result.returncode == 1
    assert "FileNotFoundError:" in result.stderr

    script_runner.run(["delocate-path", "*/"], check=True, cwd=tmp_path)
