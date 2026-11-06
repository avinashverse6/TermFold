"""Fetches the CA bundle this app installs into the guest.

The Ubuntu base image carries the archive keyring but no certificate authorities, so every
https:// request from inside the guest fails until one is provided. Installing
`ca-certificates` with apt is not possible, because apt is the thing that needs working TLS.

The bundle is the same set of authorities the distribution itself trusts, taken from whichever
source is available:

* the bundle this machine already has (`/etc/ssl/certs/ca-certificates.crt` on Debian and Ubuntu,
  which is what `update-ca-certificates` writes from that very package) — no network at all;
* otherwise the newest `ca-certificates` .deb in Ubuntu's pool, assembled the way
  `update-ca-certificates` would.

Run from the repo root:  py -3 tools/fetch-ca-bundle.py
Force the download:     py -3 tools/fetch-ca-bundle.py --download
Use another bundle:      py -3 tools/fetch-ca-bundle.py --from /path/to/ca-certificates.crt
"""
import io
import lzma
import os
import re
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "app", "src", "main", "assets")
WORK = os.path.join(ROOT, ".work")

POOL = "http://archive.ubuntu.com/ubuntu/pool/main/c/ca-certificates/"

# Where a Debian-family machine keeps the bundle `update-ca-certificates` generates, then the
# equivalents on Fedora/RHEL and macOS.
HOST_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/cert.pem",
)


def host_bundle():
    """The bundle this machine already trusts, or None.

    On Debian and Ubuntu this file is written from the same `ca-certificates` package the download
    path unpacks, so it is the same authorities without a network round trip. CI uses this: the
    pool index is a directory listing that changes shape, and a build should not depend on it.
    """
    for path in HOST_BUNDLES:
        try:
            if os.path.getsize(path) > 100_000:
                return path
        except OSError:
            continue
    return None


def newest_deb():
    """Finds the newest ca-certificates .deb the mirror offers."""
    out = subprocess.run(
        ["curl", "-fsSL", "--max-time", "120", POOL],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace")
    names = re.findall(r'href="(ca-certificates_([0-9][^"]*)_all\.deb)"', out)
    if not names:
        raise SystemExit("no ca-certificates package found at " + POOL)
    # Sort by the version string; these are date-like and sort correctly as text.
    names.sort(key=lambda pair: pair[1])
    return names[-1][0]


def ar_members(path):
    with open(path, "rb") as handle:
        if handle.read(8) != b"!<arch>\n":
            raise SystemExit("not an ar archive: " + path)
        while True:
            header = handle.read(60)
            if len(header) < 60:
                return
            name = header[0:16].decode("ascii", "replace").strip().rstrip("/")
            size = int(header[48:58].decode("ascii").strip())
            data = handle.read(size)
            if size % 2:
                handle.read(1)
            yield name, data


def data_tar(deb):
    for name, data in ar_members(deb):
        if name.startswith("data.tar"):
            if name.endswith(".xz"):
                return lzma.decompress(data)
            if name.endswith(".gz"):
                import gzip
                return gzip.decompress(data)
            if name.endswith(".zst"):
                # Python 3.14 has zstd in the standard library; older versions need the `zstandard`
                # package, which is worth avoiding as a build dependency.
                try:
                    from compression import zstd
                except ImportError:
                    try:
                        import zstandard as zstd
                    except ImportError:
                        raise SystemExit(
                            "unpacking data.tar.zst needs Python 3.14+ or `pip install zstandard`"
                        )
                return zstd.decompress(data)
            return data
    raise SystemExit("no data.tar in " + deb)


def write_bundle(pem_parts, label):
    out = os.path.join(ASSETS, "ca-certificates.crt")
    with open(out, "wb") as handle:
        for pem in pem_parts:
            handle.write(pem if pem.endswith(b"\n") else pem + b"\n")
    size = os.path.getsize(out)
    print(f"{label} -> assets/ca-certificates.crt "
          f"({size} bytes, {len(pem_parts)} authorities)")
    return out


def main(argv):
    force_download = "--download" in argv
    given = None
    if "--from" in argv:
        given = argv[argv.index("--from") + 1]
    os.makedirs(ASSETS, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)

    local = given or (None if force_download else host_bundle())
    if local:
        with open(local, "rb") as handle:
            data = handle.read()
        blocks = re.findall(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", data, re.S)
        write_bundle([block + b"\n" for block in blocks], local)
        return 0

    deb_name = newest_deb()
    deb = os.path.join(WORK, deb_name)
    if not os.path.isfile(deb):
        print("downloading", deb_name)
        subprocess.run(["curl", "-fsSL", "--max-time", "300", "-o", deb, POOL + deb_name],
                       check=True)

    # The package carries one PEM per authority under /usr/share/ca-certificates/mozilla, not a
    # concatenated bundle, so the bundle is assembled here the same way update-ca-certificates
    # would. Authorities only; the local ones are for private infrastructure.
    authorities = []
    with tarfile.open(fileobj=io.BytesIO(data_tar(deb))) as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            if "/mozilla/" in member.name and member.name.endswith(".crt"):
                authorities.append((member.name, tf.extractfile(member).read()))

    if not authorities:
        raise SystemExit("no certificates found inside " + deb_name)

    authorities.sort(key=lambda pair: pair[0])
    write_bundle([pem for _name, pem in authorities], deb_name)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
