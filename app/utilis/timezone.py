from datetime import datetime
from zoneinfo import ZoneInfo

EAT = ZoneInfo("Africa/Nairobi")


def now_eat():
#Return the current time in East Africa Time (EAT)
    return datetime.now(EAT)