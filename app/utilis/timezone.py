from datetime import datetime
from zoneinfo import ZoneInfo

EAT = ZoneInfo("Africa/Nairobi")


def now_eat():
#Return the current time in East Africa Time (EAT)
    return datetime.now(EAT)

def make_eat(dt):
#Treat a naive datetime as EAT.
    return dt.replace(tzinfo=EAT)