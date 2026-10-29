"""Disposable read-only candidate projection for the existing network viewer.

No Editor adoption, history or persistence. Preview IDs are not selectable
editing objects; the actual workspace remains the only editable source.
"""
from shapely.geometry import Point
from shapely import STRtree
from ..model import LiteError
from .validation import checked_operations
from .geometry import shape_figures


class RoutingPreview:
    def __init__(self,editor,session,candidate,*,layer_priority=None):
        self.editor=editor;self.source=editor.w;self.scope=editor.scope_id;self.candidate_id=candidate.id
        if self.scope!=session.region_id:raise LiteError('ROUTING_SCOPE_CHANGED')
        operations=checked_operations(candidate.proposal,session.problem,editor.profile)
        region=self.source.local_data.regions[self.scope]
        local=self.source.local_data.model_copy(update={'regions':{**self.source.local_data.regions,self.scope:
            region.model_copy(update={'object_uids':region.object_uids+tuple(op.uid for op in operations)})}})
        self.workspace=self.source.model_copy(update={'operations':self.source.operations+operations,'local_data':local})
        metals={r.name for r in session.problem.layers};self.all_figures=[]
        for op in operations:
            self.all_figures.extend((op.uid,layer,g) for layer,g in shape_figures(op.shape,session.problem))
        self.figures=[row for row in self.all_figures if row[1] in metals]
        self.figures.sort(key=lambda row:(layer_priority or {}).get(row[1],0))
        self.tree=STRtree([g for _,_,g in self.figures])

    def current(self,editor):
        return editor is self.editor and editor.w is self.source and editor.scope_id==self.scope

    def hit(self,x,y,tolerance):
        point=Point(x,y);indexes=self.tree.query(point,predicate='dwithin',distance=tolerance)
        if not len(indexes):return None
        i=min(indexes,key=lambda i:(self.figures[i][2].distance(point),-int(i)))
        uid,layer,_=self.figures[i];return (uid,x,y,layer,tolerance)
