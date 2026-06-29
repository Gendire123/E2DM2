from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from e2dm2.editor import SongEditorDialog
from e2dm2.entitlements import (
    CUSTOM_SONG_IMPORT_FEATURE,
    SOURCE_RESOLUTION_FEATURE,
    LicenseActivationError,
    LocalLicenseProvider,
    is_valid_license_code,
    normalize_license_code,
)
from e2dm2.licensing_ui import (
    ADMIN_TOKEN_ENV,
    ADMIN_TOOLS_ENV,
    AdminToolsDialog,
    ProLicenseDialog,
    admin_tools_enabled,
)
from e2dm2.ui import MainWindow, WorkspacePage


class FakeLicenseApi:
    def __init__(self) -> None:
        self.calls = []

    def activate(self, code: str, device_id: str) -> dict:
        self.calls.append((code, device_id))
        return {"valid": True, "activation_token": "server-token"}

    def deactivate(self, token: str, device_id: str) -> None:
        self.calls.append(("deactivate", token, device_id))


class MutableEntitlement:
    def __init__(self, active: bool = False) -> None:
        self.active = active

    def has_feature(self, feature: str) -> bool:
        return self.active and feature in {CUSTOM_SONG_IMPORT_FEATURE, SOURCE_RESOLUTION_FEATURE}


def test_license_code_normalization_is_paste_friendly():
    assert normalize_license_code(" e43 sd2-dfd_qw2 fdq ") == "E43-SD2-DFD-QW2-FDQ"
    assert is_valid_license_code("e43-sd2-dfd-qw2-fdq")
    assert not is_valid_license_code("E43-SD2")


def test_local_license_activates_only_after_server_validation(tmp_path):
    settings = QSettings(str(tmp_path / "license.ini"), QSettings.Format.IniFormat)
    api = FakeLicenseApi()
    provider = LocalLicenseProvider(settings, api)

    assert not provider.has_feature(SOURCE_RESOLUTION_FEATURE)
    provider.activate("e43 sd2 dfd qw2 fdq")

    assert provider.has_feature(SOURCE_RESOLUTION_FEATURE)
    assert api.calls[0][0] == "E43-SD2-DFD-QW2-FDQ"
    assert settings.value("license/code_hint") == "FDQ"
    assert not settings.contains("license/code")


def test_local_license_rejects_malformed_code_without_network(tmp_path):
    settings = QSettings(str(tmp_path / "license.ini"), QSettings.Format.IniFormat)
    api = FakeLicenseApi()
    provider = LocalLicenseProvider(settings, api)

    try:
        provider.activate("not-a-key")
    except LicenseActivationError:
        pass
    else:
        raise AssertionError("Malformed key should not activate")
    assert api.calls == []


def test_local_license_deactivation_releases_receipt_and_keeps_device_id(tmp_path):
    settings = QSettings(str(tmp_path / "license.ini"), QSettings.Format.IniFormat)
    api = FakeLicenseApi()
    provider = LocalLicenseProvider(settings, api)
    provider.activate("E43-SD2-DFD-QW2-FDQ")
    device_id = provider.device_id()

    provider.deactivate()

    assert not provider.is_pro
    assert not settings.contains("license/activation_token")
    assert provider.device_id() == device_id
    assert api.calls[-1] == ("deactivate", "server-token", device_id)


def test_source_resolution_click_prompts_free_user(qtbot):
    entitlement = MutableEntitlement()
    prompts = []
    page = WorkspacePage(entitlement, lambda feature: prompts.append(feature) or False)
    qtbot.addWidget(page)

    assert page.hd_export.isChecked()
    assert not page.source_export.isChecked()
    page.source_export.click()

    assert prompts == ["Source resolution exports"]
    assert page.hd_export.isChecked()
    assert not page.source_export.isChecked()
    assert page.selected_exports() != []


def test_source_resolution_click_continues_after_activation(qtbot):
    entitlement = MutableEntitlement()

    def activate(_feature: str) -> bool:
        entitlement.active = True
        return True

    page = WorkspacePage(entitlement, activate)
    qtbot.addWidget(page)
    page.source_export.click()

    assert page.source_export.isChecked()
    assert not page.hd_export.isChecked()


def test_new_song_click_prompts_free_user(qtbot):
    entitlement = MutableEntitlement()
    prompts = []
    dialog = SongEditorDialog(
        entitlement,
        request_pro=lambda feature: prompts.append(feature) or False,
    )
    qtbot.addWidget(dialog)
    original_count = len(dialog.songs)

    dialog.new_button.click()

    assert prompts == ["Importing your own songs"]
    assert len(dialog.songs) == original_count


def test_license_dialog_formats_pasted_code(qtbot, tmp_path):
    provider = LocalLicenseProvider(
        QSettings(str(tmp_path / "license.ini"), QSettings.Format.IniFormat),
        FakeLicenseApi(),
    )
    dialog = ProLicenseDialog(provider, enter_code_first=True)
    qtbot.addWidget(dialog)

    dialog._format_code("e43 sd2 dfd qw2 fdq")

    assert dialog.code_edit.text() == "E43-SD2-DFD-QW2-FDQ"
    assert dialog.pages.currentWidget() is dialog.code_page


def test_admin_tools_are_visible_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv(ADMIN_TOOLS_ENV, raising=False)
    assert admin_tools_enabled()

    monkeypatch.setenv(ADMIN_TOOLS_ENV, "0")
    assert not admin_tools_enabled()


def test_view_menu_contains_temporary_admin_tools(qtbot, monkeypatch):
    monkeypatch.delenv(ADMIN_TOOLS_ENV, raising=False)
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.admin_tools_action is not None
    assert window.admin_tools_action.text() == "Admin Tools"


def test_purchase_menu_actions_follow_live_license_state(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "license.ini"), QSettings.Format.IniFormat)
    provider = LocalLicenseProvider(settings, FakeLicenseApi())
    window = MainWindow(provider)
    qtbot.addWidget(window)

    assert window.purchase_pro_action.isVisible()
    assert window.enter_license_action.isVisible()
    provider.activate("E43-SD2-DFD-QW2-FDQ")
    window.license_activated()
    assert not window.purchase_pro_action.isVisible()
    assert not window.enter_license_action.isVisible()

    provider.deactivate()
    window.license_deactivated()
    assert window.purchase_pro_action.isVisible()
    assert window.enter_license_action.isVisible()


def test_admin_license_bought_button_calls_protected_endpoint(qtbot, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"sent": true}'

    requests = []
    monkeypatch.setenv(ADMIN_TOKEN_ENV, "short-lived-user-jwt")
    monkeypatch.setattr(
        "e2dm2.licensing_ui.urllib.request.urlopen",
        lambda request, timeout: requests.append(request) or Response(),
    )
    dialog = AdminToolsDialog()
    qtbot.addWidget(dialog)
    dialog.email_edit.setText("buyer@example.com")

    dialog.issue_button.click()

    assert len(requests) == 1
    assert requests[0].get_header("Authorization") == "Bearer short-lived-user-jwt"
    assert dialog.status.text() == "A new Pro license was sent to buyer@example.com."


def test_admin_dialog_shows_safe_backend_error(qtbot, monkeypatch):
    monkeypatch.setenv(ADMIN_TOKEN_ENV, "short-lived-user-jwt")

    def rejected(*_args, **_kwargs):
        raise HTTPError(
            "https://example.invalid",
            502,
            "Bad Gateway",
            {},
            BytesIO(b'{"error":"Resend rejected the sender domain."}'),
        )

    monkeypatch.setattr("e2dm2.licensing_ui.urllib.request.urlopen", rejected)
    dialog = AdminToolsDialog()
    qtbot.addWidget(dialog)
    dialog.email_edit.setText("buyer@example.com")

    dialog.issue_button.click()

    assert dialog.status.text() == "Could not issue license: Resend rejected the sender domain."


def test_admin_dialog_can_deactivate_this_copy(qtbot, tmp_path, monkeypatch):
    settings = QSettings(str(tmp_path / "license.ini"), QSettings.Format.IniFormat)
    provider = LocalLicenseProvider(settings, FakeLicenseApi())
    provider.activate("E43-SD2-DFD-QW2-FDQ")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog = AdminToolsDialog(license_provider=provider)
    qtbot.addWidget(dialog)
    deactivated = []
    dialog.license_deactivated.connect(lambda: deactivated.append(True))

    dialog.deactivate_button.click()

    assert not provider.is_pro
    assert not dialog.deactivate_button.isEnabled()
    assert deactivated == [True]
    assert "activation slot is available again" in dialog.status.text()
