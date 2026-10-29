; Fixed native ROD generator and read-only sample extraction.
procedure(ltGuardRecipe(cv spec uid)
 let((scale rod args offsets enclosures cuts part keys row n ring masterChoppable)
  ltKeys(spec list("version" "recipe_id" "recipe_key" "master_lpp" "width" "points" "parts" "net_intent"))
  unless(ltGet(spec "version")=="mpp-generation-2" error("MPP_RECIPE_VERSION")) scale=cv~>DBUPerUU ring=spec
    offsets=nil enclosures=nil cuts=nil masterChoppable=t
    foreach(part ltGet(ring "parts")
      ltKeys(part list("kind" "lpp" "choppable" "width" "length" "enclosure" "separation" "justification" "beginOffset" "endOffset" "beginSegOffset" "endSegOffset" "space" "gap" "diagonal"))
      ; ROD requires every subpart choppable when the master is choppable.
      ; Retain the sampled subpart flags; make a compatible master instead.
      unless(ltGet(part "choppable")=="yes" masterChoppable=nil)
      row=list(?layer ltGet(part "lpp") ?choppable ltGet(part "choppable")=="yes" ?netName ltGet(ring "net_intent"))
      case(ltGet(part "kind")
        ("offsetPath" keys=list(list("width" ?width) list("separation" ?sep) list("beginOffset" ?beginOffset) list("endOffset" ?endOffset)))
        ("enclosurePath" keys=list(list("enclosure" ?enclosure) list("beginOffset" ?beginOffset) list("endOffset" ?endOffset)))
        ("rectangle" keys=list(list("width" ?width) list("length" ?length) list("separation" ?sep) list("space" ?space) list("beginOffset" ?beginOffset) list("endOffset" ?endOffset) list("beginSegOffset" ?beginSegOffset) list("endSegOffset" ?endSegOffset)))
        (t error("UNKNOWN_GUARD_PART")))
      foreach(pair keys
        when(ltGet(part car(pair)) row=append(row list(cadr(pair) ltNumber(ltGet(part car(pair)))/scale))))
      case(ltGet(part "kind")
        ("offsetPath" offsets=append(offsets list(append(row list(?justification ltGet(part "justification"))))))
        ("enclosurePath" enclosures=append(enclosures list(row)))
        ("rectangle" cuts=append(cuts list(append(row list(?justification ltGet(part "justification") ?gap ltGet(part "gap") ?diagonal ltGet(part "diagonal")=="yes")))))))
    args=list(?cvId cv ?name strcat("colayout_mpp_" uid) ?netName ltGet(ring "net_intent")
      ?layer ltGet(ring "master_lpp") ?width ltNumber(ltGet(ring "width"))/scale ?choppable masterChoppable
      ?pts foreach(mapcar p ltGet(ring "points") ltPoint(p scale)) ?endType "truncate"
      ?offsetSubPath offsets ?encSubPath enclosures ?subRect cuts)
    rod=apply('rodCreatePath args) unless(rod error("GUARD_RECIPE_GENERATION_FAILED")) n=0
    foreach(o cons(rod~>dbId rod~>subShapes)
      dbReplaceProp(o "colayoutObjectId" "string" if(o==rod~>dbId then uid else strcat(uid ":" sprintf(nil "%d" n))))
      dbReplaceProp(o "colayoutStructureUid" "string" uid)
      dbReplaceProp(o "colayoutNetIntent" "string" or(ltGet(ring "net_intent") "")) n=n+1)
    t))

procedure(ltGuardSamples(lib cell token)
 let((cv rod rows parts path port part keys data)
  cv=lbView(lib cell)
  foreach(o cv~>shapes
    rod=rodGetObj(o)
    when(rod && rod~>dbId==o && rod~>subShapes
      parts=nil
      foreach(part rod~>subParts
        data=list(list("kind" part~>type) list("lpp" part~>lpp) list("choppable" if(part~>choppable then "yes" else "no")))
        case(part~>type
          ("offsetPath" data=append(data list(list("width" part~>width) list("separation" part~>separation) list("justification" part~>justification) list("beginOffset" part~>beginOffset) list("endOffset" part~>endOffset))))
          ("enclosurePath" data=append(data list(list("enclosure" part~>enclosure) list("beginOffset" part~>beginOffset) list("endOffset" part~>endOffset))))
          ("rectangle" data=append(data list(list("width" part~>width) list("length" part~>length) list("separation" part~>separation) list("space" part~>space) list("justification" part~>justification) list("gap" part~>gap) list("beginOffset" part~>beginOffset) list("endOffset" part~>endOffset) list("beginSegOffset" part~>beginSegOffset) list("endSegOffset" part~>endSegOffset) list("diagonal" if(part~>diagonal then "yes" else "no")))))
          (t error("UNSUPPORTED_SAMPLE_SUBPART")))
        parts=append(parts list(data)))
      rows=append(rows list(list(list("native_id" lbId(o)) list("master_lpp" o~>lpp) list("width" o~>width)
        list("points" o~>points) list("parts" parts) list("chopped" if(rod~>chopHoles then "yes" else "no")))))))
  path=strcat(lbRoot "/.colayout-bridge/guards19_" token ".sexpr")
  port=outfile(path) fprintf(port "%L\n" rows) close(port) list(path)))
