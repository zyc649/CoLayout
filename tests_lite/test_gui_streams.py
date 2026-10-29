import io
from colayout_lite.streams import resilient


def test_closed_inherited_gui_pipe_falls_back_without_failing_native_call(tmp_path):
    class Broken:
        def write(self,text):raise OSError(22,'invalid inherited pipe')
        def flush(self):raise OSError(22,'invalid inherited pipe')
    path=tmp_path/'progress.log'
    stream=resilient(Broken(),path)
    print('native progress',file=stream,flush=True)
    assert path.read_text(encoding='utf8')=='native progress\n'


def test_working_console_and_capture_stream_are_preserved(tmp_path):
    original=io.StringIO();stream=resilient(original,tmp_path/'unused.log')
    print('visible',file=stream,flush=True)
    assert original.getvalue()=='visible\n' and not (tmp_path/'unused.log').exists()
    assert resilient(stream,tmp_path/'other.log') is stream
