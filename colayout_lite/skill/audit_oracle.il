; Verification only: direct OA observations independent of the production codec.
procedure(kaPoint(p)
  when(p list(sprintf(nil "%.17g" car(p)) sprintf(nil "%.17g" cadr(p)))))
procedure(kaBox(b) when(b foreach(mapcar p b kaPoint(p))))
procedure(kaRead(lib cell)
  let((cv seen out g typ)
    cv=dbFindOpenCellView(ddGetObj(lib) cell "layout")
    unless(cv cv=dbOpenCellViewByType(lib cell "layout" "maskLayout" "r"))
    unless(cv error("AUDIT_CELL_MISSING"))
    seen=makeTable('kaSeen nil)
    foreach(o append(append(cv~>instances cv~>shapes) append(cv~>vias cv~>mosaics))
      unless(seen[o]
        seen[o]=t typ=o~>objType
        g=cond(
          (typ=="inst" list(list("name" o~>name) list("master" list(o~>libName o~>cellName o~>viewName))
            list("xy" kaPoint(o~>xy)) list("orientation" o~>orient)
            list("parameters" foreach(mapcar p o~>master~>parameters~>value list(p~>name p~>valueType sprintf(nil "%L" p~>value))))))
          (member(typ list("path" "polygon")) list(list("points" foreach(mapcar p o~>points kaPoint(p)))
            list("width" when(typ=="path" sprintf(nil "%.17g" o~>width))) list("style" when(typ=="path" o~>pathStyle))))
          (typ=="pathSeg" list(list("points" list(kaPoint(o~>beginPt) kaPoint(o~>endPt)))
            list("width" sprintf(nil "%.17g" o~>width)) list("begin_style" o~>beginStyle) list("end_style" o~>endStyle)
            list("begin_extension" sprintf(nil "%.17g" o~>beginExt)) list("end_extension" sprintf(nil "%.17g" o~>endExt))))
          (typ=="stdVia" list(list("origin" kaPoint(o~>origin)) list("orientation" o~>orient)
            list("definition" o~>viaHeader~>viaDefName) list("overrides" o~>viaHeader~>overrideParams)))
          (t nil))
        out=cons(list(o~>colayoutObjectId typ o~>lpp kaBox(o~>bBox) g
          foreach(mapcar p o~>prop list(p~>name p~>valueType sprintf(nil "%L" p~>value)))) out)))
    list(sprintf(nil "%.0f" cv~>DBUPerUU) out)))
