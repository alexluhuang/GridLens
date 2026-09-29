# Windows packaging

These files build GridLens for Windows x64: a PyInstaller bundle and a
per-user installer made with Inno Setup.

- `build_windows.ps1` builds everything. Its header lists the environment
  variables it reads, including the ones for code signing.
- `gridlens.iss` is the Inno Setup script. It installs for the current user,
  under `%LOCALAPPDATA%\Programs\GridLens`, with no administrator rights.
- `make_icon.py` renders `src/gridlens/resources/gridlens.svg` as the `.ico`
  file that the executables and the installer use.

## Build host

- Windows 10 or 11, x64.
- Python 3.11 or later, x64, from python.org.
- [Inno Setup 6.3](https://jrsoftware.org/isinfo.php) or later.
- For signing, the Windows SDK's `signtool.exe` on `PATH` and an Authenticode
  certificate in the certificate store. An unsigned installer runs, but
  SmartScreen warns about it, and managed PCs may block it.

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1
```

The output is `dist\GridLens-<version>-setup.exe`.

## What the bundle contains

The `analysis` extra installs the CPU analysis stack on Windows, because RAPIDS
publishes Linux wheels only, so the bundle has no cuDF. Analysis runs on CPU
Dask. For GPU analysis on a Windows PC, run the Linux build inside WSL2
instead; see `docs/install_windows.md`.

`dist\GridLens` holds two executables built from the same code:

- `GridLens.exe`, the windowed application.
- `gridlens-cli.exe`, a console executable. GridLens starts its MCP server,
  its agent job workers, and the tool CLI from it, because they talk over
  standard input and output, which a windowed executable does not reliably
  have. GridLens starts it with no console window.

PyInstaller's manifest already marks both executables as long-path aware. Paths
longer than 260 characters also need the `LongPathsEnabled` policy, which an
administrator sets once per machine.
