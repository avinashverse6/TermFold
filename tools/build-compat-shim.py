"""Cross-compiles tools/compat-shim/termfold_compat.c into app/src/main/assets/compat-shim-<abi>.so.

The library is preloaded into every program in the Debian guest (see the comment at the top of
the C file), so it is linked against the *guest's* libc (glibc), never Android's bionic — it is
never loaded by the Android process itself. Zig is used as the cross-compiler so this runs on any
host:

    py -3 -m pip install ziglang
    py -3 tools/build-compat-shim.py              # every architecture
    py -3 tools/build-compat-shim.py armeabi-v7a  # just one

The outputs are a few KB and are committed, so a normal build does not need Zig.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "tools", "compat-shim", "termfold_compat.c")
ASSETS = os.path.join(ROOT, "app", "src", "main", "assets")

# Android ABI -> (Zig glibc target, extra flags).
#
# arm64-v8a and x86_64: LP64, so time_t is already 64-bit and glibc 2.17 is the floor — the
# library loads in any Debian guest from 9 onwards.
#
# armeabi-v7a: 32-bit, and Debian 13 (trixie) armhf is one of the architectures that moved to a
# 64-bit time_t in the t64 transition — dpkg in the shipped image imports __stat64. Building
# against 2.17 headers would therefore give a library whose fstatat/futimens read and write the
# legacy 32-bit layout, which is wrong for every package built with _TIME_BITS=64 and truncates
# timestamps past 2038. So this target uses glibc 2.34 headers, the first that provide
# _TIME_BITS=64 and the __*_time64 entry points, and opts into them. Checked against the trixie
# armhf libc 2.41 in the bundled image: it exports __futimens64@@GLIBC_2.34,
# __fstatat64_time64@@GLIBC_2.34, dlsym@@GLIBC_2.34 and mkostemp64@@GLIBC_2.7, which are the only
# versioned symbols this build needs (readelf -V). A guest older than glibc 2.34 cannot preload
# it — no such guest is shipped or supported.
TARGETS = {
    "arm64-v8a": ("aarch64-linux-gnu.2.17", []),
    "x86_64": ("x86_64-linux-gnu.2.17", []),
    "armeabi-v7a": ("arm-linux-gnueabihf.2.34", ["-D_TIME_BITS=64", "-D_FILE_OFFSET_BITS=64"]),
}


def main(argv):
    wanted = argv[1:] or list(TARGETS)
    unknown = [abi for abi in wanted if abi not in TARGETS]
    if unknown:
        raise SystemExit(f"unknown ABI(s): {', '.join(unknown)} (have: {', '.join(TARGETS)})")
    for abi in wanted:
        target, extra = TARGETS[abi]
        out = os.path.join(ASSETS, f"compat-shim-{abi}.so")
        subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-target", target, "-shared", "-fPIC",
             "-O2", "-s", "-Wall", "-o", out, SOURCE, "-ldl"] + extra,
            check=True,
        )
        print(f"  {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main(sys.argv)
