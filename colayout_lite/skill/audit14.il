; Test-only independent native edit path. Never loaded by the normal app.
procedure(ltAudit14Fixture(lib cell lpp viaName seed)
  let((cv out o x n ext d width half cuts dir delta)
    cv=ltWritable(lib cell) n=0
    o=dbCreateRect(cv lpp list(list(100 100) list(104 103))) out=cons(o out)
    o=dbCreatePolygon(cv lpp list(list(110 100) list(114 100) list(116 102) list(113 105) list(110 103))) out=cons(o out)
    foreach(style list("truncateExtend" "extendExtend" "roundRound" "varExtendExtend")
      o=dbCreatePath(cv lpp list(list(120+n*20 100) list(125+n*20 105) list(130+n*20 105)) 0.8 style)
      when(style=="varExtendExtend" o~>beginExt=0.5 o~>endExt=0.7)
      out=cons(o out) n=n+1)
    foreach(dir list(list(1 0) list(0 1) list(-1 0) list(0 -1) list(1 1) list(-1 1) list(-1 -1) list(1 -1))
      d=car(dir)!=0 && cadr(dir)!=0 width=if(d then 1.414 else 1.0) half=width/2
      foreach(bs list("truncate" "extend" "variable" "chamfer" "custom")
        foreach(es list("truncate" "extend" "variable" "chamfer" "custom")
          x=100+n*20
          ext=list(if(member(bs list("variable" "custom")) then half else 0.0)
                   if(member(es list("variable" "custom")) then half else 0.0))
          when(bs=="custom" || es=="custom"
            cuts=nil
            foreach(st list(bs es)
              cuts=append(cuts if(st=="custom" then list(if(d then 0.5 else 0.75) if(d then 0.5 else 0.75) half) else list(0.0 0.0 0.0))))
            ext=append(ext list(cuts)))
          o=dbCreatePathSeg(cv lpp list(x 200) list(x+10*car(dir) 200+10*cadr(dir)) width bs es ext)
          unless(o error("NATIVE_PATHSEG_FIXTURE_FAILED")) out=cons(o out) n=n+1)))
    foreach(orient list("R0" "R90" "R180" "R270" "MX" "MY" "MXR90" "MYR90")
      o=dbCreateVia(cv techFindViaDefByName(techGetTechFile(cv) viaName) list(100+n*20 300) orient list(list("cutRows" 2) list("cutColumns" 3)))
      unless(o error("NATIVE_VIA_FIXTURE_FAILED")) out=cons(o out) n=n+1)
    foreach(fig out dbReplaceProp(fig "audit14Original" "string" "native-created"))
    ltMark(cv seed) dbSave(cv)
    foreach(mapcar fig out fig~>colayoutObjectId)))

procedure(ltAudit14NativeMove(lib cell uids dx dy orient)
  let((cv idx o moved)
    cv=ltWritable(lib cell) idx=ltIndex(cv)
    foreach(uid uids
      o=idx[uid] unless(o error("NATIVE_EDIT_UID_MISSING"))
      ; nil keeps the object in its original cell and retains the native ID.
      moved=dbMoveFig(o nil list(list(dx dy) orient 1.0))
      unless(moved==o error("NATIVE_EDIT_CHANGED_ID")))
    dbSave(cv) length(uids)))
