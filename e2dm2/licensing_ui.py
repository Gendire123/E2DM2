from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .entitlements import (
    LicenseActivationError,
    LocalLicenseProvider,
    SUPABASE_PROJECT_URL,
    is_valid_license_code,
    normalize_license_code,
)


PRO_PURCHASE_URL = "https://www.e2dm2.com"
ADMIN_TOOLS_ENV = "E2DM2_ENABLE_ADMIN_TOOLS"
ADMIN_API_ENV = "E2DM2_LICENSE_ADMIN_URL"
ADMIN_TOKEN_ENV = "E2DM2_ADMIN_ACCESS_TOKEN"
DEFAULT_ADMIN_API_URL = f"{SUPABASE_PROJECT_URL}/functions/v1/license-admin"


def open_purchase_page() -> bool:
    return QDesktopServices.openUrl(QUrl(PRO_PURCHASE_URL))


def admin_tools_enabled() -> bool:
    """Show temporary development tooling unless a build explicitly disables it."""
    return os.environ.get(ADMIN_TOOLS_ENV, "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


class ProLicenseDialog(QDialog):
    activated = Signal()

    def __init__(
        self,
        license_provider: LocalLicenseProvider,
        parent: QWidget | None = None,
        feature_name: str | None = None,
        enter_code_first: bool = False,
    ) -> None:
        super().__init__(parent)
        self.license_provider = license_provider
        self.feature_name = feature_name
        self.setWindowTitle("E2DM2 Pro License")
        self.setModal(True)
        self.setMinimumWidth(500)

        self.pages = QStackedWidget()
        self.pages.setObjectName("proLicensePages")
        self.info_page = self._build_info_page()
        self.code_page = self._build_code_page()
        self.pages.addWidget(self.info_page)
        self.pages.addWidget(self.code_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.addWidget(self.pages)
        if enter_code_first:
            self.pages.setCurrentWidget(self.code_page)

    def _build_info_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = QLabel("Unlock E2DM2 Pro")
        title.setObjectName("licenseTitle")
        title.setStyleSheet("font-size: 18pt; font-weight: 700; color: #142033;")
        message = self.feature_name or "This feature"
        description = QLabel(
            f"{message} is available with an E2DM2 Pro license. Purchase a license, "
            "or enter a code you already received by email."
        )
        description.setWordWrap(True)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buy_button = QPushButton("Buy license")
        buy_button.clicked.connect(open_purchase_page)
        enter_button = QPushButton("Enter Pro license code")
        enter_button.setObjectName("primaryButton")
        enter_button.clicked.connect(lambda: self._switch_page(self.code_page))

        buttons = QHBoxLayout()
        buttons.addWidget(close_button)
        buttons.addStretch(1)
        buttons.addWidget(buy_button)
        buttons.addWidget(enter_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _build_code_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("Enter Pro License Code")
        title.setStyleSheet("font-size: 18pt; font-weight: 700; color: #142033;")
        description = QLabel(
            "Paste the activation key from your purchase email. Letters are automatically capitalized."
        )
        description.setWordWrap(True)
        self.code_edit = QLineEdit()
        self.code_edit.setObjectName("proLicenseCode")
        self.code_edit.setPlaceholderText("ABC-123-DEF-456-GHI")
        self.code_edit.setMaxLength(19)
        self.code_edit.setClearButtonEnabled(True)
        self.code_edit.textEdited.connect(self._format_code)
        self.code_edit.returnPressed.connect(self.activate)
        self.code_error = QLabel()
        self.code_error.setObjectName("licenseError")
        self.code_error.setStyleSheet("color: #B42318;")
        self.code_error.setWordWrap(True)

        back_button = QPushButton("Back")
        back_button.clicked.connect(lambda: self._switch_page(self.info_page))
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        self.activate_button = QPushButton("Activate Pro")
        self.activate_button.setObjectName("primaryButton")
        self.activate_button.clicked.connect(self.activate)

        buttons = QHBoxLayout()
        buttons.addWidget(back_button)
        buttons.addWidget(close_button)
        buttons.addStretch(1)
        buttons.addWidget(self.activate_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.code_edit)
        layout.addWidget(self.code_error)
        layout.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _format_code(self, value: str) -> None:
        formatted = normalize_license_code(value)
        if value != formatted:
            cursor = len(formatted)
            self.code_edit.blockSignals(True)
            self.code_edit.setText(formatted)
            self.code_edit.setCursorPosition(cursor)
            self.code_edit.blockSignals(False)
        self.code_error.clear()

    def _switch_page(self, target: QWidget) -> None:
        if self.pages.currentWidget() is target:
            return
        effect = QGraphicsOpacityEffect(self.pages)
        self.pages.setGraphicsEffect(effect)
        fade_out = QPropertyAnimation(effect, b"opacity", self)
        fade_out.setDuration(130)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def show_target() -> None:
            self.pages.setCurrentWidget(target)
            fade_in = QPropertyAnimation(effect, b"opacity", self)
            fade_in.setDuration(170)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)
            fade_in.finished.connect(lambda: self.pages.setGraphicsEffect(None))
            self._page_animation = fade_in
            fade_in.start()
            if target is self.code_page:
                self.code_edit.setFocus(Qt.FocusReason.OtherFocusReason)

        fade_out.finished.connect(show_target)
        self._page_animation = fade_out
        fade_out.start()

    def activate(self) -> None:
        code = normalize_license_code(self.code_edit.text())
        self.code_edit.setText(code)
        if not is_valid_license_code(code):
            self.code_error.setText("Use the format ABC-123-DEF-456-GHI.")
            return
        self.activate_button.setEnabled(False)
        self.code_error.setText("Activating license…")
        try:
            self.license_provider.activate(code)
        except LicenseActivationError as exc:
            self.code_error.setText(str(exc))
            self.activate_button.setEnabled(True)
            return
        self.activated.emit()
        QMessageBox.information(self, "E2DM2 Pro", "Your Pro license is now active.")
        self.accept()


class AdminToolsDialog(QDialog):
    """Development-only client; all authorization remains in the Edge Function."""

    license_deactivated = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        license_provider: LocalLicenseProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self.license_provider = license_provider
        self.setWindowTitle("Admin Tools — Development Only")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        warning = QLabel(
            "This tool calls the protected Supabase admin function. It contains no service-role or Resend secret."
        )
        warning.setWordWrap(True)
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("Customer email")
        self.token_edit = QLineEdit(os.environ.get(ADMIN_TOKEN_ENV, ""))
        self.token_edit.setPlaceholderText("Supabase admin access token")
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.issue_button = QPushButton("License bought")
        self.issue_button.setObjectName("primaryButton")
        self.issue_button.clicked.connect(self.issue_license)
        self.deactivate_button = QPushButton("Deactivate this copy")
        self.deactivate_button.setEnabled(
            bool(self.license_provider and self.license_provider.is_pro)
        )
        self.deactivate_button.clicked.connect(self.deactivate_copy)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(close_button)
        buttons.addWidget(self.deactivate_button)
        buttons.addStretch(1)
        buttons.addWidget(self.issue_button)
        layout.addWidget(warning)
        layout.addWidget(QLabel("Send the test license to:"))
        layout.addWidget(self.email_edit)
        layout.addWidget(QLabel("Admin session token:"))
        layout.addWidget(self.token_edit)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    def issue_license(self) -> None:
        endpoint = os.environ.get(ADMIN_API_ENV, DEFAULT_ADMIN_API_URL).strip()
        email = self.email_edit.text().strip()
        token = self.token_edit.text().strip()
        if not endpoint or not email or not token:
            self.status.setText(
                "Enter a customer email and a short-lived Supabase admin access token."
            )
            return
        request = urllib.request.Request(
            endpoint,
            data=json.dumps({"email": email}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="POST",
        )
        self.issue_button.setEnabled(False)
        self.status.setText("Creating and emailing the license…")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not result.get("sent"):
                raise RuntimeError(str(result.get("error", "The license was not sent.")))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error")
            except (ValueError, AttributeError):
                detail = None
            self.status.setText(
                f"Could not issue license: {detail or f'HTTP {exc.code}'}"
            )
        except (urllib.error.URLError, OSError, ValueError, RuntimeError) as exc:
            self.status.setText(f"Could not issue license: {exc}")
        else:
            self.status.setText(f"A new Pro license was sent to {email}.")
            self.email_edit.clear()
        finally:
            self.issue_button.setEnabled(True)

    def deactivate_copy(self) -> None:
        if not self.license_provider or not self.license_provider.is_pro:
            self.status.setText("This copy does not have an active Pro license.")
            self.deactivate_button.setEnabled(False)
            return
        answer = QMessageBox.question(
            self,
            "Deactivate E2DM2 Pro?",
            "Deactivate Pro on this copy and release its activation slot?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.deactivate_button.setEnabled(False)
        self.status.setText("Deactivating this copy…")
        try:
            self.license_provider.deactivate()
        except LicenseActivationError as exc:
            self.status.setText(f"Could not deactivate this copy: {exc}")
            self.deactivate_button.setEnabled(True)
            return
        self.status.setText(
            "This copy has been deactivated. The activation slot is available again."
        )
        self.license_deactivated.emit()
