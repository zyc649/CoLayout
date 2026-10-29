; Read-only device/CDF evidence for process configuration. No binding creation,
; parameter callbacks, saving, or inference of MOS/resistor/capacitor types.
procedure(ltProcessSample(lib cell token)
  let((cv counter dirty rows path port)
    cv=lbView(lib cell)
    counter=sprintf(nil "%L" cv~>modifiedCounter)
    dirty=cv~>modifiedButNotSaved
    rows=lcReferenceRows(cv)
    unless(counter==sprintf(nil "%L" cv~>modifiedCounter) && dirty==cv~>modifiedButNotSaved
      error("PROCESS_SAMPLE_CHANGED_DURING_READ"))
    path=strcat(lbRoot "/.colayout-bridge/process_" token ".sexpr")
    port=outfile(path)
    unless(port error("PROCESS_SAMPLE_EXPORT_FAILED"))
    fprintf(port "%L\n" rows)
    close(port)
    list(path)))
