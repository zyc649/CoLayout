"""Versioned JSON contract shared by built-ins, user plugins and future callers."""
from typing import Literal
from pydantic import Field, StrictInt, model_validator
from ..model import Record, Shape, Box


class Figure(Record):
    layer: str
    geometry: dict  # GeoJSON Polygon/MultiPolygon; coordinates are DBU, not um.


class Material(Figure):
    owner: str
    net: str | None = None  # Endpoint-proven; unassigned metal is an obstacle.


class Barrier(Figure):
    owner: str
    access: dict[str, dict] = Field(default_factory=dict)  # Exact net-specific exceptions.


class TerminalGroup(Record):
    id: str
    net: str
    pin_ids: tuple[str, ...]
    figures: tuple[Figure, ...]
    landing: bool = False  # Virtual local interface; requires physical metal.
    alternative_layers: bool = False  # Any one of these landing layers suffices.


class LayerRule(Record):
    name: str
    width: StrictInt = Field(gt=0)
    spacing: float = Field(gt=0)
    minimum_area: float = Field(default=0,ge=0)  # DBU squared.


class ViaRule(Record):
    name: str
    cut_layer: str
    footprints: tuple[Figure, ...]
    cut_spacing: float = Field(gt=0)


class RoutingProblem(Record):
    schema_version: Literal['colayout-routing-problem-1','colayout-routing-problem-2'] = 'colayout-routing-problem-1'
    request_id: str
    source_digest: str
    workspace_id: str
    revision: int
    region_id: str
    region_name: str
    bounds: Box
    dbu_per_micron: int
    grid: int
    layers: tuple[LayerRule, ...]
    via: ViaRule | None = None  # v1 compatibility; v2 uses the complete vias list.
    vias: tuple[ViaRule, ...] = ()
    pins: tuple[dict, ...]
    groups: tuple[TerminalGroup, ...]
    materials: tuple[Material, ...]
    barriers: tuple[Barrier, ...]
    devices: tuple[dict, ...] = ()
    reference: dict = Field(default_factory=dict)  # Native schematic reference, never routing authority.
    coverage: dict = Field(default_factory=dict)
    limits: dict = Field(default_factory=lambda: {'grid_nodes': 160000, 'search_states': 250000,
        'shapes': 3000, 'candidates': 3, 'max_vias_per_branch': 2})

    @property
    def via_rules(self):
        return self.vias or ((self.via,) if self.via else ())


class Proposal(Record):
    title: str = Field(min_length=1, max_length=120)
    shapes: tuple[Shape, ...] = Field(max_length=3000)
    diagnostics: tuple[dict, ...] = ()
    parameters: dict = Field(default_factory=dict)


class PluginResult(Record):
    schema_version: Literal['colayout-routing-result-1'] = 'colayout-routing-result-1'
    request_id: str
    source_digest: str
    candidates: tuple[Proposal, ...] = Field(max_length=3)
    diagnostics: tuple[dict, ...] = ()


class PluginManifest(Record):
    schema_version: Literal['colayout-router-plugin-1'] = 'colayout-router-plugin-1'
    id: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$')
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    description: str = Field(default='', max_length=1500)
    entry: str  # Relative .py script, receives --input and --output paths.
    timeout_seconds: int = Field(default=90, ge=1, le=180)

    @model_validator(mode='after')
    def entry_path(self):
        from pathlib import PureWindowsPath, PurePosixPath
        if (not self.entry.endswith('.py') or any('..' in p.parts or p.is_absolute()
                for p in (PureWindowsPath(self.entry), PurePosixPath(self.entry)))
                or PureWindowsPath(self.entry).drive):
            raise ValueError('entry must be a relative Python script inside the plugin directory')
        return self
