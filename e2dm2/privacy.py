from __future__ import annotations


PRIVACY_POLICY_EFFECTIVE_DATE = "July 5, 2026"


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
  <li><b>Limited network use.</b> The application connects to GitHub to check for
      software updates and, only when you use Pro licensing, to Supabase to
      activate a license.</li>
  <li><b>No sale of personal information.</b> E2DM2 does not sell or rent personal
      information or share it for targeted advertising.</li>
</ul>

<h2>1. Who this policy covers</h2>
<p>This policy explains how the E2DM2 (Easy Epic Drone Movie Maker) Windows
desktop application handles information. E2DM2 is responsible for personal
information under its control. Felix Ouellet, creator of E2DM2, is the privacy
contact.</p>
<p>Websites and services opened in your browser, including GitHub, Stripe, and
the E2DM2 website, have their own privacy practices. Their relevant roles are
described below.</p>

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
  <li>local diagnostic logs containing application events and error details.
      A log can include local file paths or project-related error context.</li>
</ul>
<p>This information is used only to provide the editing features you request,
restore your settings, troubleshoot errors, and produce your output. It is not
sent to E2DM2 unless you deliberately include it in a support message.</p>

<h2>3. Information sent over the internet</h2>

<h3>Software update checks</h3>
<p>If automatic update checks are enabled, E2DM2 contacts the GitHub Releases API
at most once per day to learn whether a new version is available. A manual update
check makes the same request. The request identifies itself as the E2DM2 updater
and, like an ordinary internet request, gives GitHub your IP address and standard
connection metadata. E2DM2 does not receive this metadata from GitHub and does
not send your media, project contents, name, email address, or license data with
the request.</p>
<p>You can turn off automatic checks under <b>View &gt; Options &gt; Automatic
Updates</b>. You can still check manually. GitHub describes its practices in the
<a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub Privacy Statement</a>.</p>

<h3>Optional Pro licensing</h3>
<p>The free application does not require an account. If you activate Pro, E2DM2
sends the license code and a randomly generated installation identifier to the
E2DM2 licensing service hosted by Supabase. The identifier is not a hardware
serial number and is used to enforce the permitted activation count.</p>
<p>The licensing system stores the customer email used to issue the license,
hashed versions of the license code, installation identifier, and activation
receipt, the license status, and activation timestamps. The application stores
the random installation identifier, an activation receipt, Pro status, and only
the last three characters of the license code locally. Supabase may also process
ordinary network metadata such as an IP address to deliver and secure its service.
No video, audio, project, or rendered movie is sent during activation.</p>
<p>These details are used to validate the license, limit activations, prevent
fraud, provide support, and release an activation slot when you deactivate a
copy. See the <a href="https://supabase.com/privacy">Supabase Privacy Policy</a>.</p>

<h3>Purchases, contact, and external links</h3>
<p>Choosing to purchase Pro opens a Stripe checkout page in your browser. Stripe
processes payment and related transaction information under the
<a href="https://stripe.com/privacy">Stripe Privacy Policy</a>. E2DM2 does not
receive or store your full payment-card number.</p>
<p><b>Help &gt; Contact &amp; Info</b> opens the E2DM2 website. If you submit its contact
form, you choose to provide your name, email address, inquiry category, and
message. That information is used to answer the inquiry and maintain necessary
support records. Do not include footage, license keys, or other sensitive
information unless it is necessary and you intend to share it.</p>

<h2>4. Why information is used</h2>
<p>E2DM2 uses information only for the purposes described in this policy: to
provide requested application and licensing functions, maintain security,
deliver updates, respond to support requests, keep required business records,
and comply with law. Where a legal basis is required, processing is based on
providing the service or license you requested, E2DM2's legitimate interests in
security and reliable operation, consent where required, or a legal obligation.</p>
<p>E2DM2 does not use personal information for automated decisions that have legal
or similarly significant effects.</p>

<h2>5. When information is disclosed</h2>
<p>E2DM2 does not sell or rent personal information. Information is disclosed only:</p>
<ul>
  <li>to service providers such as Supabase, GitHub, Stripe, and website or
      contact-service providers when needed for the functions described above;</li>
  <li>when you direct or consent to the disclosure;</li>
  <li>to protect users, E2DM2, or others from fraud, security threats, or harm; or</li>
  <li>when required or permitted by applicable law.</li>
</ul>
<p>Service providers process information under their own terms and applicable
contractual or legal safeguards. They may process information outside your
province, state, or country, where it can be subject to local law.</p>

<h2>6. Retention and deletion</h2>
<p>Local projects, source media, renders, caches, recent-project history, settings,
and logs remain on your computer until you delete them or they are replaced by
normal cache or log rotation. Uninstalling E2DM2 may not remove projects and
settings stored in your Documents folder or Windows user profile.</p>
<p>Server-side license and customer records are retained while the license is
active and afterward when reasonably necessary for transaction records, support,
fraud prevention, disputes, and legal obligations. Deactivating Pro removes that
installation's server-side activation record and local activation receipt, but
does not cancel the license or erase records that must be retained for the
purposes above. Support messages are retained only as long as reasonably needed
to resolve the inquiry and meet recordkeeping obligations.</p>

<h2>7. Security</h2>
<p>E2DM2 uses safeguards appropriate to the information involved. Licensing
requests use encrypted HTTPS connections; license codes, installation identifiers,
and activation receipts are hashed before storage in the licensing database;
and direct client access to licensing tables is disabled. Local information is
protected by your Windows account, device security, and backups. No system is
perfectly secure, so keep your device updated and do not share license keys or
sensitive project files unnecessarily.</p>

<h2>8. Your choices and privacy rights</h2>
<p>You can use the free application without creating an E2DM2 account. You can
disable automatic update checks, choose whether to purchase or activate Pro, and
delete local projects, renders, caches, logs, and settings using Windows tools.</p>
<p>Depending on where you live, you may have rights to:</p>
<ul>
  <li>ask whether E2DM2 holds personal information about you and obtain access;</li>
  <li>correct inaccurate or incomplete information;</li>
  <li>request deletion, restriction, or portability where applicable;</li>
  <li>withdraw consent, subject to legal or contractual limits; and</li>
  <li>complain to the privacy regulator in your jurisdiction.</li>
</ul>
<p>To make a request, use the contact method below. E2DM2 may need to verify your
identity before responding. Some information may be retained or access may be
limited where permitted by law. Deleting licensing information can prevent E2DM2
from validating or restoring Pro access.</p>

<h2>9. Children</h2>
<p>E2DM2 is a general-purpose creative application and is not directed to children
under 13. E2DM2 does not knowingly collect personal information from a child who
cannot legally consent without authorization from a parent or guardian.</p>

<h2>10. Changes to this policy</h2>
<p>This policy will be updated when E2DM2's practices change. The updated policy
will show a new date and be included with a software update or otherwise made
available to affected users. If a material change requires notice or consent,
E2DM2 will provide it before the new practice begins where required by law.</p>

<h2>11. Contact and complaints</h2>
<p>For privacy questions, access or correction requests, deletion requests, or a
complaint, contact <b>Felix Ouellet, E2DM2 Privacy Contact</b>, through
<a href="https://e2dm2.com/#contact">https://e2dm2.com/#contact</a>. Select
<b>Question</b> and begin the message with "Privacy request." Please do not send
license keys or identity documents in the initial message.</p>
"""
