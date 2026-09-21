import hashlib

from config import PAYG_ACCOUNT_ID, WAGE_ACCOUNT_ID
from services.accounting_data_service import query


def _entities(data, entity_name):
    return data.get("QueryResponse", {}).get(entity_name, [])


def get_payroll_bas(client_id, start, end):
    journals = _entities(query(client_id, "JournalEntry", start, end), "JournalEntry")

    w1 = 0.0
    w2 = 0.0

    for journal in journals:
        for line in journal.get("Line", []):
            detail = line.get("JournalEntryLineDetail", {})
            account = detail.get("AccountRef", {})
            amount = float(line.get("Amount", 0) or 0)

            if (
                account.get("value") == WAGE_ACCOUNT_ID
                and detail.get("PostingType") == "Debit"
            ):
                w1 += amount

            if (
                account.get("value") == PAYG_ACCOUNT_ID
                and detail.get("PostingType") == "Credit"
            ):
                w2 += amount

    return {
        "W1_gross_wages": round(w1, 2),
        "W2_PAYG_withheld": round(w2, 2),
    }


def calculate_bas(client_id, start, end):
    invoices = _entities(query(client_id, "Invoice", start, end), "Invoice")
    sales_receipts = _entities(
        query(client_id, "SalesReceipt", start, end), "SalesReceipt"
    )
    bills = _entities(query(client_id, "Bill", start, end), "Bill")
    purchases = _entities(query(client_id, "Purchase", start, end), "Purchase")

    sales = invoices + sales_receipts
    all_purchases = bills + purchases

    g1 = sum(float(x.get("TotalAmt", 0) or 0) for x in sales)
    gst_sales = sum(
        float(x.get("TxnTaxDetail", {}).get("TotalTax", 0) or 0)
        for x in sales
    )
    gst_purchases = sum(
        float(x.get("TxnTaxDetail", {}).get("TotalTax", 0) or 0)
        for x in all_purchases
    )

    payroll = get_payroll_bas(client_id, start, end)
    w1 = payroll["W1_gross_wages"]
    w2 = payroll["W2_PAYG_withheld"]

    gst_position = gst_sales - gst_purchases
    payable = gst_position + w2

    return {
        "start": start,
        "end": end,
        "g1": round(g1, 2),
        "gst_sales": round(gst_sales, 2),
        "gst_purchases": round(gst_purchases, 2),
        "w1": round(w1, 2),
        "w2": round(w2, 2),
        "gst_position": round(gst_position, 2),
        "payable": round(payable, 2),
        "transactions": {
            "sales": sales,
            "purchases": purchases,
            "bills": bills,
        },
    }


def bas_signature(bas):
    value = (
        f"{bas['start']}|{bas['end']}|{bas['g1']:.2f}|"
        f"{bas['gst_sales']:.2f}|{bas['gst_purchases']:.2f}|"
        f"{bas['w1']:.2f}|{bas['w2']:.2f}"
    )
    return hashlib.sha256(value.encode()).hexdigest()


def bas_summary_payload(bas):
    return {
        "period": f"{bas['start']} to {bas['end']}",
        "G1_total_sales": bas["g1"],
        "1A_GST_on_sales": bas["gst_sales"],
        "1B_GST_on_purchases": bas["gst_purchases"],
        "W1_gross_wages": bas["w1"],
        "W2_PAYG_withheld": bas["w2"],
        "GST_balance": bas["gst_position"],
        "estimated_BAS_payable": bas["payable"],
    }
