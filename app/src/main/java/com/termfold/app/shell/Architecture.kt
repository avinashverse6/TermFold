package com.termfold.app.shell

import android.content.Context
import android.os.Build
import java.io.File

/**
 * The CPU architectures the bundled environment can run as.
 *
 * Every tool spells its Linux builds differently — Node `armv7l`, Bun `aarch64`, uv a whole
 * target triple, the ACP registry `linux-armv7l` — so those names live here as data, next to the
 * Android ABI name they belong to. Where a tool publishes nothing for an architecture the value
 * is null, and the caller says so instead of downloading a binary that cannot run.
 */
enum class Arch(
    /** Android's name for the ABI: the `jniLibs` directory and the APK's `lib/<abi>` path. */
    val abi: String,
    /** Short name for the things this app names itself (rootfs directories, markers). */
    val key: String,
    /** Node.js's name for its Linux builds. Node publishes one for every architecture here. */
    val node: String,
    /** Bun's name for its Linux build, or null where Bun publishes none. */
    val bun: String?,
    /** uv's release asset name, or null where uv publishes none. */
    val uv: String?,
    /** The ACP registry's key for Linux binaries on this CPU. */
    val registry: String,
    /** omp's name for its Linux build, or null where omp publishes none. */
    val omp: String?,
) {
    // Termux calls this architecture "arm" and its packages are armeabi-v7a: ARMv7 with Thumb-2
    // and VFPv3-D16, which is also the baseline every Debian 13 armhf package is built for.
    // Node and uv publish 32-bit ARM builds; Bun and omp do not.
    ARMV7(
        abi = "armeabi-v7a",
        key = "armv7",
        node = "armv7l",
        bun = null,
        uv = "uv-armv7-unknown-linux-musleabihf",
        registry = "linux-armv7l",
        omp = null,
    ),
    ARM64(
        abi = "arm64-v8a",
        key = "arm64",
        node = "arm64",
        bun = "aarch64",
        uv = "uv-aarch64-unknown-linux-musl",
        registry = "linux-aarch64",
        omp = "arm64",
    ),
    X86_64(
        abi = "x86_64",
        key = "x86_64",
        node = "x64",
        bun = "x64",
        uv = "uv-x86_64-unknown-linux-musl",
        registry = "linux-x86_64",
        omp = "x64",
    ),
    ;
}

/**
 * The one place that decides which architecture this process runs as, and whether the bundled
 * environment can run here at all.
 *
 * Three things are easy to get wrong, and all three are handled below:
 *
 *  - `Build.SUPPORTED_ABIS[0]` is the *device's* preferred ABI, not the ABI this process runs as.
 *    A 64-bit phone running an APK that only carries 32-bit libraries still lists `arm64-v8a`
 *    first, while every native library — PRoot, its loader, the rootfs — has to be 32-bit.
 *    `ApplicationInfo.primaryCpuAbi` is the ABI the package manager actually installed for, so it
 *    is trusted before the list.
 *  - An APK built without a runtime for this CPU cannot work at all. That is reported as
 *    unsupported instead of picking the nearest name, so the app can say so rather than fail in a
 *    confusing way later.
 *  - Nothing here may guess: an architecture this app does not build is null, never the closest
 *    match.
 */
object Architecture {

    /** Every architecture this app knows how to build, in preference order. */
    val KNOWN: List<Arch> = Arch.entries

    /**
     * Maps any spelling of an ABI to an [Arch]: Android's ABI names, the directory names the
     * installer uses on the device (`lib/arm`, `lib/arm64`), and `uname -m`/`os.arch` values.
     * Anything else — including `x86`, which this app does not ship — is null.
     */
    fun of(name: String?): Arch? = when (name?.trim()?.lowercase()) {
        "armeabi-v7a", "armeabi", "arm", "armv7", "armv7l" -> Arch.ARMV7
        "arm64-v8a", "arm64", "aarch64" -> Arch.ARM64
        "x86_64", "x64", "amd64" -> Arch.X86_64
        else -> null
    }

    /**
     * The architecture this process runs as, or null when it is one this app has no runtime for.
     * See [resolve] for the order the answers are taken in.
     */
    fun current(context: Context): Arch? {
        val info = context.applicationInfo
        return resolve(
            primaryCpuAbi = info.primaryCpuAbi,
            nativeLibraryDir = info.nativeLibraryDir,
            supportedAbis = Build.SUPPORTED_ABIS?.toList().orEmpty(),
        )
    }

    /**
     * Pure form of [current], so the rules can be tested on a plain JVM:
     *
     *  1. the ABI the package manager installed this app for — the only answer that stays right on
     *     a 64-bit CPU running a 32-bit-only build;
     *  2. otherwise the ABI directory the installer expanded the libraries into;
     *  3. otherwise the first ABI the device lists that this app knows.
     */
    internal fun resolve(
        primaryCpuAbi: String?,
        nativeLibraryDir: String?,
        supportedAbis: List<String>,
    ): Arch? =
        of(primaryCpuAbi)
            ?: nativeLibraryDir?.trimEnd('/')?.substringAfterLast('/')?.let { of(it) }
            ?: supportedAbis.firstNotNullOfOrNull { of(it) }

    /**
     * The architecture the bundled environment can run as here, or null when it cannot.
     *
     * Besides a CPU we know, this requires the APK to actually carry PRoot and the libraries it
     * links against. A build produced without `tools/fetch-shell-runtime.py` has no such files, and
     * on a 32-bit device it is then reported as unsupported — a clear message instead of a crash
     * or, worse, a 64-bit binary renamed to look like a 32-bit one.
     */
    fun supported(context: Context): Arch? =
        current(context)?.takeIf { runtimeInstalled(context) }

    /** The executables PRoot needs beside it, all of them in `nativeLibraryDir`. */
    private val EXECUTABLES = listOf(
        ShellConfig.NATIVE_PROOT,
        ShellConfig.NATIVE_LOADER,
        ShellConfig.NATIVE_TALLOC,
        ShellConfig.NATIVE_SHMEM,
    )

    /** True when this APK carries PRoot and the libraries it needs. */
    fun runtimeInstalled(context: Context): Boolean {
        val dir = context.applicationInfo.nativeLibraryDir
        if (dir.isNullOrEmpty()) return false
        return EXECUTABLES.all { File(dir, it).isFile }
    }
}
