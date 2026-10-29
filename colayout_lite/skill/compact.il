; Display-only abstraction. Root edits remain lbExportCV; hidden masters retain
; session-scoped version dependencies and are never flattened or saved here.
procedure(ltCChildren(cv) length(setof(i cv~>instances i~>objType=="inst"))+length(cv~>mosaics))
procedure(ltCCheckDeps(deps)
  foreach(dep deps
    let((cv) cv=lbObjects[car(dep)]
      unless(cv && dbIsId(cv) && cv~>libName==nth(1 dep) && cv~>cellName==nth(2 dep) && cv~>viewName==nth(3 dep)
        && sprintf(nil "%L" cv~>modifiedCounter)==nth(4 dep) error("MASTER_CHANGED_DURING_READ")))) t)
procedure(ltCDep(cv depth protected)
  let((row)
    when(depth>24 error("HIERARCHY_DEPTH_LIMIT"))
    when(cv && !ltCSeen[cv]
      ltCSeen[cv]=t
      row=list(lbId(cv) cv~>libName cv~>cellName cv~>viewName sprintf(nil "%L" cv~>modifiedCounter))
      ltCDeps=cons(row ltCDeps)
      when(protected ltCProtected=cons(row ltCProtected))
      when(length(ltCDeps)>10000 error("MASTER_DEPENDENCY_LIMIT_10000"))
      when(cv~>superMaster || cv~>isParamCell
        when(setof(s cv~>shapes s~>objType=="label" && s~>theLabel=="pcellEvalFailed") error("PCELL_EVALUATION_FAILED")))
      foreach(i cv~>instances ltCDep(i~>master depth+1 protected))
      foreach(m cv~>mosaics ltCDep(m~>master depth+1 protected))
      foreach(v cv~>vias when(v~>viaHeader~>master ltCDep(v~>viaHeader~>master depth+1 protected))))))

procedure(ltCNode(cv depth expand)
  let((key start scale rows children figures meta terms oldScale xy orient collapsed count)
    key=lbId(cv)
    when(depth>24 error("HIERARCHY_DEPTH_LIMIT"))
    unless(ltSeen[key]
      ltSeen[key]=t start=cv~>modifiedCounter scale=cv~>DBUPerUU count=ltCChildren(cv)
      unless(cv~>userUnits=="micron" error("UNSUPPORTED_USER_UNITS %L/%L/%L %L" cv~>libName cv~>cellName cv~>viewName cv~>userUnits))
      collapsed=depth>0 && count>0 && !expand
      when(!collapsed && lbRCount+length(cv~>shapes)>100000 error("Display primitive budget exceeded"))
      terms=foreach(mapcar tr cv~>terminals
        list(tr~>name tr~>direction tr~>net~>name
          foreach(mapcar pin tr~>pins foreach(mapcar fig pin~>figs lbObject(fig scale)))))
      oldScale=lbRScale lbRScale=scale lbRFigures=nil
      if(collapsed then
        foreach(tr cv~>terminals foreach(pin tr~>pins foreach(fig pin~>figs
          lbRVisit(fig list(list(0.0 0.0) "R0" 1.0) lbId(fig) nil nil key 0))))
      else
        ; This is a display graph, not another editable snapshot. Detailed
        ; shapes are already represented by display figures; only instance
        ; rows are needed for unresolved-master outlines. PCell failures are
        ; checked by ltCDep, with error labels retained for the client check.
        rows=foreach(mapcar o setof(o ltObjects(cv)
          member(o~>objType list("inst" "mosaic")) ||
          (o~>objType=="label" && o~>theLabel=="pcellEvalFailed")) lbObject(o scale))
        foreach(o cv~>shapes lbRVisit(o list(list(0.0 0.0) "R0" 1.0) lbId(o) nil nil key 0)))
      figures=lbRFigures lbRScale=oldScale
      unless(collapsed
        foreach(i setof(i cv~>instances i~>objType=="inst")
          if(i~>master then
            children=cons(list(lbId(i) lbId(i~>master) "inst" lbP(i~>xy scale) i~>orient sprintf(nil "%.17g" i~>mag)) children)
            ltCNode(i~>master depth+1 expand)
          else lbRUnsupported=cons(list(lbId(i) "inst" strcat("MASTER_UNRESOLVED " i~>libName "/" i~>cellName "/" i~>viewName)) lbRUnsupported)))
        foreach(v cv~>vias when(v~>viaHeader~>master
          children=cons(list(lbId(v) lbId(v~>viaHeader~>master) v~>objType lbP(v~>origin scale) v~>orient "1") children)
          ltCNode(v~>viaHeader~>master depth+1 expand)))
        foreach(m cv~>mosaics when(m~>mosaicType=="simple" && length(m~>tileArray)==1
          unless(m~>rows*m~>columns<=100000 error("ARRAY_OCCURRENCE_LIMIT"))
          orient=car(m~>tileArray) unless(stringp(orient) orient=sprintf(nil "%L" orient))
          for(r 0 m~>rows-1 for(c 0 m~>columns-1
            xy=dbTransformPoint(list(c*m~>uX r*m~>uY) list(m~>xy orient 1.0))
            children=cons(list(lbId(m) lbId(m~>master) "mosaic" lbP(xy scale) orient "1" list(r c)) children)))
          ltCNode(m~>master depth+1 expand))))
      unless(equal(start cv~>modifiedCounter) error("MASTER_CHANGED_DURING_READ"))
      ltNodes=cons(list(key cv~>libName cv~>cellName cv~>viewName lbN(scale 1) lbBounds(cv~>bBox scale)
        rows meta terms figures children list(list("child_count" count) list("collapsed" collapsed))) ltNodes))
    key))

procedure(ltCompactRead(lib cell)
  let((cv root snapshot tech ltSeen ltNodes ltCSeen ltCDeps ltCProtected lbRScale lbRTech lbRStyles lbRSeen lbRFigures lbRUnsupported lbRCount styles)
    cv=lbView(lib cell)
    when(length(cv~>shapes)>100000 error("Display primitive budget exceeded"))
    snapshot=lbExportCV(cv)
    ltCSeen=makeTable('ltCSeen nil) ltCSeen[cv]=t
    ltCDeps=list(list(lbId(cv) cv~>libName cv~>cellName cv~>viewName sprintf(nil "%L" cv~>modifiedCounter)))
    foreach(i cv~>instances ltCDep(i~>master 1 t))
    foreach(m cv~>mosaics ltCDep(m~>master 1 t))
    foreach(v cv~>vias when(v~>viaHeader~>master ltCDep(v~>viaHeader~>master 1 nil)))
    ltSeen=makeTable('ltCDisplaySeen nil) lbRScale=cv~>DBUPerUU lbRTech=techGetTechFile(cv)
    lbRStyles=makeTable('ltCStyles nil) lbRSeen=makeTable('ltCShapes nil) lbRCount=0
    root=ltCNode(cv 0 nil)
    foreach(lp lbRTech~>lps lbRStyle(list(lp~>name lp~>purpose)))
    foreach(key lbRStyles styles=cons(list(key lbRStyles[key]) styles))
    tech=ltTechnology(lib cell) ltCCheckDeps(ltCDeps)
    unless(nth(6 snapshot)==sprintf(nil "%L" cv~>modifiedCounter) error("SOURCE_CHANGED_DURING_READ"))
    list("colayout-lite-native-6" snapshot ltMeta(cv) ltCDeps tech
      list(root ltNodes styles lbRUnsupported ltCProtected) ltRoutingRead(cv) ltGroupsRead(cv) ltMppRead(cv))))

procedure(ltWriteCompact(lib cell token)
  let((path port data)
    unless(rexMatchp("^[a-zA-Z0-9_-]+$" token) error("INVALID_FILE_TOKEN"))
    data=ltCompactRead(lib cell)
    path=strcat(lbRoot "/.colayout-bridge/lite-compact-" token ".sexpr")
    port=outfile(path) unless(port error("EXPORT_FILE_FAILED"))
    fprintf(port "%L\n" data) close(port) list(path)))

procedure(ltWriteInstanceDisplay(lib cell uid token counter dependencies)
  let((cv obj root path port data ltSeen ltNodes lbRScale lbRTech lbRStyles lbRSeen lbRFigures lbRUnsupported lbRCount styles)
    cv=lbView(lib cell)
    ltCCheckDeps(dependencies)
    unless(counter==sprintf(nil "%L" cv~>modifiedCounter) error("SOURCE_CONFLICT"))
    obj=ltIndex(cv)[uid]
    unless(obj && member(obj~>objType list("inst" "mosaic")) error("EXPECTED_INSTANCE"))
    unless(obj~>master error("MASTER_UNRESOLVED"))
    ltSeen=makeTable('ltFullSeen nil) lbRScale=obj~>master~>DBUPerUU lbRTech=techGetTechFile(cv)
    lbRStyles=makeTable('ltFullStyles nil) lbRSeen=makeTable('ltFullShapes nil) lbRCount=0
    root=ltCNode(obj~>master 0 t)
    ltCCheckDeps(dependencies)
    foreach(key lbRStyles styles=cons(list(key lbRStyles[key]) styles))
    unless(counter==sprintf(nil "%L" cv~>modifiedCounter) error("SOURCE_CHANGED_DURING_READ"))
    data=list("colayout-instance-display-1" lbSession uid root ltNodes styles lbRUnsupported)
    unless(rexMatchp("^[a-zA-Z0-9_-]+$" token) error("INVALID_FILE_TOKEN"))
    path=strcat(lbRoot "/.colayout-bridge/lite-display-" token ".sexpr")
    port=outfile(path) unless(port error("EXPORT_FILE_FAILED"))
    fprintf(port "%L\n" data) close(port) list(path)))

procedure(ltRunDisplayRequest(lib cell token)
  let((request) request=ltRequests[token]
    unless(request error("REQUEST_PAYLOAD_MISSING"))
    unwindProtect(ltWriteInstanceDisplay(lib cell ltGet(request "uid") token ltGet(request "counter") ltGet(request "dependencies"))
      ltRequests[token]=nil)))
