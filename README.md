# hi-skuggsja-reflectometry

THz reflectometry stage + TOptica sweep control for the RANNIS-funded project,
with an ESC-key emergency stop woven through every blocking wait.

Controls two Standa rotation stages (via `libximc`) and a TOptica THz
source/lock-in (via socket) to run angle x frequency reflectometry sweeps,
either specular (theta-2theta) or non-specular (receiver-only).

## Install

Requires [`uv`](https://docs.astral.sh/uv/) and, on the control PC, Standa's
`libximc` vendor driver installed separately (the Python package alone does
not include it).

```powershell
uv tool install git+https://github.com/ashaliasrun/rannis_nyskopunarsjodur2026
```

This installs the `reflecto` command on your PATH.

## Configure

Hardware calibration (COM ports, stage zero offsets, angle limits) and
TOptica connection settings live in a config file shipped with the package.
Copy it to your working folder to override any of it:

```powershell
cd C:\path\to\your\workfolder
reflecto config init
```

This writes `reflecto.toml`. Edit only the keys you need to
change -- anything you don't set falls back to the packaged default. If you
run commands from a different folder, point at it explicitly with
`--config path\to\reflecto.toml`.

## Run a sweep

```powershell
reflecto spec --start-angle 30 --end-angle 30 --step 7.5 --filename 270826_specular_ref
reflecto nonspec --start-angle 45 --end-angle 75 --step 15 --filename 310826_nonspec_linear
```

`--freq-start`, `--freq-stop`, and `--int-time` default from the config's
`[scan_defaults]` if omitted. Add `--set-zero` to home and zero both stages
before the sweep (requires typing `clear` to confirm the homing path is
clear of obstacles, since homing can move stages outside their normal
operating range).

Press **Esc** at any point to abort: both stages stop immediately, any data
already collected is saved, and devices are disconnected cleanly.

## Notes

- `keyboard`'s global ESC hook depends on running in a real Windows console;
  behavior can vary in some terminal/IDE setups.
- `libximc` requires Standa's vendor driver/DLLs on the machine, independent
  of the pip package.

## Development

Tests run without any hardware attached -- the rotation stages and ESC
listener are replaced with fakes (see `tests/fakes.py`).

```
uv run pytest
```
