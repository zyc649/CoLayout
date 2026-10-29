"""Narrow proof for reusing native-instance display commands after translation.

No workspace changes happen here. Unknown/generated owners, rotation, mirror,
style or dirty cache updates use the existing full owner compilation path.
"""


def instance_translations(before,after,changed,baseline,groups):
    result={}
    for uid in changed:
        a,b=before.get(uid),after.get(uid)
        if uid not in groups or uid not in baseline.objects or a is None or b is None:continue
        if a.kind!='inst' or b.kind!='inst' or not a.placement or not b.placement:continue
        if a.placement.orientation!=b.placement.orientation:continue
        if b.model_copy(update={'placement':a.placement})!=a:continue
        dx=b.placement.origin[0]-a.placement.origin[0];dy=b.placement.origin[1]-a.placement.origin[1]
        if dx or dy:result[uid]=(dx,-dy)
    for uid,parent in baseline.text_owners.items():
        if uid in changed and uid in groups and parent in result and uid in before and uid in after:
            a,b=before[uid],after[uid];dx,dy=result[parent]
            from .geometry import box
            if a.bbox is not None and a.model_copy(update={'bbox':box(a.bbox,(1,0,0,1,dx,-dy))})==b:result[uid]=(dx,dy)
    return result
