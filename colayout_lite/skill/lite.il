; Layout-only protocol. No schematic, Binder, CDF editing or XL extraction.
unless(boundp('ltRequests) ltRequests=makeTable('ltRequests nil))
procedure(ltRunRequest(lib cell token)
  unless(ltRequests[token] error("REQUEST_PAYLOAD_MISSING"))
  unwindProtect(ltTransaction(lib cell ltRequests[token]) ltRequests[token]=nil))
procedure(ltGet(data key) cadr(assoc(key data)))
procedure(ltInit(session root)
  lbInit(session root)
  t)

procedure(ltWritable(lib cell)
  ; Direct editing is authorized for the configured project. lbView still
  ; enforces its library path boundary, so shared PDK/other projects stay out.
  lbView(lib cell))

procedure(ltObjects(cv)
  let((seen out)
    seen=makeTable('ltObjectSeen nil)
    foreach(o append(append(cv~>instances cv~>shapes) append(cv~>vias cv~>mosaics))
      unless(seen[o] seen[o]=t out=cons(o out))) out))

procedure(ltPersistVerified(lib cell counter)
  let((cv)
    cv=ltWritable(lib cell)
    unless(counter==sprintf(nil "%L" cv~>modifiedCounter) error("SOURCE_CONFLICT_BEFORE_VERIFIED_SAVE"))
    unless(dbSave(cv) error("SAVE_FAILED")) t))

procedure(ltIndex(cv)
  let((idx uid)
    idx=makeTable('ltIndex nil)
    foreach(o ltObjects(cv)
      uid=o~>colayoutObjectId
      when(uid when(idx[uid] error("DUPLICATE_UID")) idx[uid]=o)) idx))

procedure(ltMark(cv seed)
  let((n rod group child)
    n=0
    foreach(o ltObjects(cv)
      n=n+1
      unless(o~>colayoutObjectId dbReplaceProp(o "colayoutObjectId" "string" strcat(seed ":" sprintf(nil "%d" n))))
      when(member(o~>objType list("rect" "path" "pathSeg" "polygon" "stdVia")) && !o~>colayoutNetIntent
        dbReplaceProp(o "colayoutNetIntent" "string" or(o~>net~>name ""))))
    foreach(o cv~>shapes
      rod=rodGetObj(o)
      when(rod && rod~>subShapes
        group=or(o~>colayoutStructureUid strcat("native:" o~>colayoutObjectId))
        foreach(child cons(o rod~>subShapes)
          when(dbIsId(child) && child~>cellView==cv
            dbReplaceProp(child "colayoutStructureUid" "string" group)))))
    ltRoutingPrepare(cv seed)
    ltGroupsPrepare(cv seed)
    ltIndex(cv) t))

procedure(ltClone(lib source target seed)
  let((src dst)
    lbCheckPath(lib)
    unless(strlen(target)>=18 && substring(target 1 18)=="COLAYOUT_MVP_LITE_" error("LITE_PREFIX_REQUIRED"))
    when(ddGetObj(lib target) error("DESTINATION_EXISTS"))
    src=lbView(lib source)
    dst=dbCopyCellView(src lib target "layout" nil nil nil)
    unless(dst && dbReopen(dst "a") error("COPY_FAILED"))
    dbReplaceProp(dst "colayoutLiteSource" "string" strcat(lib "/" source))
    ltMark(dst seed)
    unless(dbSave(dst) error("COPY_SAVE_FAILED"))
    lbViews[strcat(lib "/" target)]=dst
    list("copied" target)))

procedure(ltPrepare(lib cell seed)
  let((cv dirty)
    cv=ltWritable(lib cell) dirty=cv~>modifiedButNotSaved
    unless(dbReopen(cv "a") error("PREPARE_REOPEN_FAILED"))
    ltMark(cv seed)
    unless(dirty unless(dbSave(cv) error("PREPARE_SAVE_FAILED")))
    list(t)))

procedure(ltViaValue(name value scale)
  cond((member(name list("cutRows" "cutColumns")) value)
       (numberp(value) lbN(value scale))
       (listp(value) foreach(mapcar v value when(v lbN(v scale))))
       (t value)))

procedure(ltViaDefaults(vd scale)
  let((names out n v)
    names=list("cutLayer" "cutWidth" "cutHeight" "cutRows" "cutColumns" "cutSpacing"
      "layer1Enc" "layer2Enc" "layer1Offset" "layer2Offset" "originOffset" "imp1Enc" "imp2Enc" "cutPattern")
    n=0
    foreach(name names
      v=nth(n vd~>params)
      when(v out=append(out list(list(name ltViaValue(name v scale))))) n=n+1)
    out))

procedure(ltViaOverrides(o scale)
  foreach(mapcar p o~>viaHeader~>overrideParams list(car(p) ltViaValue(car(p) cadr(p) scale))))

; Route metadata and eligibility are defined in routing.il.
procedure(ltMeta(cv)
  foreach(mapcar o ltObjects(cv)
    list(lbId(o) o~>colayoutObjectId o~>colayoutStructureUid
      if(o~>pin || o~>parent~>pin then t else nil)
      cond((member(o~>objType list("inst" "mosaic")) lbId(o~>master))
           (member(o~>objType list("stdVia" "customVia")) lbId(o~>viaHeader~>master)))
      when(o~>objType=="pathSeg" list(o~>beginStyle o~>endStyle))
      when(o~>objType=="stdVia" ltViaOverrides(o cv~>DBUPerUU))
      ltRelationshipReason(o)
      when(o~>objType=="textDisplay" && o~>owner && o~>owner~>objType=="inst"
        o~>owner~>colayoutObjectId)
      ltRouteKey(o~>route) ltCanDelete(o)
      when(member(o~>objType list("rect" "polygon" "path" "pathSeg" "stdVia")) && (o~>parent || o~>children)
        list(list("parent" ltRouteRef(o~>parent)) list("children" foreach(mapcar child o~>children ltRouteRef(child))))))))

procedure(ltTechnology(lib cell)
  let((cv tf scale seen templates viaRows candidateTech)
    cv=lbView(lib cell) tf=techGetTechFile(cv) scale=cv~>DBUPerUU
    seen=makeTable('ltTechSeen nil)
    foreach(techLib append(cons(tf~>libName cv~>instances~>libName)
                          append(when(boundp('ltNodes) foreach(mapcar node ltNodes cadr(node)))
                                 when(boundp('ltCDeps) foreach(mapcar dep ltCDeps cadr(dep)))))
      unless(seen[techLib]
        seen[techLib]=t
        candidateTech=when(techLib && ddGetObj(techLib) techGetTechFile(ddGetObj(techLib)))
        when(candidateTech foreach(name techGetMPPTemplateNames(candidateTech)
          templates=cons(list(techLib name sprintf(nil "%L" techGetMPPTemplateByName(candidateTech name))) templates)))))
    viaRows=foreach(mapcar vd tf~>viaDefs
      list(vd~>name vd~>objType vd~>layer1~>name vd~>layer2~>name
        vd~>implant1~>name vd~>implant2~>name
        when(vd~>objType=="stdViaDef" ltViaDefaults(vd scale))))
    list(tf~>libName lbN(scale 1) lbN(techGetMfgGridResolution(tf) scale)
      foreach(mapcar lp tf~>lps list(lp~>name lp~>purpose lp~>layer~>material))
      viaRows templates)))

; Each actual master is exported once in local coordinates. No flatten or save.
procedure(ltWalk(cv depth)
  let((key start scale rows children figures meta terms oldScale xy orient)
    key=lbId(cv)
    when(depth>24 error("HIERARCHY_DEPTH_LIMIT"))
    unless(ltSeen[key]
      ltSeen[key]=t start=cv~>modifiedCounter scale=cv~>DBUPerUU
      unless(cv~>userUnits=="micron" error("UNSUPPORTED_USER_UNITS"))
      ltDeps=cons(list(key cv~>libName cv~>cellName cv~>viewName sprintf(nil "%L" start)) ltDeps)
      rows=foreach(mapcar o ltObjects(cv) lbObject(o scale)) meta=ltMeta(cv)
      oldScale=lbRScale lbRScale=scale lbRFigures=nil
      foreach(o cv~>shapes
        lbRVisit(o list(list(0.0 0.0) "R0" 1.0) lbId(o) nil nil key 0))
      figures=lbRFigures lbRScale=oldScale
      terms=foreach(mapcar tr cv~>terminals
        list(tr~>name tr~>direction tr~>net~>name
          foreach(mapcar pin tr~>pins foreach(mapcar fig pin~>figs lbObject(fig scale)))))
      foreach(i setof(i cv~>instances i~>objType=="inst")
        children=cons(list(lbId(i) lbId(i~>master) "inst" lbP(i~>xy scale) i~>orient sprintf(nil "%.17g" i~>mag)) children)
        ltWalk(i~>master depth+1))
      foreach(v cv~>vias
        when(v~>viaHeader~>master
          children=cons(list(lbId(v) lbId(v~>viaHeader~>master) v~>objType lbP(v~>origin scale) v~>orient "1") children)
          ltWalk(v~>viaHeader~>master depth+1)))
      foreach(m cv~>mosaics
        when(m~>mosaicType=="simple" && length(m~>tileArray)==1
          unless(m~>rows*m~>columns<=100000 error("ARRAY_OCCURRENCE_LIMIT"))
          orient=car(m~>tileArray)
          unless(stringp(orient) orient=sprintf(nil "%L" orient))
          for(r 0 m~>rows-1 for(c 0 m~>columns-1
            xy=dbTransformPoint(list(c*m~>uX r*m~>uY) list(m~>xy orient 1.0))
            children=cons(list(lbId(m) lbId(m~>master) "mosaic" lbP(xy scale) orient "1" list(r c)) children)))
          ltWalk(m~>master depth+1)))
      unless(equal(start cv~>modifiedCounter) error("MASTER_CHANGED_DURING_READ"))
      ltNodes=cons(list(key cv~>libName cv~>cellName cv~>viewName lbN(scale 1) lbBounds(cv~>bBox scale)
        rows meta terms figures children) ltNodes))
    key))

procedure(ltRead(lib cell)
  let((cv root ltSeen ltNodes ltDeps lbRScale lbRTech lbRStyles lbRSeen lbRFigures lbRUnsupported lbRCount styles snapshot)
    cv=lbView(lib cell) snapshot=lbExportCV(cv)
    ltSeen=makeTable('ltSeen nil) lbRScale=cv~>DBUPerUU lbRTech=techGetTechFile(cv)
    lbRStyles=makeTable('ltStyles nil) lbRSeen=makeTable('ltShapes nil) lbRCount=0
    root=ltWalk(cv 0)
    ; Export styles for unused LPPs too: local drawing must not require a sync
    ; before the first shape on a new routing layer becomes visible.
    foreach(lp lbRTech~>lps lbRStyle(list(lp~>name lp~>purpose)))
    foreach(key lbRStyles styles=cons(list(key lbRStyles[key]) styles))
    unless(nth(6 snapshot)==sprintf(nil "%L" cv~>modifiedCounter) error("SOURCE_CHANGED_DURING_READ"))
    list("colayout-lite-native-1" snapshot ltMeta(cv) ltDeps ltTechnology(lib cell)
      list(root ltNodes styles lbRUnsupported) ltRoutingRead(cv))))

procedure(ltWriteRead(lib cell token)
  let((path port data)
    unless(rexMatchp("^[a-zA-Z0-9_-]+$" token) error("INVALID_FILE_TOKEN"))
    data=ltRead(lib cell)
    path=strcat(lbRoot "/.colayout-bridge/lite-read-" token ".sexpr")
    port=outfile(path) unless(port error("EXPORT_FILE_FAILED"))
    fprintf(port "%L\n" data) close(port) list(path)))

procedure(ltKeys(data allowed)
  foreach(p data
    unless(listp(p) && length(p)==2 && member(car(p) allowed) error("UNKNOWN_PROTOCOL_FIELD"))) t)

procedure(ltNumber(s)
  let((v)
    unless(stringp(s) error("DBU_MUST_BE_DECIMAL_STRING"))
    v=atof(s)
    unless(abs(v)<=2147483647.0 && equal(sprintf(nil "%.0f" v) s) error("INVALID_INTEGER_DBU")) v))
procedure(ltPoint(p scale)
  unless(listp(p) && length(p)==2 error("INVALID_POINT"))
  list(ltNumber(car(p))/scale ltNumber(cadr(p))/scale))

procedure(ltCheckSpec(cv spec)
  let((kind pts width previous dx dy lpp bb)
    ltKeys(spec list("kind" "lpp" "bbox" "points" "width" "style" "begin_style" "end_style"
      "begin_extension" "end_extension" "begin_custom" "end_custom" "origin" "orientation" "via_definition" "via_parameters" "net_intent"))
    kind=ltGet(spec "kind")
    unless(member(kind list("rect" "polygon" "path" "pathSeg" "stdVia")) error("UNSUPPORTED_SHAPE"))
    case(kind
      ("rect" ltKeys(spec list("kind" "lpp" "bbox" "net_intent")))
      ("polygon" ltKeys(spec list("kind" "lpp" "points" "net_intent")))
      ("path" ltKeys(spec append(list("kind" "lpp" "points" "width" "style" "net_intent")
        when(ltGet(spec "style")=="varExtendExtend" list("begin_extension" "end_extension")))))
      ("pathSeg" ltKeys(spec list("kind" "lpp" "points" "width" "begin_style" "end_style" "begin_extension" "end_extension" "begin_custom" "end_custom" "net_intent")))
      ("stdVia" ltKeys(spec list("kind" "origin" "orientation" "via_definition" "via_parameters" "net_intent"))))
    unless(null(ltGet(spec "net_intent")) || stringp(ltGet(spec "net_intent")) error("INVALID_NET_INTENT"))
    if(kind=="stdVia" then
      ltPoint(ltGet(spec "origin") cv~>DBUPerUU)
      unless(member(ltGet(spec "orientation") list("R0" "R90" "R180" "R270" "MX" "MY" "MXR90" "MYR90")) error("INVALID_ORIENTATION"))
      unless(techFindViaDefByName(techGetTechFile(cv) ltGet(spec "via_definition")) error("UNKNOWN_VIA"))
    else
      lpp=ltGet(spec "lpp")
      unless(listp(lpp) && length(lpp)==2 && techGetLP(techGetTechFile(cv) lpp) error("UNKNOWN_LPP"))
      when(boundp('ltWritableLayers) && !member(lpp ltWritableLayers) error("LAYER_NOT_WRITABLE"))
      when(kind=="rect"
        bb=ltGet(spec "bbox") unless(length(bb)==2 error("INVALID_RECTANGLE"))
        foreach(p bb ltPoint(p cv~>DBUPerUU))
        unless(ltNumber(caar(bb))<ltNumber(caadr(bb)) && ltNumber(cadar(bb))<ltNumber(cadadr(bb)) error("INVALID_RECTANGLE")))
      when(member(kind list("polygon" "path" "pathSeg"))
        pts=ltGet(spec "points")
        unless(length(pts)>=if(kind=="polygon" then 3 else 2) error("INVALID_VERTICES"))
        when(kind=="pathSeg" && length(pts)!=2 error("INVALID_PATHSEG"))
        foreach(p pts ltPoint(p cv~>DBUPerUU))
        when(kind!="polygon"
          width=ltNumber(ltGet(spec "width"))
          unless(width>0 && mod(fix(width) 2)==0 error("INVALID_PATH_WIDTH"))
          foreach(p pts
            when(previous
              dx=abs(ltNumber(car(p))-ltNumber(car(previous))) dy=abs(ltNumber(cadr(p))-ltNumber(cadr(previous)))
              unless((dx>0 || dy>0) && (dx==0 || dy==0 || dx==dy) error("INVALID_PATH_ANGLE"))) previous=p)
          if(kind=="path" then
            unless(member(ltGet(spec "style") list("truncateExtend" "extendExtend" "roundRound" "varExtendExtend")) error("INVALID_PATH_STYLE"))
            when(ltGet(spec "style")=="varExtendExtend"
              foreach(k list("begin_extension" "end_extension") unless(ltNumber(ltGet(spec k))>=0 error("INVALID_EXTENSION"))))
          else
            foreach(k list("begin_style" "end_style") unless(member(ltGet(spec k) list("truncate" "extend" "variable" "chamfer" "custom")) error("UNSUPPORTED_END_STYLE")))
            ltCheckPathSegCaps(spec width)
            foreach(k list("begin_extension" "end_extension") unless(ltNumber(ltGet(spec k))>=0 error("INVALID_EXTENSION")))))))
    t))

procedure(ltCheckPathSegCaps(spec width)
  let((caps cap style ext beginCap endCap left right pts factor dl dr)
    beginCap=ltGet(spec "begin_custom") endCap=ltGet(spec "end_custom")
    foreach(side list("begin" "end")
      style=ltGet(spec strcat(side "_style")) cap=ltGet(spec strcat(side "_custom"))
      ext=ltNumber(ltGet(spec strcat(side "_extension")))
      unless(member(style list("variable" "custom")) when(ext!=0 error("INACTIVE_EXTENSION")))
      if(style=="custom" then
        unless(listp(cap) && length(cap)==3 error("INVALID_CUSTOM_END"))
        foreach(v cap unless(ltNumber(v)>=0 error("INVALID_CUSTOM_END")))
        unless(ltNumber(nth(2 cap))>0 error("INVALID_CUSTOM_HALF_WIDTH"))
        caps=cons(ltNumber(nth(2 cap)) caps)
      else when(cap error("INACTIVE_CUSTOM_END"))))
    when(caps unless(width==if(length(caps)==2 then car(caps)+cadr(caps) else 2*car(caps)) error("CUSTOM_WIDTH_MISMATCH")))
    left=if(beginCap then ltNumber(nth(2 beginCap)) else if(endCap then ltNumber(nth(2 endCap)) else width/2))
    right=if(endCap then ltNumber(nth(2 endCap)) else left)
    pts=ltGet(spec "points") factor=if(caar(pts)!=caadr(pts) && cadar(pts)!=cadadr(pts) then 2 else 1)
    foreach(side list("begin" "end")
      cap=ltGet(spec strcat(side "_custom"))
      when(cap
        ext=ltNumber(ltGet(spec strcat(side "_extension")))
        dl=factor*ltNumber(car(cap)) dr=factor*ltNumber(cadr(cap))
        unless(2*ext<=dl+dr &&
          dl<=ext+if(side=="begin" then right else left) &&
          dr<=ext+if(side=="begin" then left else right) error("INVALID_CUSTOM_CAP")))) t))

procedure(ltPathSegEnds(spec scale)
  let((ext caps)
    ext=list(ltNumber(ltGet(spec "begin_extension"))/scale ltNumber(ltGet(spec "end_extension"))/scale)
    when(ltGet(spec "begin_style")=="custom" || ltGet(spec "end_style")=="custom"
      foreach(side list("begin" "end")
        caps=append(caps if(ltGet(spec strcat(side "_style"))=="custom" then
          foreach(mapcar v ltGet(spec strcat(side "_custom")) ltNumber(v)/scale)
        else list(0.0 0.0 0.0))))
      ext=append(ext list(caps))) ext))

procedure(ltViaInput(params scale)
  foreach(mapcar p params
    unless(member(car(p) list("cutRows" "cutColumns" "cutWidth" "cutHeight" "cutSpacing"
      "layer1Enc" "layer2Enc" "layer1Offset" "layer2Offset" "originOffset" "imp1Enc" "imp2Enc")) error("UNSUPPORTED_VIA_PARAMETER"))
    list(car(p)
      cond((member(car(p) list("cutRows" "cutColumns"))
            unless(integerp(cadr(p)) && cadr(p)>=1 && cadr(p)<=64 error("INVALID_VIA_COUNT")) cadr(p))
           (member(car(p) list("cutWidth" "cutHeight")) ltNumber(cadr(p))/scale)
           (t ltPoint(cadr(p) scale))))))

procedure(ltCreate(cv uid spec)
  let((o s vd net pts)
    s=cv~>DBUPerUU ltCheckSpec(cv spec)
    pts=foreach(mapcar p ltGet(spec "points") ltPoint(p s))
    case(ltGet(spec "kind")
      ("rect" o=dbCreateRect(cv ltGet(spec "lpp") foreach(mapcar p ltGet(spec "bbox") ltPoint(p s))))
      ("polygon" o=dbCreatePolygon(cv ltGet(spec "lpp") pts))
      ("path" o=dbCreatePath(cv ltGet(spec "lpp") pts ltNumber(ltGet(spec "width"))/s ltGet(spec "style"))
        when(o && ltGet(spec "style")=="varExtendExtend"
          o~>beginExt=ltNumber(ltGet(spec "begin_extension"))/s o~>endExt=ltNumber(ltGet(spec "end_extension"))/s))
      ("pathSeg" o=dbCreatePathSeg(cv ltGet(spec "lpp") car(pts) cadr(pts) ltNumber(ltGet(spec "width"))/s
        ltGet(spec "begin_style") ltGet(spec "end_style")
        ltPathSegEnds(spec s)))
      ("stdVia"
        vd=techFindViaDefByName(techGetTechFile(cv) ltGet(spec "via_definition"))
        unless(vd~>objType=="stdViaDef" error("CUSTOM_VIA_READ_ONLY"))
        o=dbCreateVia(cv vd ltPoint(ltGet(spec "origin") s) ltGet(spec "orientation") ltViaInput(ltGet(spec "via_parameters") s))))
    unless(o error("CREATE_FAILED"))
    dbReplaceProp(o "colayoutObjectId" "string" uid)
    dbReplaceProp(o "colayoutNetIntent" "string" or(ltGet(spec "net_intent") ""))
    o))

procedure(ltUpdateShape(o spec scale)
  ; Keep the native figure and all its unedited attributes/associations.
  case(o~>objType
    ("rect" o~>bBox=foreach(mapcar p ltGet(spec "bbox") ltPoint(p scale)))
    ("polygon" o~>points=foreach(mapcar p ltGet(spec "points") ltPoint(p scale)))
    ("path" o~>points=foreach(mapcar p ltGet(spec "points") ltPoint(p scale))
      o~>width=ltNumber(ltGet(spec "width"))/scale o~>pathStyle=ltGet(spec "style")
      when(ltGet(spec "style")=="varExtendExtend"
        o~>beginExt=ltNumber(ltGet(spec "begin_extension"))/scale o~>endExt=ltNumber(ltGet(spec "end_extension"))/scale))
    ("pathSeg"
      ; Setting endpoints separately can create an illegal intermediate angle;
      ; OA then warns and leaves the old coordinates. Set both atomically.
      unless(dbSetPathSegPoints(o ltPoint(car(ltGet(spec "points")) scale) ltPoint(cadr(ltGet(spec "points")) scale))
        error("PATHSEG_POINTS_UPDATE_FAILED"))
      unless(dbSetPathSegStyle(o ltNumber(ltGet(spec "width"))/scale
        ltGet(spec "begin_style") ltGet(spec "end_style")
        ltPathSegEnds(spec scale))
        error("PATHSEG_STYLE_UPDATE_FAILED")))
    (t error("UPDATE_KIND_UNSUPPORTED")))
  o~>lpp=ltGet(spec "lpp")
  dbReplaceProp(o "colayoutNetIntent" "string" or(ltGet(spec "net_intent") "")) t)

procedure(ltGuard(cv spec uid)
  when(ltGet(spec "rings") error("LEGACY_COMPOSITE_GENERATION_REMOVED"))
  if(ltGet(spec "version")=="mpp-generation-2" then ltGuardRecipe(cv spec uid) else ltGuardTemplate(cv spec uid)))
procedure(ltGuardTemplate(cv spec uid)
  let((tf def master offsets enclosures cuts args rod n closed points)
    ltKeys(spec list("technology_library" "template" "points" "net_intent" "definition"))
    tf=techGetTechFile(ddGetObj(ltGet(spec "technology_library")))
    def=techGetMPPTemplateByName(tf ltGet(spec "template"))
    unless(def && equal(sprintf(nil "%L" def) ltGet(spec "definition")) error("GUARD_TEMPLATE_CHANGED"))
    master=car(def) when(nth(8 master) error("UNSUPPORTED_GUARD_TEMPLATE"))
    points=ltGet(spec "points") closed=equal(car(points) nth(length(points)-1 points))
    offsets=foreach(mapcar row cadr(def)
      when(nth(7 row) error("UNSUPPORTED_GUARD_TEMPLATE"))
      append(if(closed then append(ltTemplateArgs(row '(?layer ?width ?choppable ?sep ?justification)) list(?beginOffset 0.0 ?endOffset 0.0))
        else ltTemplateArgs(row '(?layer ?width ?choppable ?sep ?justification ?beginOffset ?endOffset))) list(?netName ltGet(spec "net_intent"))))
    enclosures=foreach(mapcar row caddr(def)
      when(nth(5 row) error("UNSUPPORTED_GUARD_TEMPLATE"))
      append(if(closed then append(ltTemplateArgs(row '(?layer ?enclosure ?choppable)) list(?beginOffset 0.0 ?endOffset 0.0))
        else ltTemplateArgs(row '(?layer ?enclosure ?choppable ?beginOffset ?endOffset))) list(?netName ltGet(spec "net_intent"))))
    cuts=foreach(mapcar row nth(3 def)
      when(nth(10 row) error("UNSUPPORTED_GUARD_TEMPLATE"))
      append(ltTemplateArgs(row '(?layer ?width ?length ?choppable ?sep ?justification ?space ?beginOffset ?endOffset ?gap)) list(?netName ltGet(spec "net_intent"))))
    args=append(ltTemplateArgs(master '(?layer ?width ?choppable))
      list(?cvId cv ?name strcat("colayout_lite_guard_" uid) ?netName ltGet(spec "net_intent")
        ?pts foreach(mapcar p ltGet(spec "points") ltPoint(p cv~>DBUPerUU)) ?endType "truncate"
        ?offsetSubPath offsets ?encSubPath enclosures ?subRect cuts))
    rod=apply('rodCreatePath args) unless(rod error("GUARD_GENERATION_FAILED"))
    n=0
    foreach(o cons(rod~>dbId rod~>subShapes)
      dbReplaceProp(o "colayoutObjectId" "string" if(o==rod~>dbId then uid else strcat(uid ":" sprintf(nil "%d" n))))
      dbReplaceProp(o "colayoutStructureUid" "string" uid)
      dbReplaceProp(o "colayoutNetIntent" "string" or(ltGet(spec "net_intent") "")) n=n+1)
    t))

procedure(ltTemplateArgs(values keys)
  let((out n) n=0 foreach(key keys when(nth(n values) out=append(out list(key nth(n values)))) n=n+1) out))

procedure(ltReceiptPath(uid)
  unless(rexMatchp("^[a-zA-Z0-9_-]+$" uid) error("INVALID_REQUEST_ID"))
  strcat(lbRoot "/.colayout-bridge/lite-" uid ".receipt"))
procedure(ltReceiptRead(uid)
  let((port row)
    port=infile(ltReceiptPath(uid))
    when(port row=lineread(port) close(port) unless(row error("INVALID_RECEIPT")) car(row))))
procedure(ltReceiptWrite(uid hash status lib cell backup)
  let((port)
    port=outfile(ltReceiptPath(uid)) unless(port error("RECEIPT_WRITE_FAILED"))
    fprintf(port "%L\n" list("colayout-lite-receipt-1" uid hash status lib cell backup when(boundp('ltPhase) ltPhase))) close(port) t))

procedure(ltRestore(lib cell backup)
  let((cv b windows key dst sourceTag)
    cv=ltWritable(lib cell) b=ltWritable(lib backup) sourceTag=cv~>colayoutLiteSource
    foreach(w hiGetWindowList()
      when(w!=hiGetCIWindow() && geGetWindowCellView(w)==cv windows=cons(w windows)))
    foreach(o ltObjects(cv) lbObjects[lbIds[o]]=nil lbIds[o]=nil)
    lbObjects[lbIds[cv]]=nil lbIds[cv]=nil
    unless(dbPurge(cv) error("RESTORE_PURGE_FAILED"))
    foreach(w windows when(member(w hiGetWindowList()) hiCloseWindow(w)))
    key=strcat(lib "/" cell) lbViews[key]=nil
    dst=dbCopyCellView(b lib cell "layout" nil nil t)
    unless(dst error("RESTORE_COPY_FAILED"))
    ; The transaction backup tag must not turn an ordinary design into a
    ; managed test cell after rollback. Preserve the original top-level tag.
    if(sourceTag then dbReplaceProp(dst "colayoutLiteSource" "string" sourceTag)
      else dbDeletePropByName(dst "colayoutLiteSource"))
    unless(dbSave(dst) error("RESTORE_COPY_FAILED"))
    lbViews[key]=dst t))

procedure(ltTransaction(lib cell req)
  prog((cv idx seen ops uid hash backup receipt o spec result restored n oldAbut oldSpace net key dep ltWritableLayers routesBefore groupsBefore deleted)
    ltKeys(req list("version" "request_id" "hash" "counter" "dependencies" "backup" "operations" "fail_after" "writable_lpps"))
    ltWritableLayers=ltGet(req "writable_lpps")
    unless(ltGet(req "version")=="colayout-lite-1" error("PROTOCOL_VERSION"))
    uid=ltGet(req "request_id") hash=ltGet(req "hash") backup=ltGet(req "backup")
    receipt=ltReceiptRead(uid)
    when(receipt
      unless(nth(2 receipt)==hash && nth(4 receipt)==lib && nth(5 receipt)==cell error("REQUEST_ID_REUSED"))
      return(list("duplicate" nth(3 receipt) nth(6 receipt))))
    cv=ltWritable(lib cell)
    unless(ltGet(req "counter")==sprintf(nil "%L" cv~>modifiedCounter) error("SOURCE_CONFLICT"))
    foreach(dep ltGet(req "dependencies")
      o=lbObjects[car(dep)]
      unless(o && dbIsId(o) && o~>libName==nth(1 dep) && o~>cellName==nth(2 dep)
        && o~>viewName==nth(3 dep) && sprintf(nil "%L" o~>modifiedCounter)==nth(4 dep) error("MASTER_CONFLICT")))
    idx=ltIndex(cv) seen=makeTable('ltOpSeen nil) ops=ltGet(req "operations")
    routesBefore=ltRoutingRead(cv) deleted=makeTable('ltDeleted nil)
    ltRoutingRequirePrepared(routesBefore)
    groupsBefore=ltGroupsRead(cv) ltGroupsRequirePrepared(groupsBefore)
    foreach(op ops
      ltKeys(op list("action" "uid" "before" "shape" "placement" "guard" "mpp_before"))
      case(ltGet(op "action")
        ("create" ltKeys(op list("action" "uid" "shape")))
        ("update" ltKeys(op list("action" "uid" "before" "shape")))
        ("delete" ltKeys(op list("action" "uid" "before" "mpp_before")))
        ("transform" ltKeys(op list("action" "uid" "before" "placement" "mpp_before")))
        ("guard" ltKeys(op list("action" "uid" "guard" "placement")))
        ("delete_guard" ltKeys(op list("action" "uid"))))
      key=ltGet(op "uid") when(seen[key] error("DUPLICATE_OPERATION_UID")) seen[key]=t
      o=idx[key]
      case(ltGet(op "action")
        ("create" when(o error("UID_EXISTS")) ltCheckSpec(cv ltGet(op "shape")))
        (("update" "delete" "transform")
          unless(o error("UID_MISSING"))
          unless(equal(lbObject(o cv~>DBUPerUU) ltGet(op "before")) error("OBJECT_CONFLICT"))
          if(ltMppRod(o) then
            unless(member(ltGet(op "action") list("delete" "transform")) error("MPP_INTERNAL_READ_ONLY"))
            when(ltMppRestriction(o) error("MPP_RELATIONSHIP_READ_ONLY"))
            unless(equal(ltGet(op "mpp_before") sprintf(nil "%L" ltMppDefinition(o))) error("MPP_DEFINITION_CONFLICT"))
          else
            when(o~>colayoutStructureUid || o~>pin || o~>parent~>pin error("PROTECTED_OBJECT"))
            when(if(ltGet(op "action")=="delete" then !ltCanDelete(o) else ltRelationshipReason(o)) error("NATIVE_RELATIONSHIP_READ_ONLY")))
          if(ltGet(op "action")=="transform" then
            unless(o~>objType=="inst" || ltMppRod(o) error("EXPECTED_INSTANCE_OR_MPP"))
            when(o~>objType=="inst"
              unless(o~>master error("MASTER_UNRESOLVED"))
              when(lbSharedDiffusion(o) error("SHARED_DIFFUSION_LOCKED"))
              unless(o~>mag==1.0 error("MAGNIFICATION_READ_ONLY")))
            spec=ltGet(op "placement") ltKeys(spec list("origin" "orientation"))
            ltPoint(ltGet(spec "origin") cv~>DBUPerUU)
            unless(member(ltGet(spec "orientation") list("R0" "R90" "R180" "R270" "MX" "MY" "MXR90" "MYR90")) error("INVALID_ORIENTATION"))
          else
            unless(member(o~>objType list("rect" "polygon" "path" "pathSeg" "stdVia")) error("OBJECT_READ_ONLY"))
            when(ltGet(op "action")=="update"
              spec=ltGet(op "shape") ltCheckSpec(cv spec)
              unless(o~>objType==ltGet(spec "kind") error("TYPE_CHANGE_REQUIRES_EXPLICIT_REPLACEMENT")))))
        ("guard" when(setof(g ltObjects(cv) g~>colayoutStructureUid==key) error("GROUP_EXISTS")))
        ("delete_guard" unless(setof(g ltObjects(cv) g~>colayoutStructureUid==key) error("GROUP_MISSING")))
        (t error("UNKNOWN_OPERATION"))))
    ltClone(lib cell backup strcat(uid ":backup"))
    ; Clone does not modify the source or any child master.
    unless(dbReopen(cv "a") error("TARGET_REOPEN_FAILED"))
    ltPhase=list("prepared") ltReceiptWrite(uid hash "applying" lib cell backup)
    oldAbut=envGetVal("layoutXL" "autoAbutment") oldSpace=envGetVal("layoutXL" "autoSpace") n=0
    result=unwindProtect(progn(
      envSetVal("layoutXL" "autoAbutment" 'boolean nil) envSetVal("layoutXL" "autoSpace" 'boolean nil)
      errset(progn(
        foreach(op ops
          ltPhase=list(ltGet(op "action") ltGet(op "uid") n)
          key=ltGet(op "uid") o=idx[key]
          case(ltGet(op "action")
            ("create" ltCreate(cv key ltGet(op "shape")))
            ("update"
              if(o~>objType=="stdVia" then
                idx[key]=ltUpdateVia(o ltGet(op "shape") cv~>DBUPerUU)
              else ltUpdateShape(o ltGet(op "shape") cv~>DBUPerUU)))
            ("delete" if(ltMppRod(o) then ltMppDelete(o deleted) else deleted[key]=t unless(dbDeleteObject(o) error("DELETE_FAILED"))))
            ("transform" spec=ltGet(op "placement") if(ltMppRod(o) then ltMppMove(o spec) else o~>xy=ltPoint(ltGet(spec "origin") cv~>DBUPerUU) o~>orient=ltGet(spec "orientation")))
            ("guard" ltGuard(cv ltGet(op "guard") key)
              when(ltGet(op "placement") ltMppMove(ltIndex(cv)[key] ltGet(op "placement"))))
            ("delete_guard" foreach(g setof(g ltObjects(cv) g~>colayoutStructureUid==key)
              when(dbIsId(g) deleted[g~>colayoutObjectId]=t dbDeleteObject(g)))))
          n=n+1 when(ltGet(req "fail_after") && n==ltGet(req "fail_after") error("INJECTED_FAILURE")))
        ltRoutingVerify(routesBefore cv deleted)
        ltGroupsVerify(groupsBefore cv deleted)
        unless(dbSave(cv) error("SAVE_FAILED")) t) t))
      progn(envSetVal("layoutXL" "autoAbutment" 'boolean oldAbut) envSetVal("layoutXL" "autoSpace" 'boolean oldSpace)))
    unless(result
      restored=errset(ltRestore(lib cell backup) t)
      ltReceiptWrite(uid hash if(restored then "rolled_back" else "recovery_required") lib cell backup)
      return(list(if(restored then "rolled_back" else "recovery_required") backup)))
    ltReceiptWrite(uid hash "saved" lib cell backup)
    return(list("saved" backup))))

procedure(lbSharedDiffusion(inst)
  let((p v found)
    foreach(p inst~>master~>parameters~>value
      when(member(p~>name list("leftAbut" "rightAbut"))
        v=p~>value when(numberp(v) && v!=0 found=t))) found))

procedure(ltOpen(lib cell)
  let((cv found w other)
    cv=lbView(lib cell)
    foreach(w hiGetWindowList()
      when(w!=hiGetCIWindow()
        other=geGetWindowCellView(w)
        when(other==cv && hiGetAppType(w)=="Layout" found=w)
        when(other && other~>colayoutLiteSource && (other!=cv || hiGetAppType(w)!="Layout") hiUnmapWindow(w))))
    ; Explicit base Layout application: geOpen can inherit the user's XL
    ; default and enter a blocking connectivity-reference dialog.
    unless(found found=deOpen(list(nil 'libName lib 'cellName cell 'viewName "layout") nil "a" "Layout"))
    unless(found && hiGetAppType(found)=="Layout" && geGetWindowCellView(found)==cv error("LAYOUT_WINDOW_OPEN_FAILED"))
    when(found hiMapWindow(found) hiSetCurrentWindow(found) when(cv~>bBox hiZoomIn(found cv~>bBox)))
    list(sprintf(nil "%L" found) hiGetAppType(found))))

procedure(ltRelease(keep)
  let((all windows count key p)
    all=dbGetOpenCellViews() count=0
    foreach(w hiGetWindowList()
      when(w!=hiGetCIWindow() && geGetWindowCellView(w) windows=cons(geGetWindowCellView(w) windows)))
    foreach(cv all
      when(cv~>viewName=="layout" && cv~>colayoutLiteSource &&
        (rexMatchp("^COLAYOUT_MVP_LITE_BACKUP_" cv~>cellName) || rexMatchp("^COLAYOUT_MVP_LITE_PREVIEW_" cv~>cellName))
        key=strcat(cv~>libName "/" cv~>cellName) p=dbFullLibPath(cv~>libName)
        when(!member(key keep) && !member(cv windows) && !cv~>modifiedButNotSaved && p && strlen(p)>strlen(lbRoot) && substring(p 1 strlen(lbRoot)+1)==strcat(lbRoot "/")
          foreach(o cons(cv append(ltObjects(cv) append(cv~>nets cv~>terminals))) lbObjects[lbIds[o]]=nil lbIds[o]=nil)
          when(dbPurge(cv) lbViews[key]=nil count=count+1))))
    list(length(all) length(dbGetOpenCellViews()) count)))
