import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.8";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type",
};
const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

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

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY")!;
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const authorization = request.headers.get("Authorization") ?? "";
  if (!authorization.startsWith("Bearer ")) return json({ error: "Unauthorized" }, 401);

  const userClient = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: authorization } },
  });
  const { data: { user }, error: userError } = await userClient.auth.getUser();
  if (userError || !user) return json({ error: "Unauthorized" }, 401);

  const service = createClient(supabaseUrl, serviceKey);
  const { data: admin } = await service
    .from("license_admins")
    .select("user_id")
    .eq("user_id", user.id)
    .maybeSingle();
  if (!admin) return json({ error: "Forbidden" }, 403);

  let email = "";
  try {
    email = String((await request.json()).email ?? "").trim().toLowerCase();
  } catch {
    return json({ error: "Invalid request" }, 400);
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return json({ error: "Enter a valid customer email." }, 400);
  }

  let code = "";
  let licenseId = "";
  for (let attempt = 0; attempt < 5; attempt += 1) {
    code = generateCode();
    const { data, error } = await service
      .from("pro_licenses")
      .insert({ code_hash: await sha256(code), customer_email: email, created_by: user.id })
      .select("id")
      .single();
    if (!error && data) {
      licenseId = data.id;
      break;
    }
    if (error?.code !== "23505") return json({ error: "Could not create license." }, 500);
  }
  if (!licenseId) return json({ error: "Could not create a unique license." }, 500);

  const resendResponse = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${Deno.env.get("RESEND_API_KEY")}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: Deno.env.get("LICENSE_FROM_EMAIL") ?? "E2DM2 <licenses@e2dm2.com>",
      to: [email],
      subject: "Your E2DM2 Pro license",
      text: `Thank you for purchasing E2DM2 Pro.\n\nYour license code is:\n${code}\n\nCopy and paste this code into View > Enter Pro License Code in E2DM2.`,
      html: `<p>Thank you for purchasing E2DM2 Pro.</p><p>Your license code is:</p><p style="font:700 24px monospace;letter-spacing:2px">${code}</p><p>Copy and paste it into <strong>View &gt; Enter Pro License Code</strong> in E2DM2.</p>`,
    }),
  });
  if (!resendResponse.ok) {
    const resendPayload = await resendResponse.text();
    let resendMessage = "Email delivery was rejected.";
    try {
      const parsed = JSON.parse(resendPayload);
      if (typeof parsed?.message === "string") resendMessage = parsed.message.slice(0, 300);
    } catch {
      // Do not expose arbitrary upstream response bodies to the desktop client.
    }
    console.error("Resend rejected license email", resendResponse.status, resendMessage);
    await service.from("pro_licenses").delete().eq("id", licenseId);
    return json(
      { error: `Resend rejected the email (${resendResponse.status}): ${resendMessage}` },
      502,
    );
  }
  return json({ sent: true });
});
