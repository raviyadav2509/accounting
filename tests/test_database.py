from services import database


def test_database_initialization_and_tenant_scoped_records(database_file, user, client):
    other_user = database.create_user(
        first_name="Other",
        last_name="Accountant",
        email="other@example.com",
        password_hash="hash",
        firm_name="Other Firm",
        director_name="Other Accountant",
    )

    owned_client = database.get_client_for_user(client["id"], user["id"])
    assert owned_client["company_name"] == "Example Pty Ltd"
    assert database.get_client_for_user(client["id"], other_user["id"]) is None


def test_bas_approval_can_reopen_before_lodgement_but_not_after(database_file, client):
    bas = {
        "start": "2026-07-01",
        "end": "2026-09-30",
        "g1": 1000,
        "gst_sales": 100,
        "gst_purchases": 40,
        "w1": 500,
        "w2": 50,
        "gst_position": 60,
        "payable": 110,
    }
    signature = "signature-1"
    database.save_bas_snapshot(client["id"], bas, signature)
    database.update_review(
        client["id"], bas["start"], bas["end"], signature, "PASS", "Checks passed"
    )

    approved = database.mark_approved(
        client["id"], bas["start"], bas["end"], signature, "PASS"
    )
    assert approved["approval_status"] == "APPROVED"

    reopened = database.reopen_bas(
        client["id"], bas["start"], bas["end"], signature
    )
    assert reopened["approval_status"] is None

    database.mark_approved(client["id"], bas["start"], bas["end"], signature, "PASS")
    lodged = database.mark_lodged(
        client["id"], bas["start"], bas["end"], signature, "MOCK-BAS-123"
    )
    assert lodged["approval_status"] == "LODGED"
    assert lodged["lodgement_reference"] == "MOCK-BAS-123"

    still_lodged = database.reopen_bas(
        client["id"], bas["start"], bas["end"], signature
    )
    assert still_lodged["approval_status"] == "LODGED"


def test_tax_return_adjustments_are_scoped_to_client(database_file, client):
    tax_return = database.create_tax_return(
        client["id"], "2025-26", "2025-07-01", "2026-06-30", "COMPANY"
    )
    adjustment = database.add_tax_adjustment(
        client["id"], tax_return["id"], "ADD", "Entertainment", "Non-deductible", 250
    )

    adjustments = database.get_tax_adjustments(client["id"], tax_return["id"])
    assert adjustments[0]["id"] == adjustment
    assert adjustments[0]["amount"] == 250
    assert adjustments[0]["category"] == "Entertainment"
    assert database.get_tax_adjustments(client["id"] + 999, tax_return["id"]) == []
