"""Universal response contract for the OpsPilot Services layer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


CONTRACT_VERSION = "1.0.0"


# ============================================================
# RESPONSE MODELS
# ============================================================

class ServiceMetadata(BaseModel):
    """Identifies the service producing the response."""

    model_config = ConfigDict(extra="forbid")

    name: str
    category: str
    subcategory: str
    description: str


class ServiceError(BaseModel):
    """Standardized service-level error information."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class ServiceOutputs(BaseModel):
    """Standard container for service-specific results."""

    model_config = ConfigDict(extra="forbid")

    data: Any = None
    pagination: dict[str, Any] | None = None


class ServiceResponse(BaseModel):
    """
    Universal response envelope used by every OpsPilot service.

    This model defines the response structure only.
    Business validation, input selection, output construction,
    and data-exposure decisions belong to the individual service.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool

    http_status: int = Field(ge=100, le=599)

    contract_version: str = CONTRACT_VERSION

    service: ServiceMetadata

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    request_id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    inputs: dict[str, Any] = Field(default_factory=dict)

    outputs: ServiceOutputs = Field(
        default_factory=ServiceOutputs
    )

    error: ServiceError | None = None


# ============================================================
# SUCCESS RESPONSE BUILDER
# ============================================================

def service_success(
    *,
    name: str,
    category: str,
    subcategory: str,
    description: str,
    data: Any = None,
    inputs: dict[str, Any] | None = None,
    pagination: dict[str, Any] | None = None,
    http_status: int = 200,
    request_id: str | None = None,
) -> ServiceResponse:
    """Build a standardized successful service response."""

    return ServiceResponse(
        success=True,
        http_status=http_status,
        service=ServiceMetadata(
            name=name,
            category=category,
            subcategory=subcategory,
            description=description,
        ),
        request_id=request_id or str(uuid4()),
        inputs=inputs or {},
        outputs=ServiceOutputs(
            data=data,
            pagination=pagination,
        ),
        error=None,
    )


# ============================================================
# FAILURE RESPONSE BUILDER
# ============================================================

def service_failure(
    *,
    name: str,
    category: str,
    subcategory: str,
    description: str,
    code: str,
    message: str,
    http_status: int,
    inputs: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
    request_id: str | None = None,
) -> ServiceResponse:
    """Build a standardized failed service response."""

    return ServiceResponse(
        success=False,
        http_status=http_status,
        service=ServiceMetadata(
            name=name,
            category=category,
            subcategory=subcategory,
            description=description,
        ),
        request_id=request_id or str(uuid4()),
        inputs=inputs or {},
        outputs=ServiceOutputs(
            data=None,
            pagination=None,
        ),
        error=ServiceError(
            code=code,
            message=message,
            details=details or {},
            retryable=retryable,
        ),
    )