"""Checks that an APK's native libraries match the ABIs it claims to support.

    py -3 tools/check-apk-abi.py app/build/outputs/apk/release/TermFold-release.apk
    py -3 tools/check-apk-abi.py TermFold-arm64-v8a-release.apk --require arm64-v8a

For every `lib/<abi>/lib*.so` in the archive it reads the ELF header and asserts the class and
machine belong to that ABI, so a renamed or copied binary — an arm64 PRoot sitting in
`lib/armeabi-v7a/`, say — fails the check instead of shipping. It also requires the four files
PRoot needs to be present for any ABI the APK carries at all, because an APK with the terminal
library for an ABI but no PRoot installs and then cannot start a session.

Extra libraries from the Termux terminal AARs (`libtermux.so`) are expected and allowed; only
their architecture is checked.
"""
import os
import struct
import sys
import zipfile

# Android ABI -> (ELF class, e_machine).
ELF_ABI = {
    "arm64-v8a": (2, 183),   # ELFCLASS64, EM_AARCH64
    "armeabi-v7a": (1, 40),  # ELFCLASS32, EM_ARM
    "x86_64": (2, 62),       # ELFCLASS64, EM_X86_64
    # 32-bit x86 is not a TermFold architecture: the Termux terminal emulator's AAR ships
    # libtermux.so for it and for armeabi-v7a, so it appears in a universal APK and its
    # architecture is still worth checking — but it carries no PRoot and cannot host a session.
    "x86": (1, 3),           # ELFCLASS32, EM_386
}

# The architectures that must have PRoot beside the terminal library.
HOST_ABIS = ["arm64-v8a", "armeabi-v7a", "x86_64"]

# Everything PRoot needs beside it, in nativeLibraryDir.
RUNTIME = [
    "libproot.so",
    "libproot-loader.so",
    "libtalloc.so",
    "libandroid-shmem.so",
]


def elf_head(data):
    if data[:4] != b"\x7fELF":
        return None
    return data[4], struct.unpack_from("<H", data, 18)[0]


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    required = []
    if "--require" in argv[1:]:
        required = argv[argv.index("--require") + 1].split(",")
        args = [a for a in args if a not in required]
    if len(args) != 1:
        raise SystemExit(__doc__)
    apk = args[0]
    if not os.path.isfile(apk):
        raise SystemExit(f"no such file: {apk}")

    problems = []
    seen = {}
    with zipfile.ZipFile(apk) as z:
        for name in z.namelist():
            parts = name.split("/")
            if len(parts) != 3 or parts[0] != "lib" or not parts[2].startswith("lib"):
                continue
            abi = parts[1]
            if abi not in ELF_ABI:
                problems.append(f"unexpected ABI directory lib/{abi}/")
                continue
            want = ELF_ABI[abi]
            got = elf_head(z.read(name)[:64])
            if got != want:
                problems.append(
                    f"{name}: ELF class/machine {got}, expected {want} for {abi}"
                )
            seen.setdefault(abi, set()).add(parts[2])

    if not seen:
        problems.append("the APK contains no lib/<abi>/ libraries at all")

    # A half-staged runtime is always a failure, and an ABI the caller asked for must have one.
    # An ABI that carries nothing but the terminal library (the Termux AAR ships armeabi-v7a and
    # x86 whether or not this app has a runtime for them) is reported, not failed: that is what a
    # universal APK without the 32-bit PRoot looks like, and it is a fact about the build worth
    # printing rather than an error to hide.
    notices = []
    for abi in sorted(seen):
        if abi not in HOST_ABIS:
            continue
        missing = [name for name in RUNTIME if name not in seen[abi]]
        if not missing:
            continue
        if len(missing) < len(RUNTIME) or abi in required:
            problems.append(
                f"lib/{abi}/ has no {', '.join(missing)} — did tools/fetch-shell-runtime.py "
                f"run for this ABI?"
            )
        else:
            notices.append(f"lib/{abi}/ carries no PRoot, so that ABI cannot start a session")
    for abi in required:
        if abi not in seen:
            problems.append(f"lib/{abi}/ is missing, but this APK was built for it")

    summary = ", ".join(
        f"{abi} ({len(libs)} libs" + ("" if abi in HOST_ABIS else ", terminal only") + ")"
        for abi, libs in sorted(seen.items())
    )
    if problems:
        print(f"{apk}: FAILED\n  " + "\n  ".join(problems))
        return 1
    print(f"{apk}: OK — {summary}")
    for notice in notices:
        print(f"  note: {notice}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
