package com.termfold.app.shell

import android.content.Context
import java.io.File

/** Locates the pieces of the bundled Linux environment. */
object ShellPaths {

    /** Everything the environment owns lives under this app-private directory. */
    fun rootDir(context: Context): File = File(context.filesDir, ShellConfig.ROOT_DIR)

    /**
     * The extracted Debian root filesystem for the architecture this process runs as.
     *
     * The name is normally `rootfs`, which is what every install made before 32-bit ARM support
     * uses — an upgrade must never move, re-unpack or otherwise touch that tree, because
     * everything the user installed lives in it. Only when the tree that is already there belongs
     * to a *different* architecture (a 64-bit install now running a 32-bit-only build) does this
     * point at `rootfs-<arch>`, so the two coexist and neither is overwritten.
     */
    fun rootfsDir(context: Context): File =
        File(rootDir(context), rootfsDirName(Architecture.current(context), imageArch(rootfsDirLegacy(context))))

    /** The shared name every rootfs was unpacked under before architectures were distinguished. */
    private fun rootfsDirLegacy(context: Context): File = File(rootDir(context), ShellConfig.ROOTFS_DIR)

    /** The directory name [rootfsDir] uses; separate so the rule can be tested without Android. */
    internal fun rootfsDirName(running: Arch?, installed: Arch?): String = when {
        // Nothing there yet (a fresh install), an install that predates Debian, or a CPU this app
        // does not know: leave the historical name alone.
        installed == null || running == null -> ShellConfig.ROOTFS_DIR
        installed == running -> ShellConfig.ROOTFS_DIR
        else -> "${ShellConfig.ROOTFS_DIR}-${running.key}"
    }

    /**
     * Which architecture the image unpacked at [dir] belongs to, read from the dynamic loader
     * every Debian image carries. Null when there is no image there.
     *
     * A symlink is fine: `/lib/ld-linux-armhf.so.3` points at
     * `arm-linux-gnueabihf/ld-linux-armhf.so.3` inside the same tree, and `/lib` itself may be a
     * merged-usr symlink.
     */
    internal fun imageArch(dir: File): Arch? = when {
        File(dir, "lib/ld-linux-armhf.so.3").exists() -> Arch.ARMV7
        File(dir, "lib/ld-linux-aarch64.so.1").exists() -> Arch.ARM64
        File(dir, "lib64/ld-linux-x86-64.so.2").exists() -> Arch.X86_64
        else -> null
    }

    /** PRoot's scratch space. Must exist before PRoot starts or forked children can die. */
    fun tempDir(context: Context): File =
        File(context.filesDir, ShellConfig.TEMP_DIR).apply { mkdirs() }

    /**
     * PRoot needs a writable `/dev/shm`, and Android's own is owned by the system. Debian's apt
     * refuses to run without one, so this directory is bind-mounted over `/dev/shm` in the guest.
     */
    fun shmDir(context: Context): File = File(tempDir(context), "shm").apply { mkdirs() }

    /** The resolver configuration bind-mounted over the guest's `/etc/resolv.conf`. */
    fun resolvConf(context: Context): File = File(tempDir(context), "resolv.conf")

    /** The hosts table bind-mounted over the guest's `/etc/hosts`. */
    fun hostsFile(context: Context): File = File(tempDir(context), "hosts")

    /** The scratch tree a new rootfs is unpacked into before it takes over. */
    fun stagingDir(context: Context): File = File(rootDir(context), ShellConfig.ROOTFS_STAGING_DIR)

    /** The Ubuntu rootfs that is being migrated away from (see [DistroMigration]). */
    fun oldRootfsDir(context: Context): File = File(rootDir(context), ShellConfig.ROOTFS_OLD_DIR)

    /** Marks a completed extraction, so provisioning runs at most once. */
    fun rootfsMarker(context: Context): File = File(rootfsDir(context), ".termfold-rootfs")

    /** True once the rootfs is unpacked; the tools themselves always live in nativeLibraryDir. */
    fun isReady(context: Context): Boolean =
        rootfsMarker(context).isFile && File(rootfsDir(context), "usr/bin/bash").isFile
}
