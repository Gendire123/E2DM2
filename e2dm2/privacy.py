from __future__ import annotations


PRIVACY_POLICY_EFFECTIVE_DATE = "August 4, 2026"


PRIVACY_POLICY_HTML = f"""
<h1>Privacy Policy</h1>
<p><b>Effective date and last updated:</b> {PRIVACY_POLICY_EFFECTIVE_DATE}</p>

<h2>Privacy at a glance</h2>
<ul>
  <li><b>Your videos stay on your computer.</b> E2DM2 processes video, audio,
      project, preview, and rendered movie files locally. E2DM2 does not upload
      them for cloud processing.</li>
  <li><b>No advertising tracking.</b> The desktop application does not contain
      advertising, analytics SDKs, cross-app tracking, or profiling.</li>
  <li><b>Limited network use.</b> The application contacts GitHub to check for
      software updates if enabled. No license keys or account details are collected.</li>
  <li><b>No sale of personal information.</b> E2DM2 does not sell or rent personal
      information or share it for targeted advertising.</li>
</ul>

<h2>1. Who this policy covers</h2>
<p>This policy explains how the E2DM2 (Easy Epic Drone Movie Maker) Windows
desktop application handles information. E2DM2 is an open-source application
released under the MIT License. Felix Ouellet, creator of E2DM2, is the privacy
contact.</p>

<h2>2. Information kept locally</h2>
<p>E2DM2 reads and creates information on your computer so that it can edit your
movie. Depending on the features you use, this can include:</p>
<ul>
  <li>the video and audio files you select and their file locations;</li>
  <li>project names, editing choices, required or excluded segments, soundtrack
      choices, export settings, and render queue details;</li>
  <li>project files, rendered movies, thumbnails, low-resolution previews,
      waveform caches, and custom soundtrack presets;</li>
  <li>a list of recently opened project locations;</li>
  <li>application preferences, such as update, onboarding, output, codec, and
      hardware-acceleration settings; and</li>
  <li>local diagnostic logs containing application events and error details.</li>
</ul>

<h2>3. Information sent over the internet</h2>

<h3>Software update checks</h3>
<p>If automatic update checks are enabled, E2DM2 contacts the GitHub Releases API
at most once per day to learn whether a new version is available. A manual update
check makes the same request. The request identifies itself as the E2DM2 updater
and, like an ordinary internet request, gives GitHub your IP address and standard
connection metadata. E2DM2 does not receive this metadata from GitHub and does
not send your media, project contents, name, or email address with the request.</p>

<h3>Support and external links</h3>
<p><b>Help &gt; Buy Me a Coffee ☕</b> opens an optional donation page in your default browser.
<b>Help &gt; Contact &amp; Info</b> opens the E2DM2 website.</p>

<h2>4. Your choices and privacy rights</h2>
<p>You can use the application without creating an account. You can
disable automatic update checks, and delete local projects, renders, caches, logs, and settings using Windows tools.</p>

<h2>5. Contact and complaints</h2>
<p>For privacy questions, contact <b>Felix Ouellet, E2DM2 Privacy Contact</b>, through
<a href="https://e2dm2.com/#contact">https://e2dm2.com/#contact</a>.</p>
"""
