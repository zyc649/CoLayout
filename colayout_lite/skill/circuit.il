; Native correspondence query, not a second circuit matcher.
; IC618: bndGetBoundObjects, lxRunCmdInXL, lxCheckAgainstSource,
; dbGetMemName, dbGetMemNetSig and net.sigNames verified in IC618 docs.

procedure(lcConnRef(cv)
  let((ref)
    ref=lxGetConnRef(cv)
    ; IC618's empty strings mean same library/cell and the schematic view.
    ; Explicit nonempty references are never replaced.
    if(ref && car(ref)=="CELLVIEW" then
      list("CELLVIEW"
        if(nth(1 ref) && nth(1 ref)!="" then nth(1 ref) else cv~>libName)
        if(nth(2 ref) && nth(2 ref)!="" then nth(2 ref) else cv~>cellName)
        if(nth(3 ref) && nth(3 ref)!="" then nth(3 ref) else "schematic")
        nth(4 ref))
    else ref)))

; Sole reference write: preserve native source identity on a NEW private copy.
; ltClone enforces project boundary, private prefix and destination nonexistence.
; It remains independent of Layout XL for layout-only configuration samples.
procedure(lcClonePaired(lib source target seed)
  let((reference result)
    reference=lcConnRef(lbView(lib source))
    unless(reference && car(reference)=="CELLVIEW" error("NATIVE_CONNREF_REQUIRED"))
    result=ltClone(lib source target seed)
    unless(lxSetConnRef(lib target "layout" "CELLVIEW"
      ?schLib nth(1 reference) ?schCell nth(2 reference) ?schView nth(3 reference))
      error("COPY_SOURCE_REFERENCE_FAILED"))
    result))

procedure(lcMemberSignalName(net index)
  let((sig names)
    when(net
      sig=dbGetMemNetSig(net index)
      when(sig
        ; Keep this display signal separate from the member alias: child nets
        ; encode Layout XL pseudoparallel must-connect groups. Never flatten
        ; those groups, parse their names, or borrow schematic connectivity.
        if(sig~>objType=="net" then
          names=sig~>sigNames
          unless(length(names)==1 error("AMBIGUOUS_NATIVE_MEMBER_SIGNAL"))
          car(names)
        else dbGetMemNetSigName(net index))))))

procedure(lcTerminalRow(name net direction bits)
  let((members signals member)
    for(index 0 or(bits 1)-1
      member=dbGetMemName(name index)
      members=cons(list(member when(net dbGetMemNetSigName(net index))) members)
      signals=cons(list(member lcMemberSignalName(net index)) signals))
    list(name when(net net~>name) direction reverse(members) reverse(signals))))

procedure(lcInstanceTerms(inst)
  foreach(mapcar it inst~>instTerms
    lcTerminalRow(it~>name it~>net it~>term~>direction it~>term~>numBits)))

procedure(lcPorts(cv)
  foreach(mapcar term cv~>terminals
    lcTerminalRow(term~>name term~>net term~>direction term~>numBits)))

; Preserve CDF values verbatim. No callbacks, expression evaluation or matching.
procedure(lcParameters(inst)
  let((cdf explicit)
    cdf=cdfGetInstCDF(inst)
    if(cdf then
      list("captured" foreach(mapcar param cdf~>parameters
        explicit=car(setof(prop inst~>prop prop~>name==param~>name))
        list(param~>name param~>type param~>units lbVal(param~>value) lbVal(param~>defValue)
          if(explicit then "instance_property" else "effective_cdf")
          when(explicit lbVal(explicit~>value)))))
    else list("no_cdf" nil))))

procedure(lcReferenceRows(schematic)
  foreach(mapcar inst setof(i schematic~>instances i~>purpose!="pin")
    list(inst~>name list(inst~>libName inst~>cellName inst~>viewName)
      lcInstanceTerms(inst) lcParameters(inst) lbProps(inst) or(inst~>numInst 1))))

procedure(lcPathRows(paths)
  foreach(mapcar path paths
    foreach(mapcar segment path
      let((obj)
        obj=car(segment)
        unless(dbIsId(obj) && obj~>objType=="inst" error("UNSUPPORTED_NATIVE_BINDING_PATH"))
        list(obj~>cellView~>libName obj~>cellView~>cellName obj~>cellView~>viewName obj~>name
          nth(1 segment) nth(2 segment) nth(3 segment))))))

procedure(lcNativePaths(inst) lcPathRows(bndGetBoundObjects(inst)))

; Capture only owning schematic views already present in the native binder.
; A leaf binding does not authorize descent into that leaf's master.
procedure(lcHierarchy(layout)
  let((records prefix cv converted)
    foreach(inst append(layout~>instances layout~>mosaics)
      foreach(path bndGetBoundObjects(inst)
        prefix=nil converted=car(lcPathRows(list(path)))
        for(index 0 length(path)-1
          cv=car(nth(index path))~>cellView
          when(prefix && !assoc(prefix records)
            lbCheckPath(cv~>libName)
            records=cons(list(prefix cv sprintf(nil "%L" cv~>modifiedCounter)
              lcReferenceRows(cv) lcPorts(cv)) records))
          prefix=append(prefix list(nth(index converted))))))
    reverse(records)))

procedure(lcHierarchyStable(records)
  let((ok cv)
    ok=t
    foreach(record records
      cv=nth(1 record)
      unless(equal(nth(2 record) sprintf(nil "%L" cv~>modifiedCounter))
        && equal(nth(3 record) lcReferenceRows(cv)) && equal(nth(4 record) lcPorts(cv)) ok=nil))
    ok))

procedure(lcHierarchyRows(records)
  foreach(mapcar record records
    let((cv)
      cv=nth(1 record)
      list(car(record) list(cv~>libName cv~>cellName cv~>viewName lbSession nth(2 record))
        nth(3 record) nth(4 record)))))

procedure(lcReportText(path)
  let((port line text)
    text="" port=infile(path)
    unless(port error("NATIVE_REPORT_MISSING"))
    unwindProtect(progn(while(gets(line port) text=strcat(text line)) text) close(port))))

procedure(lcCaptureNative(schematic layout lib cell token)
  let((schCounter layCounter snapshot sourceRows sourcePorts hierarchy layoutRows source reportPath reportOK report context)
    unless(layout~>libName==lib && layout~>cellName==cell error("NATIVE_CONTEXT_TARGET_MISMATCH"))
    lbCheckPath(schematic~>libName)
    schCounter=schematic~>modifiedCounter layCounter=layout~>modifiedCounter
    reportPath=strcat(lbRoot "/.colayout-bridge/correspondence-" token ".log")
    source=list(schematic~>libName schematic~>cellName schematic~>viewName lbSession
      sprintf(nil "%L" schCounter))
    sourceRows=lcReferenceRows(schematic)
    sourcePorts=lcPorts(schematic)
    hierarchy=lcHierarchy(layout)
    layoutRows=foreach(mapcar inst append(layout~>instances layout~>mosaics)
      list(or(inst~>colayoutObjectId strcat("session:" lbId(inst))) inst~>name
        list(inst~>libName inst~>cellName inst~>viewName)
        ltCChildren(inst~>master) lcInstanceTerms(inst) lcNativePaths(inst)))
    snapshot=ltCompactRead(lib cell)
    unless(equal(schCounter schematic~>modifiedCounter) && equal(layCounter layout~>modifiedCounter)
      error("SOURCE_CHANGED_DURING_READ"))
    ; Run CAS after acquisition: a failing check can add diagnostic markers.
    ; Return its report even then; it must not be masked by a counter error.
    reportOK=lxCheckAgainstSource(schematic layout ?masterDiff t ?paramDiff nil
      ?unboundInsts t ?connectivity nil ?nameDiff nil ?dummyDiff nil ?busTermDiff nil
      ?logFileName reportPath ?appendToLog nil)
    report=lcReportText(reportPath)
    context=list("colayout-context-native-5" source sourceRows sourcePorts
      layoutRows lcPorts(layout) list(reportOK report
        equal(schCounter schematic~>modifiedCounter) && equal(layCounter layout~>modifiedCounter)
        && equal(sourceRows lcReferenceRows(schematic)) && equal(sourcePorts lcPorts(schematic))
        && lcHierarchyStable(hierarchy)) token lcHierarchyRows(hierarchy))
    list("colayout-paired-native-3" snapshot context)))

procedure(lcWritePaired(lib cell schLib schCell schView token)
  let((layout reference data path port)
    unless(rexMatchp("^[a-zA-Z0-9_-]+$" token) error("INVALID_FILE_TOKEN"))
    layout=lbView(lib cell) reference=lcConnRef(layout)
    unless(reference && car(reference)=="CELLVIEW" error("NATIVE_CONNREF_REQUIRED"))
    when(schLib
      unless(equal(list(schLib schCell schView) list(nth(1 reference) nth(2 reference) nth(3 reference)))
        error("NATIVE_SOURCE_REFERENCE_MISMATCH")))
    data=lxRunCmdInXL(layout 'lcCaptureNative ?cmdArgs list(lib cell token)
      ?editLayout nil ?editSchematic nil)
    unless(data error("NATIVE_BINDER_UNAVAILABLE"))
    path=strcat(lbRoot "/.colayout-bridge/paired-" token ".sexpr")
    port=outfile(path) unless(port error("EXPORT_FILE_FAILED"))
    fprintf(port "%L\n" data) close(port) list(path)))
