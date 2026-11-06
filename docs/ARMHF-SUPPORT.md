# 32-bit ARM (`armeabi-v7a`) support

TermFold runs a Debian userland and a set of AI coding agents on top of PRoot. Every native piece
of that stack — PRoot, its loader, `libtalloc`, `libandroid-shmem`, the terminal's `libtermux.so`,
the compatibility shim and the Debian image itself — belongs to one CPU architecture. This page
records what 32-bit ARM needs, what is in place, and what is still missing.

## What is supported

| Android ABI | Debian port | Status |
| --- | --- | --- |
| `arm64-v8a` | arm64 | Supported (unchanged; this is what almost every device uses) |
| `x86_64` | amd64 | Supported (unchanged; emulators and a few tablets) |
| `armeabi-v7a` | armhf | **Runtime binaries not in this repository yet** — see [Completing the port](#completing-the-port) |
| `x86`, `armeabi`, `riscv64`, … | — | Not supported, and never presented as supported |

### Hardware baseline

Debian 13 (`trixie`) `armhf` is built for **ARMv7-A with Thumb-2 and VFPv3-D16** hard-float, and
that is what the bundled image requires. Verified on the shipped image (`readelf -A bin/bash`):

```
Tag_CPU_arch: v7
Tag_CPU_arch_profile: Application
Tag_FP_arch: VFPv3-D16
Tag_ABI_VFP_args: VFP registers
```

Devices older than that (ARMv6, ARMv5, `armel`, soft-float) are **not** supported: there is no
`armel` image, no emulation, and no plan to add one. In practice every Android device on API 26+
with a 32-bit ARM neon-capable core meets the baseline; a handful of very old ARMv7 chips without
VFPv3 do not.

### What is not claimed

- No CPU emulation. An `armhf` image runs only on an ARMv7 CPU, in a 32-bit process.
- No 64-bit binary is ever renamed, copied or reused as `armeabi-v7a`. `tools/fetch-shell-runtime.py`
  checks the ELF class and machine of every file it stages, and `tools/check-apk-abi.py` checks the
  same thing inside a built APK, so a mistake fails the build instead of shipping.

## Debian image

| Property | Value |
| --- | --- |
| Source | `debuerreotype/docker-debian-artifacts`, branch `dist-arm32v7`, `trixie/slim/oci/blobs/rootfs.tar.gz` |
| Pinned commit | `7978fc031d5b52b4496cff0bafb95b9bc828c79a` |
| SHA-256 | `0b78a5fe7810b9342d6d9e33a1bae5b9a7b92e5a742e413e190b32a7b0b3cfb5` |
| Size | 26,272,915 bytes (25.1 MB) |
| Licence | Debian's own (mixed free licences; `/usr/share/doc/*/copyright` inside the image) |

Checked against the extracted image:

- `/lib/ld-linux-armhf.so.3` → `arm-linux-gnueabihf/ld-linux-armhf.so.3` — present.
- `dpkg` database `Architecture: armhf`; `/etc/os-release` is `Debian GNU/Linux 13 (trixie)`.
- `glibc` 2.41, and the image **is a 64-bit `time_t` port**: `usr/bin/dpkg` itself imports
  `__stat64`, and `libc.so.6` exports both the legacy (`futimens@GLIBC_2.6`) and the time64
  (`__futimens64@@GLIBC_2.34`, `__fstatat64_time64@@GLIBC_2.34`) entry points.

That last point is why the 32-bit compatibility shim is built differently from the 64-bit ones; see
the next section.

## Compatibility shim

`app/src/main/assets/compat-shim-armeabi-v7a.so`, built by
`tools/build-compat-shim.py armeabi-v7a` from the same C source as the others. It is loaded *inside
the guest*, so it is built against the guest's glibc (Zig's `arm-linux-gnueabihf`), not against
Android's bionic.

Verified with `readelf`:

```
Class: ELF32   Machine: ARM   Type: DYN (Shared object file)   5,460 bytes
Tag_CPU_arch: v7   Tag_FP_arch: VFPv3   Tag_ABI_VFP_args: VFP registers   (hard-float)
Tag_ABI_align_needed: 8-byte   Tag_ABI_align_preserved: 8-byte, except leaf SP
LOAD … Align 0x10000
NEEDED: libc.so.6
Exports: dlopen link linkat
Version needs: GLIBC_2.4, GLIBC_2.7, GLIBC_2.34 (all present in the image's glibc 2.41)
```

It differs from the 64-bit shims in one way: it is compiled with `-D_TIME_BITS=64
-D_FILE_OFFSET_BITS=64` against glibc 2.34 headers, because trixie `armhf` is a time64 port. The
arm64 and x86_64 shims need nothing (`time_t` is already 64-bit there) and were not rebuilt.

The 16 KB page-size requirement that applies to **arm64** libraries on newer devices does not apply
here: 32-bit ARM images are 4 KB-page devices. What was actually checked is that the shim's
segments are aligned well past 4 KB (`0x10000`), which is safe either way.

## Completing the port

The four host-side binaries are Termux `arm` packages, which is what the existing `arm64-v8a` and
`x86_64` builds use as well (Termux patches PRoot for Android's seccomp policy and adds
`--kill-on-exit`, which upstream PRoot does not have):

| File in `jniLibs/armeabi-v7a/` | Termux package (arch `arm`) | Expected ELF |
| --- | --- | --- |
| `libproot.so` | `proot_5.1.107.92_arm.deb` → `bin/proot` | ELF32, EM_ARM, DYN |
| `libproot-loader.so` | same deb → `libexec/proot/loader` | ELF32, EM_ARM, EXEC, static |
| `libtalloc.so` | `libtalloc_2.4.3_arm.deb` → `lib/libtalloc.so.2.4.3` | ELF32, EM_ARM, DYN |
| `libandroid-shmem.so` | `libandroid-shmem_0.7_arm.deb` → `lib/libandroid-shmem.so` | ELF32, EM_ARM, DYN |

A 32-bit PRoot needs only **one** loader: upstream `src/arch.h` defines `HAS_LOADER_32BIT` for the
64-bit architectures only, so Termux's `arm` package ships no `loader32` and `PROOT_LOADER_32` is
not used at all.

To finish it, on a machine with network access:

```bash
py -3 tools/fetch-shell-runtime.py --record-checksums armeabi-v7a   # prints the SHA-256s
# paste them into DEB_SHA256 in tools/fetch-shell-runtime.py, review, commit
py -3 tools/fetch-shell-runtime.py --abi armeabi-v7a                # stages jniLibs/ + assets/
git add app/src/main/jniLibs/armeabi-v7a app/src/main/assets/debian-armeabi-v7a.bin
```

The fetch script refuses to stage an unpinned package, so an unreviewed binary cannot reach
`jniLibs` by accident. Until the digests are in `DEB_SHA256`, the CI workflow builds the other two
ABIs and skips the 32-bit one with a notice rather than publishing an unverified runtime.

### What does *not* need changing

- `app/build.gradle.kts`: ABIs come from the `jniLibs` directories that exist, `useLegacyPackaging`
  stays on for all of them, and no `abiFilters` are applied by default, so existing APKs are
  unchanged. `-Ptermfold.abis=<abi>` builds a single-ABI APK for CI.
- The terminal emulator: Termux's `terminal-emulator` AAR declares
  `abiFilters 'x86', 'x86_64', 'armeabi-v7a', 'arm64-v8a'`, so `libtermux.so` already exists for
  32-bit ARM (upstream `termux-app`, `terminal-emulator/build.gradle`).
- Rootfs unpacking (`TarExtractor`), PRoot's bind mounts and environment, and the first-run flow
  are all architecture-neutral.

## Where the rootfs lives

Installs made before this change live in `files/linux/rootfs` and **keep that directory**: an
upgrade never moves or re-unpacks the tree the user has been installing into. The directory is
keyed by architecture only when the tree on disk belongs to a *different* one — a 64-bit install
now running a 32-bit-only APK — which then uses `files/linux/rootfs-armv7` and leaves the arm64
tree untouched (`ShellPaths.rootfsDirName`, covered by `ArchitectureTest`). The image's own
architecture is read from its dynamic loader (`lib/ld-linux-armhf.so.3`,
`lib/ld-linux-aarch64.so.1`, `lib64/ld-linux-x86-64.so.2`).

## Agents and tools on 32-bit ARM

The guest is a normal Debian `armhf` system, so `apt`, `dpkg`, `python3`, `git` and `node` are the
distribution's own packages. The agent CLIs are a different matter: several publish only 64-bit
binaries. Checked against the npm registry and each project's release assets on 2026-11-06:

| Agent | Installed how | 32-bit ARM | Evidence |
| --- | --- | --- | --- |
| Claude Code | npm, native binary per platform | **Not supported** | `@anthropic-ai/claude-code` 2.1.318 `optionalDependencies`: `-linux-x64`, `-linux-arm64`, `-linux-x64-musl`, `-linux-arm64-musl`; no armv7 package |
| Codex | npm, native binary per platform | **Not supported** | `@openai/codex` 0.167.0: `-linux-x64`, `-linux-arm64` only |
| Gemini CLI | npm, pure JS bundle | **Works** | `bin` is `bundle/gemini.js`, `engines.node >= 20`; `node-pty` is optional |
| OpenCode | npm, Bun-compiled binaries | **Not supported** | `opencode-ai` 1.19.5 declares `cpu: ["arm64","x64"]`, so npm refuses to install on `arm`; Bun has no 32-bit ARM build |
| Pi | npm, pure JS bundle | **Works** | `@earendil-works/pi-coding-agent` 1.5.0: `dist/bundle/cli.js`, dependencies all pure JS; needs Node >= 22.19 |
| Qwen Code | npm, JS entry | **Works via a workaround** | JS entry point; platform extras (`node-pty`, `sharp`, Bun) are optional and may fall back to source builds |
| Cursor CLI, Devin | registry binary | **Not supported** (expected) | the ACP registry offers these as `linux-x86_64`/`linux-aarch64` binaries only |
| omp (oh-my-pi) | GitHub release binary | **Not supported** | `can1357/oh-my-pi` v18.17.0 assets: `omp-linux-{x64,arm64,musl-x64,musl-arm64}`; no armv7 |
| Node.js | official tarball | **Works** | `node-v22.x-linux-armv7l.tar.xz` is published with every v22 release |
| uv / uvx | official tarball | **Works** | `uv-armv7-unknown-linux-musleabihf.tar.gz` (note: `musleabihf`, not `musl`) |
| Bun | official tarball | **Not supported** | `oven-sh/bun` v1.4.4 assets: no 32-bit ARM |

Agents without a 32-bit build are **not offered**, and a session opened for one explains why
(`acp_agent_cpu_unsupported`) instead of blaming the network. Nothing else is affected: Shell,
`apt`, Python, Node, git and the agents above keep working.

Practical limit worth knowing: a 32-bit process has about 2–3 GB of address space, and TermFold's
own limit is lower still once the agent and Node are resident. Large agent workloads on an ARMv7
device will be memory-bound long before they are CPU-bound.

## Remaining risks (not verified)

- PRoot's seccomp path on 32-bit ARM (`src/arch.h` uses `tcall(2)` as the "void" syscall there)
  has not been exercised. `PROOT_NO_SECCOMP` must stay unset, exactly as on arm64.
- `apt update` / `apt install` / `dpkg -i` under PRoot on armhf, and hard links, symlinks, `chmod`,
  and executing guest `armhf` binaries have **not** been run: no 32-bit ARM device, emulator or
  `qemu-arm` is available in the environment where this was written.
- 32-bit Android devices are usually older and slower; expect the first-run setup to take
  noticeably longer than on arm64.
