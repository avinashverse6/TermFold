# Third-party notices

TermFold itself is licensed under the Apache License 2.0 (see [LICENSE](LICENSE)). The app, its
APK and this repository also contain the following third-party components, each under its own
license. Where a license requires the corresponding source to be available, it is linked below.

## Bundled executables (`app/src/main/jniLibs/`)

| Component | Version | License | Source |
| --- | --- | --- | --- |
| PRoot (Termux build): `libproot.so`, `libproot-loader.so` | 5.1.107.92 (arm64, x86_64); 5.1.107.102 (ARMv7) | GPL-2.0 | [termux/proot](https://github.com/termux/proot), packaging in [termux/termux-packages](https://github.com/termux/termux-packages/tree/master/packages/proot) |
| talloc: `libtalloc.so` | 2.4.3 (arm64, x86_64); 2.5.0 (ARMv7) | LGPL-3.0-or-later | [samba.org/ftp/talloc](https://www.samba.org/ftp/talloc/), packaging in [termux/termux-packages](https://github.com/termux/termux-packages/tree/master/packages/libtalloc) |
| libandroid-shmem: `libandroid-shmem.so` | 0.7 | BSD-3-Clause | [termux/libandroid-shmem](https://github.com/termux/libandroid-shmem) |

These are the unmodified Termux builds, taken from the packages at
`https://packages.termux.dev/apt/termux-main/pool/main` by `tools/fetch-shell-runtime.py`. The only
change is that `libproot.so`'s `DT_NEEDED` entry for `libtalloc.so.2` is rewritten in place to
`libtalloc.so` so Android installs it (see the script). TermFold runs PRoot as a separate program;
it does not link against it.

The ARMv7 builds carry different version numbers because Termux stopped publishing 32-bit
architecture packages in 2023; `proot_5.1.107.102_arm.deb` and `libtalloc_2.5.0_arm.deb` are the
last ARMv7 builds it made, from the same sources and build system as the 64-bit ones. There is no
later ARMv7 Android build of either upstream.

## Bundled data (`app/src/main/assets/`)

| Component | License | Source |
| --- | --- | --- |
| Debian 13 "trixie-slim" base images (`debian-*.bin`: arm64, armhf, amd64) | Various free licenses (see `/usr/share/doc/*/copyright` inside the image) | [debuerreotype/docker-debian-artifacts](https://github.com/debuerreotype/docker-debian-artifacts) (`dist-arm64v8`, `dist-arm32v7`, `dist-amd64`); package sources at [sources.debian.org](https://sources.debian.org) |
| Mozilla CA certificate bundle (`ca-certificates.crt`) | MPL-2.0 | Ubuntu's [`ca-certificates`](https://launchpad.net/ubuntu/+source/ca-certificates) package |
| CodeMirror 6 and its language packages (`editor/editor.js`, built from `tools/editor/`) | MIT | [codemirror.net](https://codemirror.net) |
| Material Icon Theme file and folder icons (`fileicons/`) | MIT (`fileicons/LICENSE`) | [material-extensions/vscode-material-icon-theme](https://github.com/material-extensions/vscode-material-icon-theme) |

Debian is a registered trademark of Software in the Public Interest, Inc., and Ubuntu of Canonical Ltd. TermFold is not affiliated with or endorsed by
either.

## Libraries

| Library | License |
| --- | --- |
| Termux `terminal-emulator` and `terminal-view` 0.118.3 | Apache-2.0 |
| AndroidX, Jetpack Compose, Kotlin, kotlinx.coroutines | Apache-2.0 |
| Coil (image loading, SVG) | Apache-2.0 |
| Apache Commons Compress | Apache-2.0 |

## Fonts (`app/src/main/res/font/`)

| Font | License |
| --- | --- |
| Outfit | SIL Open Font License 1.1 |
| JetBrains Mono | SIL Open Font License 1.1 |

## Agents

TermFold does not bundle any AI agent. Agents (Claude Code, Codex, Gemini CLI, OpenCode, Cursor,
Devin, Pi, omp, Google Antigravity and others) are downloaded from their official sources when you
first use them, under their own licenses and terms. All product names are trademarks of their
respective owners; TermFold is not affiliated with any of them.
