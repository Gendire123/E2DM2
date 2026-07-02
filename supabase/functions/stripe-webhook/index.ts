import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.8";
import Stripe from "npm:stripe@^14";

const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function generateCode(): string {
  const random = new Uint32Array(15);
  crypto.getRandomValues(random);
  const compact = Array.from(random, (value) => alphabet[value % alphabet.length]).join("");
  return compact.match(/.{3}/g)!.join("-");
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function licenseEmailHtml(code: string): string {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="color-scheme" content="light only">
    <title>Your E2DM2 Pro license</title>
  </head>
  <body style="margin:0;padding:0;background:#eef3f7;color:#142033;font-family:'Segoe UI',Arial,sans-serif;">
    <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
      Your E2DM2 Pro license is ready. Copy your activation key inside.
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#eef3f7;">
      <tr>
        <td align="center" style="padding:40px 16px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:620px;background:#ffffff;border:1px solid #dce5eb;border-radius:20px;box-shadow:0 14px 36px rgba(20,32,51,.10);overflow:hidden;">
            <tr>
              <td style="padding:34px 40px;background:#101d30;background-image:linear-gradient(135deg,#101d30 0%,#173b67 100%);">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td style="color:#ffffff;font-size:24px;font-weight:800;letter-spacing:.3px;">E2DM2</td>
                    <td align="right"><span style="display:inline-block;padding:7px 12px;border:1px solid rgba(255,255,255,.30);border-radius:999px;color:#dcecff;font-size:12px;font-weight:700;letter-spacing:1.2px;">PRO</span></td>
                  </tr>
                </table>
                <div style="padding-top:32px;color:#ffffff;font-size:30px;line-height:1.2;font-weight:800;">Your creative upgrade is ready.</div>
                <div style="padding-top:10px;color:#c7d8eb;font-size:16px;line-height:1.6;">Welcome to E2DM2 Pro. Your license key is waiting below.</div>
              </td>
            </tr>
            <tr>
              <td style="padding:38px 40px 16px;">
                <div style="color:#526173;font-size:12px;font-weight:800;letter-spacing:1.4px;text-transform:uppercase;">Your Pro license key</div>
                <div style="margin-top:12px;padding:22px 14px;border:1px solid #bcd3ee;border-radius:14px;background:#f1f7ff;color:#0e56aa;font-family:Consolas,'Courier New',monospace;font-size:24px;line-height:1.4;font-weight:800;letter-spacing:2px;text-align:center;overflow-wrap:anywhere;">${code}</div>
                <div style="padding-top:10px;color:#718096;font-size:13px;line-height:1.5;text-align:center;">Select the complete key above and copy it exactly as shown.</div>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 40px 38px;">
                <div style="color:#142033;font-size:18px;font-weight:750;">Activate in three quick steps</div>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:18px;">
                  <tr>
                    <td width="36" valign="top"><div style="width:28px;height:28px;border-radius:50%;background:#0e56aa;color:#ffffff;font-size:14px;font-weight:800;line-height:28px;text-align:center;">1</div></td>
                    <td style="padding:3px 0 15px;color:#526173;font-size:15px;line-height:1.5;">Open E2DM2 and select <strong style="color:#142033;">View</strong>.</td>
                  </tr>
                  <tr>
                    <td width="36" valign="top"><div style="width:28px;height:28px;border-radius:50%;background:#0e56aa;color:#ffffff;font-size:14px;font-weight:800;line-height:28px;text-align:center;">2</div></td>
                    <td style="padding:3px 0 15px;color:#526173;font-size:15px;line-height:1.5;">Choose <strong style="color:#142033;">Enter Pro License Code</strong>.</td>
                  </tr>
                  <tr>
                    <td width="36" valign="top"><div style="width:28px;height:28px;border-radius:50%;background:#0e56aa;color:#ffffff;font-size:14px;font-weight:800;line-height:28px;text-align:center;">3</div></td>
                    <td style="padding:3px 0;color:#526173;font-size:15px;line-height:1.5;">Paste your key and click <strong style="color:#142033;">Activate Pro</strong>.</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 40px;background:#f7f9fb;border-top:1px solid #e5ebef;color:#718096;font-size:12px;line-height:1.6;text-align:center;">
                Keep this email somewhere safe. Your license key is a private credential.<br>
                <span style="color:#9aa8b5;">© 2026 E2DM2 · Easy Epic Drone Movie Maker</span>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>`;
}

// Initialise Stripe with SubtleCryptoProvider
const stripeKey = Deno.env.get("STRIPE_API_KEY") || "";
const stripe = new Stripe(stripeKey, {
  httpClient: Stripe.createFetchHttpClient(),
});
const cryptoProvider = Stripe.createSubtleCryptoProvider();

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", {
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "content-type",
      },
    });
  }

  const signature = req.headers.get("Stripe-Signature");
  if (!signature) {
    return new Response("Missing Stripe-Signature header", { status: 400 });
  }

  const webhookSecret = Deno.env.get("STRIPE_WEBHOOK_SIGNING_SECRET");
  if (!webhookSecret) {
    console.error("Missing STRIPE_WEBHOOK_SIGNING_SECRET env var");
    return new Response("Webhook secret not configured", { status: 500 });
  }

  const body = await req.text();
  let event;

  try {
    event = await stripe.webhooks.constructEventAsync(
      body,
      signature,
      webhookSecret,
      undefined,
      cryptoProvider
    );
  } catch (err) {
    console.error(`Webhook signature verification failed: ${err.message}`);
    return new Response(`Webhook Error: ${err.message}`, { status: 400 });
  }

  console.log(`Received Stripe event: ${event.type} (${event.id})`);

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    const email = session.customer_details?.email?.trim().toLowerCase();

    if (!email) {
      console.error(`Checkout session completed without customer email (session ID: ${session.id})`);
      return new Response("Checkout session missing email", { status: 400 });
    }

    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const service = createClient(supabaseUrl, serviceKey);

    // Let's generate a unique license code
    let code = "";
    let licenseId = "";
    for (let attempt = 0; attempt < 5; attempt += 1) {
      code = generateCode();
      const { data, error } = await service
        .from("pro_licenses")
        .insert({
          code_hash: await sha256(code),
          customer_email: email,
          created_by: null, // automated
        })
        .select("id")
        .single();
      if (!error && data) {
        licenseId = data.id;
        break;
      }
      if (error?.code !== "23505") {
        console.error("Could not insert license into database", error);
        return new Response("Database error", { status: 500 });
      }
    }

    if (!licenseId) {
      console.error("Failed to generate a unique license key after 5 attempts");
      return new Response("Failed to generate unique key", { status: 500 });
    }

    const resendApiKey = Deno.env.get("RESEND_API_KEY");
    if (!resendApiKey) {
      console.error("Missing RESEND_API_KEY environment variable");
      // Clean up license if we cannot send email
      await service.from("pro_licenses").delete().eq("id", licenseId);
      return new Response("Email credentials not configured", { status: 500 });
    }

    const resendResponse = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${resendApiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: Deno.env.get("LICENSE_FROM_EMAIL") ?? "E2DM2 <licenses@e2dm2.com>",
        to: [email],
        subject: "Welcome to E2DM2 Pro: Your License Key",
        text: `WELCOME TO E2DM2 PRO\n\nYour license key:\n${code}\n\nHOW TO ACTIVATE\n1. Open E2DM2 and select View.\n2. Choose Enter Pro License Code.\n3. Paste your key and click Activate Pro.\n\nKeep this email somewhere safe. Your license key is a private credential.`,
        html: licenseEmailHtml(code),
      }),
    });

    if (!resendResponse.ok) {
      const resendPayload = await resendResponse.text();
      console.error(`Resend rejected license email to ${email}`, resendResponse.status, resendPayload);
      // Clean up license if we cannot send email
      await service.from("pro_licenses").delete().eq("id", licenseId);
      return new Response(`Email send failed: ${resendPayload}`, { status: 502 });
    }

    console.log(`Successfully issued and emailed license key to ${email} for checkout session ${session.id}`);
  }

  return new Response(JSON.stringify({ received: true }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
