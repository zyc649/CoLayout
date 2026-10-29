"""Configured guard catalog and main-thread adoption of native preview results."""
from uuid import uuid4
from .model import LiteError
from .editor import Editor
from .actions import Actions
from .mpp_recipe import available,native_templates


def catalog(profile):
    rows=[{'label':t['name']+' · 原生模板','template':t} for t in native_templates(profile)]
    rows += [{'label':t['name']+' · '+('双排' if t['kind']=='double' else '单排'),'template':t} for t in available(profile)]
    return rows


def generate(source,profile,scope,adapter,action,params,*,progress=None):
    # The preview has a separate persistence ID; an unadopted result cannot
    # overwrite this user's adapter workspace record from a worker thread.
    staging=Editor(source.model_copy(update={'id':str(uuid4())}),profile,scope_id=scope)
    result=Actions(staging).execute(action,params,adapter=adapter,progress=progress)
    return result.uid,staging.w


def adopt(editor,source,scope,result):
    editor.work_sessions._on_thread();editor.check_revision(source.revision)
    if editor.w is not source or editor.scope_id!=scope:raise LiteError('GUARD_PREVIEW_STALE','工作区或当前层已变化，未采用保护环预览。')
    editor.work_sessions.assert_editable()
    uid,candidate=result
    editor.publish(source.model_copy(update={'operations':candidate.operations,'guard_previews':candidate.guard_previews}))
    return uid
