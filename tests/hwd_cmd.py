"""Which hardware daemon the daemon tests start.

By default daemon/hmi_hwd.py (the reference). With HMI_HWD_CMD set to the C
port's binary (native/hmi-hwd/out/hmi-hwd, Linux) the same tests run
against it instead -- the C daemon's acceptance gate. The Python tests make
a read fail by monkeypatching IioSim.read; the C daemon takes the same
instruction from HWD_SIM_FAIL (docs/CONTRACT.md section 14).
"""
import os
import shlex


def native() -> bool:
    return bool(os.environ.get("HMI_HWD_CMD"))


def command(config_path, extra=(), fail=()):
    """(argv, env) starting the C daemon on `config_path` in sim mode."""
    argv = shlex.split(os.environ["HMI_HWD_CMD"]) + ["--config", str(config_path), "--sim", *extra]
    env = dict(os.environ)
    if fail:
        env["HWD_SIM_FAIL"] = ",".join(fail)
    else:
        env.pop("HWD_SIM_FAIL", None)
    return argv, env
