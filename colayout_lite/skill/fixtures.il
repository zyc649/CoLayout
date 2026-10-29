; Integration fixtures only, never loaded by the normal adapter.
procedure(ltFixtureHierarchy(lib source stem layer)
  let((leaf mid top cv net fig)
    unless(strlen(stem)>18 && substring(stem 1 18)=="COLAYOUT_MVP_LITE_" error("FIXTURE_PREFIX"))
    foreach(name list(strcat(stem "_MID") strcat(stem "_TOP")) when(ddGetObj(lib name) error("FIXTURE_EXISTS")))
    ltClone(lib source strcat(stem "_LEAF") strcat(stem "_leaf_uid"))
    leaf=ltWritable(lib strcat(stem "_LEAF"))
    mid=dbOpenCellViewByType(lib strcat(stem "_MID") "layout" "maskLayout" "w")
    dbCreateInst(mid leaf "A" 5:7 "R90") dbCreateInst(mid leaf "B" 50:0 "MY")
    net=dbCreateNet(mid "PORT") dbCreateTerm(net "PORT" "inputOutput")
    fig=dbCreateRect(mid list(layer "drawing") list(0:0 2:2)) dbCreatePin(net fig)
    fig=dbCreateRect(mid list(layer "drawing") list(3:0 5:2)) dbCreatePin(net fig)
    dbReplaceProp(mid "colayoutLiteSource" "string" "hierarchy-fixture") ltMark(mid strcat(stem "_mid_uid")) dbSave(mid)
    lbViews[strcat(lib "/" strcat(stem "_MID"))]=mid
    top=dbOpenCellViewByType(lib strcat(stem "_TOP") "layout" "maskLayout" "w")
    dbCreateInst(top mid "U_A" 0:0 "R0") dbCreateInst(top mid "U_B" 150:100 "MXR90")
    dbCreateInst(top leaf "U_LEAF" 300:0 "R180")
    dbReplaceProp(top "colayoutLiteSource" "string" "hierarchy-fixture") ltMark(top strcat(stem "_top_uid")) dbSave(top)
    lbViews[strcat(lib "/" strcat(stem "_TOP"))]=top
    list(strcat(stem "_LEAF") strcat(stem "_MID") strcat(stem "_TOP"))))

procedure(ltFixtureArray(lib source target)
  let((cv master m)
    when(ddGetObj(lib target) error("FIXTURE_EXISTS"))
    master=lbView(lib source)
    cv=dbOpenCellViewByType(lib target "layout" "maskLayout" "w")
    m=dbCreateSimpleMosaic(cv master "ARRAY" 10:20 "MXR90" 2 3 40.0 50.0)
    dbReplaceProp(cv "colayoutLiteSource" "string" "array-fixture") ltMark(cv target) dbSave(cv)
    lbViews[strcat(lib "/" target)]=cv
    list(m~>?? m~>instances~>??)))

procedure(ltFixturePinOracle(lib cell)
  let((cv out pi fi)
    cv=lbView(lib cell)
    foreach(i setof(i cv~>instances i~>objType=="inst")
      foreach(term i~>master~>terminals
        pi=0
        foreach(pin term~>pins
          fi=0
          foreach(fig pin~>figs
            out=cons(list(i~>colayoutObjectId term~>name pi fi
              lbBounds(dbTransformBBox(fig~>bBox i~>transform) cv~>DBUPerUU)) out)
            fi=fi+1)
          pi=pi+1)))
    out))
