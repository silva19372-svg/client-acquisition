const identity = window.netlifyIdentity;
const elements = {
  signIn: document.querySelector("#signIn"),
  signOut: document.querySelector("#signOut"),
  app: document.querySelector("#callerApp"),
  refresh: document.querySelector("#refresh"),
  leads: document.querySelector("#leads"),
  updated: document.querySelector("#updated"),
  notice: document.querySelector("#notice"),
};

let lastNonEmptyBatch = null;

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[character]);

const safeUrl = (value) => {
  try {
    const url = new URL(String(value || ""));
    return ["https:", "http:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
};

function showNotice(message, bad = false) {
  elements.notice.textContent = message;
  elements.notice.className = `notice${bad ? " bad" : ""}`;
  elements.notice.hidden = false;
}

function contacts(items) {
  const phones = (items || []).filter((item) => item?.type === "phone" && item.value);
  if (!phones.length) return '<span class="subtle">No public business phone available.</span>';
  return phones.map((item) => `<a class="call" href="tel:${escapeHtml(item.value)}">Call ${escapeHtml(item.value)}</a>`).join("");
}

function links(lead) {
  const destinations = [
    [lead.website_url, "website"],
    [lead.source_url, "source"],
  ].filter(([url]) => safeUrl(url));
  return destinations.length
    ? destinations.map(([url, label]) => `<a href="${escapeHtml(safeUrl(url))}" target="_blank" rel="noreferrer">${label}</a>`).join(" / ")
    : "";
}

function leadCard(lead) {
  const reasons = (lead.score_reasons || []).map((reason) => `<span class="pill">${escapeHtml(reason)}</span>`).join("");
  const issues = (lead.issues || []).map((issue) => `<li>${escapeHtml(issue)}</li>`).join("");
  return `<article class="lead">
    <div class="lead-copy">
      <p class="eyebrow">${escapeHtml(lead.category)} / ${escapeHtml(lead.area || lead.city)}</p>
      <h2>${escapeHtml(lead.name)}</h2>
      <div class="contact-row">${contacts(lead.contact_channels)}</div>
      ${issues ? `<ul>${issues}</ul>` : ""}
      ${lead.outreach_pitch ? `<p class="pitch">${escapeHtml(lead.outreach_pitch)}</p>` : ""}
      <p class="sources">${links(lead)}</p>
      <div class="pills">${reasons}</div>
    </div>
    <div class="score" aria-label="Lead score ${escapeHtml(lead.score)}"><strong>${escapeHtml(lead.score)}</strong><span>fit score</span></div>
  </article>`;
}

function render(data) {
  const leads = data.leads || [];
  if (!leads.length) {
    elements.leads.innerHTML = `<section class="empty"><h2>No new businesses are ready for you yet.</h2><p>The team is replenishing the public lead pool. Refresh again later.</p></section>`;
  } else {
    elements.leads.innerHTML = leads.map(leadCard).join("");
    lastNonEmptyBatch = data;
  }
  elements.updated.textContent = data.batch_created_at
    ? `Batch prepared ${new Date(data.batch_created_at).toLocaleString()}. ${data.remaining_pool || 0} more are currently available.`
    : "Your current public-business call batch.";
}

async function callApi(method = "GET") {
  const token = identity?.currentUser()?.token?.access_token;
  const response = await fetch("/.netlify/functions/caller-gateway", {
    method,
    cache: "no-store",
    headers: token ? { authorization: `Bearer ${token}` } : {},
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Could not load the call list.");
  return data;
}

async function loadInitialBatch() {
  elements.refresh.disabled = true;
  try {
    let data = await callApi();
    if (!(data.leads || []).length) data = await callApi("POST");
    render(data);
    elements.notice.hidden = true;
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    elements.refresh.disabled = false;
  }
}

async function refresh() {
  elements.refresh.disabled = true;
  elements.refresh.textContent = "Refreshing…";
  try {
    const data = await callApi("POST");
    if ((data.leads || []).length) {
      render(data);
    } else if (lastNonEmptyBatch) {
      render(lastNonEmptyBatch);
    } else {
      render(data);
    }
    showNotice(data.refreshed === false
      ? (data.message || "Your current call list is still ready while the next reserve is prepared.")
      : "Your next call batch is ready.");
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    elements.refresh.disabled = false;
    elements.refresh.textContent = "Refresh call list";
  }
}
function setSignedIn(signedIn) {
  elements.signIn.hidden = signedIn;
  elements.signOut.hidden = !signedIn;
  elements.app.hidden = !signedIn;
  if (signedIn) loadInitialBatch();
}

elements.signIn.addEventListener("click", () => identity?.open("login"));
elements.signOut.addEventListener("click", () => identity?.logout());
elements.refresh.addEventListener("click", refresh);

if (!identity) {
  showNotice("Login is unavailable until Netlify Identity is configured.", true);
} else {
  identity.on("init", (user) => setSignedIn(Boolean(user)));
  identity.on("login", () => {
    identity.close();
    setSignedIn(true);
  });
  identity.on("logout", () => setSignedIn(false));
  identity.init();
}
