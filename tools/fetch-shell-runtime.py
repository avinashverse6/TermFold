"""Stages PRoot + its loaders into jniLibs, and the Debian rootfs into assets.

Run from the repo root:  py -3 tools/fetch-shell-runtime.py
One architecture only:    py -3 tools/fetch-shell-runtime.py --abi armeabi-v7a

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

Each ABI takes the Termux package built for it — Termux calls armeabi-v7a simply
"arm" — and the Debian image debuerreotype builds for it, which lives on that
architecture's own branch of the artifacts repository (dist-arm32v7 for armhf).
Nothing is ever copied from one architecture to another: stage_native() checks
the ELF class and machine of every file it writes.
"""
import hashlib
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
PROOT_PKGS = {
    "arm64-v8a": {
        "proot": f"{TERMUX_POOL}/p/proot/proot_5.1.107.92_aarch64.deb",
        "talloc": f"{TERMUX_POOL}/libt/libtalloc/libtalloc_2.4.3_aarch64.deb",
        "shmem": f"{TERMUX_POOL}/liba/libandroid-shmem/libandroid-shmem_0.7_aarch64.deb",
    },
    # Termux's 32-bit ARM arch is spelled "arm"; its packages are armeabi-v7a
    # (softfp-compatible, VFPv3 baseline), which is what the app ships.
    "armeabi-v7a": {
        "proot": f"{TERMUX_POOL}/p/proot/proot_5.1.107.92_arm.deb",
        "talloc": f"{TERMUX_POOL}/libt/libtalloc/libtalloc_2.4.3_arm.deb",
        "shmem": f"{TERMUX_POOL}/liba/libandroid-shmem/libandroid-shmem_0.7_arm.deb",
    },
    "x86_64": {
        "proot": f"{TERMUX_POOL}/p/proot/proot_5.1.107.92_x86_64.deb",
        "talloc": f"{TERMUX_POOL}/libt/libtalloc/libtalloc_2.4.3_x86_64.deb",
        "shmem": f"{TERMUX_POOL}/liba/libandroid-shmem/libandroid-shmem_0.7_x86_64.deb",
    },
}

# SHA-256 of each .deb that is staged, keyed "<abi>/<package>". A missing key means the ABI
# predates this table and is left exactly as it was; a key whose value is None means the digests
# have not been recorded yet, and the script then refuses to stage that file rather than trust
# whatever the network returned. Record them with:
#
#     py -3 tools/fetch-shell-runtime.py --record-checksums armeabi-v7a
#
# which downloads, prints the lines to paste here, and stages nothing. No checksum in this table
# may be guessed or copied from another architecture: it is the fingerprint of the exact bytes
# that ship.
DEB_SHA256 = {
    "armeabi-v7a/proot": None,
    "armeabi-v7a/talloc": None,
    "armeabi-v7a/shmem": None,
}

# The official Debian 13 "trixie-slim" rootfs, taken from the debuerreotype artifacts repository
# (the same tarball the Docker image is built from). Each architecture lives on its own branch:
# dist-arm64v8, dist-arm32v7, dist-amd64. Pinned to a commit and a SHA-256 so the bytes that ship
# are exactly these.
DEBIAN_ARTIFACTS = "https://raw.githubusercontent.com/debuerreotype/docker-debian-artifacts"
DEBIAN = {
    "arm64-v8a": (
        "ca011a8b1c3b259e4cbbf83bf6841f1fd5f497c1",
        "bd36565c0fdebaf0f3af5c3b4ce610ca085ced32e9e9da850d95912f5f18f47b",
    ),
    # trixie armhf, from the dist-arm32v7 branch. Verified 2026-11-06: the tarball unpacks to
    # Debian GNU/Linux 13, dpkg reports Architecture: armhf, /lib/ld-linux-armhf.so.3 is present,
    # and its binaries are ARMv7 + VFPv3-D16 hard-float.
    "armeabi-v7a": (
        "7978fc031d5b52b4496cff0bafb95b9bc828c79a",
        "0b78a5fe7810b9342d6d9e33a1bae5b9a7b92e5a742e413e190b32a7b0b3cfb5",
    ),
    "x86_64": (
        "8f962b15d7884a90e17876a9303cbac909d119aa",
        "6b37362b3da78869050b894b799ad4df04f1f3b52774087db0d81151570244c8",
    ),
}

# ELF class and e_machine per ABI, so a binary from the wrong architecture can never be staged
# under the right name.
ELF_ABI = {
    "arm64-v8a": (2, 183),   # ELFCLASS64, EM_AARCH64
    "armeabi-v7a": (1, 40),  # ELFCLASS32, EM_ARM
    "x86_64": (2, 62),       # ELFCLASS64, EM_X86_64
}


# Each ABI gets its own asset named after the ABI.
def download(url, dest):
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        print(f"  cached {os.path.basename(dest)}")
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"  downloading {url}")
    try:
        subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", dest, url], check=True)
    except subprocess.CalledProcessError:
        raise SystemExit(
            f"could not download {url}\n"
            "Either the host is unreachable from here, or the file is gone: Termux removes "
            "superseded packages from its pool, so a 404 means the versions in PROOT_PKGS need "
            "bumping for every ABI at once."
        )
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


def deb_file(deb, wanted):
    """Returns the bytes of one path inside a .deb's data.tar."""
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
                    name = member.name.lstrip("./")
                    if name == prefix + wanted:
                        return tf.extractfile(member).read()
    raise SystemExit(f"{wanted} not found in {deb}")


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


def elf_abi(path):
    """Returns (ELF class, e_machine) of the file at [path]."""
    with open(path, "rb") as f:
        ident = f.read(20)
    if ident[:4] != b"\x7fELF":
        raise SystemExit(f"not an ELF file: {path}")
    return ident[4], struct.unpack_from("<H", ident, 18)[0]


def stage_native(abis, record=False):
    for abi in abis:
        urls = PROOT_PKGS[abi]
        print(f"[{abi}] native")
        dest = os.path.join(JNI, abi)
        cache = os.path.join(WORK, "debs")
        debs = {
            "proot": download(urls["proot"], os.path.join(cache, f"proot-{abi}.deb")),
            "talloc": download(urls["talloc"], os.path.join(cache, f"talloc-{abi}.deb")),
            "shmem": download(urls["shmem"], os.path.join(cache, f"shmem-{abi}.deb")),
        }

        # Refuse to stage anything that is not pinned (see DEB_SHA256).
        unpinned = [name for name in debs
                    if DEB_SHA256.get(f"{abi}/{name}", "") is None]
        if record:
            print("  # paste into DEB_SHA256, after checking each download by hand:")
            for name, deb in debs.items():
                print(f'    "{abi}/{name}": "{sha256_of(deb)}",')
            continue
        if unpinned:
            raise SystemExit(
                f"[{abi}] no pinned SHA-256 for: {', '.join(unpinned)}\n"
                f"Record it first:\n    py -3 tools/fetch-shell-runtime.py "
                f"--record-checksums {abi}\n"
                "then paste the printed lines into DEB_SHA256 and commit them."
            )
        for name, deb in debs.items():
            expected = DEB_SHA256.get(f"{abi}/{name}")
            if expected is not None and sha256_of(deb) != expected:
                os.remove(deb)
                raise SystemExit(f"checksum mismatch for {urls[name]}")

        os.makedirs(dest, exist_ok=True)
        bins = os.path.join(dest, "libproot.so")
        with open(bins, "wb") as f:
            f.write(deb_file(debs["proot"], "bin/proot"))
        with open(os.path.join(dest, "libtalloc.so"), "wb") as f:
            f.write(deb_file(debs["talloc"], "lib/libtalloc.so.2.4.3"))
        with open(os.path.join(dest, "libandroid-shmem.so"), "wb") as f:
            f.write(deb_file(debs["shmem"], "lib/libandroid-shmem.so"))
        # The loader is statically linked on purpose: it runs before any dynamic
        # linker exists inside the guest, and it is what makes exec from
        # nativeLibraryDir work at all. Only the 64-bit builds of proot carry a
        # second, 32-bit loader (installed by Termux as libexec/proot/loader32),
        # and only to run 32-bit guests — which this app never does, so the
        # single loader here is complete for every ABI.
        with open(os.path.join(dest, "libproot-loader.so"), "wb") as f:
            f.write(deb_file(debs["proot"], "libexec/proot/loader"))

        if patch_needed(bins, "libtalloc.so.2", "libtalloc.so"):
            print("  patched DT_NEEDED libtalloc.so.2 -> libtalloc.so")
        else:
            print("  !! DT_NEEDED patch did not apply")

        want_class, want_machine = ELF_ABI[abi]
        for name in os.listdir(dest):
            path = os.path.join(dest, name)
            os.chmod(path, 0o755)
            cls, machine = elf_abi(path)
            if (cls, machine) != (want_class, want_machine):
                raise SystemExit(
                    f"{path} is ELF class {cls} machine {machine}, but {abi} needs "
                    f"class {want_class} machine {want_machine}"
                )


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_rootfs(abis):
    os.makedirs(ASSETS, exist_ok=True)
    for abi in abis:
        commit, digest = DEBIAN[abi]
        print(f"[{abi}] rootfs")
        cache = os.path.join(WORK, "rootfs")
        url = f"{DEBIAN_ARTIFACTS}/{commit}/trixie/slim/oci/blobs/rootfs.tar.gz"
        # A neutral extension: AGP transparently gunzips assets that end in .gz,
        # which would silently change the bytes we ship.
        archive = download(url, os.path.join(cache, f"debian-{abi}.tar.gz"))
        if sha256_of(archive) != digest:
            os.remove(archive)
            raise SystemExit(f"checksum mismatch for {url}")
        out = os.path.join(ASSETS, f"debian-{abi}.bin")
        shutil.copyfile(archive, out)
        print(f"  -> assets/{os.path.basename(out)} "
              f"({os.path.getsize(out) / 1e6:.1f} MB)")


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return
    record = "--record-checksums" in argv
    args = [a for a in argv[1:] if a != "--record-checksums"]
    abis = list(PROOT_PKGS)
    if "--abi" in args:
        i = args.index("--abi")
        abis = args[i + 1].split(",")
        del args[i:i + 2]
    if args:
        raise SystemExit(f"unknown argument(s): {' '.join(args)}")
    unknown = [abi for abi in abis if abi not in PROOT_PKGS]
    if unknown:
        raise SystemExit(f"unknown ABI(s): {', '.join(unknown)} (have: {', '.join(PROOT_PKGS)})")

    os.makedirs(WORK, exist_ok=True)
    stage_native(abis, record=record)
    if not record:
        stage_rootfs(abis)
    print("done")


if __name__ == "__main__":
    main(sys.argv)
