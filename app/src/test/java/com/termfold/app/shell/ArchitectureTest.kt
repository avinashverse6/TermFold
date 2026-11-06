package com.termfold.app.shell

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * The architecture decision table, and the rule that keeps an existing rootfs where it is.
 *
 * These are plain JVM tests: nothing here reaches Android, which is the point of keeping the
 * decisions as pure functions.
 */
class ArchitectureTest {

    @get:Rule
    val tmp = TemporaryFolder()

    // --- names ----------------------------------------------------------------------------------

    @Test
    fun `android abi names map to architectures`() {
        assertEquals(Arch.ARMV7, Architecture.of("armeabi-v7a"))
        assertEquals(Arch.ARM64, Architecture.of("arm64-v8a"))
        assertEquals(Arch.X86_64, Architecture.of("x86_64"))
    }

    @Test
    fun `the library directory android expands into maps to the same architecture`() {
        // The package manager uses short names on the device: lib/arm, lib/arm64.
        assertEquals(Arch.ARMV7, Architecture.of("arm"))
        assertEquals(Arch.ARM64, Architecture.of("arm64"))
    }

    @Test
    fun `uname and os arch spellings map too`() {
        assertEquals(Arch.ARMV7, Architecture.of("armv7l"))
        assertEquals(Arch.ARMV7, Architecture.of("armv7"))
        assertEquals(Arch.ARM64, Architecture.of("aarch64"))
        assertEquals(Arch.X86_64, Architecture.of("amd64"))
        assertEquals(Arch.X86_64, Architecture.of("X86_64"))
    }

    @Test
    fun `architectures this app does not ship are unsupported`() {
        // 32-bit x86 is deliberately absent: no PRoot, no image, nothing is ever renamed for it.
        assertNull(Architecture.of("x86"))
        assertNull(Architecture.of("i686"))
        assertNull(Architecture.of("riscv64"))
        assertNull(Architecture.of(""))
        assertNull(Architecture.of(null))
    }

    // --- choosing the process architecture ------------------------------------------------------

    @Test
    fun `a 64 bit phone running a 32 bit build is armv7`() {
        // The case Build.SUPPORTED_ABIS alone gets wrong: the device still lists arm64-v8a first,
        // but the installed APK only carries armeabi-v7a, so every native library is 32-bit.
        assertEquals(
            Arch.ARMV7,
            Architecture.resolve(
                primaryCpuAbi = "armeabi-v7a",
                nativeLibraryDir = "/data/app/~~abc/com.termfold.app-xyz/lib/arm",
                supportedAbis = listOf("arm64-v8a", "armeabi-v7a", "armeabi"),
            ),
        )
    }

    @Test
    fun `the installed abi wins over the device list`() {
        assertEquals(
            Arch.ARMV7,
            Architecture.resolve("armeabi-v7a", null, listOf("arm64-v8a")),
        )
        assertEquals(
            Arch.ARM64,
            Architecture.resolve("arm64-v8a", null, listOf("armeabi-v7a")),
        )
    }

    @Test
    fun `without a primary abi the expanded library directory decides`() {
        assertEquals(
            Arch.ARMV7,
            Architecture.resolve(null, "/data/app/~~abc/com.termfold.app-xyz/lib/arm/", listOf("arm64-v8a")),
        )
        assertEquals(
            Arch.ARM64,
            Architecture.resolve(null, "/data/app/~~abc/com.termfold.app-xyz/lib/arm64", listOf("armeabi-v7a")),
        )
    }

    @Test
    fun `the device list is the last resort and skips what this app has no runtime for`() {
        assertEquals(Arch.X86_64, Architecture.resolve(null, null, listOf("x86_64", "arm64-v8a")))
        assertEquals(Arch.ARM64, Architecture.resolve(null, null, listOf("x86", "arm64-v8a")))
        assertNull(Architecture.resolve(null, null, listOf("x86", "riscv64")))
        assertNull(Architecture.resolve(null, null, emptyList()))
    }

    // --- per-tool names -------------------------------------------------------------------------

    @Test
    fun `32 bit arm has node and uv but no bun or omp`() {
        assertEquals("armv7l", Arch.ARMV7.node)
        assertEquals("uv-armv7-unknown-linux-musleabihf", Arch.ARMV7.uv)
        assertEquals("linux-armv7l", Arch.ARMV7.registry)
        // Neither project publishes a 32-bit ARM build, so there is nothing to point at.
        assertNull(Arch.ARMV7.bun)
        assertNull(Arch.ARMV7.omp)
    }

    @Test
    fun `the 64 bit architectures keep the names they had before armv7 support`() {
        assertEquals("arm64", Arch.ARM64.node)
        assertEquals("aarch64", Arch.ARM64.bun)
        assertEquals("linux-aarch64", Arch.ARM64.registry)
        assertEquals("x64", Arch.X86_64.node)
        assertEquals("x64", Arch.X86_64.bun)
        assertEquals("linux-x86_64", Arch.X86_64.registry)
    }

    // --- where the rootfs lives -----------------------------------------------------------------

    @Test
    fun `an existing rootfs keeps its historical directory`() {
        // Same architecture, or nothing installed yet: the name every pre-ARMv7 install uses.
        assertEquals("rootfs", ShellPaths.rootfsDirName(Arch.ARMV7, Arch.ARMV7))
        assertEquals("rootfs", ShellPaths.rootfsDirName(Arch.ARM64, Arch.ARM64))
        assertEquals("rootfs", ShellPaths.rootfsDirName(Arch.X86_64, Arch.X86_64))
        assertEquals("rootfs", ShellPaths.rootfsDirName(Arch.ARMV7, null))
        // An unknown CPU must not be moved off the tree it has been using either.
        assertEquals("rootfs", ShellPaths.rootfsDirName(null, Arch.ARM64))
    }

    @Test
    fun `a rootfs of another architecture is never unpacked over`() {
        assertEquals("rootfs-armv7", ShellPaths.rootfsDirName(Arch.ARMV7, Arch.ARM64))
        assertEquals("rootfs-arm64", ShellPaths.rootfsDirName(Arch.ARM64, Arch.ARMV7))
        assertEquals("rootfs-x86_64", ShellPaths.rootfsDirName(Arch.X86_64, Arch.ARM64))
    }

    @Test
    fun `the architecture of an unpacked image is read from its dynamic loader`() {
        assertEquals(Arch.ARMV7, ShellPaths.imageArch(rootfs("lib/ld-linux-armhf.so.3")))
        assertEquals(Arch.ARM64, ShellPaths.imageArch(rootfs("lib/ld-linux-aarch64.so.1")))
        assertEquals(Arch.X86_64, ShellPaths.imageArch(rootfs("lib64/ld-linux-x86-64.so.2")))
    }

    @Test
    fun `a directory without an image has no architecture`() {
        assertNull(ShellPaths.imageArch(tmp.newFolder("empty")))
        // A half-unpacked tree is not an image either: nothing may be concluded from it.
        assertNull(ShellPaths.imageArch(File(tmp.newFolder("partial"), "usr/bin")))
    }

    /** Creates a directory with one file in it, like the loader of an unpacked rootfs. */
    private fun rootfs(path: String): File {
        val dir = tmp.newFolder(path.replace('/', '-'))
        File(dir, path).apply { parentFile?.mkdirs(); writeText("") }
        return dir
    }
}
