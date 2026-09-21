"""Select data by persisted client type, never by a request-supplied flag."""
from services import qbo_service
from services.database import get_client_by_id
from services.demo_service import is_demo, demo_query, demo_profit_report


def query(client_id, entity, start_date=None, end_date=None):
    if is_demo(get_client_by_id(client_id)):
        return demo_query(client_id, entity, start_date, end_date)
    return qbo_service.query(client_id, entity, start_date, end_date)


def get_report(client_id, report_name, start_date, end_date):
    if is_demo(get_client_by_id(client_id)):
        if report_name != "ProfitAndLoss":
            raise ValueError("This report is not supported in demo mode.")
        return demo_profit_report(client_id, start_date, end_date)
    return qbo_service.get_report(client_id, report_name, start_date, end_date)
