from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import uuid
from typing import Protocol

from PySide6.QtCore import QSettings


PRESET_EDITOR_FEATURE = "preset_editor"
CUSTOM_SONG_IMPORT_FEATURE = "custom_song_import"
SOURCE_RESOLUTION_FEATURE = "source_resolution"
PRO_FEATURES = frozenset(
    {PRESET_EDITOR_FEATURE, CUSTOM_SONG_IMPORT_FEATURE, SOURCE_RESOLUTION_FEATURE}
)
LICENSE_PATTERN = re.compile(r"^[A-Z0-9]{3}(?:-[A-Z0-9]{3}){4}$")
LICENSE_API_ENV = "E2DM2_LICENSE_API_URL"
SUPABASE_PROJECT_URL = "https://kzozxeyktwxcsukkheah.supabase.co"
DEFAULT_LICENSE_API_URL = f"{SUPABASE_PROJECT_URL}/functions/v1/license-activate"


class EntitlementProvider(Protocol):
    def has_feature(self, feature: str) -> bool: ...


def normalize_license_code(value: str) -> str:
    """Return a pasted key in the canonical ABC-123-DEF-456-GHI form."""
    compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()[:15]
    return "-".join(compact[index : index + 3] for index in range(0, len(compact), 3))


def is_valid_license_code(value: str) -> bool:
    return LICENSE_PATTERN.fullmatch(normalize_license_code(value)) is not None


class LicenseActivationError(RuntimeError):
    pass


class LicenseApiClient:
    """Small HTTP boundary for the Supabase activation Edge Function."""

    def __init__(self, endpoint: str | None = None, timeout: float = 10.0) -> None:
        self.endpoint = (
            endpoint or os.environ.get(LICENSE_API_ENV) or DEFAULT_LICENSE_API_URL
        ).strip()
        self.timeout = timeout

    def activate(self, license_code: str, device_id: str) -> dict:
        if not self.endpoint:
            raise LicenseActivationError(
                f"License activation is not configured. Set {LICENSE_API_ENV} to the "
                "Supabase license-activate function URL."
            )
        payload = json.dumps(
            {"license_code": normalize_license_code(license_code), "device_id": device_id}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except (ValueError, AttributeError):
                detail = None
            raise LicenseActivationError(detail or "The license code could not be activated.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LicenseActivationError(
                "E2DM2 could not reach the license service. Check your internet connection and try again."
            ) from exc
        except (ValueError, TypeError) as exc:
            raise LicenseActivationError("The license service returned an invalid response.") from exc

        if not isinstance(result, dict):
            raise LicenseActivationError("The license service returned an invalid response.")
        if not result.get("valid"):
            raise LicenseActivationError(str(result.get("error", "This license code is not valid.")))
        if not isinstance(result.get("activation_token"), str) or not result["activation_token"].strip():
            raise LicenseActivationError("The license service did not return an activation receipt.")
        return result

    def deactivate(self, activation_token: str, device_id: str) -> None:
        payload = json.dumps(
            {
                "action": "deactivate",
                "activation_token": activation_token,
                "device_id": device_id,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except (ValueError, AttributeError):
                detail = None
            raise LicenseActivationError(
                detail or "This copy could not be deactivated."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LicenseActivationError(
                "E2DM2 could not reach the license service. Check your internet connection and try again."
            ) from exc
        except (ValueError, TypeError) as exc:
            raise LicenseActivationError("The license service returned an invalid response.") from exc
        if not isinstance(result, dict) or not result.get("deactivated"):
            raise LicenseActivationError("The license service did not confirm deactivation.")


class LocalLicenseProvider:
    """Persist the locally activated Pro state; validation happens at the API boundary."""

    def __init__(
        self,
        settings: QSettings | None = None,
        api_client: LicenseApiClient | None = None,
    ) -> None:
        self.settings = settings if settings is not None else QSettings()
        self.api_client = api_client or LicenseApiClient()

    @property
    def is_pro(self) -> bool:
        return True

    def has_feature(self, feature: str) -> bool:
        return True

    def device_id(self) -> str:
        value = str(self.settings.value("license/device_id", "")).strip()
        if not value:
            value = str(uuid.uuid4())
            self.settings.setValue("license/device_id", value)
            self.settings.sync()
        return value

    def activate(self, license_code: str) -> None:
        normalized = normalize_license_code(license_code)
        if not is_valid_license_code(normalized):
            raise LicenseActivationError(
                "Enter a license code in the format ABC-123-DEF-456-GHI."
            )
        result = self.api_client.activate(normalized, self.device_id())
        self.settings.setValue("license/pro_active", True)
        self.settings.setValue("license/code_hint", normalized[-3:])
        self.settings.setValue("license/activation_token", result["activation_token"])
        self.settings.sync()

    def deactivate(self) -> None:
        token = str(self.settings.value("license/activation_token", "")).strip()
        if not self.is_pro or not token:
            raise LicenseActivationError("This copy does not have an active Pro license.")
        self.api_client.deactivate(token, self.device_id())
        self.settings.remove("license/pro_active")
        self.settings.remove("license/code_hint")
        self.settings.remove("license/activation_token")
        self.settings.sync()


class AlphaEntitlementProvider:
    """Test/development provider that unlocks every currently defined Pro feature."""

    def has_feature(self, feature: str) -> bool:
        return feature in PRO_FEATURES
