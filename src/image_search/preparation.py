"""Prepare the shared search runtime once, without blocking health endpoints."""

import logging
from threading import Event, Thread


class SearchPreparation:
    def __init__(self, search, enabled=True):
        self.search = search
        self.done = Event()
        self.failed = False
        self.thread = None
        if enabled:
            self.thread = Thread(target=self._prepare, name="search-preparation")
            self.thread.start()
        else:
            self.done.set()

    def _prepare(self):
        try:
            self.search.prepare()
        except Exception as error:
            self.failed = True
            logging.getLogger(__name__).error("Search preparation failed: %s", type(error).__name__)
        finally:
            self.done.set()

    @property
    def status(self):
        if not self.done.is_set():
            return "preparing"
        return "failed" if self.failed else "ready"

    def close(self):
        # Do not close Qdrant/graph clients while the preparation thread still uses them.
        if self.thread is not None:
            self.thread.join()
