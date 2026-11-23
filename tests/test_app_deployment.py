import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Pipelines" / "scripts" / "deploy-app.ps1"
POWERSHELL = shutil.which("pwsh")
if os.name == "nt":
    POWERSHELL = POWERSHELL or shutil.which("powershell.exe")


@pytest.fixture
def deployment(tmp_path):
    if not POWERSHELL:
        pytest.skip("PowerShell is required to exercise the deployment script")
    package = tmp_path / "accounting.zip"
    package.write_bytes(b"test package")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    az_stub = bin_dir / "mock_az.py"
    az_stub.write_text(
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['webapp', 'list']:\n"
        "    with open(os.environ['AZ_LIST_LOG'], 'w', encoding='utf-8') as f: "
        "json.dump(args, f)\n"
        "    if os.environ.get('FAIL_LIST') == '1': sys.exit(7)\n"
        "    for app in json.loads(os.environ['MOCK_APPS_JSON']): print(app)\n"
        "else:\n"
        "    with open(os.environ['AZ_LOG'], 'w', encoding='utf-8') as f: "
        "json.dump(args, f)\n"
        "    if os.environ.get('FAIL_DEPLOY') == '1': sys.exit(8)\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        az = bin_dir / "az.cmd"
        python = sys.executable.replace('"', '""')
        stub = str(az_stub).replace('"', '""')
        az.write_text(
            f'@"{python}" "{stub}" %*\r\n@exit /b %ERRORLEVEL%\r\n',
            encoding="utf-8",
        )
    else:
        az = bin_dir / "az"
        az.write_text(
            f"#!{sys.executable}\n"
            "import runpy\n"
            f"runpy.run_path({str(az_stub)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        az.chmod(0o755)

    log = tmp_path / "az.log"
    list_log = tmp_path / "az-list.log"

    def run(apps, **extra):
        env = os.environ.copy()
        env.update(
            APP_PACKAGE=str(package),
            AZ_LOG=str(log),
            AZ_LIST_LOG=str(list_log),
            MOCK_APPS_JSON=json.dumps(apps),
            PATH=str(bin_dir) + os.pathsep + env["PATH"],
            **extra,
        )
        if os.name == "nt":
            command = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)]
        else:
            command = [POWERSHELL, "-NoLogo", "-NoProfile", "-File", str(SCRIPT)]
        return subprocess.run(
            command, env=env, text=True, capture_output=True, timeout=20
        )

    return run, log, list_log


def test_deploys_only_the_unique_matching_app(deployment):
    run, log, list_log = deployment
    result = run(["quickbooks-dev-12345678"])

    assert result.returncode == 0, result.stderr
    args = json.loads(log.read_text(encoding="utf-8"))
    assert args[:6] == ["webapp", "deploy", "--resource-group", "rg-quickbooks-dev",
                        "--name", "quickbooks-dev-12345678"]
    assert "--type" in args and "zip" in args
    assert str(Path(args[args.index("--src-path") + 1])) == str(
        Path(list_log.parent / "accounting.zip")
    )
    query_args = json.loads(list_log.read_text(encoding="utf-8"))
    assert "--output" in query_args and "tsv" in query_args
    query = query_args[query_args.index("--query") + 1]
    assert "tags.application=='quickbooks-accounting'" in query
    assert "tags.environment=='dev'" in query
    assert "tags.managed_by=='terraform'" in query
    assert "starts_with(name, 'quickbooks-dev-')" in query


@pytest.mark.parametrize("apps", [[], ["quickbooks-dev-first", "quickbooks-dev-second"]])
def test_does_not_deploy_when_target_is_ambiguous(deployment, apps):
    run, log, _ = deployment
    result = run(apps)

    assert result.returncode != 0
    assert not log.exists()


def test_deployment_and_discovery_errors_fail_the_step(deployment):
    run, log, _ = deployment
    assert run([], FAIL_LIST="1").returncode != 0
    assert not log.exists()
    assert run(["quickbooks-dev-12345678"], FAIL_DEPLOY="1").returncode != 0
    assert log.exists()


def test_deployment_package_includes_database_and_starts(tmp_path):
    packager_path = ROOT / "Pipelines" / "utility" / "package_app.py"
    spec = importlib.util.spec_from_file_location("package_app", packager_path)
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    archive_path = tmp_path / "app.zip"
    packager.package(ROOT, archive_path)

    extracted = tmp_path / "app"
    with zipfile.ZipFile(archive_path) as archive:
        assert {"database/__init__.py", "database/store.py"} <= set(archive.namelist())
        archive.extractall(extracted)

    env = os.environ.copy()
    env.update(
        BAS_DATABASE_FILE=str(tmp_path / "app.db"),
        PYTHON_DOTENV_DISABLED="1",
        OPENAI_API_KEY="test-only-not-a-real-key",
        FLASK_SECRET_KEY="test-only-session-key",
    )
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-c", "from azure_wsgi import app; assert app"],
        cwd=extracted,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
