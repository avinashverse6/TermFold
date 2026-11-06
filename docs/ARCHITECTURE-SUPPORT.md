# Architecture support

TermFold ships a complete Linux runtime per Android ABI. This page lists exactly what exists for
each architecture, where every binary comes from, what that means for the AI agents, and what has
actually been verified as opposed to assumed.

| | `armeabi-v7a` | `arm64-v8a` | `x86_64` |
| --- | --- | --- | --- |
| Android device | 32-bit ARM (older phones and tablets) | almost every phone and tablet since 2017 | emulators, Chromebooks, x86 tablets |
| Debian image | 13 "trixie" **armhf** (32-bit, hard-float) | 13 "trixie" **arm64** | 13 "trixie" **amd64** |
| Dynamic loader in the guest | `/lib/ld-linux-armhf.so.3` | `/lib/ld-linux-aarch64.so.1` | `/lib64/ld-linux-x86-64.so.2` |
| PRoot (Termux build) | 5.1.107.102 `arm` | 5.1.107.92 `aarch64` | 5.1.107.92 `x86_64` |
| talloc | 2.5.0 `arm` | 2.4.3 `aarch64` | 2.4.3 `x86_64` |
| libandroid-shmem | 0.7 `arm` | 0.7 `aarch64` | 0.7 `x86_64` |
| Compatibility library | `compat-shim-armeabi-v7a.so` (armhf) | `compat-shim-arm64-v8a.so` | `compat-shim-x86_64.so` |
| Node.js | 22 `linux-armv7l` | 22 `linux-arm64` | 22 `linux-x64` |
| uv | `armv7-unknown-linux-musleabihf` | `aarch64-unknown-linux-musl` | `x86_64-unknown-linux-musl` |
| Bun | — (none published) | `aarch64` | `x64` |
| 64-bit native agents | ✗ | ✓ | ✓ |

Everything is native. There is no CPU emulation anywhere: the Debian image, PRoot, the loader and
the compatibility library are all built for the device's own architecture, and a mismatch is a
build error (see [How a mismatched binary is caught](#how-a-mismatched-binary-is-caught)).

## How the runtime is chosen

`GuestAbi` (`app/src/main/java/com/termfold/app/shell/GuestAbi.kt`) is the single list of
architectures and of what each one means for the things the app downloads. Every other place that
used to guess — the rootfs asset name, PRoot's ABI folder, Node's tarball suffix, uv's target
triple, the ACP registry's binary key, omp's release name — reads from it, so there is no second
place for an `arm64` assumption to hide in.

The ABI comes from `Build.SUPPORTED_ABIS.first()`, which is the ABI *this process* is running as:

* a 32-bit-only device reports `armeabi-v7a` and nothing else;
* a 64-bit device reports `arm64-v8a` first even though it can also run 32-bit code, so it gets the
  arm64 runtime;
* an ABI with no runtime (`x86`, `armeabi`, `riscv64`) is refused before anything is downloaded,
  with a message naming the CPU.

## ARMv7 in detail

**The userspace is genuinely 32-bit.** The image is `debian:trixie-slim` from the
`dist-arm32v7` branch of the debuerreotype artifacts (Debian 13.7, armhf, `libc6:armhf`,
`dpkg --print-architecture` = `armhf`). Its `/bin/bash`, `/usr/bin/apt-get` and
`/usr/lib/arm-linux-gnueabihf/libc.so.6` are `ELF 32-bit LSB, ARM, EABI5`. Nothing from an arm64
image is used, and an arm64 image on a 32-bit device would be unexecutable.

**The native pieces are Termux's own ARMv7 builds.** Termux stopped building the 32-bit
architectures in 2023, so the files it publishes for `arm` are frozen at the last build it made
for them (`proot_5.1.107.102_arm.deb`, `libtalloc_2.5.0_arm.deb`,
`libandroid-shmem_0.7_arm.deb`). They come from the same build system and the same sources as the
arm64/x86_64 files, are built with NDK r29 for `armv7a-linux-androideabi` (the same ABI Android
itself calls `armeabi-v7a`), and are the only genuine ARMv7 *Android* builds of PRoot that exist
upstream. Nothing is renamed or repackaged: the arm64 and x86_64 files keep the versions they had.
`libandroid-shmem` is version 0.7 on every architecture.

**The loader.** PRoot does not `execve` guest programs; it injects `libproot-loader.so`, which maps
the guest ELF and jumps into it. It is statically linked and is stored separately in the APK
(`PROOT_LOADER` points at it in `nativeLibraryDir`). Termux builds it for Android's `armv7a`
target, whose float ABI is softfp, while the Debian guest is armhf (hard-float). That is the same
combination `proot-distro` uses on 32-bit ARM devices, and it is safe here for the same reason it
is there: the loader only sets up the address space and jumps to the guest's entry point, so no
floating-point value is ever passed across the two ABIs. The guest binaries themselves are armhf
throughout.

**The compatibility library is armhf, not softfp.** `compat-shim-armeabi-v7a.so` is built for
`arm-linux-gnueabihf` because it is only ever loaded *inside* the Debian guest, by that guest's
`/lib/ld-linux-armhf.so.3` via `/etc/ld.so.preload`. Matching the app process's ABI would be wrong
here; matching the guest's is what matters. It is a normal 4 KB-page-aligned 32-bit ARM shared
object, so it also needs no 16 KB alignment work.

**32-bit limits.** The address space is 4 GB and a single process usually gets 2–3 GB. Agent CLIs
that are several hundred MB of mapped binary, or that assume a 48-bit address space, are not
comfortable there — and, as the table below shows, most of them do not publish ARMv7 builds at
all.

## AI coding agents on ARMv7

Checked against each package's own published metadata on 2026-11-06 (npm registry
`optionalDependencies`/`cpu`, the ACP registry's binary keys, and the projects' release assets).
"JavaScript" agents run on the Node.js `linux-armv7l` build; "native" agents are a native binary
that does not exist for 32-bit ARM.

| Agent | Distributed as | On `armeabi-v7a` | Evidence |
| --- | --- | --- | --- |
| Gemini CLI (`gemini`) | JavaScript on npm | **Works** | `@google/gemini-cli` has no required native dependency (its optional `node-pty` prebuilds are arm64/x64 only and are not needed to start) |
| Pi (`pi`, `pi-acp`) | JavaScript on npm | **Works** | `@earendil-works/pi-coding-agent` declares only pure-JS dependencies |
| Qwen Code (`qwen`) | JavaScript on npm | **Works**, some extras unavailable | pure-JS CLI; optional `sharp`, `node-pty` and clipboard prebuilds have no ARMv7 build, so image/clipboard helpers may be missing |
| Claude Code (`claude`, `claude-acp`) | native binary per platform | **Not available** | `@anthropic-ai/claude-code` ships `linux-x64`, `linux-arm64` and their musl twins only |
| Codex (`codex`, `codex-acp`) | native binary per platform | **Not available** | `@openai/codex` ships `linux-x64` and `linux-arm64` only |
| OpenCode (`opencode`) | Bun-compiled native | **Not available** | `opencode-ai` declares `cpu: ["arm64", "x64"]`; Bun has no 32-bit ARM build |
| Cursor CLI (`cursor`) | native binary (ACP registry) | **Not available** | registry binary keys are `linux-x86_64` / `linux-aarch64` |
| Devin (`devin`) | native binary (ACP registry) | **Not available** | as above |
| omp / oh-my-pi (`omp`) | Bun-compiled native | **Not available** | `omp-linux-arm64`/`omp-linux-x64` only |
| Goose, and other registry agents | varies | depends on their distribution | a binary-only agent without a 32-bit ARM build is simply not offered |

Nothing is silently broken by this. On a 32-bit ARM device:

* the agents that cannot run are never listed as ACP sessions (`AcpRegistry.usable()`), and an
  existing session for one says why instead of downloading a 200 MB binary that cannot execute;
* the shell stand-ins for `claude`, `codex` and `opencode` print what is going on and which agents
  do work, rather than failing with a platform error from npm;
* everything else — the terminal, apt, Debian's own tools, Python, git, Node.js, uv, and the
  JavaScript agents — is unaffected.

The same list is why Bun is only installed on demand: it is used as a fallback package runner for
`npx` agents when npm's renames misbehave, which cannot happen on ARMv7 because no `npx` agent is
offered there.

## How a mismatched binary is caught

`tools/fetch-shell-runtime.py` reads the ELF header of every file it stages and refuses to write it
under the wrong ABI:

* `libproot.so`, `libproot-loader.so`, `libtalloc.so`, `libandroid-shmem.so`: ELF class and
  `e_machine` must match the ABI's `jniLibs/<abi>/` folder (`armeabi-v7a` = class 1, machine 40).
* the Debian image: `usr/bin/bash`, `usr/lib/<triplet>/libc.so.6` and the `ld-linux-*` loader are
  read out of the archive and must be the same architecture, which is what stops a 64-bit image
  from ever being shipped to a 32-bit device.
* the archive itself must still match the pinned SHA-256, so the bytes that ship are the bytes that
  were reviewed.

`tools/build-compat-shim.py` checks its output the same way (`arm-linux-gnueabihf` must produce
ELF class 1 / machine 40) and `app/build.gradle.kts` pins `abiFilters` to the three ABIs that have
a complete runtime, so Gradle cannot produce an APK for an ABI that is missing a piece.

## Rebuilding one architecture

```bash
py -3 tools/fetch-shell-runtime.py --abi armeabi-v7a
py -3 -m pip install ziglang
py -3 tools/build-compat-shim.py --abi armeabi-v7a
./gradlew :app:assembleDebug
```

`./gradlew :app:assembleDebug` then produces a universal APK whose `lib/armeabi-v7a/` holds the
ARMv7 PRoot, loader, talloc, libandroid-shmem, Termux terminal library and compatibility shim, with
`assets/debian-armeabi-v7a.bin` beside them.

## What has been verified, and what has not

Verified in this repository's CI (Debian 13 armhf guest, ARMv7 executed under QEMU user-mode
emulation on an x86_64 runner):

* the staged `libproot.so`, `libproot-loader.so`, `libtalloc.so` and `libandroid-shmem.so` are
  `ELF 32-bit LSB ... ARM, EABI5`;
* the armhf image unpacks, and `apt-get update`, `apt-get install`, `python3`, `git`, `dpkg` and
  `bash` work in it;
* the ARMv7 compatibility library loads through `/etc/ld.so.preload` in that guest, does not break
  any of the above, and turns a `link()` the filesystem refuses into a real copy (tested on a
  filesystem that cannot hold hard links, the same failure Android's SELinux policy produces);
* Node.js 22 `linux-armv7l` starts in the guest and reports `process.arch == "arm"`;
* the debug and release APKs build, and the `armeabi-v7a` APK entry contains the ARMv7 binaries and
  the armhf image (see `build-report.txt`).

**Not verified, and not claimed:**

* PRoot has not been *run* on an ARMv7 Android device. Emulating the Android kernel's seccomp and
  SELinux behaviour for a 32-bit app process is not possible with QEMU user-mode, and no 32-bit ARM
  device or ARMv7 Android emulator was available. What is verified is that the binary is the
  correct architecture, statically correct about its dependencies, and the same Termux ARMv7 build
  that proot-distro ships for 32-bit devices — not that a full first run has been observed there.
* The terminal (Termux `terminal-emulator`/`terminal-view`) is assumed to carry an `armeabi-v7a`
  `libtermux.so`; the APK contents check above shows whether it does.
* Agent behaviour on ARMv7 beyond "the package has a build that can load" was not exercised: no
  agent was installed or run on 32-bit ARM.
