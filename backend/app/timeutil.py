"""All business time is Asia/Karachi (PKT, UTC+5, no DST)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")


def now_pkt() -> datetime:
    return datetime.now(PKT)


def today_pkt() -> date:
    return now_pkt().date()
