"""Small public helper parameter models; lengths are workspace micrometres."""

from typing import Literal,get_args
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from ..model import Orientation


class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    @model_validator(mode='before')
    @classmethod
    def reject_boolean_numbers(cls, data):
        if not isinstance(data, dict):
            return data

        def check(value):
            if isinstance(value, bool):
                raise ValueError('A boolean cannot stand for a geometry number')
            if isinstance(value, dict):
                for item in value.values():
                    check(item)
            if isinstance(value, (tuple, list)):
                for item in value:
                    check(item)

        for name, value in data.items():
            if name in cls.model_fields:
                annotation=cls.model_fields[name].annotation
                if annotation is bool or set(get_args(annotation))=={bool,type(None)}:continue
            check(value)
        return data


class Bus(Parameters):
    lpp: tuple[str, str]
    x: float
    y: float
    length: float = Field(gt=0)
    count: StrictInt = Field(ge=1, le=256)
    spacing: float = Field(ge=0)
    width: float | None = Field(default=None, gt=0)
    direction: Literal['horizontal', 'vertical'] = 'horizontal'
    net_intent: str | None = None
    nets: list[str | None] | None = None

    @model_validator(mode='after')
    def valid(self):
        if self.nets is not None and (len(self.nets) != self.count or self.net_intent is not None):
            raise ValueError('nets must match count and cannot be combined with net_intent')
        return self


class EmptySlot(Parameters):
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Arrange(Parameters):
    uids: list[str | EmptySlot] | None = Field(default=None, min_length=1, max_length=512)
    rows: list[list[str | EmptySlot]] | None = Field(default=None, min_length=1, max_length=64)
    direction: Literal['horizontal', 'vertical'] = 'horizontal'
    align: Literal['top', 'bottom', 'left', 'right', 'center'] = 'center'
    spacing: float = Field(default=0, ge=0)
    row_spacing: float = Field(default=0, ge=0)
    x: float | None = None
    y: float | None = None
    orientation: Orientation | None = None

    @model_validator(mode='after')
    def valid(self):
        if (self.uids is None) == (self.rows is None):
            raise ValueError('Provide uids or rows, exactly one')
        if (self.x is None) != (self.y is None):
            raise ValueError('x and y must be provided together')
        if self.rows is not None and (
            any(not row for row in self.rows) or sum(map(len, self.rows)) > 512
        ):
            raise ValueError('Rows must be nonempty with at most 512 slots')
        if self.align not in (
            ('left', 'right', 'center')
            if self.direction == 'vertical' and self.rows is None
            else ('top', 'bottom', 'center')
        ):
            raise ValueError('Alignment does not match arrangement direction')
        return self


class Align(Parameters):
    uids: list[str] = Field(min_length=1, max_length=512)
    edge: Literal['left', 'right', 'top', 'bottom', 'center_x', 'center_y']
    reference_uid: str | None = None
    coordinate: float | None = None

    @model_validator(mode='after')
    def valid(self):
        if (self.reference_uid is None) == (self.coordinate is None):
            raise ValueError('Provide reference_uid or coordinate, exactly one')
        return self


class Guard(Parameters):
    template_id: str = Field(min_length=1)
    net_intent: str = Field(min_length=1)
    bounds_um: tuple[float, float, float, float] | None = None
    points_um: list[tuple[float, float]] | None = Field(default=None, min_length=2, max_length=512,
        description='Open 90-degree main-path vertices in workspace absolute micrometres. Mutually exclusive with bounds_um and uids.')
    uids: list[str] | None = Field(default=None, min_length=1, max_length=512)
    clearance: float | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def valid(self):
        if sum(value is not None for value in (self.bounds_um,self.points_um,self.uids)) != 1:
            raise ValueError('Provide bounds_um, points_um or uids, exactly one')
        if self.uids is None and self.clearance is not None:
            raise ValueError('clearance applies only to enclosed uids, not explicit main-path bounds/points')
        return self


class AutoVias(Parameters):
    bounds_um: tuple[float, float, float, float]
    start_layer: str
    end_layer: str
    net_intent: str = Field(min_length=1)
    targets: list[str] | None = Field(default=None, min_length=1, max_length=128)
    via_definitions: list[str] | None = Field(default=None, min_length=1, max_length=16)
    allow_landing: bool = False
    landing_policy: Literal['fit_target', 'expand_window'] = 'fit_target'
    landing_reference: str | None = None
    minimum_cuts: StrictInt = Field(default=2, ge=2, le=4096)
    max_cuts: StrictInt = Field(default=4096, ge=2, le=4096)
    array_direction: Literal['any','horizontal','vertical'] = 'any'


class MultilayerPath(Parameters):
    points: list[tuple[float, float]] = Field(min_length=2, max_length=64)
    net_intent: str = Field(min_length=1)
    layers: list[str] | None = Field(default=None,
        description='One layer per segment: len(layers) == len(points)-1. Omit to use configured horizontal/vertical preferences.')
    widths_um: dict[str, float] = Field(default_factory=dict)
    bounds_um: tuple[float, float, float, float] | None = None
    landing_size_um: float | None = Field(default=None, gt=0,
        description='Square landing search window side in um; must fit the generated via array (at least two cuts per level). Omit for native-footprint sizing; a 1x1 via size is usually too small.')
    start_layer: str | None = None
    end_layer: str | None = None
    start_pin_id: str | None = None
    end_pin_id: str | None = None

    @model_validator(mode='after')
    def valid(self):
        if self.layers is not None and len(self.layers) != len(self.points) - 1:
            raise ValueError('layers must name each segment')
        if any(v <= 0 for v in self.widths_um.values()):
            raise ValueError('Widths must be positive')
        return self


MODELS = {
    'create_bus': Bus,
    'arrange': Arrange,
    'align': Align,
    'create_guard': Guard,
    'create_auto_vias': AutoVias,
    'create_multilayer_path': MultilayerPath,
}
SLOW_ACTIONS = {'create_guard', 'create_auto_vias', 'create_multilayer_path'}
