"""Shared public editing contract for Actions, the test panel and API inspection.

Public lengths are physical micrometres. Conversion to integer DBU and native
diagonal units belongs to Actions; the form must not perform a second conversion.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Command:
    title: str
    form: str
    fields: frozenset[str]
    required: frozenset[str]
    kinds: frozenset[str]=frozenset()
    show_in_panel: bool=True

def command(title,form,fields,required='',kinds='',*,show_in_panel=True):
    return Command(title,form,frozenset(fields.split()),frozenset(required.split()),frozenset(kinds.split()),show_in_panel)

ENDS='style begin_style end_style begin_extension end_extension begin_custom end_custom'
SHAPES='rect polygon path pathSeg stdVia'
COMMANDS={
 'create_rect':command('创建 · 矩形','rect','x y width height lpp net_intent','x y width height lpp'),
 'create_path90':command('创建 · 90° 折线 Path','vertices','points width lpp net_intent '+ENDS,'points lpp'),
 'create_path45':command('创建 · 45°/90° 折线 Path','vertices','points width lpp net_intent '+ENDS,'points lpp'),
 'create_pathseg90':command('创建 · 90° 单段 PathSeg','vertices','points width lpp net_intent '+ENDS,'points lpp'),
 'create_pathseg45':command('创建 · 45°/90° 单段 PathSeg','vertices','points width lpp net_intent '+ENDS,'points lpp'),
 'create_polygon':command('创建 · 多边形','vertices','points lpp net_intent','points lpp'),
 'create_via':command('创建 · 标准过孔','via','x y definition orientation via_parameters net_intent','x y definition'),
 'move':command('变换 · 相对移动','relative','dx dy','dx dy','inst mpp '+SHAPES),
 'rotate':command('变换 · 相对旋转','rotate','degrees pivot','','inst mpp '+SHAPES),
 'mirror':command('变换 · 镜像','mirror','axis pivot','axis','inst mpp '+SHAPES),
 'place_instance':command('变换 · 实例绝对位置/方向','placement','x y orientation','x y','inst'),
 'set_width':command('线 · 修改物理线宽','width','width','width','path pathSeg'),
 'edit_rect':command('矩形 · 位置/尺寸/图层','rect','x y width height lpp net_intent','x y width height','rect'),
 'edit_path90':command('线 · 修改走势（仅90°）','vertices','points width lpp net_intent '+ENDS,'points width','path pathSeg'),
 'edit_path45':command('线 · 修改走势（45°/90°）','vertices','points width lpp net_intent '+ENDS,'points width','path pathSeg'),
 'edit_path_ends':command('线 · 端头与延伸量','wire_ends',ENDS,'','path pathSeg'),
 'edit_polygon':command('多边形 · 顶点/图层','vertices','points lpp net_intent','points','polygon'),
 'edit_via':command('过孔 · 位置/阵列/定义/偏移','via','x y definition orientation via_parameters net_intent','','stdVia'),
 'reset_via':command('过孔 · 参数恢复工艺默认','via_reset','names','names','stdVia'),
 'set_net_intent':command('标注 · 网络意图','net','net_intent','net_intent',SHAPES),
 'copy':command('复制 · 外部图形','copy','dx dy orientation pivot','dx dy',SHAPES),
 'delete':command('删除 · 当前对象','delete','','','mpp '+SHAPES),
 'create_guard':command('MPP · 创建保护环','guard','x y width height template net_intent','x y width height template net_intent'),
 'create_mpp':command('MPP · 创建开放路径','mpp','points template net_intent','points template net_intent'),
 # Compatibility API for older scripts; the panel uses the unified delete.
 'delete_guard':command('MPP · 整体删除','delete','','',show_in_panel=False),
}
TITLES={k:v.title for k,v in COMMANDS.items()}
FIELDS={k:v.fields for k,v in COMMANDS.items()}
PATH_STYLES=[('平端 / 直角转角','truncateExtend'),('延伸半线宽','extendExtend'),('八边形端头 / 转角','roundRound'),('自定义两端延伸','varExtendExtend')]
SEG_STYLES=[('平端','truncate'),('延伸半线宽','extend'),('自定义延伸','variable'),('八边形倒角','chamfer'),('原生自定义倒角','custom')]
ORIENTATIONS=('R0','R90','R180','R270','MX','MY','MXR90','MYR90')

def wire_kind(action,obj=None):
    if action.startswith('create_pathseg'):return 'pathSeg'
    if action.startswith('create_path'):return 'path'
    return obj.kind if obj is not None else 'path'

def allowed_fields(action,obj=None):
    fields=FIELDS[action]
    if fields.intersection(ENDS.split()):
        fields=fields-({'style'} if wire_kind(action,obj)=='pathSeg' else {'begin_style','end_style','begin_custom','end_custom'})
    return fields
