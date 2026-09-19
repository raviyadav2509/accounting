import json
from urllib.parse import urlencode

import requests

from config import (
    QBO_AUTH_URL,
    QBO_BASE_URL,
    QBO_CLIENT_ID,
    QBO_CLIENT_SECRET,
    QBO_REDIRECT_URI,
    QBO_TOKEN_URL,
    TOKEN_FILE,
)


def _load_tokens():
    with open(TOKEN_FILE, "r") as f:
        return json.load(f)


def _save_tokens(tokens):
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def build_authorization_url(state):
    params = {
        "client_id": QBO_CLIENT_ID,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": QBO_REDIRECT_URI,
        "state": state,
    }
    return f"{QBO_AUTH_URL}?{urlencode(params)}"


def exchange_authorization_code(code, realm_id):
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
    token_data["realmId"] = realm_id
    _save_tokens(token_data)
    return token_data


def refresh_access_token():
    token_data = _load_tokens()
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
    updated["realmId"] = token_data["realmId"]
    _save_tokens(updated)
    return updated["access_token"]


def _request(method, url, *, params=None):
    token_data = _load_tokens()

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
        response = send(refresh_access_token())
    if not response.ok:
        raise RuntimeError(
            f"QuickBooks request failed: {response.status_code} {response.text}"
        )
    return response.json()


def query(entity, start_date=None, end_date=None):
    token_data = _load_tokens()
    realm_id = token_data["realmId"]
    query_text_value = f"select * from {entity}"
    if start_date and end_date:
        query_text_value += (
            f" where TxnDate >= '{start_date}'"
            f" and TxnDate <= '{end_date}'"
        )
    return _request(
        "GET",
        f"{QBO_BASE_URL}/v3/company/{realm_id}/query",
        params={"query": query_text_value},
    )


def query_text(query_text_value):
    token_data = _load_tokens()
    realm_id = token_data["realmId"]
    return _request(
        "GET",
        f"{QBO_BASE_URL}/v3/company/{realm_id}/query",
        params={"query": query_text_value},
    )


def get_report(report_name, start_date, end_date):
    token_data = _load_tokens()
    realm_id = token_data["realmId"]
    return _request(
        "GET",
        f"{QBO_BASE_URL}/v3/company/{realm_id}/reports/{report_name}",
        params={"start_date": start_date, "end_date": end_date},
    )


def get_company_info():
    token_data = _load_tokens()
    realm_id = token_data["realmId"]
    return _request(
        "GET",
        f"{QBO_BASE_URL}/v3/company/{realm_id}/companyinfo/{realm_id}",
    )


def get_accounts():
    return query_text("select * from Account")


def get_tax_codes():
    return query_text("select * from TaxCode where Active = true")
