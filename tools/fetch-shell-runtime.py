"""Stages PRoot + its loaders into jniLibs, and the Debian rootfs into assets.

Run from the repo root:  py -3 tools/fetch-shell-runtime.py

Why this is done the way it is
------------------------------
Android refuses to execve() anything under an app's filesDir/cacheDir (the W^X
policy), with exactly one exception: nativeLibraryDir. The only way to get a
file there is to place it in app/src/main/jniLibs/<abi>/ under a lib*.so name,
so every executable we bundle is renamed to fit that pattern and then copied out
to a real filename at first run.

Renaming libtalloc.so.2 to libtalloc.so means libproot.so can no longer resolve
its DT_NEEDED entry, so that string is rewritten in place (it only gets shorter,
so no ELF offsets move).

Every binary is checked against the ABI it is filed under before it is staged:
a .deb whose architecture is wrong (arm64 pulled for armeabi-v7a, say) is a
build error, not something to discover on a device. The same goes for the
rootfs: its /bin/bash and libc are read out of the archive and their ELF
headers checked, so a 32-bit ARM APK can never be shipped with a 64-bit image.
"""
import lzma
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, ".work")
JNI = os.path.join(ROOT, "app", "src", "main", "jniLibs")
ASSETS = os.path.join(ROOT, "app", "src", "main", "assets")

TERMUX_POOL = "https://packages.termux.dev/apt/termux-main/pool/main"

# proot is built by Termux and is the only thing here that understands
# Android's seccomp policy and the loader hand-off.
#
# Termux stopped building the 32-bit architectures in 2023, so the files it
# publishes for arm are frozen at the last build it made for them: proot
# 5.1.107.102 and talloc 2.5.0, against 5.1.107.92 / 2.4.3 for arm64 and
# x86_64. They are the same GPL-2.0 / LGPL-3.0 PRoot and talloc sources, built
# for Android ARMv7 by the same Termux build system (NDK r29), and they are the
# only genuine ARMv7 Android builds that exist upstream. libandroid-shmem is
# 0.7 for every ABI.
PROOT_PKGS = {
    "arm64-v8a": {
        "proot": f"{TERMUX_POOL}/p/proot/proot_5.1.107.92_aarch64.deb",
        "talloc": f"{TERMUX_POOL}/libt/libtalloc/libtalloc_2.4.3_aarch64.deb",
        "shmem": f"{TERMUX_POOL}/liba/libandroid-shmem/libandroid-shmem_0.7_aarch64.deb",
    },
    "armeabi-v7a": {
        "proot": f"{TERMUX_POOL}/p/proot/proot_5.1.107.102_arm.deb",
        "talloc": f"{TERMUX_POOL}/libt/libtalloc/libtalloc_2.5.0_arm.deb",
        "shmem": f"{TERMUX_POOL}/liba/libandroid-shmem/libandroid-shmem_0.7_arm.deb",
    },
    "x86_64": {
        "proot": f"{TERMUX_POOL}/p/proot/proot_5.1.107.92_x86_64.deb",
        "talloc": f"{TERMUX_POOL}/libt/libtalloc/libtalloc_2.4.3_x86_64.deb",
        "shmem": f"{TERMUX_POOL}/liba/libandroid-shmem/libandroid-shmem_0.7_x86_64.deb",
    },
}

# The official Debian 13 "trixie-slim" rootfs, taken from the debuerreotype artifacts repository
# (the same tarball the Docker image is built from). Pinned to a commit and a SHA-256 so the
# bytes that ship are exactly these. Each ABI is a different Debian architecture: armhf (32-bit
# ARM hard-float) for armeabi-v7a, arm64 for arm64-v8a and amd64 for x86_64.
DEBIAN_ARTIFACTS = "https://raw.githubusercontent.com/debuerreotype/docker-debian-artifacts"
DEBIAN = {
    "arm64-v8a": (
        "ca011a8b1c3b259e4cbbf83bf6841f1fd5f497c1",
        "bd36565c0fdebaf0f3af5c3b4ce610ca085ced32e9e9da850d95912f5f18f47b",
    ),
    "armeabi-v7a": (
        # dist-arm32v7 branch, debian:trixie-slim, Debian 13.7 (armhf).
        "7978fc031d5b52b4496cff0bafb95b9bc828c79a",
        "0b78a5fe7810b9342d6d9e33a1bae5b9a7b92e5a742e413e190b32a7b0b3cfb5",
    ),
    "x86_64": (
        "8f962b15d7884a90e17876a9303cbac909d119aa",
        "6b37362b3da78869050b894b799ad4df04f1f3b52774087db0d81151570244c8",
    ),
}

# ELF identity each ABI must have: (ELF class, e_machine, Debian multiarch triplet).
ELF = {
    "armeabi-v7a": (1, 40, "arm-linux-gnueabihf"),   # ELFCLASS32, EM_ARM
    "arm64-v8a": (2, 183, "aarch64-linux-gnu"),      # ELFCLASS64, EM_AARCH64
    "x86_64": (2, 62, "x86_64-linux-gnu"),           # ELFCLASS64, EM_X86_64
}

# How each ABI is named in ELF terms, for messages.
ARCH_NAME = {"armeabi-v7a": "ARMv7 (32-bit ARM)", "arm64-v8a": "ARM64", "x86_64": "x86_64"}


def download(url, dest):
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        print(f"  cached {os.path.basename(dest)}")
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"  downloading {url}")
    subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", dest, url], check=True)
    return dest


def ar_members(path):
    with open(path, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            raise SystemExit(f"not an ar archive: {path}")
        while True:
            header = f.read(60)
            if len(header) < 60:
                return
            name = header[0:16].decode("ascii", "replace").strip().rstrip("/")
            size = int(header[48:58].decode("ascii").strip())
            data = f.read(size)
            if size % 2:
                f.read(1)
            yield name, data


def deb_members(deb):
    """Yields (path, bytes) for every file in a .deb's data.tar, without extracting to disk."""
    for name, data in ar_members(deb):
        if name.startswith("data.tar"):
            if name.endswith(".xz"):
                data = lzma.decompress(data)
            elif name.endswith(".gz"):
                import gzip
                data = gzip.decompress(data)
            with tarfile.open(fileobj=io.BytesIO(data)) as tf:
                prefix = "data/data/com.termux/files/usr/"
                for member in tf.getmembers():
                    path = member.name.lstrip("./")
                    if path.startswith(prefix) and member.isfile():
                        yield path[len(prefix):], tf.extractfile(member).read()


def deb_file(deb, wanted):
    """Returns the bytes of one path inside a .deb's data.tar.

    Extension packages version their shared libraries in the file name
    (libtalloc.so.2.4.3), and Termux's arm build is a different version from its
    arm64 one, so a bare name may also be a prefix: libtalloc.so.2.
    """
    for path, data in deb_members(deb):
        if path == wanted:
            return data
    for path, data in deb_members(deb):
        if path.startswith(wanted) and not path.endswith((".a", ".h")):
            return data
    raise SystemExit(f"{wanted} not found in {deb}")


def elf_identity(data):
    """(class, machine) from an ELF header, or None when the bytes are not an ELF."""
    if len(data) < 20 or data[:4] != b"\x7fELF":
        return None
    return data[4], struct.unpack_from("<H", data, 18)[0]


def check_elf(path, abi, what=None):
    """Fails the build when a staged file is not the architecture it is filed under."""
    data = open(path, "rb").read()
    found = elf_identity(data)
    if found is None:
        raise SystemExit(f"{what or path} is not an ELF file")
    want = ELF[abi][:2]
    if found != want:
        raise SystemExit(
            f"{what or path} is not {ARCH_NAME[abi]}: ELF class {found[0]}, machine {found[1]} "
            f"(expected class {want[0]}, machine {want[1]})"
        )
    return data


def patch_needed(path, old, new):
    """Rewrites a DT_NEEDED string in place. `new` must not be longer than `old`."""
    if len(new) > len(old):
        raise SystemExit("in-place patch can only shorten a string")
    data = bytearray(open(path, "rb").read())
    is64 = data[4] == 2
    if is64:
        phoff, phentsize, phnum = (struct.unpack_from("<Q", data, 32)[0],
                                  struct.unpack_from("<H", data, 54)[0],
                                  struct.unpack_from("<H", data, 56)[0])
    else:
        phoff, phentsize, phnum = (struct.unpack_from("<I", data, 28)[0],
                                  struct.unpack_from("<H", data, 42)[0],
                                  struct.unpack_from("<H", data, 44)[0])
    dynoff = dynsz = None
    for i in range(phnum):
        off = phoff + i * phentsize
        if struct.unpack_from("<I", data, off)[0] == 2:
            if is64:
                dynoff = struct.unpack_from("<Q", data, off + 8)[0]
                dynsz = struct.unpack_from("<Q", data, off + 32)[0]
            else:
                dynoff = struct.unpack_from("<I", data, off + 4)[0]
                dynsz = struct.unpack_from("<I", data, off + 16)[0]
    if dynoff is None:
        return False
    entsz = 16 if is64 else 8
    strtab = None
    targets = []
    for i in range(dynsz // entsz):
        off = dynoff + i * entsz
        if is64:
            tag = struct.unpack_from("<q", data, off)[0]
            val = struct.unpack_from("<Q", data, off + 8)[0]
        else:
            tag = struct.unpack_from("<i", data, off)[0]
            val = struct.unpack_from("<I", data, off + 4)[0]
        if tag == 0:
            break
        if tag == 5:
            strtab = val
        elif tag == 1:
            targets.append(val)
    if strtab is None:
        return False
    patched = False
    for value in targets:
        start = strtab + value
        end = data.index(b"\x00", start)
        if bytes(data[start:end]) == old.encode():
            data[start:start + len(old)] = new.encode() + b"\x00" * (len(old) - len(new))
            patched = True
    if patched:
        open(path, "wb").write(data)
    return patched


def stage_native(abis):
    for abi in abis:
        urls = PROOT_PKGS[abi]
        print(f"[{abi}] native ({ARCH_NAME[abi]})")
        dest = os.path.join(JNI, abi)
        os.makedirs(dest, exist_ok=True)
        cache = os.path.join(WORK, "debs")
        proot_deb = download(urls["proot"], os.path.join(cache, f"proot-{abi}.deb"))
        talloc_deb = download(urls["talloc"], os.path.join(cache, f"talloc-{abi}.deb"))
        shmem_deb = download(urls["shmem"], os.path.join(cache, f"shmem-{abi}.deb"))

        files = {
            "libproot.so": (proot_deb, "bin/proot"),
            "libtalloc.so": (talloc_deb, "lib/libtalloc.so.2"),
            "libandroid-shmem.so": (shmem_deb, "lib/libandroid-shmem.so"),
            # The loader is statically linked on purpose: it runs before any dynamic
            # linker exists inside the guest, and it is what makes exec from
            # nativeLibraryDir work at all.
            "libproot-loader.so": (proot_deb, "libexec/proot/loader"),
        }
        for name, (deb, wanted) in files.items():
            path = os.path.join(dest, name)
            with open(path, "wb") as f:
                f.write(deb_file(deb, wanted))
            check_elf(path, abi, what=f"{abi}/{name} (from {os.path.basename(deb)})")

        bins = os.path.join(dest, "libproot.so")
        if patch_needed(bins, "libtalloc.so.2", "libtalloc.so"):
            print("  patched DT_NEEDED libtalloc.so.2 -> libtalloc.so")
        else:
            print("  !! DT_NEEDED patch did not apply")

        for name in os.listdir(dest):
            os.chmod(os.path.join(dest, name), 0o755)


def sha256_of(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_rootfs_arch(archive, abi):
    """Reads bash and libc out of the image and checks they are this ABI's.

    A mismatched image is the one mistake that cannot be recovered from on a
    device — a 32-bit ARM phone cannot run an arm64 Debian — so the bytes that
    are about to be shipped are inspected rather than trusted.
    """
    class_, machine, triplet = ELF[abi]
    libdir = f"usr/lib/{triplet}/"
    required = {"usr/bin/bash", libdir + "libc.so.6"}
    seen = set()
    loader = False
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf:
            name = member.name.lstrip("./")
            is_loader = name.startswith(libdir + "ld-linux-")
            if name not in required and not is_loader:
                continue
            if not member.isfile():
                continue
            found = elf_identity(tf.extractfile(member).read(64))
            if found is None:
                raise SystemExit(f"{abi} rootfs: {name} is not an ELF file")
            if found != (class_, machine):
                raise SystemExit(
                    f"{abi} rootfs: {name} is class {found[0]} machine {found[1]}, expected "
                    f"{class_}/{machine} - this is not a {ARCH_NAME[abi]} image"
                )
            if is_loader:
                loader = True
            else:
                seen.add(name)
            if loader and required <= seen:
                break
    missing = required - seen
    if missing or not loader:
        raise SystemExit(
            f"{abi} rootfs: missing {', '.join(sorted(missing)) or libdir + 'ld-linux-*'}; "
            "this is not a usable Debian image"
        )


def stage_rootfs(abis):
    os.makedirs(ASSETS, exist_ok=True)
    for abi in abis:
        commit, digest = DEBIAN[abi]
        print(f"[{abi}] rootfs ({ARCH_NAME[abi]})")
        cache = os.path.join(WORK, "rootfs")
        url = f"{DEBIAN_ARTIFACTS}/{commit}/trixie/slim/oci/blobs/rootfs.tar.gz"
        # A neutral extension: AGP transparently gunzips assets that end in .gz,
        # which would silently change the bytes we ship.
        archive = download(url, os.path.join(cache, f"debian-{abi}.tar.gz"))
        if sha256_of(archive) != digest:
            os.remove(archive)
            raise SystemExit(f"checksum mismatch for {url}")
        check_rootfs_arch(archive, abi)
        out = os.path.join(ASSETS, f"debian-{abi}.bin")
        shutil.copyfile(archive, out)
        print(f"  -> assets/{os.path.basename(out)} "
              f"({os.path.getsize(out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        print("usage: fetch-shell-runtime.py [--abi armeabi-v7a ...]")
        raise SystemExit(0)
    selected = list(PROOT_PKGS)
    if "--abi" in sys.argv:
        selected = [a for a in sys.argv[sys.argv.index("--abi") + 1:] if not a.startswith("-")]
        unknown = [a for a in selected if a not in PROOT_PKGS]
        if unknown:
            raise SystemExit(f"unknown ABI(s): {', '.join(unknown)}; known: {', '.join(PROOT_PKGS)}")
    os.makedirs(WORK, exist_ok=True)
    stage_native(selected)
    stage_rootfs(selected)
    print(f"done ({', '.join(selected)})")
