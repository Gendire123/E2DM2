# Pro licensing backend

This directory contains the temporary manual purchase flow and the production activation boundary. Secret values stay in Supabase Edge Function secrets; never add them to the desktop app or repository.

1. Apply `migrations/202606290001_pro_licenses.sql`.
2. Add your own authenticated Supabase user ID to `public.license_admins`.
3. Set Edge Function secrets `RESEND_API_KEY` and `LICENSE_FROM_EMAIL`.
4. Link and deploy to project `kzozxeyktwxcsukkheah`:

```powershell
supabase link --project-ref kzozxeyktwxcsukkheah
supabase db push
supabase functions deploy license-activate --no-verify-jwt
supabase functions deploy license-admin
```

The desktop app already defaults to this project's deployed function URLs. `E2DM2_LICENSE_API_URL` and `E2DM2_LICENSE_ADMIN_URL` remain optional overrides for staging.

Admin Tools are temporarily visible under **View** by default. Supply a short-lived admin session token before launching:

```powershell
$env:E2DM2_ADMIN_ACCESS_TOKEN = "A_SHORT_LIVED_SUPABASE_USER_TOKEN"
```

The access token must belong to a user listed in `license_admins`. Set `E2DM2_ENABLE_ADMIN_TOOLS=0` to remove the menu from a release build. The Edge Function still enforces authorization if somebody recreates the client request. Stripe should eventually invoke an equivalent server-side issuance routine from a verified webhook; it must not call or expose the desktop Admin Tools flow.
