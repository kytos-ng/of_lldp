"""DB models."""
# pylint: disable=unused-argument,invalid-name,unsubscriptable-object
# pylint: disable=no-name-in-module

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DocumentBaseModel(BaseModel):
    """DocumentBaseModel."""

    id: str = Field(None, alias="_id")
    inserted_at: Optional[datetime]
    updated_at: Optional[datetime]

    def dict(self, **kwargs) -> dict:
        """Model to dict."""
        values = super().dict(**kwargs)
        if "id" in values and values["id"]:
            values["_id"] = values["id"]
        if "exclude" in kwargs and "_id" in kwargs["exclude"]:
            values.pop("_id")
        return values


class LivenessDoc(DocumentBaseModel):
    """Liveness document model."""

    enabled: bool
