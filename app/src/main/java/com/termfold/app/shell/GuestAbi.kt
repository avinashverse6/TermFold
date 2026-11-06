package com.termfold.app.shell

import android.os.Build

/**
 * Everything the app has to do differently for the CPU it is running on.
 *
 * TermFold ships one runtime per Android ABI: a Debian root filesystem, PRoot and its loader in
 * `jniLibs/<abi>/`, and a compatibility library per ABI. On top of that, the tools the guest
 * downloads for itself — Node.js, uv, Bun, the agent CLIs — are all published per architecture,
 * and the ones that matter do *not* all exist for 32-bit ARM. Keeping the names in one place is
 * what stops an `arm64` assumption from being hardcoded somewhere and only failing on a device
 * nobody tested.
 *
 * The values here were taken from each project's own release listing:
 *
 *  - Node.js publishes `linux-armv7l`, `linux-arm64` and `linux-x64` tarballs (verified for the
 *    pinned version: the armv7l tarball and its SHA-256 are in `SHASUMS256.txt`).
 *  - uv publishes `armv7-unknown-linux-musleabihf`, plus the aarch64/x86_64 musl builds.
 *  - Bun and oh-my-pi (omp) publish **no 32-bit ARM build at all**, which is why those two are
 *    null for [ARM_V7] instead of silently resolving to an arm64 download.
 *  - The ACP registry keys binary distributions by `linux-aarch64` / `linux-x86_64`; it has no
 *    32-bit ARM key, so no registry binary agent can be installed on [ARM_V7].
 *
 * Anything a caller cannot do on the current ABI is reported as null and turned into a message,
 * never guessed at.
 */
enum class GuestAbi(
    /** The Android ABI name, as `Build.SUPPORTED_ABIS` reports it. */
    val androidAbi: String,
    /** Debian's own name for the architecture, as `dpkg --print-architecture` prints it. */
    val debianArch: String,
    /** The Debian triplet whose `usr/lib/<triplet>/` holds the dynamic loader. */
    val triplet: String,
    /** Suffix of the official Node.js tarball; also what `uname -m` prints in the guest. */
    val nodeArch: String,
    /** Node's own name for the CPU, i.e. `process.arch`. */
    val nodeProcessArch: String,
    /** Suffix of the uv release archive. */
    val uvTarget: String,
    /** Suffix of the Bun release archive, or null when Bun publishes no build for this CPU. */
    val bunTarget: String?,
    /** Key in an ACP registry `binary` distribution map, or null when the registry has none. */
    val acpBinaryPlatform: String?,
    /** Suffix of the oh-my-pi (omp) release binary, or null there is no build. */
    val ompTarget: String?,
) {
    /**
     * 32-bit ARM (ARMv7-A), `armeabi-v7a`.
     *
     * The one architecture that is genuinely second class: the Debian image, PRoot, the loader
     * and the compatibility library are all real ARMv7 builds, but several of the agent CLIs
     * ship only 64-bit binaries upstream.
     */
    ARM_V7(
        androidAbi = "armeabi-v7a",
        debianArch = "armhf",
        triplet = "arm-linux-gnueabihf",
        nodeArch = "armv7l",
        nodeProcessArch = "arm",
        uvTarget = "armv7-unknown-linux-musleabihf",
        bunTarget = null,
        acpBinaryPlatform = null,
        ompTarget = null,
    ),

    /** 64-bit ARM, `arm64-v8a`. */
    ARM64(
        androidAbi = "arm64-v8a",
        debianArch = "arm64",
        triplet = "aarch64-linux-gnu",
        nodeArch = "arm64",
        nodeProcessArch = "arm64",
        uvTarget = "aarch64-unknown-linux-musl",
        bunTarget = "aarch64",
        acpBinaryPlatform = "linux-aarch64",
        ompTarget = "arm64",
    ),

    /** 64-bit Intel, `x86_64`. */
    X86_64(
        androidAbi = "x86_64",
        debianArch = "amd64",
        triplet = "x86_64-linux-gnu",
        nodeArch = "x64",
        nodeProcessArch = "x64",
        uvTarget = "x86_64-unknown-linux-musl",
        bunTarget = "x64",
        acpBinaryPlatform = "linux-x86_64",
        ompTarget = "x64",
    );

    /**
     * True for the two 64-bit ABIs. Everything a package manager downloads for a 64-bit device is
     * assumed present unless a project says otherwise; 32-bit ARM is where the gaps are.
     */
    val is64Bit: Boolean get() = this != ARM_V7

    companion object {
        /** Maps an Android ABI name, or null when this app has no runtime for it. */
        fun of(androidAbi: String?): GuestAbi? =
            entries.firstOrNull { it.androidAbi == androidAbi }

        /**
         * The ABI of the running process.
         *
         * `SUPPORTED_ABIS` is ordered best first and the *process* is what matters: on a 64-bit
         * device that runs this app 64-bit it is `arm64-v8a` even though `armeabi-v7a` is also
         * listed, and a 32-bit-only device lists `armeabi-v7a` first with nothing else.
         */
        fun current(): GuestAbi? = of(Build.SUPPORTED_ABIS.firstOrNull())
    }
}
