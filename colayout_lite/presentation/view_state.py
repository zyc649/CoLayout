"""Small selection/status state shared by canvas controllers; no test UI."""
class ViewState:
    materialized = False
    def __init__(self):
        self._editor=None;self.selected_uid=None;self.result='';self.coordinates=''
        self.native_routing_window_id=None
    def bind(self,editor):
        self._editor=editor;self.selected_uid=None;self.native_routing_window_id=None
    def set_selected(self,uid,*,reload=True):self.selected_uid=uid
    def refresh_objects(self,changed):
        if self.selected_uid in changed and self._editor:
            from ..editor import projected
            if self.selected_uid not in projected(self._editor.w):self.selected_uid=None
    def set_busy(self,value):pass
    def set_discard_enabled(self,value):pass
    def set_coordinates(self,text):self.coordinates=text
    def set_result(self,text):self.result=text
    def show_error(self,message):self.set_result('未执行：'+str(message))
