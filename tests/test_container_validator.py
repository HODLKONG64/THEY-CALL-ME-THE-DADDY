import json
import subprocess

import pytest

from the_daddy.doctor_repair import ContainerValidator


@pytest.mark.parametrize(("options", "expected"), [
    (["name=seccomp,profile=builtin", "name=rootless", "name=cgroupns"], "0:0"),
    (["name=seccomp,profile=builtin", "name=cgroupns"], "1002:1002"),
])
def test_workspace_mapping_and_isolation(monkeypatch, tmp_path, options, expected):
    monkeypatch.setattr("the_daddy.doctor_repair.os.getuid", lambda: 1002)
    monkeypatch.setattr("the_daddy.doctor_repair.os.getgid", lambda: 1002)
    (tmp_path / "sample.txt").write_text("fixture")
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        if args[1] == "info":
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(options))
        assert args[1] == "run"
        assert args[args.index("--user") + 1] == expected
        assert all(flag in args for flag in (
            "--pull=never", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--memory=2g", "--pids-limit=128", "--cpus=2",
        ))
        assert "--privileged" not in args
        mount = args[args.index("--mount") + 1]
        assert mount.startswith("type=bind,src=") and mount.endswith(",dst=/workspace")
        assert str(tmp_path) not in mount
        kwargs["stdout"].write(b"validation passed")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("the_daddy.doctor_repair.subprocess.run", run)
    assert ContainerValidator("validation", "pytest", 60)(tmp_path) == (True, "validation passed")
    assert len(commands) == 2


@pytest.mark.parametrize("output", ["null", "{}", "not json", "[1]"])
def test_invalid_daemon_metadata_fails_closed(monkeypatch, output):
    monkeypatch.setattr("the_daddy.doctor_repair.subprocess.run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=output))
    with pytest.raises(RuntimeError, match="Docker security"):
        ContainerValidator._container_user()


def test_daemon_probe_failure_fails_closed(monkeypatch):
    def fail(*a, **k):
        raise subprocess.TimeoutExpired("docker info", 15)
    monkeypatch.setattr("the_daddy.doctor_repair.subprocess.run", fail)
    with pytest.raises(RuntimeError, match="verify Docker security mode"):
        ContainerValidator._container_user()


@pytest.mark.parametrize("options", [["name=rootless"], ["name=seccomp"]])
def test_root_host_worker_rejected(monkeypatch, options):
    monkeypatch.setattr("the_daddy.doctor_repair.os.getuid", lambda: 0)
    monkeypatch.setattr("the_daddy.doctor_repair.os.getgid", lambda: 0)
    monkeypatch.setattr("the_daddy.doctor_repair.subprocess.run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=json.dumps(options)))
    with pytest.raises(RuntimeError, match="unprivileged host worker"):
        ContainerValidator._container_user()
