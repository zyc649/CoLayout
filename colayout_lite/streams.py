"""Keep GUI progress logging from aborting native work when inherited pipes close."""
from pathlib import Path


class FallbackStream:
    def __init__(self,stream,path):
        self.stream=stream;self.path=Path(path);self.fallback=None

    def _use_file(self):
        if self.fallback is None:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.fallback=self.path.open('a',encoding='utf8',buffering=1)
        self.stream=self.fallback
        return self.fallback

    def write(self,text):
        try:
            return (self.stream or self._use_file()).write(text)
        except (OSError,ValueError):
            return self._use_file().write(text)

    def flush(self):
        try:return (self.stream or self._use_file()).flush()
        except (OSError,ValueError):return self._use_file().flush()

    def __getattr__(self,name):
        return getattr(self.stream or self._use_file(),name)


def resilient(stream,path):
    return stream if isinstance(stream,FallbackStream) else FallbackStream(stream,path)
