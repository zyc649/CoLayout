"""Shared human bounds interface for local frames and editable top-level rects."""
from .frame_edit import FrameEdit
from .human_edit import HumanEdit
from .editor import Editor,projected
from .model import LiteError
from .regions.query import owner_map


class BoundsEdit:
    def __init__(self,editor):self.editor=editor;self.frames=FrameEdit(editor)

    def record(self,ident):
        obj=projected(self.editor.w).get(ident)
        if obj is None:return self.frames.record(ident)
        HumanEdit(self.editor).kind(ident)
        if obj.kind!='rect' or not obj.shape:raise LiteError('RECTANGLE_REQUIRED','只支持独立矩形和本地框的尺寸调整。')
        self.editor.profile.check(obj.shape)
        return 'rectangle',obj.model_copy(update={'bbox':obj.shape.bbox})

    def limits(self,ident):
        field,_=self.record(ident)
        return None if field=='rectangle' else self.frames.limits(ident)

    def outer(self,ident):
        field,row=self.record(ident);local=self.editor.w.local_data
        parent=row.parent_id if field=='regions' else owner_map(self.editor.w).get(ident) if field=='rectangle' else None
        return local.regions[parent].bbox if parent else None

    def candidate(self,ident,bounds):
        field,row=self.record(ident)
        if field!='rectangle':return self.frames.candidate(ident,bounds)
        grid=self.editor.profile.grid;bbox=tuple(tuple(round(v/grid)*grid for v in p) for p in bounds)
        trial=Editor(self.editor.w,self.editor.profile,scope_id=self.editor.scope_id)
        trial.edit(ident,bbox=bbox)
        return trial.w

    def resize(self,ident,bounds,*,expected_revision=None):
        e=self.editor;e.check_revision(expected_revision);field,row=self.record(ident)
        if field!='rectangle':return self.frames.resize(ident,bounds,expected_revision=expected_revision)
        grid=e.profile.grid;bbox=tuple(tuple(round(v/grid)*grid for v in p) for p in bounds)
        e.edit(ident,bbox=bbox)
        return e.w
