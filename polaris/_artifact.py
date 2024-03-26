import json
from typing import Dict, Optional, Union

import fsspec
from loguru import logger
from packaging.version import Version
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
)
from pydantic.alias_generators import to_camel

import polaris as po
from polaris.utils.misc import sluggify
from polaris.utils.types import HubOwner, SlugCompatibleStringType


class BaseArtifactModel(BaseModel):
    """
    Base class for all artifacts on the Hub. Specifies meta-data that is used by the Hub.

    Info: Optional
        Despite all artifacts basing this class, note that all attributes are optional.
        This ensures the library can be used without the Polaris Hub.
        Only when uploading to the Hub, some of the attributes are required.

    Attributes:
        name: A slug-compatible name for the dataset.
            Together with the owner, this is used by the Hub to uniquely identify the benchmark.
        description: A beginner-friendly, short description of the dataset.
        tags: A list of tags to categorize the benchmark by. This is used by the hub to search over benchmarks.
        user_attributes: A dict with additional, textual user attributes.
        owner: A slug-compatible name for the owner of the dataset.
            If the dataset comes from the Polaris Hub, this is the associated owner (organization or user).
            Together with the name, this is used by the Hub to uniquely identify the benchmark.
        version: The version of the Polaris library that was used to create the artifact.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, arbitrary_types_allowed=True)

    name: Optional[SlugCompatibleStringType] = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    user_attributes: Dict[str, str] = Field(default_factory=dict)
    owner: Optional[HubOwner] = None
    version: Optional[Union[str, Version]] = Field(
        default_factory=lambda: Version(po.__version__) if po.__version__ != "dev" else None
    )

    @computed_field
    @property
    def artifact_id(self) -> Optional[str]:
        return f"{self.owner}/{sluggify(self.name)}" if self.owner and self.name else None

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: Union[str, Version]):
        current_version = Version(po.__version__)
        if value is None:
            value = current_version
        elif isinstance(value, str):
            if value != "dev":
                value = Version(value)

        if value is not None and value != current_version:
            logger.info(
                f"The Polaris version that was used to create the artifact ({value}) is different from "
                f"the currently installed version of Polaris ({current_version})."
            )
        if not isinstance(value, Version):
            raise ValueError(f"Version must be a string or Version object. Got: {type(value)}")
        return value

    @field_validator("owner", mode="before")
    @classmethod
    def _validate_owner(cls, value: Union[str, HubOwner, None]):
        if isinstance(value, str):
            return HubOwner(slug=value)
        return value

    @field_serializer("version")
    def _serialize_version(self, value: Version) -> str:
        return str(value)

    @field_serializer("owner")
    def _serialize_owner(self, value: HubOwner) -> Union[str, None]:
        return value.slug if value else None

    @classmethod
    def from_json(cls, path: str):
        """Loads a benchmark from a JSON file.

        Args:
            path: Loads a benchmark specification from a JSON file.
        """
        with fsspec.open(path, "r") as f:
            data = json.load(f)
        return cls.model_validate(data)

    def to_json(self, path: str):
        """Saves the benchmark to a JSON file.

        Args:
            path: Saves the benchmark specification to a JSON file.
        """
        with fsspec.open(path, "w") as f:
            json.dump(self.model_dump(), f)
