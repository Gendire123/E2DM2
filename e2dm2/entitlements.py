from __future__ import annotations

from typing import Protocol


PRESET_EDITOR_FEATURE = "preset_editor"


class EntitlementProvider(Protocol):
    def has_feature(self, feature: str) -> bool: ...


class AlphaEntitlementProvider:
    def has_feature(self, feature: str) -> bool:
        return feature == PRESET_EDITOR_FEATURE

