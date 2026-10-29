"""Native connectivity/reference records. No PDK or matching logic."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class ViewRef(Record):
    library: str
    cell: str
    view: str
    session: str
    counter: str


class Terminal(Record):
    name: str
    net: str | None
    direction: str | None = None
    # Member names/signals are produced by Cadence, never expanded locally.
    members: dict[str, str | None] = Field(default_factory=dict)
    # Human-readable native signals. Members retain the distinct must-connect
    # identities of OA child nets (e.g. pseudoparallel groups of one signal).
    member_signals: dict[str, str | None] = Field(default_factory=dict)


class InstanceInterface(Record):
    name: str
    master: tuple[str, str, str]
    terminals: dict[str, Terminal]


class ReferenceInstance(InstanceInterface):
    member_count: int | None = Field(default=None,ge=1)
    parameters: dict[str, 'NativeParameter'] = Field(default_factory=dict)
    parameter_capture: Literal['not_captured','captured','no_cdf'] = 'not_captured'
    instance_properties: list[Any] = Field(default_factory=list)


class NativeParameter(Record):
    value_type: str | None
    units: str | None = None
    value: Any = None
    default: Any = None
    origin: Literal['instance_property','effective_cdf']
    instance_value: Any = None
    provider: Literal['Cadence cdfGetInstCDF'] = 'Cadence cdfGetInstCDF'


class NativePathSegment(Record):
    library: str
    cell: str
    view: str
    instance: str
    member: int
    row: int
    column: int


class NativeBinding(Record):
    layout_uid: str
    schematic_paths: tuple[tuple[NativePathSegment, ...], ...]


class NativeCheck(Record):
    provider: Literal['Cadence lxCheckAgainstSource'] = 'Cadence lxCheckAgainstSource'
    status: Literal['pass'] = 'pass'
    report: str
    scope: str = 'native instance correspondence; not physical routing, parameter comparison or LVS'


class ReferenceScope(Record):
    """One schematic occurrence opened by an actual native binding path."""
    path: tuple[NativePathSegment, ...]
    source: ViewRef
    instances: dict[str, ReferenceInstance]
    ports: dict[str, Terminal]


class CircuitContext(Record):
    """Schematic reference only, never a source of routing targets."""
    schema_version: Literal['colayout-circuit-2','colayout-circuit-3','colayout-circuit-4'] = 'colayout-circuit-3'
    pair_id: str | None = None
    source: ViewRef
    instances: dict[str, ReferenceInstance]
    ports: dict[str, Terminal]
    bindings: tuple[NativeBinding, ...]
    native_check: NativeCheck
    hierarchy: tuple[ReferenceScope, ...] = ()

    @model_validator(mode='after')
    def valid_hierarchy(self):
        if self.schema_version=='colayout-circuit-4':
            from .hierarchy import validate_capture
            validate_capture(self)
        return self


class LayoutInstance(InstanceInterface):
    uid: str
    black_box: bool


class LayoutConnectivity(Record):
    """Routing targets read from Layout's own instTerms and top terminals."""
    schema_version: Literal['colayout-layout-connectivity-1'] = 'colayout-layout-connectivity-1'
    pair_id: str | None = None
    source: ViewRef
    instances: dict[str, LayoutInstance]
    ports: dict[str, Terminal]
