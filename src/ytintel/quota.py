"""Atomic project-wide quota reservations. Crashes conservatively keep reservations charged."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from zoneinfo import ZoneInfo

from .errors import AppError

active_ticket = ContextVar("quota_ticket", default=None)


class Ticket:
    def __init__(self, units, searches):
        self.units, self.searches = units, searches
        self.used_units, self.used_searches = 0, 0

    def consume(self, units=0, searches=0):
        if self.used_units + units > self.units or self.used_searches + searches > self.searches:
            raise AppError("quota_reservation", "Workflow quota reservation exhausted", 429)
        self.used_units += units
        self.used_searches += searches


class Quota:
    def __init__(self, store, units=10000, searches=100):
        self.store, self.units, self.searches = store, units, searches

    def day(self):
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()

    @contextmanager
    def reserve(self, units, searches):
        day = self.day()
        self.store.reserve_quota(day, units, searches, self.units, self.searches)
        ticket = Ticket(units, searches)
        token = active_ticket.set(ticket)
        try:
            yield ticket
        finally:
            active_ticket.reset(token)
            self.store.release_quota(
                day, units - ticket.used_units, searches - ticket.used_searches
            )

    def status(self):
        row = self.store.quota_usage(self.day())
        return dict(
            day=self.day(),
            units_used=row[0],
            searches_used=row[1],
            units_limit=self.units,
            searches_limit=self.searches,
        )
