; Native physical-route adapter. Never changes logical terminals or nets.
procedure(ltRoutingPrepare(cv seed)
  let((n)
    n=0
    foreach(r cv~>routes
      n=n+1
      unless(r~>colayoutRouteId dbReplaceProp(r "colayoutRouteId" "string" strcat(seed ":route:" sprintf(nil "%d" n)))))
    foreach(r cv~>routes
      foreach(ref append(list(r~>startConn r~>endConn r~>parent r~>figGroup)
                         append(append(r~>children r~>groupMembers) append(r~>textDisplays r~>assocTextDisplays)))
        when(ref && (ref~>cellView==cv || ref~>group~>cellView==cv || ref~>object~>cellView==cv) &&
             !ref~>colayoutObjectId && !ref~>colayoutRouteId && !ref~>colayoutReferenceId
          n=n+1 dbReplaceProp(ref "colayoutReferenceId" "string" strcat(seed ":ref:" sprintf(nil "%d" n)))))) t))

procedure(ltRouteKey(r) when(r or(r~>colayoutRouteId strcat("session:" lbId(r)))))
procedure(ltRouteRef(o) when(o or(o~>colayoutObjectId o~>colayoutRouteId o~>colayoutReferenceId strcat("session:" lbId(o)))))
procedure(ltRouteRestrictions(r)
  list(r~>isGlobal r~>isTopological r~>hasGuide
    ltRouteRef(r~>parent) foreach(mapcar o r~>children ltRouteRef(o))
    ltRouteRef(r~>figGroup) foreach(mapcar o r~>groupMembers ltRouteRef(o))
    foreach(mapcar o r~>textDisplays ltRouteRef(o)) foreach(mapcar o r~>assocTextDisplays ltRouteRef(o))))
; Installed IC618 skdfref/attrib: a physical route can meet other routes at a
; Steiner. Keep the connection object fixed when editing its member figures.
procedure(ltRouteEndpointData(o)
  when(o
    if(o~>objType=="steiner" then
      list(ltRouteRef(o) o~>objType lbBounds(o~>bBox o~>cellView~>DBUPerUU)
        o~>layer lbProps(o) sort(foreach(mapcar r o~>connRoutes ltRouteKey(r)) 'alphalessp))
    else list(ltRouteRef(o) o~>objType))))
procedure(ltRouteEndpointEditable(o cv)
  !o || (o~>objType=="steiner" && o~>cellView==cv && o~>colayoutReferenceId &&
    !o~>parent && !o~>children && !o~>figGroup && !o~>groupMembers &&
    !o~>textDisplays && !o~>assocTextDisplays))
procedure(ltRoutingRead(cv)
  foreach(mapcar r cv~>routes
    list(ltRouteKey(r) foreach(mapcar o r~>objects ltRouteRef(o)) r~>routeStatus r~>net~>name lbProps(r)
      ltRouteRef(r~>startConn) ltRouteRef(r~>endConn) ltRouteRestrictions(r) r~>isContiguous
      when(r~>startConn || r~>endConn list(ltRouteEndpointData(r~>startConn) ltRouteEndpointData(r~>endConn))))))

procedure(ltStableRouteRefs(value)
  cond((stringp(value) !rexMatchp("^session:" value))
       (listp(value) forall(v value ltStableRouteRefs(v)))
       (t t)))
procedure(ltRoutingRequirePrepared(rows)
  let((seen)
    seen=makeTable('ltRouteUidSeen nil)
    foreach(row rows
      when(seen[car(row)] error("DUPLICATE_ROUTE_ID")) seen[car(row)]=t
      unless(ltStableRouteRefs(list(car(row) cadr(row) nth(5 row) nth(6 row) nth(7 row))) error("ROUTE_IDENTITY_NOT_PREPARED"))) t))

procedure(ltRelationshipReason(o @optional groupDelete)
  let((r restrictions)
    r=o~>route
    when(r
      restrictions=ltRouteRestrictions(r)
      when(groupDelete && ltGroupAllowsDelete(r~>figGroup o~>cellView)
        restrictions=foreach(mapcar index list(0 1 2 3 4 6 7 8) nth(index restrictions))))
    cond(
      (member(o~>objType list("rect" "polygon" "path" "pathSeg" "stdVia")) &&
        (o~>parent || o~>children) "native_parent_child_requires_adapter")
      ((r && member(r~>routeStatus list("fixed" "locked"))) "native_route_locked")
      (member(o~>objType list("stdVia" "pathSeg")) && member(o~>routeStatus list("fixed" "locked")) "native_route_locked")
      (o~>connRoutes "native_route_topology_requires_adapter")
      (r && (!member(o~>objType list("pathSeg" "stdVia")) || r~>routeStatus!="normal" ||
        r~>cellView!=o~>cellView || !member(o r~>objects) ||
        !ltRouteEndpointEditable(r~>startConn r~>cellView) || !ltRouteEndpointEditable(r~>endConn r~>cellView) ||
        exists(v restrictions v) ||
        exists(f r~>objects !member(f~>objType list("pathSeg" "stdVia"))))
        "native_route_topology_requires_adapter")
      (o~>figGroup && !ltGroupAllowsDelete(o~>figGroup o~>cellView) "native_relationship_requires_adapter")
      (o~>objType=="stdVia" && (o~>textDisplays || o~>assocTextDisplays ||
        (o~>figGroup && !groupDelete) || o~>groupMembers || o~>parent || o~>children) "native_relationship_requires_adapter"))))

procedure(ltCanDelete(o)
  o~>colayoutObjectId && member(o~>objType list("rect" "polygon" "path" "pathSeg" "stdVia")) &&
  !o~>colayoutStructureUid && !o~>pin && !o~>parent~>pin && !ltRelationshipReason(o t))

procedure(ltRouteExact(row)
  ; Field 8 alone is physical contiguity. Connection geometry remains exact.
  list(car(row) cadr(row) nth(2 row) nth(3 row) nth(4 row) nth(5 row) nth(6 row) nth(7 row) nth(9 row)))
procedure(ltRoutingVerify(before cv deleted)
  let((after expected row indexed)
    after=ltRoutingRead(cv)
    unless(length(before)==length(after) error("ROUTE_COLLECTION_CHANGED"))
    indexed=makeTable('ltRouteVerify nil)
    foreach(row after
      when(indexed[car(row)] error("DUPLICATE_ROUTE_ID")) indexed[car(row)]=row)
    foreach(old before
      expected=cons(car(old) cons(setof(uid cadr(old) !deleted[uid]) cddr(old)))
      row=indexed[car(old)]
      ; Contiguity is computed physical state. All other route data is exact.
      unless(row && equal(ltRouteExact(expected) ltRouteExact(row))
        error("ROUTE_RELATIONSHIP_CHANGED"))) t))

procedure(ltUpdateVia(o spec scale)
  let((key value replacement r members)
    when(o~>viaHeader~>viaDefName!=ltGet(spec "via_definition")
      replacement=ltCreate(o~>cellView o~>colayoutObjectId spec)
      dbCopyProp(o replacement)
      dbReplaceProp(replacement "colayoutNetIntent" "string" or(ltGet(spec "net_intent") ""))
      when(o~>net unless(dbAddFigToNet(replacement o~>net) error("NET_PRESERVE_FAILED")))
      foreach(field list("routeStatus" "direction" "topology" "isUnshielded" "shieldedNet1" "shieldedNet2")
        value=dbGet(o field)
        unless(equal(dbGet(replacement field) value) dbSet(replacement value field))
        unless(equal(dbGet(replacement field) value) error("VIA_ATTRIBUTE_PRESERVE_FAILED")))
      r=o~>route
      when(r
        members=foreach(mapcar member r~>objects if(member==o then replacement else member))
        ; IC618 route.objects setter accepts DB objects (verified on this
        ; installation); preserve all neighboring IDs and the original slot.
        r~>objects=members
        unless(equal(r~>objects members) && replacement~>route==r && !o~>route error("VIA_ROUTE_SLOT_FAILED")))
      unless(dbDeleteObject(o) error("VIA_REPLACEMENT_DELETE_FAILED"))
      o=replacement)
    ; Change the native via itself, not the shared master/header. OA creates
    ; the proper variant and retains route slot, identity and unedited fields.
    foreach(p ltViaInput(ltGet(spec "via_parameters") scale)
      key=car(p) value=cadr(p)
      unless(equal(dbGet(o key) value)
        dbSet(o value key)
        unless(equal(dbGet(o key) value) error("VIA_PARAMETER_UPDATE_FAILED"))))
    o~>origin=ltPoint(ltGet(spec "origin") scale) o~>orient=ltGet(spec "orientation")
    dbReplaceProp(o "colayoutNetIntent" "string" or(ltGet(spec "net_intent") "")) o))
