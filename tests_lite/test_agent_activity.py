from colayout_lite.agent_tools.activity import ActivityFeed, details, outcome


def test_many_polls_share_one_visible_task_and_clear_starts_new_summary():
    feed=ActivityFeed(lambda rid:rid,limit=20)
    def req(key,action):
        feed.add({'event':'request','request_id':key,'client_id':'a','document_id':'doc','region_id':'r',
                  'tool':'server_drc_region','arguments':{'action':action,'job_id':'job'}})
    def response(key):
        feed.add({'event':'response','request_id':key,'response':{'ok':True,'result':{'job_id':'job','state':'running'}}})
    req('start','start');response('start')
    for i in range(100):req(str(i),'status');response(str(i))
    assert len(feed.rows)==1 and feed.rows['start'].poll_count==100
    assert '100 次进度' in details(feed.rows['start'])
    feed.clear_display('doc','r');req('after-clear','status');response('after-clear')
    assert [row.key for row in feed.visible('doc','r')]==['after-clear']
    req('after-clear-2','status');response('after-clear-2')
    assert feed.rows['after-clear'].poll_count==1 and len(feed.rows)==2


def test_document_region_filter_and_clear_does_not_resurrect_old_calls():
    feed = ActivityFeed(lambda rid: rid)
    for key, doc, rid in [('one', 'doc1', 'a'), ('two', 'doc1', 'b'), ('three', 'doc2', 'a')]:
        feed.add({'event': 'request', 'request_id': key, 'tool': 'inspect_region',
                  'document_id': doc, 'region_id': rid, 'arguments': {}})
    assert [r.key for r in feed.visible('doc1', 'a')] == ['one']
    feed.clear_display('doc1', 'a')
    feed.add({'event': 'response', 'request_id': 'one', 'response': {'ok': True, 'result': {}}})
    assert not feed.visible('doc1', 'a')
    assert len(feed.rows) == 3 and len(feed.visible('doc1', 'b')) == 1
    feed.add({'event': 'request', 'request_id': 'four', 'tool': 'inspect_region',
              'document_id': 'doc1', 'region_id': 'a', 'arguments': {}})
    assert [r.key for r in feed.visible('doc1', 'a')] == ['four']


def request(feed, key='one', tool='edit_region', args=None):
    feed.add({'event': 'request', 'request_id': key, 'tool': tool,
              'source': 'http / client / public-id-' + key,
              'arguments': args or {}, 'agent_name': '客户 Agent', 'region_id': 'area-a'})


def test_business_arguments_stay_complete_without_schema_or_auth_noise():
    feed = ActivityFeed(lambda rid: '操作区 2')
    request(feed, args={'session_token': 'secret', 'expected_revision': 4,
                       'operations': [{'action': 'move', 'uid': 'obj-1', 'params': {'dx': 0.2, 'dy': 0}}]})
    feed.add({'event': 'response', 'request_id': 'one', 'duration_ms': 10,
              'response': {'ok': True, 'result': {'created_uids': [], 'changed': True}}})
    row = feed.rows['one']
    text = details(row)
    assert all(t in text for t in ['客户 Agent', '操作区 2', 'edit_region', 'move', 'obj-1', '0.2', '依据版本', 'public-id-one'])
    assert 'secret' not in text and 'session_token' not in text
    feed.add({'event': 'replayed', 'request_id': 'one'})
    assert len(feed.rows) == 1 and row.retries == 1


def test_async_completion_and_failed_validation_are_not_generic_success():
    feed = ActivityFeed(lambda rid: rid)
    request(feed, tool='check_region', args={'action': 'start'})
    feed.add({'event': 'response', 'request_id': 'one', 'response': {'ok': True,
              'result': {'state': 'running', 'job_id': 'j'}}})
    assert feed.rows['one'].status == '进行中'
    feed.add({'event': 'job_finished', 'job_id': 'j', 'kind': 'check', 'state': 'completed', 'result': {'passed': False}})
    assert feed.rows['one'].status == '未通过'
    assert outcome({'ok': True, 'result': {'state': 'completed', 'passed': True, 'current': False}})[0] == '需重检'
    request(feed, 'bad', 'claim_region', {'region_id': 'old-id', 'agent_name': '客户 Agent'})
    feed.add({'event': 'response', 'request_id': 'bad', 'response': {'ok': False,
              'error': {'code': 'REGION_MISSING', 'message': '操作区不存在'}}})
    assert 'REGION_MISSING' in details(feed.rows['bad'])


def test_large_image_payload_and_long_history_do_not_fill_the_observer():
    feed = ActivityFeed(lambda rid: rid, limit=2)
    for i in range(3):
        request(feed, str(i), 'capture_region')
        feed.add({'event': 'response', 'request_id': str(i), 'response': {'ok': True,
                  'result': {'image_base64': 'x' * 100000, 'width': 500, 'height': 400}}})
    assert len(feed.rows) == 2 and '0' not in feed.rows
    assert len(str(feed.rows)) < 2000
    assert '500 × 400' in details(feed.rows['2'])


def test_invalid_api_input_still_has_a_readable_failure_record():
    feed = ActivityFeed(lambda rid: rid)
    for i, (tool, args) in enumerate([
        ('inspect_region', {'kind': {'wrong': 'shape'}}),
        ('route_region', {'action': ['generate']}),
        ('edit_region', {'operations': [{'action': {}, 'params': [1, 2]}]}),
        ('edit_region', {'operations': 'not a list'}),
    ]):
        key = str(i)
        request(feed, key, tool, args)
        feed.add({'event': 'response', 'request_id': key, 'response': {'ok': False,
                  'error': {'code': 'INVALID_ARGUMENTS', 'message': '输入参数无效'}}})
        assert 'INVALID_ARGUMENTS' in details(feed.rows[key])
