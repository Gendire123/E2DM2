import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.8";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function activationToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);

  let code = "";
  let deviceId = "";
  try {
    const body = await request.json();
    code = String(body.license_code ?? "").trim().toUpperCase();
    deviceId = String(body.device_id ?? "").trim();
  } catch {
    return json({ valid: false, error: "Invalid request." }, 400);
  }
  if (!/^[A-Z0-9]{3}(?:-[A-Z0-9]{3}){4}$/.test(code) || deviceId.length < 16) {
    return json({ valid: false, error: "The license code is not valid." }, 400);
  }

  const service = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );
  const { data: license } = await service
    .from("pro_licenses")
    .select("id,max_activations,status")
    .eq("code_hash", await sha256(code))
    .eq("status", "active")
    .maybeSingle();
  if (!license) return json({ valid: false, error: "The license code is not valid." }, 401);

  const deviceHash = await sha256(deviceId);
  const { data: existing } = await service
    .from("license_activations")
    .select("id")
    .eq("license_id", license.id)
    .eq("device_hash", deviceHash)
    .maybeSingle();
  const token = activationToken();
  if (existing) {
    await service
      .from("license_activations")
      .update({ token_hash: await sha256(token), last_seen_at: new Date().toISOString() })
      .eq("id", existing.id);
    return json({ valid: true, activation_token: token });
  }

  const { count } = await service
    .from("license_activations")
    .select("id", { count: "exact", head: true })
    .eq("license_id", license.id);
  if ((count ?? 0) >= license.max_activations) {
    return json({ valid: false, error: "This license has reached its activation limit." }, 409);
  }
  const { error } = await service.from("license_activations").insert({
    license_id: license.id,
    device_hash: deviceHash,
    token_hash: await sha256(token),
  });
  if (error) return json({ valid: false, error: "The license could not be activated." }, 500);
  return json({ valid: true, activation_token: token });
});

