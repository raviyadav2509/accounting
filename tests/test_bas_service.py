from services import bas_service


def test_calculate_bas_aggregates_qbo_transactions_and_payroll(monkeypatch):
    responses = {
        "Invoice": {"QueryResponse": {"Invoice": [
            {"TotalAmt": "110", "TxnTaxDetail": {"TotalTax": "10"}}
        ]}},
        "SalesReceipt": {"QueryResponse": {"SalesReceipt": [
            {"TotalAmt": 55, "TxnTaxDetail": {"TotalTax": 5}}
        ]}},
        "Bill": {"QueryResponse": {"Bill": [
            {"TotalAmt": 33, "TxnTaxDetail": {"TotalTax": 3}}
        ]}},
        "Purchase": {"QueryResponse": {"Purchase": [
            {"TotalAmt": 22, "TxnTaxDetail": {"TotalTax": 2}}
        ]}},
    }

    monkeypatch.setattr(
        bas_service,
        "query",
        lambda client_id, entity, start, end: responses[entity],
    )
    monkeypatch.setattr(
        bas_service,
        "get_payroll_bas",
        lambda client_id, start, end: {
            "W1_gross_wages": 2000,
            "W2_PAYG_withheld": 300,
        },
    )

    result = bas_service.calculate_bas(7, "2026-07-01", "2026-09-30")

    assert result["g1"] == 165
    assert result["gst_sales"] == 15
    assert result["gst_purchases"] == 5
    assert result["gst_position"] == 10
    assert result["payable"] == 310
    assert result["w1"] == 2000
    assert result["w2"] == 300


def test_get_payroll_bas_uses_configured_debit_and_credit_accounts(monkeypatch):
    journals = {
        "QueryResponse": {
            "JournalEntry": [{
                "Line": [
                    {"Amount": 1000, "JournalEntryLineDetail": {
                        "PostingType": "Debit",
                        "AccountRef": {"value": bas_service.WAGE_ACCOUNT_ID},
                    }},
                    {"Amount": 150, "JournalEntryLineDetail": {
                        "PostingType": "Credit",
                        "AccountRef": {"value": bas_service.PAYG_ACCOUNT_ID},
                    }},
                    {"Amount": 999, "JournalEntryLineDetail": {
                        "PostingType": "Credit",
                        "AccountRef": {"value": bas_service.WAGE_ACCOUNT_ID},
                    }},
                ]
            }]
        }
    }
    monkeypatch.setattr(
        bas_service,
        "query",
        lambda client_id, entity, start, end: journals,
    )

    result = bas_service.get_payroll_bas(7, "2026-07-01", "2026-09-30")
    assert result == {"W1_gross_wages": 1000, "W2_PAYG_withheld": 150}


def test_bas_signature_is_stable_and_changes_with_figures():
    bas = {
        "start": "2026-07-01",
        "end": "2026-09-30",
        "g1": 100.0,
        "gst_sales": 10.0,
        "gst_purchases": 5.0,
        "w1": 200.0,
        "w2": 20.0,
    }
    original = bas_service.bas_signature(bas)
    assert bas_service.bas_signature(dict(bas)) == original

    changed = dict(bas, w2=21.0)
    assert bas_service.bas_signature(changed) != original

