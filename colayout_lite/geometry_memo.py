"""Bounded identity caches for immutable published geometry, never edit evidence.

Snapshot replacement selects a new source. Retaining each source prevents ID
reuse; the small LRU limits retention across documents and worker previews.
"""

from collections import OrderedDict
from threading import RLock


class GeometryMemo:
    def __init__(self, *, sources=3, entries=128):
        self.sources = sources
        self.entries = entries
        self._values = OrderedDict()
        self._lock = RLock()

    def get(self, source, key, compute):
        ident = id(source)
        with self._lock:
            found = self._values.get(ident)
            if found is not None and key in found[1]:
                self._values.move_to_end(ident)
                found[1].move_to_end(key)
                return found[1][key]
        value = compute()
        with self._lock:
            if ident not in self._values:
                self._values[ident] = (source, OrderedDict())
            bucket = self._values[ident][1]
            bucket[key] = value
            bucket.move_to_end(key)
            self._values.move_to_end(ident)
            while len(bucket) > self.entries:
                bucket.popitem(last=False)
            while len(self._values) > self.sources:
                self._values.popitem(last=False)
        return value

    def clear(self):
        with self._lock:
            self._values.clear()
