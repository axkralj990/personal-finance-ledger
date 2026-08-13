from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.database.models import ImportMappingTemplateOrigin
from backend.app.imports.models import ImportInspection, UniversalMappingSpec
from backend.app.imports.openai_mapping import MappingSuggestionPayload, MappingSuggestionResult


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RevisionRequest(StrictRequest):
    expected_revision: int = Field(ge=1)


class LifecycleRequest(RevisionRequest):
    pass


class InspectionPatch(RevisionRequest):
    selected_sheet: str | int | None = None
    header_row: int | None = Field(default=None, ge=1)
    confirm_restaging: bool = False


class TemplateProposal(BaseModel):
    template_id: str
    template_version_id: str
    name: str
    scope: Literal["ACCOUNT", "GLOBAL"]
    origin: ImportMappingTemplateOrigin
    execution_plan: UniversalMappingSpec


class MappingProposals(BaseModel):
    templates: list[TemplateProposal]
    universal: UniversalMappingSpec | None


class InspectionRead(BaseModel):
    batch_id: str
    revision: int
    inspection: ImportInspection
    proposals: MappingProposals


class MappingPreviewRequest(StrictRequest):
    execution_plan: UniversalMappingSpec
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=100)


class MappedRowPreview(BaseModel):
    row_number: int
    raw: dict
    transaction_date: str | None
    transaction_at: str | None
    description: str | None
    amount_minor: int | None
    currency: str | None
    disposition: str
    issues: list[dict]


class MappingPreviewRead(BaseModel):
    total_rows: int
    importable_rows: int
    error_rows: int
    audit_rows: int
    rows: list[MappedRowPreview]


class MappingConfirmRequest(RevisionRequest):
    execution_plan: UniversalMappingSpec
    source_template_id: str | None = None
    source_template_version_id: str | None = None
    confirm_restaging: bool = False

    @model_validator(mode="after")
    def complete_template_reference(self) -> MappingConfirmRequest:
        if (self.source_template_id is None) != (self.source_template_version_id is None):
            raise ValueError("template ID and version ID must be provided together")
        return self


class MappingConfirmRead(BaseModel):
    batch_id: str
    revision: int
    mapping_revision: int
    execution_plan: UniversalMappingSpec


class StageRequest(RevisionRequest):
    expected_mapping_revision: int = Field(ge=1)


class SuggestionPayloadRead(BaseModel):
    batch_id: str
    revision: int
    sha256: str
    payload: MappingSuggestionPayload


class SuggestionRequest(RevisionRequest):
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consent: Literal[True]


class SuggestionRead(BaseModel):
    batch_id: str
    revision: int
    result: MappingSuggestionResult


class TemplateCreate(StrictRequest):
    name: str = Field(min_length=1, max_length=120)
    structural_signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    account_id: str | None = None
    execution_plan: UniversalMappingSpec
    source_batch_id: str | None = None
    source_batch_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def complete_suggestion_reference(self) -> TemplateCreate:
        if (self.source_batch_id is None) != (self.source_batch_revision is None):
            raise ValueError("source batch ID and revision must be provided together")
        return self


class TemplatePatch(RevisionRequest):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    execution_plan: UniversalMappingSpec | None = None


class TemplateVersionRead(BaseModel):
    id: str
    version: int
    execution_plan: UniversalMappingSpec
    created_at: datetime


class TemplateRead(BaseModel):
    id: str
    name: str
    structural_signature: str
    account_id: str | None
    origin: ImportMappingTemplateOrigin
    is_active: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    current_version: TemplateVersionRead
    versions: list[TemplateVersionRead] = Field(default_factory=list)
