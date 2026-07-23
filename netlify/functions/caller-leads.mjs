import { getUser } from "@netlify/identity";

const json = (statusCode, body) =>
  new Response(JSON.stringify(body), {
    status: statusCode,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });

const configured = () => {
  const apiUrl = (process.env.RAILWAY_API_BASE_URL || "").replace(/\/$/, "");
  const sharedSecret = process.env.PORTAL_SHARED_SECRET || "";
  return { apiUrl, sharedSecret };
};

export default async (request) => {
  if (!["GET", "POST"].includes(request.method)) {
    return json(405, { ok: false, error: "Method not allowed." });
  }

  const user = await getUser();
  const roles = Array.isArray(user?.app_metadata?.roles) ? user.app_metadata.roles : [];
  if (!user || !roles.includes("caller")) {
    return json(403, { ok: false, error: "A caller invitation is required." });
  }

  const { apiUrl, sharedSecret } = configured();
  if (!apiUrl || !sharedSecret) {
    console.error("Caller portal is missing Railway service configuration.");
    return json(503, { ok: false, error: "The caller portal is not configured yet." });
  }

  const path = request.method === "POST" ? "/v1/caller/refresh" : "/v1/caller/current";
  try {
    const response = await fetch(apiUrl + path, {
      method: request.method,
      headers: {
        "x-portal-secret": sharedSecret,
        "x-portal-user": String(user.id || ""),
        "accept": "application/json",
      },
    });
    const data = await response.json().catch(() => ({}));
    return json(response.status, data);
  } catch (error) {
    console.error("Railway API request failed", error);
    return json(502, { ok: false, error: "The lead service is temporarily unavailable." });
  }
};
