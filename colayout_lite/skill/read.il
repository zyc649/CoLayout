; Reused read-only DBU codec from Colayout; private namespace.
; Colayout MVP. No production-cell mutation; writes restricted to cells cloned here.
; Verified against installed IC618 skdfref/sktechfile docs.
unless(boundp('lbSession) lbSession=nil)
unless(boundp('lbIds) lbIds=makeTable('lbIds nil))
unless(boundp('lbObjects) lbObjects=makeTable('lbObjects nil))
unless(boundp('lbViews) lbViews=makeTable('lbViews nil))
unless(boundp('lbAllowed) lbAllowed=makeTable('lbAllowed nil))
unless(boundp('lbReceipts) lbReceipts=makeTable('lbReceipts nil))
unless(boundp('lbNextId) lbNextId=0)

procedure(lbInit(session root)
  unless(lbSession lbSession=session lbRoot=root)
  unless(equal(root lbRoot) error("Colayout root mismatch"))
  ; New process projects do not yet have the exchange directory. Create only
  ; this application-owned directory after the existing root identity check.
  unless(isDir(strcat(lbRoot "/.colayout-bridge"))
    createDir(strcat(lbRoot "/.colayout-bridge")))
  lbSession)

procedure(lbId(obj)
  when(obj
    unless(lbIds[obj]
      lbNextId=lbNextId+1
      lbIds[obj]=strcat(lbSession ":" sprintf(nil "%d" lbNextId))
      lbObjects[lbIds[obj]]=obj)
    lbIds[obj]))

procedure(lbN(value scale)
  let((n text)
    n=value*scale*1.0
    unless(abs(n)<=2147483647.0 error("DBU range exceeded"))
    text=sprintf(nil "%.0f" n)
    unless(abs(n-atof(text))<0.00001 error("Non-integral DBU coordinate: %.17g" n))
    text))
procedure(lbP(p scale) when(p list(lbN(car(p) scale) lbN(cadr(p) scale))))
procedure(lbBox(b scale) when(b list(lbP(car(b) scale) lbP(cadr(b) scale))))
procedure(lbBounds(b scale)
  when(b foreach(mapcar p b foreach(mapcar v p sprintf(nil "%.17g" v*scale)))))
procedure(lbVal(v)
  cond((null(v) nil)
       (numberp(v) list("number" sprintf(nil "%.17g" v*1.0)))
       (stringp(v) list("string" v))
       (listp(v) cons("list" foreach(mapcar x v lbVal(x))))
       (t list("opaque" sprintf(nil "%L" v)))))
procedure(lbProps(obj)
  foreach(mapcar p obj~>prop list(p~>name p~>valueType lbVal(p~>value))))

procedure(lbPathSegCustom(obj scale begin)
  let((values offset)
    when(if(begin then obj~>beginStyle=="custom" else obj~>endStyle=="custom")
      values=nth(2 nth(3 dbGetPathSegStyle(obj))) offset=if(begin then 0 else 3)
      unless(length(values)==6 error("MISSING_CUSTOM_PATHSEG_STYLE"))
      list(lbN(nth(offset values) scale) lbN(nth(offset+1 values) scale) lbN(nth(offset+2 values) scale)))))

procedure(lbObject(obj scale)
  let((g typ)
    typ=obj~>objType
    g=cond(
      (typ=="inst"
        list(list("name" obj~>name) list("master" list(obj~>libName obj~>cellName obj~>viewName))
             list("xy" lbP(obj~>xy scale)) list("orientation" obj~>orient)
             list("magnification" sprintf(nil "%.17g" obj~>mag))
             list("master_bbox" lbBounds(obj~>master~>bBox scale))
             list("master_counter" sprintf(nil "%L" obj~>master~>modifiedCounter))
             list("parameters" foreach(mapcar p obj~>master~>parameters~>value
                list(p~>name p~>valueType lbVal(p~>value))))
             list("connections" foreach(mapcar it obj~>instTerms list(it~>name it~>net~>name)))))
      (typ=="mosaic" list(list("name" obj~>name) list("master" list(obj~>libName obj~>cellName obj~>viewName))
        list("xy" lbP(obj~>xy scale)) list("rows" obj~>rows) list("columns" obj~>columns)
        list("pitch" list(lbN(obj~>uX scale) lbN(obj~>uY scale))) list("tile_array" obj~>tileArray)
        list("mosaic_type" obj~>mosaicType)))
      (typ=="rect" nil)
      (typ=="polygon" list(list("points" foreach(mapcar p obj~>points lbP(p scale)))))
      (typ=="path" list(list("points" foreach(mapcar p obj~>points lbP(p scale)))
          list("width" lbN(obj~>width scale)) list("style" obj~>pathStyle)
          list("begin_extension" lbN(obj~>beginExt scale)) list("end_extension" lbN(obj~>endExt scale))))
      (typ=="pathSeg" list(list("begin" lbP(obj~>beginPt scale)) list("end" lbP(obj~>endPt scale))
          list("begin_custom" lbPathSegCustom(obj scale t)) list("end_custom" lbPathSegCustom(obj scale nil))
          list("width" lbN(obj~>width scale)) list("begin_extension" lbN(obj~>beginExt scale))
          list("boundary" foreach(mapcar p obj~>boundary lbP(p scale)))
          list("end_extension" lbN(obj~>endExt scale))))
      (typ=="label" list(list("text" obj~>theLabel) list("xy" lbP(obj~>xy scale))
          list("orientation" obj~>orient) list("height" lbN(obj~>height scale))
          list("justification" obj~>justify) list("font" obj~>font)))
      (member(typ list("stdVia" "customVia"))
        list(list("origin" lbP(obj~>origin scale)) list("orientation" obj~>orient)
          list("definition" obj~>viaHeader~>viaDefName)
          list("override_parameters" lbVal(obj~>viaHeader~>overrideParams))))
      (t list(list("opaque_type" typ))))
    list(lbId(obj) typ if(typ=="rect" then lbBox(obj~>bBox scale) else lbBounds(obj~>bBox scale))
         when(obj~>isShape obj~>lpp) obj~>net~>name lbProps(obj) g)))

procedure(lbCheckPath(lib)
  let((p)
    p=dbFullLibPath(lib)
    unless(p && substring(p 1 strlen(lbRoot)+1)==strcat(lbRoot "/")
      error("Library is outside Colayout experimental project"))
    p))

procedure(lbView(lib cell)
  let((key cv)
    lbCheckPath(lib)
    key=strcat(lib "/" cell)
    cv=lbViews[key]
    ; OA can recycle a purged database handle for a different cellview.
    when(cv && (!dbIsId(cv) || cv~>libName!=lib || cv~>cellName!=cell || cv~>viewName!="layout")
      cv=nil lbViews[key]=nil)
    unless(cv
      cv=dbFindOpenCellView(ddGetObj(lib) cell "layout")
      unless(cv cv=dbOpenCellViewByType(lib cell "layout" "maskLayout" "r"))
      unless(cv error("Cell does not exist"))
      lbViews[key]=cv)
    cv))

procedure(lbExportCV(cv)
  let((scale grid start out objs terms nets seen)
    start=cv~>modifiedCounter
    scale=cv~>DBUPerUU
    unless(cv~>userUnits=="micron" error("MVP requires micron user units"))
    grid=techGetMfgGridResolution(techGetTechFile(cv))
    seen=makeTable('lbSeen nil)
    objs=nil
    foreach(obj append(append(cv~>instances cv~>shapes) append(cv~>vias cv~>mosaics))
      unless(seen[obj] objs=cons(lbObject(obj scale) objs) seen[obj]=t))
    terms=foreach(mapcar tr cv~>terminals
      list(tr~>name tr~>direction tr~>net~>name
        foreach(mapcar pin tr~>pins list(lbId(pin) pin~>name pin~>accessDir
          foreach(mapcar fig pin~>figs lbId(fig))))))
    nets=foreach(mapcar net cv~>nets list(net~>name lbProps(net)))
    out=list(lbSession lbId(cv) lbRoot dbFullLibPath(cv~>libName) cv~>libName cv~>cellName
      sprintf(nil "%L" start) cv~>modifiedButNotSaved cv~>fileTimeStamp
      lbN(scale 1) when(grid lbN(grid scale)) objs terms nets
      list(length(cv~>mosaics) length(cv~>figGroups) length(cv~>routes)
           length(cv~>blockages) length(cv~>groups)))
    unless(equal(start cv~>modifiedCounter) error("Source changed during export"))
    out))

procedure(lbExport(lib cell) lbExportCV(lbView(lib cell)))
