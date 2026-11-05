"""Per-account usage accounting only. Google alone enforces quota."""

from contextlib import contextmanager

from sqlalchemy import Column, Integer, String, Table, select, update

from .observability import event
from .quota import Quota, Ticket, active_ticket


class TenantQuota(Quota):
    def __init__(
        self,
        store,
        context_key,
        units=10000,
        searches=100,
        user_units=1000,
        anonymous_units=3000,
        max_searches=3,
        anonymous=False,
    ):
        super().__init__(store, units, searches)
        self.context_key = ("anonymous:" if anonymous else "user:") + context_key
        self.user_units, self.anonymous_units = user_units, anonymous_units
        self.max_searches, self.anonymous = max_searches, anonymous
        name = (store.schema + "." if store.schema else "") + "quota_ledger"
        if name not in store.metadata.tables:
            Table(
                "quota_ledger",
                store.metadata,
                Column("day", String, primary_key=True),
                Column("context_key", String, primary_key=True),
                Column("user_id", String, nullable=True),
                Column("units", Integer, nullable=False),
                Column("searches", Integer, nullable=False),
            )
        self.ledger = store.metadata.tables[name]
        with store.tx() as db:
            store.metadata.create_all(db)

    def _anonymous_search_limit(self):
        if self.units <= 0:
            return 0
        return min(self.searches, int(self.searches * self.anonymous_units / self.units))

    def _scopes(self):
        result = [("global", self.units, self.searches)]
        if self.anonymous:
            result.append(("anonymous_pool", self.anonymous_units, self._anonymous_search_limit()))
        else:
            result.append((self.context_key, self.user_units, max(3, self.searches // 10)))
        return result

    def _where(self, day, key):
        return (self.ledger.c.day == day) & (self.ledger.c.context_key == key)

    @contextmanager
    def reserve(self, units, searches):
        if units < 0 or searches < 0:
            raise ValueError("Quota reservations cannot be negative")
        day = self.day()
        with self.store.tx() as db:
            for key, _, _ in self._scopes():
                db.execute(
                    self.store._insert(self.ledger)
                    .values(
                        day=day,
                        context_key=key,
                        user_id=key.removeprefix("user:") if key.startswith("user:") else None,
                        units=0,
                        searches=0,
                    )
                    .on_conflict_do_nothing(index_elements=["day", "context_key"])
                )
                u, s = db.execute(
                    select(self.ledger.c.units, self.ledger.c.searches).where(self._where(day, key))
                ).one()
                db.execute(
                    update(self.ledger)
                    .where(self._where(day, key))
                    .values(units=u + units, searches=s + searches)
                )
        event(
            "quota.reserved",
            units=units,
            searches=searches,
            auth_class="anonymous" if self.anonymous else "authenticated",
        )
        ticket = Ticket(units, searches)
        token = active_ticket.set(ticket)
        try:
            yield ticket
        finally:
            event("quota.settled", used_units=ticket.used_units, used_searches=ticket.used_searches)
            active_ticket.reset(token)
            with self.store.tx() as db:
                for key, _, _ in self._scopes():
                    db.execute(
                        update(self.ledger)
                        .where(self._where(day, key))
                        .values(
                            units=self.ledger.c.units - (units - ticket.used_units),
                            searches=self.ledger.c.searches - (searches - ticket.used_searches),
                        )
                    )

    def status(self):
        day = self.day()
        key = "anonymous_pool" if self.anonymous else self.context_key
        with self.store.tx() as db:
            row = db.execute(
                select(self.ledger.c.units, self.ledger.c.searches).where(self._where(day, key))
            ).first()
        usage = tuple(row) if row else (0, 0)
        return dict(
            day=day,
            units_used=usage[0],
            searches_used=usage[1],
            units_limit=None,
            searches_limit=None,
            max_searches_per_request=None,
            enforcement="google",
        )
