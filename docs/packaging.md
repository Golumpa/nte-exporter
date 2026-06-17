# Packaging

## Windows local build

Build the Windows console executable with:

```powershell
.\tools\build-windows.ps1
```

The output is:

```text
dist\nte-history-exporter.exe
```

Run live capture from an elevated PowerShell prompt:

```powershell
.\dist\nte-history-exporter.exe --live
```

## Packet capture runtime

Windows live capture defaults to `--capture-backend auto`, which tries an installed system Npcap runtime first, then the built-in raw-socket backend. If `--capture-backend libpcap` is specified, raw fallback is disabled. If `--capture-backend raw` is specified, only the Windows raw-socket backend is used.

Npcap is Windows-only; Linux and macOS use the system libpcap runtime.

The GitHub Actions release does not download or bundle Npcap. The Windows executable can use a user's installed Npcap runtime when present, then falls back to raw sockets. A future pktmon backend can provide the same kind of no-extra-install Windows path that stardb-exporter uses.

Npcap is not committed or bundled by default. Windows users who want the Npcap backend should install Npcap separately. Users who do not install Npcap can still use the Windows raw-socket fallback.

## Cross-platform CI shape

Use one GitHub Actions job per OS. PyInstaller must build on the target platform, so Windows produces `.exe`, macOS produces a macOS binary, and Linux produces a Linux binary.

This repository has a manual release workflow at:

```text
.github\workflows\release.yml
```

It builds Windows, Linux, and macOS artifacts, then publishes a `v<version>` GitHub release with raw binaries and versioned zip files.

Linux runners install the libpcap runtime for parity with live-capture usage, but the build itself uses `ctypes` and does not link against libpcap at package time.
