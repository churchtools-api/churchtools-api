"""Monatsplan: calendars, the appointments of one month and the events with their services.

    CT_URL=https://meinegemeinde.church.tools CT_TOKEN=... python examples/monatsplan.py

Without CT_TOKEN only public calendars are read; events and services need a token.
"""

import datetime as dt
import os
from zoneinfo import ZoneInfo

import churchtools_api as ct

LOCAL = ZoneInfo("Europe/Berlin")  # the API returns timezone-aware UTC datetimes
client = ct.Client(os.environ.get("CT_URL", "https://demo.church.tools"), os.environ.get("CT_TOKEN"))
start = dt.date.today().replace(day=1)
end = (start + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)

calendars = client.calendars.list()
print("Kalender:", ", ".join(f"{c.id}={c.name}" for c in calendars))

occurrences = client.calendars.appointments.list(
    calendar_ids=[c.id for c in calendars],
    from_=start,
    to=end,
    include=["event"],
)
print(f"\n{len(occurrences)} Termine {start:%m/%Y}:")
for occ in occurrences[:10]:
    base = occ.appointment.base
    when = (occ.appointment.calculated.start_date if occ.appointment.calculated else base.start_date).astimezone(LOCAL)
    place = base.address.name if base.address else ""
    print(f"  {when:%d.%m. %H:%M}  {base.title:<30} {base.calendar.name:<15} {place or ''}")

try:
    services = {s.id: s.name for s in client.services.list()}
    print(f"\n{len(services)} Dienste")
    for event in client.events.list(from_=start, to=end, include="event_services"):
        assigned = [
            f"{services.get(es.service_id, es.service_id)}: {es.person.title if es.person else '—'}"
            for es in (event.event_services or [])
        ]
        print(f"  {event.start_date.astimezone(LOCAL):%d.%m.} {event.name}: {'; '.join(assigned)}")
except ct.Unauthorized as e:
    print(f"\nDienste/Events übersprungen: {e.translated_message}")
