import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "infra" / "azure" / "scripts" / "plan-summary.py"
spec = importlib.util.spec_from_file_location("plan_summary", SCRIPT)
plan_summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_summary)

PLAN = {
    "resource_changes": [
        {
            "address": "azurerm_resource_group.app",
            "mode": "managed",
            "change": {"actions": ["delete"], "before": {"name": "rg-old"}, "after": None},
        },
        {
            "address": "azurerm_linux_web_app.app",
            "mode": "managed",
            "change": {
                "actions": ["delete", "create"],
                "replace_paths": [["resource_group_name"]],
                "before": {"resource_group_name": "rg-old"},
                "after": {"resource_group_name": "rg-new"},
            },
        },
        {
            "address": "azurerm_service_plan.app",
            "mode": "managed",
            "change": {
                "actions": ["update"],
                "before": {"sku_name": "F1", "tags": {}, "name": "asp"},
                "after": {"sku_name": "B1", "tags": {}, "name": "asp"},
                "after_unknown": {"id": True},
            },
        },
        {
            "address": "azurerm_resource_group.legacy",
            "mode": "managed",
            "change": {"actions": ["forget"]},
        },
        {
            "address": "random_string.suffix",
            "mode": "managed",
            "change": {"actions": ["no-op"]},
        },
        {
            "address": "data.azurerm_client_config.current",
            "mode": "data",
            "change": {"actions": ["read"]},
        },
    ],
    "output_changes": {
        "resource_group_name": {"actions": ["update"]},
        "web_app_name": {"actions": ["no-op"]},
    },
}


def run_summary(tmp_path, capsys, monkeypatch, plan):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setattr("sys.argv", ["plan-summary.py", "dev", str(summary_path)])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(plan)))
    plan_summary.main()
    return summary_path.read_text(encoding="utf-8"), capsys.readouterr().out


def test_summary_groups_changes_and_warns_on_destruction(tmp_path, capsys, monkeypatch):
    summary, output = run_summary(tmp_path, capsys, monkeypatch, PLAN)

    assert "| Destroy | 1 |" in summary
    assert "| Replace | 1 |" in summary
    assert "| Update in place | 1 |" in summary
    assert "| Forget (stop managing, not deleted) | 1 |" in summary
    assert "`azurerm_linux_web_app.app` (forced by: resource_group_name)" in summary
    assert "`azurerm_service_plan.app` (changes: id, sku_name)" in summary
    assert "random_string.suffix" not in summary
    assert "data.azurerm_client_config" not in summary
    assert "Outputs changing: resource_group_name" in summary
    # The destroy section must come before less disruptive changes.
    assert summary.index("### Destroy") < summary.index("### Update in place")
    assert "##vso[task.logissue type=warning]" in output
    assert "replaces 2 resource(s)" in output


def test_summary_never_includes_attribute_values(tmp_path, capsys, monkeypatch):
    plan = {
        "resource_changes": [{
            "address": "azurerm_linux_web_app.app",
            "mode": "managed",
            "change": {
                "actions": ["update"],
                "before": {"app_settings": {"OPENAI_API_KEY": "old-secret"}},
                "after": {"app_settings": {"OPENAI_API_KEY": "new-secret"}},
            },
        }],
    }

    summary, output = run_summary(tmp_path, capsys, monkeypatch, plan)

    assert "(changes: app_settings)" in summary
    assert "secret" not in summary
    assert "secret" not in output


def test_summary_reports_no_changes_without_warning(tmp_path, capsys, monkeypatch):
    plan = {"resource_changes": [{
        "address": "random_string.suffix",
        "mode": "managed",
        "change": {"actions": ["no-op"]},
    }]}

    summary, output = run_summary(tmp_path, capsys, monkeypatch, plan)

    assert "**No infrastructure changes.**" in summary
    assert "##vso" not in output
