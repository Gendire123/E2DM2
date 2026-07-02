from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
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


PRO_PURCHASE_URL = "https://buy.stripe.com/fZu6oGeob02Sbgy6Q3aEE01"
ADMIN_TOOLS_ENV = "E2DM2_ENABLE_ADMIN_TOOLS"
ADMIN_API_ENV = "E2DM2_LICENSE_ADMIN_URL"
ADMIN_TOKEN_ENV = "E2DM2_ADMIN_ACCESS_TOKEN"
DEFAULT_ADMIN_API_URL = f"{SUPABASE_PROJECT_URL}/functions/v1/license-admin"
DEVELOPMENT_ROOT = Path(__file__).resolve().parent.parent
ADMIN_TOOLS_MARKER = DEVELOPMENT_ROOT / ".e2dm2-admin-tools"
BUILTIN_ADMIN_MARKER = DEVELOPMENT_ROOT / ".e2dm2-builtin-admin"


def _pro_shield_pixmap(size: int = 68) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setPen(QPen(QColor("#B9DDF6"), 1.5))
    painter.setBrush(QColor("#EAF6FF"))
    painter.drawEllipse(QRectF(2, 2, size - 4, size - 4))

    scale = size / 68
    shield = QPolygonF([
        QPointF(34 * scale, 11 * scale),
        QPointF(54 * scale, 19 * scale),
        QPointF(51 * scale, 43 * scale),
        QPointF(34 * scale, 57 * scale),
        QPointF(17 * scale, 43 * scale),
        QPointF(14 * scale, 19 * scale),
    ])
    gradient = QLinearGradient(18 * scale, 14 * scale, 50 * scale, 54 * scale)
    gradient.setColorAt(0, QColor("#39A6F4"))
    gradient.setColorAt(1, QColor("#0759C7"))
    painter.setPen(QPen(QColor("#0873D5"), 1.5))
    painter.setBrush(gradient)
    painter.drawPolygon(shield)

    check_pen = QPen(QColor("#FFFFFF"), 4 * scale)
    check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(check_pen)
    painter.drawPolyline(QPolygonF([
        QPointF(25 * scale, 33 * scale),
        QPointF(32 * scale, 40 * scale),
        QPointF(44 * scale, 26 * scale),
    ]))
    painter.end()
    return pixmap


def open_purchase_page() -> bool:
    return QDesktopServices.openUrl(QUrl(PRO_PURCHASE_URL))


def admin_tools_enabled() -> bool:
    """Enable admin tooling only for an explicitly opted-in source checkout."""
    if not (DEVELOPMENT_ROOT / "pyproject.toml").is_file():
        return False
    configured = os.environ.get(ADMIN_TOOLS_ENV)
    if configured is None:
        return ADMIN_TOOLS_MARKER.is_file()
    return configured.strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def builtin_library_admin_enabled() -> bool:
    """Enable showing the option to add to built-in song library."""
    if not (DEVELOPMENT_ROOT / "pyproject.toml").is_file():
        return False
    return BUILTIN_ADMIN_MARKER.is_file()


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
        self.success_page: QWidget | None = None
        self.pages.addWidget(self.info_page)
        self.pages.addWidget(self.code_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.addWidget(self.pages)
        if enter_code_first:
            self.pages.setCurrentWidget(self.code_page)
        self.resize(520, 310 if enter_code_first else 250)

    def _center_on_screen(self) -> None:
        parent = self.parentWidget()
        screen = (
            parent.screen() if parent is not None else None
        ) or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._center_on_screen()
        QTimer.singleShot(0, self._center_on_screen)

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

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        self.activate_button = QPushButton("Activate Pro")
        self.activate_button.setObjectName("primaryButton")
        self.activate_button.clicked.connect(self.activate)

        buttons = QHBoxLayout()
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

    def _build_success_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("licenseSuccessPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(14)

        verification_card = QFrame()
        verification_card.setObjectName("licenseVerificationCard")
        verification_card.setFixedSize(360, 108)
        verification_card.setStyleSheet(
            "QFrame#licenseVerificationCard { background: #F8FBFF; border: 1px solid #BFD8EE; "
            "border-radius: 12px; }"
        )
        card_shadow = QGraphicsDropShadowEffect(verification_card)
        card_shadow.setBlurRadius(22)
        card_shadow.setOffset(0, 5)
        card_shadow.setColor(QColor(16, 55, 94, 65))
        verification_card.setGraphicsEffect(card_shadow)

        verification_layout = QHBoxLayout(verification_card)
        verification_layout.setContentsMargins(22, 15, 22, 15)
        verification_layout.setSpacing(17)
        shield = QLabel()
        shield.setObjectName("licenseVerificationShield")
        shield.setFixedSize(72, 72)
        shield.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shield.setPixmap(_pro_shield_pixmap())

        verification_copy = QVBoxLayout()
        verification_copy.setSpacing(5)
        verification_copy.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        verification_title = QLabel("Pro License Active")
        verification_title.setObjectName("licenseVerificationTitle")
        verification_title.setStyleSheet("font-size: 13pt; font-weight: 750; color: #142033;")
        verification_detail = QLabel("You're a verified E2DM2 Pro owner.")
        verification_detail.setObjectName("licenseVerificationDetail")
        verification_detail.setStyleSheet("font-size: 9.5pt; color: #526173;")
        verification_copy.addWidget(verification_title)
        verification_copy.addWidget(verification_detail)
        verification_layout.addWidget(shield)
        verification_layout.addLayout(verification_copy, 1)

        title = QLabel("Welcome to E2DM2 Pro")
        title.setObjectName("licenseSuccessTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20pt; font-weight: 750; color: #142033;")

        description = QLabel(
            "Thanks for choosing E2DM2. Your Pro license is active, and these creative tools are now unlocked:"
        )
        description.setObjectName("licenseSuccessDescription")
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        description.setStyleSheet("font-size: 10.5pt; color: #526173;")

        features = QFrame()
        features.setObjectName("licenseSuccessFeatures")
        features.setStyleSheet(
            "QFrame#licenseSuccessFeatures { background: #F5F9FD; border: 1px solid #D6E4F0; "
            "border-radius: 10px; }"
        )
        features_layout = QVBoxLayout(features)
        features_layout.setContentsMargins(18, 14, 18, 14)
        features_layout.setSpacing(12)
        for feature_title, feature_description in (
            ("Custom soundtracks", "Import your own songs and build videos around your music."),
            ("Source-resolution rendering", "Export at your footage's original resolution for maximum detail."),
            ("Advanced song presets", "Create and edit cut timing, transitions, and visual effects."),
        ):
            row = QHBoxLayout()
            row.setSpacing(11)
            icon = QLabel("✓")
            icon.setFixedSize(24, 24)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setStyleSheet(
                "background: #0E62B7; color: white; border-radius: 12px; font-size: 10pt; font-weight: 800;"
            )
            copy = QVBoxLayout()
            copy.setSpacing(1)
            feature_label = QLabel(feature_title)
            feature_label.setStyleSheet("font-size: 10.5pt; font-weight: 700; color: #142033;")
            feature_detail = QLabel(feature_description)
            feature_detail.setWordWrap(True)
            feature_detail.setStyleSheet("font-size: 9.5pt; color: #526173;")
            copy.addWidget(feature_label)
            copy.addWidget(feature_detail)
            row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            row.addLayout(copy, 1)
            features_layout.addLayout(row)

        start_button = QPushButton("Start creating")
        start_button.setObjectName("primaryButton")
        start_button.setMinimumHeight(44)
        start_button.clicked.connect(self.accept)

        layout.addWidget(verification_card, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(features)
        layout.addSpacing(2)
        layout.addWidget(start_button)
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
            self.resize(max(self.width(), 520), 310 if target is self.code_page else 250)
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
        self.setWindowTitle("Welcome to E2DM2 Pro")
        if self.success_page is None:
            self.success_page = self._build_success_page()
            self.pages.addWidget(self.success_page)
        self.setMinimumSize(560, 570)
        self.resize(560, 570)
        self.pages.setCurrentWidget(self.success_page)
        self._center_on_screen()
        QTimer.singleShot(0, self._center_on_screen)


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
