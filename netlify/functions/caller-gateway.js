const json = (statusCode, body) => ({
  statusCode,
  headers: {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  },
  body: JSON.stringify(body),
});

const configured = () => ({
  apiUrl: (process.env.RAILWAY_API_BASE_URL || "").replace(/\/$/, ""),
  sharedSecret: process.env.PORTAL_SHARED_SECRET || "",
});

exports.handler = async (event) => {
  if (!["GET", "POST"].includes(event.httpMethod)) {
    return json(405, { ok: false, error: "Method not allowed." });
  }

  const token = event.headers.authorization || event.headers.Authorization;
  const origin = event.rawUrl ? new URL(event.rawUrl).origin : `https://${event.headers.host}`;
  const identityResponse = token
    ? await fetch(`${origin}/.netlify/identity/user`, { headers: { authorization: token } })
    : null;
  const user = identityResponse?.ok ? await identityResponse.json().catch(() => null) : null;
  if (!user) return json(403, { ok: false, error: "Sign in to open your call list." });

  const { apiUrl, sharedSecret } = configured();
  if (!apiUrl || !sharedSecret) {
    console.error("Caller portal is missing Railway service configuration.");
    return json(503, { ok: false, error: "The caller portal is not configured yet." });
  }

  const path = event.httpMethod === "POST" ? "/v1/caller/refresh" : "/v1/caller/current";
  try {
    const response = await fetch(apiUrl + path, {
      method: event.httpMethod,
      headers: {
        "x-portal-secret": sharedSecret,
        "x-portal-user": String(user.id || user.email || "caller"),
        accept: "application/json",
      },
    });
    return json(response.status, await response.json().catch(() => ({})));
  } catch (error) {
    console.error("Railway API request failed", error);
    return json(502, { ok: false, error: "The lead service is temporarily unavailable." });
  }
};
