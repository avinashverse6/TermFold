"""Cross-compiles tools/compat-shim/termfold_compat.c into app/src/main/assets/compat-shim-<abi>.so.

The library is preloaded into every program in the Debian guest (see the comment at the top of
the C file). Zig is used as the cross-compiler so this runs on any host:

    py -3 -m pip install ziglang
    py -3 tools/build-compat-shim.py

Pass `--abi <abi>` to rebuild a single architecture.

The outputs are a few KB and are committed, so a normal build does not need Zig. Each one is
checked after it is built: it must be the ELF class and machine of the ABI it is named after, or
the guest's loader would refuse it at first use (or, worse, on a 32-bit ARM phone the app would
ship an arm64 library that silently never preloads).
"""
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "tools", "compat-shim", "termfold_compat.c")
ASSETS = os.path.join(ROOT, "app", "src", "main", "assets")

# Android ABI -> (Zig target, ELF class, e_machine). glibc 2.17 is the floor, so the library loads
# in any Debian guest (trixie ships 2.41 on every architecture).
#
# armeabi-v7a is armhf — the same hard-float ABI Debian's armhf port uses — and not the softfp
# Android target: this library is only ever loaded *inside* the Debian guest, whose userspace is
# hard-float, so it has to match the guest rather than the app process.
TARGETS = {
    "arm64-v8a": ("aarch64-linux-gnu.2.17", 2, 183),
    "armeabi-v7a": ("arm-linux-gnueabihf.2.17", 1, 40),
    "x86_64": ("x86_64-linux-gnu.2.17", 2, 62),
}


def check(path, want_class, want_machine):
    data = open(path, "rb").read(20)
    if data[:4] != b"\x7fELF":
        raise SystemExit(f"{path} is not an ELF file")
    machine = struct.unpack_from("<H", data, 18)[0]
    if (data[4], machine) != (want_class, want_machine):
        raise SystemExit(
            f"{path} came out as ELF class {data[4]} machine {machine}, "
            f"expected class {want_class} machine {want_machine}"
        )


def main():
    abis = list(TARGETS)
    if "--abi" in sys.argv:
        abis = [a for a in sys.argv[sys.argv.index("--abi") + 1:] if not a.startswith("-")]
        unknown = [a for a in abis if a not in TARGETS]
        if unknown:
            raise SystemExit(f"unknown ABI(s): {', '.join(unknown)}; known: {', '.join(TARGETS)}")
    for abi in abis:
        target, want_class, want_machine = TARGETS[abi]
        out = os.path.join(ASSETS, f"compat-shim-{abi}.so")
        subprocess.run(
            [sys.executable, "-m", "ziglang", "cc", "-target", target, "-shared", "-fPIC",
             "-O2", "-s", "-Wall", "-o", out, SOURCE, "-ldl"],
            check=True,
        )
        check(out, want_class, want_machine)
        print(f"  {out} ({os.path.getsize(out)} bytes)")


if __name__ == "__main__":
    main()
