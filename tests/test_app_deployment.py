import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "azure" / "scripts" / "deploy-app.sh"
BASH = shutil.which("bash") if os.name != "nt" else None
if os.name == "nt":
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if git_bash.is_file():
        BASH = str(git_bash)


@pytest.fixture
def deployment(tmp_path):
    if not BASH:
        pytest.skip("Bash is required to exercise the deployment script")
    package = tmp_path / "accounting.zip"
    package.write_bytes(b"test package")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    az = bin_dir / "az"
    az.write_text(
        '#!/usr/bin/env bash\n'
        'if [[ "$2" == list ]]; then\n'
        '  printf "%s\\n" "$@" > "$AZ_LIST_LOG"\n'
        '  if [[ "${FAIL_LIST:-}" == 1 ]]; then exit 7; fi\n'
        '  printf "%s" "$MOCK_APPS"\n'
        'else\n'
        '  printf "%s\\n" "$@" > "$AZ_LOG"\n'
        '  if [[ "${FAIL_DEPLOY:-}" == 1 ]]; then exit 8; fi\n'
        'fi\n',
        encoding="utf-8",
    )
    az.chmod(0o755)
    log = tmp_path / "az.log"
    list_log = tmp_path / "az-list.log"

    def run(apps, **extra):
        env = os.environ.copy()
        env.update(
            APP_PACKAGE=str(package),
            DEPLOY_SCRIPT=str(SCRIPT),
            MOCK_BIN=str(bin_dir),
            AZ_LOG=str(log),
            AZ_LIST_LOG=str(list_log),
            MOCK_APPS=apps,
            **extra,
        )
        command = (
            'if command -v cygpath >/dev/null 2>&1; then '
            'APP_PACKAGE="$(cygpath -u "$APP_PACKAGE")"; '
            'DEPLOY_SCRIPT="$(cygpath -u "$DEPLOY_SCRIPT")"; '
            'MOCK_BIN="$(cygpath -u "$MOCK_BIN")"; '
            'AZ_LOG="$(cygpath -u "$AZ_LOG")"; '
            'AZ_LIST_LOG="$(cygpath -u "$AZ_LIST_LOG")"; fi; '
            'export APP_PACKAGE AZ_LOG AZ_LIST_LOG PATH="$MOCK_BIN:$PATH"; '
            'exec bash "$DEPLOY_SCRIPT"'
        )
        return subprocess.run(
            [BASH, "-c", command], env=env, text=True, capture_output=True, timeout=20
        )

    return run, log, list_log


def test_deploys_only_the_unique_matching_app(deployment):
    run, log, list_log = deployment
    result = run("quickbooks-dev-12345678\n")

    assert result.returncode == 0, result.stderr
    args = log.read_text(encoding="utf-8").splitlines()
    assert args[:6] == ["webapp", "deploy", "--resource-group", "rg-quickbooks-dev",
                        "--name", "quickbooks-dev-12345678"]
    assert "--type" in args and "zip" in args
    assert "accounting.zip" in args[args.index("--src-path") + 1]
    query = list_log.read_text(encoding="utf-8")
    assert "tags.application=='quickbooks-accounting'" in query
    assert "tags.environment=='dev'" in query
    assert "tags.managed_by=='terraform'" in query
    assert "starts_with(name, 'quickbooks-dev-')" in query


@pytest.mark.parametrize("apps", ["", "quickbooks-dev-first\nquickbooks-dev-second\n"])
def test_does_not_deploy_when_target_is_ambiguous(deployment, apps):
    run, log, _ = deployment
    result = run(apps)

    assert result.returncode != 0
    assert not log.exists()


def test_deployment_and_discovery_errors_fail_the_step(deployment):
    run, log, _ = deployment
    assert run("", FAIL_LIST="1").returncode != 0
    assert not log.exists()
    assert run("quickbooks-dev-12345678", FAIL_DEPLOY="1").returncode != 0
    assert log.exists()
