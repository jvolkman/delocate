#!/usr/bin/env python3
""" Add platform tags to wheel filename(s) and WHEEL file in wheel

Example:

    delocate-addplat -p macosx_10_9_intel -p macosx_10_9_x86_64 *.whl

or (same result):

    delocate-addplat -x 10_9 *.whl

or (adds tags for OSX 10.9 and 10.10):

    delocate-addplat -x 10_9 -x 10_10 *.whl
"""
# vim: ft=python
from __future__ import absolute_import, division, print_function

import os
from argparse import ArgumentParser
from os.path import expanduser, realpath
from os.path import join as exists

from delocate.cmd.common import common_parser, verbosity_config
from delocate.wheeltools import WheelToolsError, add_platforms

parser = ArgumentParser(description=__doc__, parents=[common_parser])
parser.add_argument(
    "wheels",
    nargs="+",
    metavar="WHEEL",
    type=str,
    help="Wheel to modify",
)
parser.add_argument(
    "-p",
    "--plat-tag",
    metavar="PLATFORM_TAG",
    action="append",
    type=str,
    help="Platform tag to add (e.g. macosx_10_9_intel)"
    " (can be specified multiple times)",
)
parser.add_argument(
    "-x",
    "--osx-ver",
    metavar="OSX_VERSION",
    action="append",
    type=str,
    help="Alternative method to specify platform tags, by giving "
    'OSX version numbers - e.g. "10_10" results in adding platform '
    'tags "macosx_10_10_intel, "macosx_10_10_x86_64") (can be '
    "specified multiple times)",
)
parser.add_argument(
    "-w",
    "--wheel-dir",
    action="store",
    type=str,
    help=(
        "Directory to store delocated wheels (default is to " "overwrite input)"
    ),
)
parser.add_argument(
    "-c",
    "--clobber",
    action="store_true",
    help="Overwrite pre-existing wheels",
)
parser.add_argument(
    "-r",
    "--rm-orig",
    action="store_true",
    help="Remove unmodified wheel if wheel is rewritten",
)
parser.add_argument(
    "-k",
    "--skip-errors",
    action="store_true",
    help="Skip wheels that raise errors (e.g. pure wheels)",
)
parser.add_argument(
    "-d",
    "--dual-arch-type",
    metavar="ARCHITECTURE",
    action="store",
    type=str,
    default="intel",
    help="Dual architecture wheel type; one of 'intel', 'universal2';"
    " (default %(default)s)",
)


def main() -> None:
    args = parser.parse_args()
    verbosity_config(args)
    multi = len(args.wheels) > 1
    if args.wheel_dir:
        wheel_dir = expanduser(args.wheel_dir)
        if not exists(wheel_dir):
            os.makedirs(wheel_dir)
    else:
        wheel_dir = None
    plat_tags = [] if args.plat_tag is None else args.plat_tag
    if args.osx_ver is not None:
        for ver in args.osx_ver:
            plat_tags += [
                "macosx_{0}_{1}".format(ver, args.dual_arch_type),
                "macosx_{0}_x86_64".format(ver),
            ]
    if len(plat_tags) == 0:
        raise RuntimeError("Need at least one --osx-ver or --plat-tag")
    for wheel in args.wheels:
        if multi or args.verbose:
            print(
                "Setting platform tags {0} for wheel {1}".format(
                    ",".join(plat_tags), wheel
                )
            )
        try:
            fname = add_platforms(
                wheel, plat_tags, wheel_dir, clobber=args.clobber
            )
        except WheelToolsError as e:
            if args.skip_errors:
                print("Cannot modify {0} because {1}".format(wheel, e))
                continue
            raise
        if args.verbose:
            if fname is None:
                print(
                    "{0} already has tags {1}".format(
                        wheel, ", ".join(plat_tags)
                    )
                )
            else:
                print("Wrote {0}".format(fname))
        if (
            args.rm_orig
            and fname is not None
            and realpath(fname) != realpath(wheel)
        ):
            os.unlink(wheel)
            if args.verbose:
                print("Deleted old wheel " + wheel)


if __name__ == "__main__":
    main()
