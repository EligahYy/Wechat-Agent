"""Resolve common dates from source time, never the day a history import runs."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def due_date(text, event_time):
    if not text:
        return None
    day = datetime.fromisoformat(event_time).astimezone(TZ).date()
    for word, days in [("大后天", 3), ("后天", 2), ("明天", 1), ("今天", 0)]:
        if word in text:
            return (day + timedelta(days=days)).isoformat()
    match = re.search(r"(下周|本周|这周|周|星期)([一二三四五六日天])", text)
    if match:
        delta = WEEKDAYS[match[2]] - day.weekday()
        if match[1] == "下周":
            delta += 7
        elif match[1] in {"周", "星期"} and delta < 0:
            delta += 7
        return (day + timedelta(days=delta)).isoformat()
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if match:
        return datetime.strptime(match[1], "%Y-%m-%d").date().isoformat()
    return None
