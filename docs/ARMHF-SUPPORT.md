# 32-bit ARM (`armeabi-v7a`) support

TermFold runs a Debian userland and a set of AI coding agents on top of PRoot. Every native piece
of that stack — PRoot, its loader, `libtalloc`, `libandroid-shmem`, the terminal's `libtermux.so`,
the compatibility shim and the Debian image itself — belongs to one CPU architecture. This page
records what 32-bit ARM needs, what is in place, and what has actually been run.

## What is supported

| Android ABI | Debian port | Status |
| --- | --- | --- |
| `arm64-v8a` | arm64 | Supported (unchanged; this is what almost every device uses) |
| `x86_64` | amd64 | Supported (unchanged; emulators and a few tablets) |
| `armeabi-v7a` | armhf | Supported — own PRoot build, own Debian `armhf` image, own compatibility shim |
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

## The 32-bit runtime

The four host-side binaries are Termux `arm` packages, the same provenance as the `arm64-v8a` and
`x86_64` builds (Termux patches PRoot for Android's seccomp policy and adds `--kill-on-exit`, which
upstream PRoot does not have). Termux stopped building the 32-bit architectures in 2023, so the
`arm` packages are a different version from the 64-bit ones — they are the last builds it published
and nothing newer exists for them:

| File in `jniLibs/armeabi-v7a/` | Termux package (arch `arm`) | Bytes | SHA-256 of the staged file |
| --- | --- | --- | --- |
| `libproot.so` | `proot_5.1.107.102_arm.deb` → `bin/proot` | 172,676 | `c8054f34248e9ada0efb2453fe024166077bd3a7948dc745411f24034f02e6cd` |
| `libproot-loader.so` | same package → `libexec/proot/loader` | 5,632 | `7c3d9f74b8c8a87c46766d8bbeebeabf24cc4de507690ab04ba7f0190a598500` |
| `libtalloc.so` | `libtalloc_2.5.0_arm.deb` → `lib/libtalloc.so.2.5.0` | 21,168 | `a376ac7cbd18e6777657328c701b4979610473811761edc0fdb0ec388d8504af` |
| `libandroid-shmem.so` | `libandroid-shmem_0.7_arm.deb` → `lib/libandroid-shmem.so` | 11,028 | `ef35602fa6c8bca9081af1594fabeacbd98b6e8921dd6be54484291933b8040f` |

Licences are the packages' own: PRoot GPL-2.0, `libtalloc` LGPL-3.0-or-later, `libandroid-shmem`
BSD-3-Clause (same as the 64-bit copies).

Everything below was checked with `readelf` on the files that ship:

```
libproot.so          ELF32  Machine: ARM  DYN   NEEDED libtalloc.so, libandroid-shmem.so, libc.so
libproot-loader.so   ELF32  Machine: ARM  EXEC  (statically linked, no NEEDED)
libtalloc.so         ELF32  Machine: ARM  DYN   NEEDED libc.so
libandroid-shmem.so  ELF32  Machine: ARM  DYN   NEEDED liblog.so, libc.so
Tag_CPU_arch: v7   Tag_THUMB_ISA_use: Thumb-2   Tag_FP_arch: VFPv3   Tag_ARM_ISA_use: Yes
```

`libproot.so`'s three dependencies are two files that sit beside it (renamed `lib*.so` so Android
lets them live in `nativeLibraryDir`, with the `DT_NEEDED` of `libtalloc.so.2` rewritten in place)
and bionic's `libc.so`, which the device provides.

A 32-bit PRoot needs only **one** loader: upstream `src/arch.h` defines `HAS_LOADER_32BIT` for the
64-bit architectures only, so Termux's `arm` package ships no `loader32` and `PROOT_LOADER_32` is
not used at all.

### Why the binaries are committed, and how they stay pinned

The four files live in the repository, exactly like the arm64 and x86_64 ones, because Android will
only execute what is in `nativeLibraryDir`, and that directory only ever holds what the APK carries.
`tools/fetch-shell-runtime.py` therefore checks the committed files against `STAGE_SHA256` and, when
they match, stages nothing at all — a normal build needs no network for them:

```
[arm64-v8a] native: already staged, digests match STAGE_SHA256
[armeabi-v7a] native: already staged, digests match STAGE_SHA256
[x86_64] native: already staged, digests match STAGE_SHA256
```

If a file is missing or different, the script goes back to the pinned `.deb` and refuses to stage
anything whose package digest has not been recorded (`DEB_SHA256`; record with
`py -3 tools/fetch-shell-runtime.py --record-checksums armeabi-v7a`). A downloaded package is then
staged and the result re-checked against `STAGE_SHA256`, so a differently repackaged `.deb` is a
build failure rather than a surprise on a device.

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
| Node.js | official tarball | **Works**, once `libatomic1` is installed | `node-v22.x-linux-armv7l.tar.xz` is published with every v22 release; that build links against `libatomic.so.1`, which no Debian base image installs |
| uv / uvx | official tarball | **Works** | `uv-armv7-unknown-linux-musleabihf.tar.gz` (note: `musleabihf`, not `musl`) |
| Bun | official tarball | **Not supported** | `oven-sh/bun` v1.4.4 assets: no 32-bit ARM |

The `libatomic1` package is what 32-bit ARM Node needs and the 64-bit builds do not: without it
`node` dies with `error while loading shared libraries: libatomic.so.1` before it runs a line of
JavaScript, which broke every JavaScript agent at once. Both install paths now provide it — the
setup script installs the package with the other developer tools, and `AcpInstaller` probes Node
after unpacking it and installs `libatomic1` only if the linker asks for it, so 64-bit devices never
take that path.

Agents without a 32-bit build are **not offered**, and a session opened for one explains why
(`acp_agent_cpu_unsupported`) instead of blaming the network. Nothing else is affected: Shell,
`apt`, Python, Node, git and the agents above keep working.

Practical limit worth knowing: a 32-bit process has about 2–3 GB of address space, and TermFold's
own limit is lower still once the agent and Node are resident. Large agent workloads on an ARMv7
device will be memory-bound long before they are CPU-bound.

## What has been run, and what has not

Verified in CI (`.github/workflows/android.yml`, job *armhf guest (qemu-arm)*): the shipped
`armhf` image is unpacked and booted with `qemu-arm` in a chroot on a normal x86_64 runner, and the
compatibility shim is preloaded into it. That exercises the guest itself; it does **not** exercise
PRoot (nothing runs the guest through it) and it is not a 32-bit Android device.

- `uname -m` → `armv7l`, `dpkg --print-architecture` → `armhf`, glibc 2.41.
- The 32-bit compatibility shim is accepted by `ld.so` for every guest program (`ld.so.preload`).
- A filesystem that refuses `link(2)` (vfat, standing in for Android's SELinux policy) makes a
  hard link fall back to a copy; a link the kernel allows stays a link.
- `apt-get install python3 git curl ca-certificates libatomic1`, then `python3` and `git` run.
- Node.js `v22.23.3` `linux-armv7l`: the tarball matches its published SHA-256, `node` starts,
  reports `arm linux`, and `npm --version` works.
- `npm install -g @earendil-works/pi-coding-agent` then `pi --version`.
- A native-only agent (`@anthropic-ai/claude-code`) is installed and run, and its refusal is
  recorded rather than assumed.

Still unverified, and not claimed:

- **PRoot itself on 32-bit ARM.** Its seccomp path (`src/arch.h` uses `tcall(2)` where the 64-bit
  builds use a different void syscall) has not been exercised. `PROOT_NO_SECCOMP` must stay unset,
  exactly as on arm64.
- **A real 32-bit Android device.** First run, the PTY, the terminal emulator's `libtermux.so`, the
  app's own JNI, and the file paths under Android's storage have only been checked statically (the
  terminal AAR declares `armeabi-v7a` and the APK is checked with `readelf` per entry).
- **Memory pressure.** A 32-bit process has about 2–3 GB of address space, and less once the agent
  and Node are resident; large agent workloads will be memory-bound before they are CPU-bound.
- 32-bit Android devices are usually older and slower: expect the first-run setup to take
  noticeably longer than on arm64.
