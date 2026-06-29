from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QSettings,
    QTimer,
    Property,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QBrush,
    QPixmap,
)
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QPushButton,
    QCheckBox,
    QHBoxLayout,
    QVBoxLayout,
    QGraphicsDropShadowEffect,
    QDialog,
)

LOGGER = logging.getLogger(__name__)

# ==============================================================================
# TWEAKABLE CONFIGURATION VARIABLES FOR ALIGNMENT AND STYLE
# ==============================================================================
# If the highlight spotlight or the popup card is not aligned to your liking,
# you can easily adjust these variables. The application will immediately
# respect these changes upon restart.
# ==============================================================================
SPOTLIGHT_PADDING = 8            # Extra padding around the target widget (pixels)
SPOTLIGHT_ROUNDNESS = 10         # Corner roundness of the spotlight highlight (pixels)
SPOTLIGHT_BORDER_WIDTH = 2.5     # Outline border thickness of the spotlight (pixels)
SPOTLIGHT_OFFSET_X = 0           # Manual horizontal offset to shift the spotlight (pixels)
SPOTLIGHT_OFFSET_Y = -48           # Manual vertical offset to shift the spotlight (pixels)
POPUP_MARGIN = 12                # Vertical gap between the spotlight and the popup card (pixels)
BACKGROUND_MASK_OPACITY = 180    # Dimming intensity of the background overlay (0 to 255)
GLOW_COLOR = QColor(14, 86, 170)  # Primary theme blue color for the glowing highlights
MASK_COLOR = QColor(15, 23, 42)   # Dark slate base color of the background mask
# ==============================================================================


def onboarding_enabled(settings: QSettings | None = None) -> bool:
    """Check if the onboarding tour is enabled."""
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return False
    settings = settings or QSettings()
    return settings.value("startup/show_onboarding", True, type=bool)


def welcome_modal_enabled(settings: QSettings | None = None) -> bool:
    """Check if the welcome modal is enabled."""
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return False
    settings = settings or QSettings()
    return settings.value("startup/show_welcome_modal", True, type=bool)


def workspace_onboarding_enabled(settings: QSettings | None = None) -> bool:
    """Check if the workspace onboarding tour is enabled."""
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return False
    settings = settings or QSettings()
    return settings.value("startup/show_workspace_onboarding", True, type=bool)


def preview_onboarding_enabled(settings: QSettings | None = None) -> bool:
    """Check if the preview onboarding tour is enabled."""
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return False
    settings = settings or QSettings()
    return settings.value("startup/show_preview_onboarding", True, type=bool)


def soundtrack_onboarding_enabled(settings: QSettings | None = None) -> bool:
    """Check if the soundtrack onboarding tour is enabled."""
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return False
    settings = settings or QSettings()
    return settings.value("startup/show_soundtrack_onboarding", True, type=bool)


def library_onboarding_enabled(settings: QSettings | None = None) -> bool:
    """Check if the library editor onboarding tour is enabled."""
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return False
    settings = settings or QSettings()
    return settings.value("startup/show_library_onboarding", True, type=bool)


def produce_onboarding_enabled(settings: QSettings | None = None) -> bool:
    """Check if the produce onboarding tour is enabled."""
    if "pytest" in sys.modules or "unittest" in sys.modules:
        return False
    settings = settings or QSettings()
    return settings.value("startup/show_produce_onboarding", True, type=bool)


class WelcomeDialog(QDialog):
    """A beautiful welcome dialog shown on first startup before onboarding."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to E2DM2")
        self.setObjectName("welcomeDialog")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(490, 520)

        # Main background card (centered inside dialog with padding for shadow)
        card = QFrame(self)
        card.setObjectName("welcomeCard")
        card.setFixedSize(450, 480)
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(15, 23, 42, 60))
        shadow.setOffset(0, 8)
        card.setGraphicsEffect(shadow)

        # Logo
        logo_label = QLabel()
        logo_label.setObjectName("welcomeLogo")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = Path(__file__).parent / "assets" / "logo_small.jpg"
        logo_pixmap = QPixmap(str(logo_path))
        if not logo_pixmap.isNull():
            logo_label.setPixmap(logo_pixmap.scaled(
                280, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            ))
        else:
            logo_label.setText("E2DM2")
            logo_label.setStyleSheet("font-size: 28pt; font-weight: bold; color: #0E56AA; font-family: 'Segoe UI';")

        # Title
        title_label = QLabel("Welcome to E2DM2")
        title_label.setObjectName("welcomeTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Description
        desc_label = QLabel(
            "Easy Epic Drone Movie Maker helps you import your drone footage, "
            "guide the edit automatically, and produce a polished, music-driven movie.\n\n"
            "Would you like a quick tour of the interface to get started?"
        )
        desc_label.setObjectName("welcomeDesc")
        desc_label.setWordWrap(True)
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Checkbox
        self.opt_out_cb = QCheckBox("Don't show this welcome screen again")
        self.opt_out_cb.setObjectName("welcomeOptOut")
        settings = QSettings()
        self.opt_out_cb.setChecked(not settings.value("startup/show_welcome_modal", True, type=bool))

        # Buttons
        self.tour_btn = QPushButton("Take the Tour")
        self.tour_btn.setObjectName("primaryButton")
        self.tour_btn.clicked.connect(self.accept)  # Accept = Take Tour

        self.skip_btn = QPushButton("Explore on My Own")
        self.skip_btn.setObjectName("secondaryButton")
        self.skip_btn.clicked.connect(self.reject)  # Reject = Skip Tour

        # Stylesheet (applied to self to style both dialog and child card)
        self.setStyleSheet(f"""
            QDialog#welcomeDialog {{
                background: transparent;
            }}
            QFrame#welcomeCard {{
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 16px;
            }}
            QLabel#welcomeTitle {{
                color: #0F172A;
                font-size: 16pt;
                font-weight: 800;
                background: transparent;
                border: none;
            }}
            QLabel#welcomeDesc {{
                color: #475569;
                font-size: 10pt;
                line-height: 1.5;
                background: transparent;
                border: none;
                padding: 0px 20px;
            }}
            QCheckBox#welcomeOptOut {{
                color: #64748B;
                font-size: 9.5pt;
                background: transparent;
                border: none;
            }}
            QCheckBox#welcomeOptOut::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid #CBD5E1;
                border-radius: 3.5px;
                background: #FFFFFF;
            }}
            QCheckBox#welcomeOptOut::indicator:checked {{
                background-color: {GLOW_COLOR.name()};
                border-color: {GLOW_COLOR.name()};
                image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIzIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5bGluZSBwb2ludHM9IjIwIDYgOSAxNyA0IDEyIj48L3BvbHlsaW5lPjwvc3ZnPg==");
            }}
            QPushButton {{
                font-size: 10pt;
                font-weight: 600;
                padding: 10px 20px;
                border-radius: 8px;
            }}
            QPushButton#primaryButton {{
                background-color: {GLOW_COLOR.name()};
                color: #FFFFFF;
                border: 1px solid {GLOW_COLOR.name()};
            }}
            QPushButton#primaryButton:hover {{
                background-color: #084481;
                border-color: #084481;
            }}
            QPushButton#secondaryButton {{
                background-color: #FFFFFF;
                color: #475569;
                border: 1px solid #CBD5E1;
            }}
            QPushButton#secondaryButton:hover {{
                background-color: #F8FAFC;
                color: #0F172A;
                border-color: #94A3B8;
            }}
        """)

        # Layouts
        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 32, 28, 32)
        layout.setSpacing(20)

        layout.addWidget(logo_label)
        layout.addWidget(title_label)
        layout.addWidget(desc_label)
        layout.addStretch()
        
        # Checkbox alignment
        cb_layout = QHBoxLayout()
        cb_layout.addStretch()
        cb_layout.addWidget(self.opt_out_cb)
        cb_layout.addStretch()
        layout.addLayout(cb_layout)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addWidget(self.skip_btn, 1)
        btn_layout.addWidget(self.tour_btn, 1)
        layout.addLayout(btn_layout)

        # Dialog outer layout (with padding for shadow rendering)
        dialog_layout = QVBoxLayout(self)
        dialog_layout.setContentsMargins(20, 20, 20, 20)
        dialog_layout.addWidget(card)

    def save_settings(self) -> None:
        settings = QSettings()
        settings.setValue("startup/show_welcome_modal", not self.opt_out_cb.isChecked())
        settings.sync()

    def accept(self) -> None:
        self.save_settings()
        super().accept()

    def reject(self) -> None:
        settings = QSettings()
        settings.setValue("startup/show_welcome_modal", not self.opt_out_cb.isChecked())
        settings.setValue("startup/show_onboarding", False)
        settings.setValue("startup/show_workspace_onboarding", False)
        settings.setValue("startup/show_preview_onboarding", False)
        settings.setValue("startup/show_soundtrack_onboarding", False)
        settings.setValue("startup/show_library_onboarding", False)
        settings.setValue("startup/show_produce_onboarding", False)
        settings.sync()
        super().reject()


class DotIndicator(QWidget):
    """A series of small dots indicating progress in the onboarding steps."""

    def __init__(self, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.dots: list[QFrame] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for _ in range(count):
            dot = QFrame()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet("border-radius: 4px; background-color: #CBD5E1;")
            layout.addWidget(dot)
            self.dots.append(dot)

    def set_current(self, index: int) -> None:
        for i, dot in enumerate(self.dots):
            if i == index:
                dot.setStyleSheet(f"border-radius: 4px; background-color: {GLOW_COLOR.name()};")
            else:
                dot.setStyleSheet("border-radius: 4px; background-color: #CBD5E1;")


class OnboardingPopup(QFrame):
    """The explanation card widget that positions itself next to the highlighted element."""

    def __init__(self, parent: QWidget | None = None, settings_key: str = "startup/show_onboarding") -> None:
        super().__init__(parent)
        self.settings_key = settings_key
        self.setObjectName("onboardingPopup")
        self.setFixedWidth(320)
        self.setMinimumHeight(250)
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(15, 23, 42, 40))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        self.title_label = QLabel()
        self.title_label.setObjectName("title")
        self.title_label.setWordWrap(True)
        
        self.desc_label = QLabel()
        self.desc_label.setObjectName("description")
        self.desc_label.setWordWrap(True)
        
        self.dots = None
        self.step_label = QLabel()
        self.step_label.setObjectName("stepText")
        self.step_label.setStyleSheet("color: #64748B; font-size: 9pt;")
        
        self.opt_out_cb = QCheckBox("Never show this again")
        self.opt_out_cb.setObjectName("optOut")
        settings = QSettings()
        self.opt_out_cb.setChecked(not settings.value(self.settings_key, True, type=bool))
        self.opt_out_cb.stateChanged.connect(self.on_opt_out_changed)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setObjectName("textButton")
        
        self.back_btn = QPushButton("Back")
        self.back_btn.setObjectName("secondaryButton")
        
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("primaryButton")

        self.setStyleSheet(f"""
            QFrame#onboardingPopup {{
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
            }}
            QLabel#title {{
                color: #0F172A;
                font-size: 11.5pt;
                font-weight: 700;
                border: none;
                background: transparent;
            }}
            QLabel#description {{
                color: #475569;
                font-size: 9.5pt;
                line-height: 1.4;
                border: none;
                background: transparent;
            }}
            QCheckBox {{
                color: #64748B;
                font-size: 9pt;
                border: none;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 14px;
                height: 14px;
                border: 1px solid #CBD5E1;
                border-radius: 3.5px;
                background: #FFFFFF;
            }}
            QCheckBox::indicator:checked {{
                background-color: {GLOW_COLOR.name()};
                border-color: {GLOW_COLOR.name()};
                image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIzIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5bGluZSBwb2ludHM9IjIwIDYgOSAxNyA0IDEyIj48L3BvbHlsaW5lPjwvc3ZnPg==");
            }}
            QPushButton {{
                font-size: 9pt;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QPushButton#primaryButton {{
                background-color: {GLOW_COLOR.name()};
                color: #FFFFFF;
                border: 1px solid {GLOW_COLOR.name()};
            }}
            QPushButton#primaryButton:hover {{
                background-color: #084481;
                border-color: #084481;
            }}
            QPushButton#secondaryButton {{
                background-color: #FFFFFF;
                color: #475569;
                border: 1px solid #CBD5E1;
            }}
            QPushButton#secondaryButton:hover {{
                background-color: #F8FAFC;
                color: #0F172A;
                border-color: #94A3B8;
            }}
            QPushButton#secondaryButton:disabled {{
                color: #CBD5E1;
                border-color: #E2E8F0;
                background-color: #F8FAFC;
            }}
            QPushButton#textButton {{
                background-color: transparent;
                color: #64748B;
                border: none;
                padding: 6px 8px;
            }}
            QPushButton#textButton:hover {{
                color: #0F172A;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        main_layout.addWidget(self.title_label)
        main_layout.addWidget(self.desc_label)

        self.progress_layout = QHBoxLayout()
        self.progress_layout.addWidget(self.step_label)
        self.progress_layout.addStretch()
        main_layout.addLayout(self.progress_layout)

        main_layout.addWidget(self.opt_out_cb)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.skip_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.back_btn)
        btn_layout.addWidget(self.next_btn)
        main_layout.addLayout(btn_layout)

    def on_opt_out_changed(self, state: int) -> None:
        settings = QSettings()
        settings.setValue(self.settings_key, not self.opt_out_cb.isChecked())
        settings.sync()

    def update_opt_out_checkbox(self) -> None:
        settings = QSettings()
        self.opt_out_cb.blockSignals(True)
        self.opt_out_cb.setChecked(not settings.value(self.settings_key, True, type=bool))
        self.opt_out_cb.blockSignals(False)

    def set_step(self, step_num: int, total_steps: int, title: str, description: str, disable_next: bool = False) -> None:
        self.title_label.setText(title)
        self.desc_label.setText(description)
        
        # Force label width restrictions so standard wrap metrics calculate correct size hints
        self.title_label.setFixedWidth(288)
        self.desc_label.setFixedWidth(288)
        
        self.step_label.setText(f"{step_num} / {total_steps}")
        
        # Recreate dots indicator if total steps count changed between tours
        if self.dots and len(self.dots.dots) != total_steps:
            self.progress_layout.removeWidget(self.dots)
            self.dots.deleteLater()
            self.dots = None

        if not self.dots:
            self.dots = DotIndicator(total_steps, self)
            self.progress_layout.insertWidget(0, self.dots)
        
        self.dots.set_current(step_num - 1)
        self.back_btn.setEnabled(step_num > 1)
        if step_num == total_steps:
            self.next_btn.setText("Finish")
        else:
            self.next_btn.setText("Next")
            
        self.next_btn.setVisible(not disable_next)


class OnboardingOverlay(QWidget):
    """Full-page transparent overlay that handles mask rendering and spotlight transitions."""
    finished = Signal()

    def __init__(self, parent: QWidget, steps: list[dict] | None = None, settings_key: str = "startup/show_onboarding") -> None:
        super().__init__(parent)
        self.setObjectName("onboardingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        
        self._spotlight_rect = QRectF()
        self._mask_alpha = 0
        self.current_step = -1
        
        if steps is not None:
            self.steps = steps
        else:
            # Fallback to welcome screen steps for backward compatibility in tests
            self.steps = [
                {
                    "target": lambda home: home.new_button,
                    "title": "New Project",
                    "description": "Allows you to create a new project, this should be the first option to select if it's your first time.",
                },
                {
                    "target": lambda home: home.open_button,
                    "title": "Open Project",
                    "description": "When you click on this button, it will automaticly open the last project that you worked on.",
                },
                {
                    "target": lambda home: home.recent_list,
                    "title": "Recent Projects Section",
                    "description": "If you double click on one of those projects listed, it will automaticly open it up.",
                }
            ]

        self.popup = OnboardingPopup(self, settings_key)
        self.popup.skip_btn.clicked.connect(self.close_tour)
        self.popup.back_btn.clicked.connect(self.prev_step)
        self.popup.next_btn.clicked.connect(self.next_step)

    def get_spotlight_rect(self) -> QRectF:
        return self._spotlight_rect

    def set_spotlight_rect(self, rect: QRectF) -> None:
        self._spotlight_rect = rect
        self.update()

    spotlightRect = Property(QRectF, get_spotlight_rect, set_spotlight_rect)

    def get_mask_alpha(self) -> int:
        return self._mask_alpha

    def set_mask_alpha(self, alpha: int) -> None:
        self._mask_alpha = alpha
        self.update()

    maskAlpha = Property(int, get_mask_alpha, set_mask_alpha)

    def show_onboarding(self) -> None:
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        
        self.popup.update_opt_out_checkbox()
        
        # Start with full-page spotlight (closes in on first target)
        self.set_spotlight_rect(QRectF(self.rect()))
        
        import sys
        is_testing = "pytest" in sys.modules or "unittest" in sys.modules
        
        self.fade_anim = QPropertyAnimation(self, b"maskAlpha")
        self.fade_anim.setDuration(0 if is_testing else 300)
        self.fade_anim.setStartValue(0)
        self.fade_anim.setEndValue(BACKGROUND_MASK_OPACITY)
        self.fade_anim.start()
        
        self.goToStep(0)

    def goToStep(self, index: int) -> None:
        if not (0 <= index < len(self.steps)):
            return
        
        self.current_step = index
        step_data = self.steps[index]
        target_obj = step_data["target"](self.parent())
        if not target_obj:
            LOGGER.warning("Onboarding target widget not found for step %d", index)
            self.close_tour()
            return
            
        if isinstance(target_obj, (QRectF, QRect)):
            target_rect = QRectF(target_obj)
        else:
            pos = target_obj.mapTo(self, QPoint(0, 0))
            target_rect = QRectF(
                pos.x() - SPOTLIGHT_PADDING + SPOTLIGHT_OFFSET_X,
                pos.y() - SPOTLIGHT_PADDING + SPOTLIGHT_OFFSET_Y,
                target_obj.width() + 2 * SPOTLIGHT_PADDING,
                target_obj.height() + 2 * SPOTLIGHT_PADDING
            )
        
        disable_next = step_data.get("disable_next", False)
        self.popup.set_step(
            index + 1,
            len(self.steps),
            step_data["title"],
            step_data["description"],
            disable_next=disable_next,
        )
        
        import sys
        is_testing = "pytest" in sys.modules or "unittest" in sys.modules

        # Animate spotlight and popup position in parallel
        self.anim_group = QParallelAnimationGroup(self)
        
        # Spotlight ease anim
        self.spotlight_anim = QPropertyAnimation(self, b"spotlightRect")
        self.spotlight_anim.setDuration(0 if is_testing else 450)
        self.spotlight_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.spotlight_anim.setStartValue(self.spotlightRect)
        self.spotlight_anim.setEndValue(target_rect)
        self.anim_group.addAnimation(self.spotlight_anim)
        
        # Card position transition
        self.popup.layout().activate()
        popup_size = self.popup.sizeHint().expandedTo(self.popup.minimumSize())
        self.popup.resize(popup_size)
        popup_size = self.popup.size()
        
        position = step_data.get("position", "bottom")
        target_popup_pos = self.calculate_popup_position(target_rect, popup_size, position)
        
        self.popup_anim = QPropertyAnimation(self.popup, b"pos")
        self.popup_anim.setDuration(0 if is_testing else 450)
        self.popup_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.popup_anim.setStartValue(self.popup.pos() if index > 0 else target_popup_pos - QPoint(0, 20))
        self.popup_anim.setEndValue(target_popup_pos)
        self.anim_group.addAnimation(self.popup_anim)
        
        self.anim_group.start()

    def calculate_popup_position(self, spotlight_rect: QRectF, popup_size: QSize, position: str = "bottom") -> QPoint:
        if position == "left":
            x = spotlight_rect.left() - popup_size.width() - POPUP_MARGIN
            y = spotlight_rect.center().y() - popup_size.height() / 2
        elif position == "right":
            x = spotlight_rect.right() + POPUP_MARGIN
            y = spotlight_rect.center().y() - popup_size.height() / 2
        elif position == "top":
            x = spotlight_rect.center().x() - popup_size.width() / 2
            y = spotlight_rect.top() - popup_size.height() - POPUP_MARGIN
        else: # "bottom"
            x = spotlight_rect.center().x() - popup_size.width() / 2
            y = spotlight_rect.bottom() + POPUP_MARGIN
            # fallback to top if bottom overlaps screen bottom
            if y + popup_size.height() > self.height() - 16:
                y = spotlight_rect.top() - popup_size.height() - POPUP_MARGIN

        # Clamping to screen boundaries
        x = max(16, min(x, self.width() - popup_size.width() - 16))
        y = max(16, min(y, self.height() - popup_size.height() - 16))
        
        return QPoint(int(x), int(y))

    def update_layout(self) -> None:
        if self.current_step < 0 or self.current_step >= len(self.steps):
            return
            
        step_data = self.steps[self.current_step]
        target_obj = step_data["target"](self.parent())
        if not target_obj:
            return
            
        if isinstance(target_obj, (QRectF, QRect)):
            target_rect = QRectF(target_obj)
        else:
            pos = target_obj.mapTo(self, QPoint(0, 0))
            target_rect = QRectF(
                pos.x() - SPOTLIGHT_PADDING + SPOTLIGHT_OFFSET_X,
                pos.y() - SPOTLIGHT_PADDING + SPOTLIGHT_OFFSET_Y,
                target_obj.width() + 2 * SPOTLIGHT_PADDING,
                target_obj.height() + 2 * SPOTLIGHT_PADDING
            )
        
        if hasattr(self, "anim_group") and self.anim_group.state() == QPropertyAnimation.State.Running:
            self.anim_group.stop()
            
        self.set_spotlight_rect(target_rect)
        self.popup.layout().activate()
        popup_size = self.popup.sizeHint().expandedTo(self.popup.minimumSize())
        self.popup.resize(popup_size)
        popup_size = self.popup.size()
        
        position = step_data.get("position", "bottom")
        self.popup.move(self.calculate_popup_position(target_rect, popup_size, position))

    def next_step(self) -> None:
        if 0 <= self.current_step < len(self.steps):
            step_data = self.steps[self.current_step]
            on_next = step_data.get("on_next")
            if on_next:
                on_next(self.parent())
                
        if self.current_step < len(self.steps) - 1:
            self.goToStep(self.current_step + 1)
        else:
            self.close_tour()

    def prev_step(self) -> None:
        if self.current_step > 0:
            step_data = self.steps[self.current_step]
            on_back = step_data.get("on_back")
            if on_back:
                on_back(self.parent())
            self.goToStep(self.current_step - 1)

    def close_tour(self) -> None:
        import sys
        is_testing = "pytest" in sys.modules or "unittest" in sys.modules

        self.fade_out = QPropertyAnimation(self, b"maskAlpha")
        self.fade_out.setDuration(0 if is_testing else 250)
        self.fade_out.setStartValue(self.maskAlpha)
        self.fade_out.setEndValue(0)
        self.fade_out.finished.connect(self._do_hide)
        self.fade_out.start()

    def _do_hide(self) -> None:
        self.hide()
        self.finished.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Use zero-duration singleShot timer to defer layout calculations
        # until the layout engine has completed repositioning child widgets.
        QTimer.singleShot(0, self.update_layout)

    def paintEvent(self, event) -> None:
        if self.maskAlpha == 0:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        
        spotlight_path = QPainterPath()
        spotlight_path.addRoundedRect(self._spotlight_rect, SPOTLIGHT_ROUNDNESS, SPOTLIGHT_ROUNDNESS)
        
        mask_path = path.subtracted(spotlight_path)
        painter.fillPath(mask_path, QBrush(QColor(MASK_COLOR.red(), MASK_COLOR.green(), MASK_COLOR.blue(), self.maskAlpha)))
        
        # Render border highlights only when showcasing a target
        if self._spotlight_rect.width() < self.width() - 20:
            # Draw glow layers
            for i in range(1, 4):
                glow_pen = QPen(QColor(GLOW_COLOR.red(), GLOW_COLOR.green(), GLOW_COLOR.blue(), int(50 / i)), i * 2)
                painter.setPen(glow_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(self._spotlight_rect.adjusted(-i, -i, i, i), SPOTLIGHT_ROUNDNESS + i, SPOTLIGHT_ROUNDNESS + i)
            
            # Draw primary outline
            border_pen = QPen(GLOW_COLOR, SPOTLIGHT_BORDER_WIDTH)
            painter.setPen(border_pen)
            painter.drawRoundedRect(self._spotlight_rect, SPOTLIGHT_ROUNDNESS, SPOTLIGHT_ROUNDNESS)
            
        painter.end()

    def mousePressEvent(self, event) -> None:
        if self.spotlightRect.contains(event.position()):
            self.hide()
            widget = self.parent().childAt(event.position().toPoint())
            self.show()
            self.raise_()
            if widget:
                local_pos = widget.mapFrom(self, event.position().toPoint())
                from PySide6.QtGui import QMouseEvent
                from PySide6.QtCore import QPointF, QCoreApplication
                forwarded_event = QMouseEvent(
                    event.type(),
                    QPointF(local_pos),
                    event.button(),
                    event.buttons(),
                    event.modifiers()
                )
                QCoreApplication.sendEvent(widget, forwarded_event)
                return
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self.spotlightRect.contains(event.position()):
            self.hide()
            widget = self.parent().childAt(event.position().toPoint())
            self.show()
            self.raise_()
            if widget:
                local_pos = widget.mapFrom(self, event.position().toPoint())
                from PySide6.QtGui import QMouseEvent
                from PySide6.QtCore import QPointF, QCoreApplication
                forwarded_event = QMouseEvent(
                    event.type(),
                    QPointF(local_pos),
                    event.button(),
                    event.buttons(),
                    event.modifiers()
                )
                QCoreApplication.sendEvent(widget, forwarded_event)
                return
        event.accept()
