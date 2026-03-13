from datetime import datetime, timedelta
from dateutil import parser as dateutil_parser
from auth import get_calendar_service


def get_todays_events():
    """Fetch all events for today."""
    service = get_calendar_service()
    now = datetime.utcnow()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat() + "Z"

    result = service.events().list(
        calendarId="primary",
        timeMin=start_of_day,
        timeMax=end_of_day,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    return result.get("items", [])


def get_weeks_events():
    """Fetch all events for the next 7 days."""
    service = get_calendar_service()
    now = datetime.utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
    end = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59, microsecond=0).isoformat() + "Z"

    result = service.events().list(
        calendarId="primary",
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    return result.get("items", [])


def create_event(summary, start, end, attendees=None, add_meet_link=False):
    """Create a new Google Calendar event.

    Args:
        summary: Event title.
        start: Start datetime string (ISO format or parseable).
        end: End datetime string (ISO format or parseable).
        attendees: List of email addresses.
        add_meet_link: If True, attach a Google Meet link.
    """
    service = get_calendar_service()

    # Parse datetimes
    start_dt = dateutil_parser.parse(start)
    end_dt = dateutil_parser.parse(end)

    event_body = {
        "summary": summary,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "America/Los_Angeles",
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "America/Los_Angeles",
        },
    }

    if attendees:
        event_body["attendees"] = [{"email": e.strip()} for e in attendees]

    if add_meet_link:
        event_body["conferenceData"] = {
            "createRequest": {
                "requestId": f"meet-{int(datetime.utcnow().timestamp())}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    conference_version = 1 if add_meet_link else 0
    created = service.events().insert(
        calendarId="primary",
        body=event_body,
        conferenceDataVersion=conference_version,
    ).execute()

    return created


def create_event_from_deadline(description, date_str):
    """Create an all-day reminder event from a deadline string."""
    service = get_calendar_service()

    deadline_date = dateutil_parser.parse(date_str, fuzzy=True)

    event_body = {
        "summary": f"Deadline: {description}",
        "start": {"date": deadline_date.strftime("%Y-%m-%d")},
        "end": {"date": deadline_date.strftime("%Y-%m-%d")},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 60}],
        },
    }

    created = service.events().insert(
        calendarId="primary", body=event_body
    ).execute()

    return created
