; Reclaim only an exact application-created copy after its owner has completed.
; A prefix is not ownership: require the original source tag, saved state,
; no window/other view/reference, and an unchanged counter before deletion.
procedure(ltTemporarySource(lib cell)
  let((cv)
    lbCheckPath(lib)
    unless(rexMatchp("^COLAYOUT_MVP_LITE_" cell) error("NOT_TEMPORARY"))
    when(ddGetObj(lib cell "layout") cv=lbView(lib cell) cv~>colayoutLiteSource)))

procedure(ltTemporaryInfo(lib cell source)
 prog((cv object views key)
  lbCheckPath(lib)
  unless(rexMatchp("^COLAYOUT_MVP_LITE_" cell) return(list("retained" "not_private")))
  object=ddGetObj(lib cell)
  unless(object return(list("absent")))
  views=object~>views
  unless(length(views)==1 && car(views)~>name=="layout" return(list("retained" "other_views")))
  cv=lbView(lib cell)
  unless(cv~>colayoutLiteSource==strcat(lib "/" source) return(list("retained" "source_tag")))
  when(cv~>modifiedButNotSaved return(list("retained" "unsaved")))
  foreach(w hiGetWindowList()
    when(w!=hiGetCIWindow() && geGetWindowCellView(w)==cv return(list("retained" "window_open"))))
  foreach(other dbGetOpenCellViews()
    unless(other==cv
      foreach(inst other~>instances when(inst~>master==cv return(list("retained" "referenced"))))))
  return(list("ready" sprintf(nil "%L" cv~>modifiedCounter) strcat(dbFullLibPath(lib) "/" cell)))))

procedure(ltTemporaryDelete(lib cell source counter)
 prog((info cv object key)
  info=ltTemporaryInfo(lib cell source)
  unless(car(info)=="ready" return(info))
  unless(cadr(info)==counter return(list("retained" "changed")))
  cv=lbView(lib cell) object=ddGetObj(lib cell) key=strcat(lib "/" cell)
  foreach(o cons(cv append(ltObjects(cv) append(cv~>nets cv~>terminals))) lbObjects[lbIds[o]]=nil lbIds[o]=nil)
  unless(dbPurge(cv) return(list("retained" "purge_failed")))
  lbViews[key]=nil
  unless(ddDeleteObj(object) return(list("retained" "delete_failed")))
  return(list("deleted"))))

procedure(ltTemporaryRelease(lib cell source counter)
 prog((info cv key)
  info=ltTemporaryInfo(lib cell source)
  unless(car(info)=="ready" return(info))
  unless(cadr(info)==counter return(list("retained" "changed")))
  cv=lbView(lib cell) key=strcat(lib "/" cell)
  foreach(o cons(cv append(ltObjects(cv) append(cv~>nets cv~>terminals))) lbObjects[lbIds[o]]=nil lbIds[o]=nil)
  unless(dbPurge(cv) return(list("retained" "purge_failed")))
  lbViews[key]=nil
  return(list("released"))))
