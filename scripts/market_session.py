"""Published NYSE cash-equity calendar, evaluated without network or model calls.

Source: https://www.nyse.com/trade/hours-calendars (verified 2026-09-05).
Bounded to published years; unknown years fail instead of assuming a session.
Unscheduled exchange closures require updating this calendar.
"""
import argparse
import datetime as dt
import json
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
HOLIDAYS = {
    2026: "01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25",
    2027: "01-01 01-18 02-15 03-26 05-31 06-18 07-05 09-06 11-25 12-24",
    2028: "01-17 02-21 04-14 05-29 06-19 07-04 09-04 11-23 12-25",
}
EARLY_CLOSE = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}


def now_central():
    return dt.datetime.now(CENTRAL)


def session_at(now):
    if now.tzinfo is None:
        raise ValueError("time must include a UTC offset")
    now = now.astimezone(CENTRAL)
    day = now.date()
    if day.year not in HOLIDAYS:
        raise ValueError(f"NYSE calendar not verified for {day.year}; update market_session.py")
    is_day = day.weekday() < 5 and day.strftime("%m-%d") not in HOLIDAYS[day.year].split()
    opening = dt.datetime.combine(day, dt.time(8, 30), CENTRAL)
    closing = dt.datetime.combine(day, dt.time(12 if day.isoformat() in EARLY_CLOSE else 15), CENTRAL)
    if not is_day:
        state = "closed_day"
    elif now < opening:
        state = "pre_market"
    elif now < closing:
        state = "regular"
    elif now < closing + dt.timedelta(hours=1):
        state = "post_close"
    else:
        state = "closed"
    return {"date": day.isoformat(), "now_central": now.isoformat(), "state": state,
            "is_trading_day": is_day, "is_regular_session": state == "regular",
            "open_central": opening.isoformat() if is_day else None,
            "close_central": closing.isoformat() if is_day else None}


def scheduled_plan(now):
    session = session_at(now)
    local = now.astimezone(CENTRAL)
    plan = {**session, "action": "skip", "reason": session["state"], "slot": None}
    if session["state"] == "regular":
        for hour in (9, 12, 14):
            start = local.replace(hour=hour, minute=10, second=0, microsecond=0)
            if start <= local < start + dt.timedelta(minutes=30):
                plan.update(action="intraday", reason="scheduled_session", slot=f"{session['date']}-{hour:02d}")
                break
        else:
            plan["reason"] = "outside_scheduled_window"
    elif session["state"] == "post_close":
        close = dt.datetime.fromisoformat(session["close_central"])
        if close + dt.timedelta(minutes=10) <= local < close + dt.timedelta(minutes=40):
            plan.update(action="end_of_day", reason="scheduled_review", slot=f"{session['date']}-eod")
        else:
            plan["reason"] = "outside_scheduled_window"
    return plan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", help="Read-only calendar query, ISO time with offset")
    args = parser.parse_args()
    print(json.dumps(scheduled_plan(dt.datetime.fromisoformat(args.at) if args.at else now_central())))
