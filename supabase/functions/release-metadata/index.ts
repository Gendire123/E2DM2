import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.8";

const CHANNEL = "windows-stable";
const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

type ReleasePayload = {
  version?: unknown;
  download_url?: unknown;
  sha256?: unknown;
  virustotal_url?: unknown;
  file_size_bytes?: unknown;
};

type ValidReleasePayload = {
  version: string;
  download_url: string;
  sha256: string;
  virustotal_url: string;
  file_size_bytes: number;
};

function jsonResponse(body: unknown, status = 200, cacheControl = "no-store") {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders,
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cacheControl,
    },
  });
}

function isAllowedUrl(value: unknown, hostname: string): value is string {
  if (typeof value !== "string") return false;

  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === hostname;
  } catch {
    return false;
  }
}

function validatePayload(payload: ReleasePayload): string | null {
  if (typeof payload.version !== "string" ||
      !/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(payload.version)) {
    return "version must be a semantic version without a leading v";
  }
  if (!isAllowedUrl(payload.download_url, "github.com")) {
    return "download_url must be an HTTPS github.com URL";
  }
  if (typeof payload.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(payload.sha256)) {
    return "sha256 must be a lowercase SHA-256 digest";
  }
  if (!isAllowedUrl(payload.virustotal_url, "www.virustotal.com")) {
    return "virustotal_url must be an HTTPS www.virustotal.com URL";
  }
  if (typeof payload.file_size_bytes !== "number" ||
      !Number.isSafeInteger(payload.file_size_bytes) || payload.file_size_bytes <= 0) {
    return "file_size_bytes must be a positive integer";
  }
  return null;
}

Deno.serve(async (request) => {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  const service = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  if (request.method === "GET") {
    const { data, error } = await service
      .from("release_metadata")
      .select("version, download_url, sha256, virustotal_url, file_size_bytes, published_at")
      .eq("channel", CHANNEL)
      .maybeSingle();

    if (error) {
      console.error("Could not read release metadata", error);
      return jsonResponse({ error: "Could not read release metadata" }, 500);
    }
    if (!data) {
      return jsonResponse({ error: "No release has been published" }, 404);
    }

    return jsonResponse(data, 200, "public, max-age=60, stale-while-revalidate=300");
  }

  if (request.method === "POST") {
    const expectedToken = Deno.env.get("RELEASE_PUBLISH_TOKEN");
    const suppliedToken = request.headers.get("Authorization")?.replace(/^Bearer\s+/i, "");
    if (!expectedToken || suppliedToken !== expectedToken) {
      return jsonResponse({ error: "Unauthorized" }, 401);
    }

    let payload: ReleasePayload;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse({ error: "Request body must be valid JSON" }, 400);
    }

    const validationError = validatePayload(payload);
    if (validationError) {
      return jsonResponse({ error: validationError }, 400);
    }

    const release = payload as ValidReleasePayload;
    const now = new Date().toISOString();
    const { data, error } = await service
      .from("release_metadata")
      .upsert({
        channel: CHANNEL,
        version: release.version,
        download_url: release.download_url,
        sha256: release.sha256,
        virustotal_url: release.virustotal_url,
        file_size_bytes: release.file_size_bytes,
        published_at: now,
        updated_at: now,
      }, { onConflict: "channel" })
      .select("version, download_url, sha256, virustotal_url, file_size_bytes, published_at")
      .single();

    if (error) {
      console.error("Could not publish release metadata", error);
      return jsonResponse({ error: "Could not publish release metadata" }, 500);
    }

    return jsonResponse(data);
  }

  return jsonResponse({ error: "Method not allowed" }, 405);
});
