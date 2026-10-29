; Whole native MPP identity and operations. Children are derived ROD figures.
procedure(ltMppRod(o)
  let((r) when(o && o~>objType=="path" r=rodGetObj(o) when(r && r~>dbId==o && r~>subParts r))))
procedure(ltMppParts(r)
  foreach(mapcar p r~>subParts
    list(p~>name p~>type p~>lpp p~>choppable p~>netName p~>termName
      when(p~>width sprintf(nil "%.12g" p~>width)) when(p~>length sprintf(nil "%.12g" p~>length))
      when(p~>enclosure sprintf(nil "%.12g" p~>enclosure)) when(p~>separation sprintf(nil "%.12g" p~>separation))
      p~>justification when(p~>beginOffset sprintf(nil "%.12g" p~>beginOffset)) when(p~>endOffset sprintf(nil "%.12g" p~>endOffset))
      when(p~>beginSegOffset sprintf(nil "%.12g" p~>beginSegOffset)) when(p~>endSegOffset sprintf(nil "%.12g" p~>endSegOffset))
      when(p~>space sprintf(nil "%.12g" p~>space)) p~>gap p~>diagonal)))
procedure(ltMppDefinition(o)
 let((r) r=ltMppRod(o) unless(r error("EXPECTED_MPP"))
  list(ltMppParts(r) rodIsMasterChoppable(r) r~>chopHoles if(r~>align then t else nil))))
procedure(ltMppRestriction(o)
 let((r reason members)
  r=ltMppRod(o) unless(r error("EXPECTED_MPP")) members=cons(o r~>subShapes)
  when(r~>align reason="mpp_alignment")
  when(r~>chopHoles reason="mpp_chopped")
  foreach(v members
    when(v~>route || v~>figGroup || v~>groupMembers || v~>parent || v~>children || v~>pin || v~>parent~>pin reason="mpp_external_relationship"))
  reason))
procedure(ltMppRead(cv)
 let((r rows definition)
  foreach(o cv~>shapes
    r=ltMppRod(o)
    when(r
      definition=ltMppDefinition(o)
      rows=cons(list(list("master" lbId(o)) list("name" r~>name)
        list("members" foreach(mapcar v cons(o r~>subShapes) lbId(v)))
        list("parts" car(definition)) list("choppable" cadr(definition)) list("chopped" if(r~>chopHoles then t else nil))
        list("restriction" ltMppRestriction(o)) list("delete_allowed" !ltMppRestriction(o)) list("definition" sprintf(nil "%L" definition))) rows))) rows))
procedure(ltMppMarkChildren(o)
 let((r uid group n)
  r=ltMppRod(o) uid=o~>colayoutObjectId group=or(o~>colayoutStructureUid uid) n=0
  foreach(v r~>subShapes
    unless(v~>colayoutObjectId dbReplaceProp(v "colayoutObjectId" "string" strcat(uid ":mpp:" sprintf(nil "%d" n))))
    dbReplaceProp(v "colayoutStructureUid" "string" group) n=n+1) t))
procedure(ltMppMove(o placement)
 let((origin orient rotated target offset)
  when(ltMppRestriction(o) error("MPP_RELATIONSHIP_READ_ONLY"))
  origin=car(o~>points) orient=ltGet(placement "orientation")
  unless(member(orient list("R0" "R90" "R180" "R270" "MX" "MY" "MXR90" "MYR90")) error("INVALID_ORIENTATION"))
  target=ltPoint(ltGet(placement "origin") o~>cellView~>DBUPerUU)
  rotated=dbTransformPoint(origin list(0:0 orient 1.0))
  offset=list(car(target)-car(rotated) cadr(target)-cadr(rotated))
  unless(dbMoveFig(o nil list(offset orient 1.0)) error("MPP_MOVE_FAILED"))
  ltMppMarkChildren(o) t))
procedure(ltMppDelete(o deleted)
 let((r members)
  when(ltMppRestriction(o) error("MPP_RELATIONSHIP_READ_ONLY"))
  r=ltMppRod(o) members=cons(o r~>subShapes)
  foreach(v members deleted[v~>colayoutObjectId]=t)
  ; Deleting only the master removes the live DB figures but leaves the ROD
  ; definition able to emit stale subparts in a separate XStream process.
  ; Capture exact membership first; never discover children spatially.
  unless(rodUnNameShape(r) error("MPP_UNNAME_FAILED"))
  foreach(v members when(dbIsId(v) unless(dbDeleteObject(v) error("MPP_DELETE_FAILED"))))
  when(setof(v members dbIsId(v)) error("MPP_DELETE_INCOMPLETE")) t))
