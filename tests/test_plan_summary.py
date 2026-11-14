import importlib.util
import io
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "infra" / "azure" / "scripts" / "plan-summary.py"
spec = importlib.util.spec_from_file_location("plan_summary", SCRIPT)
plan_summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_summary)

PLAN = {
    "resource_changes": [
        {
            "address": "azurerm_service_plan.app",
            "mode": "managed",
            "change": {
                "actions": ["update"],
                "before": {"sku_name": "F1", "tags": {}, "name": "asp"},
                "after": {"sku_name": "B1", "tags": {}, "name": "asp"},
                "after_unknown": {},
            },
        },
        {
            "address": "azurerm_resource_group.app",
            "mode": "managed",
            "action_reason": "delete_because_no_resource_config",
            "change": {
                "actions": ["delete"],
                "before": {"name": "rg-old", "location": "australiaeast"},
                "after": None,
            },
        },
        {
            "address": "azurerm_linux_web_app.app",
            "mode": "managed",
            "change": {
                "actions": ["delete", "create"],
                "replace_paths": [["resource_group_name"]],
                "before": {"name": "web-old", "resource_group_name": "rg-old", "id": "/old"},
                "after": {"name": "web-new", "resource_group_name": "rg-new"},
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
        "resource_group_name": {"actions": ["update"], "before": "rg-old", "after": "rg-new"},
        "web_app_name": {"actions": ["no-op"]},
    },
}


def run_summary(tmp_path, capsys, monkeypatch, plan):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setattr("sys.argv", ["plan-summary.py", "dev", str(summary_path)])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(plan)))
    plan_summary.main()
    return summary_path.read_text(encoding="utf-8"), capsys.readouterr().out


def test_log_has_overview_and_collapsible_resource_details(tmp_path, capsys, monkeypatch):
    _, log = run_summary(tmp_path, capsys, monkeypatch, PLAN)

    assert "Plan: 1 to destroy, 1 to replace, 1 to forget, 1 to update." in log
    assert "##[group]-/+ replace: azurerm_linux_web_app.app (web-old -> web-new)" in log
    assert '~ resource_group_name : "rg-old" -> "rg-new"   # forces replacement' in log
    assert '~ id                  : "/old" -> (known after apply)' in log
    assert '- location = "australiaeast"' in log
    assert '~ sku_name : "F1" -> "B1"' in log
    assert log.count("##[group]") == log.count("##[endgroup]") == 5
    # Most disruptive first; untouched resources and data sources are left out.
    assert log.index("destroy: azurerm_resource_group.app") < log.index("update: azurerm_service_plan.app")
    assert "random_string.suffix" not in log
    assert "data.azurerm_client_config" not in log
    assert "| " not in log
    assert "##vso[task.logissue type=warning]" in log
    assert "replaces 2 resource(s)" in log


def test_markdown_summary_tables(tmp_path, capsys, monkeypatch):
    summary, _ = run_summary(tmp_path, capsys, monkeypatch, PLAN)

    assert "| Replace | `azurerm_linux_web_app.app` | web-old -> web-new | forced by: resource_group_name |" in summary
    assert "| Destroy | `azurerm_resource_group.app` | rg-old | removed from configuration |" in summary
    assert "| Update in place | `azurerm_service_plan.app` | asp | changes: sku_name |" in summary
    assert '| `resource_group_name` | "rg-old" | "rg-new" | yes |' in summary
    assert '| `resource_group_name` | "rg-old" | "rg-new" |' in summary
    assert "**Warning:**" in summary


def test_secret_values_are_masked(tmp_path, capsys, monkeypatch):
    plan = {
        "resource_changes": [{
            "address": "azurerm_linux_web_app.app",
            "mode": "managed",
            "change": {
                "actions": ["update"],
                "before": {"app_settings": {"OPENAI_API_KEY": "old-1", "QBO_CLIENT_ID": "old-2", "MODE": "a"}},
                "after": {"app_settings": {"OPENAI_API_KEY": "new-1", "QBO_CLIENT_ID": "new-2", "MODE": "b"}},
                # Terraform marks values from sensitive variables; names catch the rest.
                "before_sensitive": {"app_settings": {"QBO_CLIENT_ID": True}},
                "after_sensitive": {"app_settings": {"QBO_CLIENT_ID": True}},
            },
        }],
        "output_changes": {"api_token": {"actions": ["create"], "after": "new-3"}},
    }

    summary, log = run_summary(tmp_path, capsys, monkeypatch, plan)

    assert '~ app_settings.MODE           : "a" -> "b"' in log
    assert "~ app_settings.OPENAI_API_KEY : (sensitive) -> (sensitive, changed)" in log
    assert "~ api_token : (none) -> (sensitive)" in log
    for value in ("old-1", "new-1", "old-2", "new-2", "new-3"):
        assert value not in summary
        assert value not in log


def test_no_changes_without_warning(tmp_path, capsys, monkeypatch):
    plan = {"resource_changes": [{
        "address": "random_string.suffix",
        "mode": "managed",
        "change": {"actions": ["no-op"]},
    }]}

    summary, log = run_summary(tmp_path, capsys, monkeypatch, plan)

    assert "**No infrastructure changes.**" in summary
    assert "##vso" not in log
    assert "##[warning]" not in log
