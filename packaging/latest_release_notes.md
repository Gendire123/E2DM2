E2DM2 v1.0.8 improves onboarding at every supported window size and adds a clear, accessible in-app Privacy Policy. This release focuses on making the first-run experience reliable, transparent, and easier to understand.

## Highlights

- Onboarding highlights now remain aligned when E2DM2 is windowed, maximized, resized, or used on a display smaller than 1920x1080.
- Checked onboarding options now display a proper checkmark instead of an ambiguous solid-colored square.
- A complete Privacy Policy is available from **Help > Privacy Policy**, immediately above **About E2DM2**.
- The Privacy Policy uses a scrollable, resizable modal with explicit high-contrast colors that remain readable with Windows light and dark themes.
- The About dialog and startup splash screen now identify the application as version 1.0.8.

## Onboarding Improvements

### Highlights stay attached to the intended controls

Onboarding spotlights could previously drift away from buttons, tables, and other interface elements when the application was not maximized at 1920x1080. The offset varied with the layout: on smaller windows, a tour could highlight part of a table row or a status field instead of the control described by the onboarding card.

E2DM2 now calculates each spotlight from the target's real on-screen position and translates it into the onboarding overlay's coordinate system. This removes the fixed vertical correction that only happened to look correct at one window configuration.

The overlay also responds to window and target geometry changes. If E2DM2 is resized while a tour is open, the overlay fills the new window and recalculates both the highlighted area and the explanatory card after the interface finishes rearranging itself.

The correction applies consistently to:

- the Welcome Screen tour;
- the Workspace and Footage tour;
- the Soundtrack tour;
- the Produce tour;
- the Preview and Selection tour; and
- the Music Library tour.

### Onboarding checkboxes are visually unambiguous

The checked state of **Never show this again** previously depended on an embedded SVG image that Qt did not reliably render on every Windows configuration. The result was a blue square with no visible tick.

The checkmark is now painted directly by E2DM2. Checked controls show a clear white tick inside the blue box across supported Qt and Windows styles. The same correction is applied to the welcome screen's opt-out checkbox.

## Privacy and Transparency

### New in-app Privacy Policy

The Help menu now includes **Privacy Policy** directly above **About E2DM2**. It opens a dedicated modal window that can be resized and scrolled through the complete policy without leaving the application.

The policy begins with a plain-language summary and then explains:

- which videos, audio files, project settings, previews, caches, renders, preferences, and logs remain locally on the user's computer;
- that E2DM2 does not upload footage for cloud processing and contains no advertising analytics or cross-app tracking;
- how automatic and manual update checks communicate with GitHub;
- what is sent to Supabase when a user chooses to activate or deactivate an optional Pro license;
- how Stripe and the E2DM2 website are involved when a user chooses to purchase a license or submit a contact request;
- why information is used and when service providers may process it;
- retention, deletion, and security practices;
- user choices and privacy rights; and
- how to contact E2DM2 with a privacy request or complaint.

Adding this policy does not introduce new telemetry, cloud video processing, or background collection. It documents the application's existing local-first behavior and its limited network functions.

### Readable with Windows light and dark themes

The policy viewer now explicitly defines its page background, body text, headings, links, selected text, and scrollbar colors. Windows can no longer apply a dark editor background while leaving E2DM2's dark text in place. The document remains high contrast and readable regardless of the active system palette.

## Technical Improvements

- Replaced resolution-dependent spotlight offsets with reliable global-to-overlay coordinate conversion.
- Added deferred layout updates so spotlight and popup positions are measured after responsive layouts settle.
- Added target and parent resize tracking for active onboarding tours.
- Added a reusable native-painted onboarding checkbox checkmark.
- Added a dedicated privacy-policy content module and scrollable policy dialog.
- Added palette-independent colors for the privacy document and its selection states.
- Added regression coverage for nested onboarding targets, live window resizing, Help menu ordering, complete scrollable policy content, and forced dark palettes.
- The full automated test suite passes with 167 tests.

## Privacy Reminder

E2DM2 continues to process imported footage, custom audio, previews, and rendered movies locally. Update checks and optional Pro licensing use the limited network connections described in the Privacy Policy. Users can disable automatic update checks under **View > Options > Automatic Updates**.

## Download and Installation

1. Download `E2DM2-Setup-1.0.8.exe` from the assets section below.
2. Double-click the installer and follow the on-screen instructions.
3. The installer can replace an earlier E2DM2 version while preserving existing projects and user-created media.
4. After installation, open **Help > About E2DM2** to confirm that version 1.0.8 is running.

Existing projects do not need to be recreated or re-imported for these improvements.
