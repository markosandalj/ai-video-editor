"""Local startup config contract, using Compose's real parser (no daemon/jobs)."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from deployment.local import configure


def compose_config(env_path, compose_file=None):
    if not shutil.which("docker"):
        pytest.skip("Docker Compose is required for the env round-trip contract")
    command = ["docker", "compose", "--env-file", str(env_path)]
    if compose_file:
        command.extend(["-f", str(compose_file)])
    result = subprocess.run(
        command + ["config", "--format", "json"],
        cwd=env_path.parent,
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "NAME": "must-not-expand",
        },
    )
    # `compose config` escapes dollars for reusable Compose output. Loading
    # this canonical representation restores the literal value once.
    return json.loads(result.stdout.replace("$$", "$"))


def test_env_round_trip_through_compose_and_helper(tmp_path):
    path = tmp_path / "worker.env"
    values = {
        "TOKEN": "literal-$NAME-${NAME} # suffix's \\path",
        "MOUNT": str(tmp_path / "$NAME ${NAME} # editor's checkout"),
        "EMPTY": "",
        "BACKSLASHES": r"double\\backslash and \'quote",
    }
    configure.write_env(path, values)
    assert configure.read_env(path) == values
    assert path.stat().st_mode & 0o777 == 0o600
    compose = tmp_path / "compose.yaml"
    compose.write_text("""services:
  worker:
    image: fixture
    env_file: [worker.env]
    environment:
      INTERPOLATED_TOKEN: ${TOKEN}
    volumes:
      - type: bind
        source: ${MOUNT}
        target: /state
""")
    worker = compose_config(path, compose)["services"]["worker"]
    assert worker["environment"]["TOKEN"] == values["TOKEN"]
    assert worker["environment"]["INTERPOLATED_TOKEN"] == values["TOKEN"]
    assert worker["environment"]["EMPTY"] == ""
    assert worker["environment"]["BACKSLASHES"] == values["BACKSLASHES"]
    assert worker["volumes"][0]["source"] == values["MOUNT"]


def test_configure_rerun_preserves_literals_and_uses_host_owner(tmp_path, monkeypatch):
    root = tmp_path / "$NAME # worker's checkout"
    root.mkdir()
    # Use the real shared/local Compose files under a path containing special characters.
    shutil.copytree(configure.ROOT / "deployment", root / "deployment")
    gradivo = tmp_path / "gradivo"
    gradivo.mkdir()
    (gradivo / "docker-compose.worktree.yml").touch()
    (gradivo / ".env").write_text("UNRELATED=unchanged\n")
    configure.write_env(
        root / ".env", {"OPENROUTER_API_KEY": "literal-$NAME-${NAME} # suffix's"}
    )
    monkeypatch.setattr(configure, "ROOT", root)
    monkeypatch.setenv("NAME", "must-not-expand")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "configure",
            "--gradivo-dir",
            str(gradivo),
            "--callback-url",
            "http://main.gradivo.localhost",
        ],
    )
    monkeypatch.setattr(os, "getuid", lambda: 12345)
    monkeypatch.setattr(os, "getgid", lambda: 12346)
    configure.main()
    path = root / ".env.worker.local"
    first = configure.read_env(path)
    configure.main()
    assert configure.read_env(path) == first
    worker = compose_config(path)["services"]["worker"]
    assert worker["user"] == "12345:12346"
    assert (
        worker["environment"]["OPENROUTER_API_KEY"]
        == "literal-$NAME-${NAME} # suffix's"
    )
    for mount in worker["volumes"]:
        assert Path(mount["source"]).is_dir()
    assert "UNRELATED=unchanged" in (gradivo / ".env").read_text()


@pytest.mark.parametrize("value", ["line\nbreak", "carriage\rreturn"])
def test_multiline_configuration_is_rejected(tmp_path, value):
    with pytest.raises(ValueError, match="single-line"):
        configure.write_env(tmp_path / "worker.env", {"TOKEN": value})


@pytest.mark.skipif(
    not os.environ.get("LOCAL_WORKER_TEST_IMAGE"),
    reason="Opt in with a built local worker image",
)
def test_container_can_write_bind_mounts_and_receives_literal_values(
    tmp_path, monkeypatch
):
    """Run the shared image without the application or any provider calls."""
    from uuid import uuid4

    root = tmp_path / "$NAME # runtime's checkout"
    root.mkdir()
    shutil.copytree(configure.ROOT / "deployment", root / "deployment")
    gradivo = tmp_path / "gradivo"
    gradivo.mkdir()
    (gradivo / "docker-compose.worktree.yml").touch()
    (gradivo / ".env").touch()
    secret = "fixture-$NAME-${NAME} # suffix's \\path and \\\\pair"
    configure.write_env(root / ".env", {"OPENROUTER_API_KEY": secret})
    monkeypatch.setattr(configure, "ROOT", root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "configure",
            "--gradivo-dir",
            str(gradivo),
            "--callback-url",
            "http://main.gradivo.localhost",
        ],
    )
    configure.main()
    path = root / ".env.worker.local"
    values = configure.read_env(path)
    values["AI_VIDEO_WORKER_IMAGE"] = os.environ["LOCAL_WORKER_TEST_IMAGE"]
    configure.write_env(path, values)
    command = [
        "docker",
        "compose",
        "--env-file",
        str(path),
        "-p",
        f"worker-config-test-{uuid4().hex[:10]}",
    ]
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "NAME": "must-not-expand",
    }
    script = """import json, os, pathlib, sqlite3
state = pathlib.Path(os.environ["VIDEO_PROCESSING_STATE_DB_PATH"])
with sqlite3.connect(state) as db:
    db.execute("CREATE TABLE fixture (id INTEGER)")
for key in ("VIDEO_PROCESSING_SCRATCH_DIR", "VIDEO_PROCESSING_LOG_DIR"):
    (pathlib.Path(os.environ[key]) / "write-check").write_text("ok")
print(json.dumps({"uid": os.getuid(), "gid": os.getgid(), "literal": os.environ["OPENROUTER_API_KEY"]}))
"""
    try:
        result = subprocess.run(
            command
            + [
                "run",
                "--rm",
                "--no-deps",
                "--pull",
                "never",
                "--entrypoint",
                "python",
                "worker",
                "-c",
                script,
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {
            "uid": os.getuid(),
            "gid": os.getgid(),
            "literal": secret,
        }
    finally:
        subprocess.run(
            command + ["down"], cwd=root, env=env, capture_output=True, check=True
        )
