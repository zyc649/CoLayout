; Read-only display extraction. Never creates, flattens, edits, or saves OA figures.
; All transformations are performed by native dbConcatTransform/dbTransformPoint.

procedure(lbRN(x) sprintf(nil "%.17g" x*lbRScale))
procedure(lbRP(p tr)
  let((v) v=dbTransformPoint(p tr) list(lbRN(car(v)) lbRN(cadr(v)))))
procedure(lbRB(b tr)
  let((v) v=dbTransformBBox(b tr) list(list(lbRN(caar(v)) lbRN(cadar(v)))
    list(lbRN(caadr(v)) lbRN(cadadr(v))))))

procedure(lbRStyle(lpp)
  let((key lp packet name)
    key=strcat(car(lpp) "/" cadr(lpp))
    unless(lbRStyles[key]
      lp=techGetLP(lbRTech lpp)
      when(lp name=lp~>packet packet=drGetPacket("display" name))
      if(packet then
        lbRStyles[key]=list(lpp name lp~>priority leIsLayerVisible(lpp lbRTech) lp~>layer~>material packet
          drGetColor("display" nth(4 packet)) drGetColor("display" nth(5 packet))
          drGetStipple("display" nth(2 packet)) drGetLineStyle("display" nth(3 packet)))
      else
        lbRStyles[key]=list(lpp nil 0 t nil nil nil nil nil nil)))
    key))

procedure(lbRWalkCV(cv tr owner internal via occurrence depth)
  let((seen)
    when(depth>12 error("Display hierarchy limit exceeded"))
    unless(cv~>userUnits=="micron" error("Display master uses non-micron units"))
    seen=makeTable('lbRSeenCV nil)
    foreach(obj append(append(cv~>shapes cv~>instances) append(cv~>vias cv~>mosaics))
      unless(seen[obj]
        seen[obj]=t
        lbRVisit(obj tr if(owner then owner else lbId(obj)) internal via occurrence depth)))))

procedure(lbRVisit(obj tr owner internal via occurrence depth)
  let((kind key childTr geom mag orient)
    kind=obj~>objType
    key=strcat(occurrence "/" lbId(obj))
    unless(lbRSeen[key]
      lbRSeen[key]=t
      lbRCount=lbRCount+1
      when(lbRCount>100000 error("Display primitive budget exceeded"))
      cond(
        (kind=="inst"
          childTr=dbConcatTransform(obj~>transform tr)
          lbRWalkCV(obj~>master childTr owner t via key depth+1))
        (member(kind list("stdVia" "customVia"))
          if(obj~>viaHeader~>master then
            childTr=dbConcatTransform(list(obj~>origin obj~>orient 1.0) tr)
            lbRWalkCV(obj~>viaHeader~>master childTr owner internal key key depth+1)
          else
            lbRUnsupported=cons(list(key kind "via master unavailable") lbRUnsupported)))
        (t
          mag=if(caddr(tr) then caddr(tr) else 1.0)
          geom=cond(
            (kind=="rect" nil)
            (member(kind list("polygon" "line")) list(list("points" foreach(mapcar p obj~>points lbRP(p tr)))))
            (kind=="path" list(list("points" foreach(mapcar p obj~>points lbRP(p tr)))
              list("width" lbRN(obj~>width*mag)) list("style" obj~>pathStyle)
              list("begin_extension" lbRN(obj~>beginExt*mag)) list("end_extension" lbRN(obj~>endExt*mag))))
            (kind=="pathSeg" list(list("points" list(lbRP(obj~>beginPt tr) lbRP(obj~>endPt tr)))
              list("width" lbRN(obj~>width*mag)) list("begin_extension" lbRN(obj~>beginExt*mag))
              list("begin_style" obj~>beginStyle) list("end_style" obj~>endStyle)
              list("boundary" foreach(mapcar p obj~>boundary lbRP(p tr)))
              list("end_extension" lbRN(obj~>endExt*mag))))
            (member(kind list("label" "textDisplay"))
              orient=cadr(dbConcatTransform(list(list(0.0 0.0) obj~>orient 1.0) tr))
              list(list("text" if(kind=="label" then obj~>theLabel
                   else if(obj~>text=="name" then obj~>associate~>name else obj~>text)))
                list("visible" obj~>isVisible) list("xy" lbRP(obj~>xy tr))
                list("pin_label" if(obj~>pin || obj~>parent~>pin then t else nil))
                list("orientation" orient) list("height" lbRN(obj~>height*mag))
                list("justification" obj~>justify) list("font" obj~>font)))
            (kind=="ellipse" nil)
            (t lbRUnsupported=cons(list(key kind "bbox proxy only") lbRUnsupported)
              list(list("opaque_type" kind))))
          when(obj~>bBox && obj~>lpp
            lbRFigures=cons(list(key owner internal via kind lbRStyle(obj~>lpp)
              lbRB(obj~>bBox tr) geom) lbRFigures))
          ; Multipart path / ROD child figures may not be direct cell members.
          foreach(child obj~>children
            when(child~>isShape lbRVisit(child tr owner internal via occurrence depth))))))))

procedure(lbDisplay(lib cell)
  let((cv lbRScale lbRTech lbRStyles lbRSeen lbRFigures lbRUnsupported lbRCount start styles win)
    cv=lbView(lib cell)
    start=cv~>modifiedCounter
    lbRScale=cv~>DBUPerUU lbRTech=techGetTechFile(cv)
    lbRStyles=makeTable('lbRStyles nil) lbRSeen=makeTable('lbRSeen nil)
    lbRFigures=nil lbRUnsupported=nil lbRCount=0
    lbRWalkCV(cv list(list(0.0 0.0) "R0" 1.0) nil nil nil "root" 0)
    foreach(key lbRStyles styles=cons(list(key lbRStyles[key]) styles))
    foreach(w hiGetWindowList() when(geGetWindowCellView(w)==cv win=w))
    unless(equal(start cv~>modifiedCounter) error("Source changed during display extraction"))
    list("colayout-display-0.1" lbSession lbId(cv) sprintf(nil "%L" start)
      lbRB(cv~>bBox list(list(0.0 0.0) "R0" 1.0)) lbRFigures styles lbRUnsupported
      list(list("pin_names_visible" if(win then win~>displayPinNames else envGetVal("layout" "displayPinNames")))
        list("native_stop_level" if(win then win~>stopLevel else envGetVal("layout" "stopLevel")))))))
t
