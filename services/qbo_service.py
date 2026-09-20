from urllib.parse import urlencode

import requests

from config import (
    QBO_AUTH_URL,
    QBO_BASE_URL,
    QBO_CLIENT_ID,
    QBO_CLIENT_SECRET,
    QBO_REDIRECT_URI,
    QBO_TOKEN_URL,
)
from services.database import get_qbo_connection, save_qbo_connection


def build_authorization_url(state):
    params = {
        "client_id": QBO_CLIENT_ID,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": QBO_REDIRECT_URI,
        "state": state,
    }
    return f"{QBO_AUTH_URL}?{urlencode(params)}"


def exchange_authorization_code(code, realm_id, client_id):
    response = requests.post(
        QBO_TOKEN_URL,
        auth=(QBO_CLIENT_ID, QBO_CLIENT_SECRET),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": QBO_REDIRECT_URI,
        },
    )
    response.raise_for_status()

    token_data = response.json()
    save_qbo_connection(client_id, realm_id, token_data)
    return token_data


def _load_tokens(client_id):
    connection = get_qbo_connection(client_id)
    if not connection:
        raise RuntimeError("QuickBooks is not connected for this client.")
    return connection["tokens"]


def refresh_access_token(client_id):
    connection = get_qbo_connection(client_id)
    if not connection:
        raise RuntimeError("QuickBooks is not connected for this client.")

    token_data = connection["tokens"]
    response = requests.post(
        QBO_TOKEN_URL,
        auth=(QBO_CLIENT_ID, QBO_CLIENT_SECRET),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],
        },
    )

    if not response.ok:
        raise RuntimeError(
            f"QuickBooks token refresh failed: "
            f"{response.status_code} {response.text}"
        )

    updated = {**token_data, **response.json()}
    save_qbo_connection(client_id, connection["realm_id"], updated)
    return updated["access_token"]


def _request(client_id, method, url, *, params=None):
    connection = get_qbo_connection(client_id)
    if not connection:
        raise RuntimeError("QuickBooks is not connected for this client.")

    token_data = connection["tokens"]

    def send(access_token):
        return requests.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            params=params,
        )

    response = send(token_data["access_token"])
    if response.status_code == 401:
        response = send(refresh_access_token(client_id))

    if not response.ok:
        raise RuntimeError(
            f"QuickBooks request failed: {response.status_code} {response.text}"
        )

    return response.json()


def query(client_id, entity, start_date=None, end_date=None):
    connection = get_qbo_connection(client_id)
    if not connection:
        raise RuntimeError("QuickBooks is not connected for this client.")

    realm_id = connection["realm_id"]
    query_text_value = f"select * from {entity}"

    if start_date and end_date:
        query_text_value += (
            f" where TxnDate >= '{start_date}'"
            f" and TxnDate <= '{end_date}'"
        )

    return _request(
        client_id,
        "GET",
        f"{QBO_BASE_URL}/v3/company/{realm_id}/query",
        params={"query": query_text_value},
    )


def query_text(client_id, query_text_value):
    connection = get_qbo_connection(client_id)
    if not connection:
        raise RuntimeError("QuickBooks is not connected for this client.")

    realm_id = connection["realm_id"]
    return _request(
        client_id,
        "GET",
        f"{QBO_BASE_URL}/v3/company/{realm_id}/query",
        params={"query": query_text_value},
    )


def get_report(client_id, report_name, start_date, end_date):
    connection = get_qbo_connection(client_id)
    if not connection:
        raise RuntimeError("QuickBooks is not connected for this client.")

    realm_id = connection["realm_id"]
    return _request(
        client_id,
        "GET",
        f"{QBO_BASE_URL}/v3/company/{realm_id}/reports/{report_name}",
        params={"start_date": start_date, "end_date": end_date},
    )


def get_company_info(client_id):
    connection = get_qbo_connection(client_id)
    if not connection:
        raise RuntimeError("QuickBooks is not connected for this client.")

    realm_id = connection["realm_id"]
    return _request(
        client_id,
        "GET",
        f"{QBO_BASE_URL}/v3/company/{realm_id}/companyinfo/{realm_id}",
    )


def get_accounts(client_id):
    return query_text(client_id, "select * from Account")


def get_tax_codes(client_id):
    return query_text(client_id, "select * from TaxCode where Active = true")
