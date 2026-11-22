"""Bind explicitly stated ISO-date ranges; leave other phrasing to clarification/model interpretation."""
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.contracts import Window


def explicit_windows(messages):
    for message in reversed(messages):
        if message['role'] != 'user':
            continue
        text = message.get('content') or ''
        pairs = re.findall(r'\b(\d{4}-\d{2}-\d{2})\s+inclusive\s+(?:to|through)\s+(\d{4}-\d{2}-\d{2})\s+exclusive\b',text,re.I)
        zone = re.search(r'\bin\s+(UTC|[A-Za-z_]+/[A-Za-z_]+(?:/[A-Za-z_]+)?)\b',text)
        if len(pairs) != 2 or zone is None:
            continue
        try:
            tz = ZoneInfo(zone[1])
            windows = [Window(start=datetime.combine(date.fromisoformat(a),time.min,tz),
                              end=datetime.combine(date.fromisoformat(b),time.min,tz)) for a,b in pairs]
        except (ValueError,ZoneInfoNotFoundError):
            return None
        return dict(zip(('baseline','comparison'),windows))
    return None


class WindowMismatch(ValueError):
    def __init__(self, windows):
        super().__init__('Tool windows differ from explicitly requested date boundaries')
        self.expected = {key:value.model_dump(mode='json') for key,value in windows.items()}
