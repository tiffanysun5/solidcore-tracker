/**
 * Solidcore booking worker (Cloudflare Workers)
 *
 * GET  /book?class_id=X&secret=Y  → confirmation page
 * POST /book                       → triggers GitHub Actions booking workflow
 *
 * Environment variables (set via `wrangler secret put`):
 *   BOOKING_SECRET  — random string embedded in email URLs to prevent unauthorized use
 *   GITHUB_TOKEN    — GitHub PAT with `workflow` scope
 *   GITHUB_REPO     — e.g. "tiffanysun/solidcore-tracker"
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname !== "/book") {
      return new Response("Not found", { status: 404 });
    }

    if (request.method === "GET") {
      return handleConfirmPage(url, env);
    }

    if (request.method === "POST") {
      return handleBook(request, env);
    }

    return new Response("Method not allowed", { status: 405 });
  },
};

// ── GET: show confirmation page ───────────────────────────────────────────

function handleConfirmPage(url, env) {
  const classId = url.searchParams.get("class_id");
  const secret  = url.searchParams.get("secret");
  const studio  = url.searchParams.get("studio")     || "";
  const instructor = url.searchParams.get("instructor") || "";
  const dt      = url.searchParams.get("dt")         || "";
  const muscles = url.searchParams.get("muscles")    || "";

  if (!classId || secret !== env.BOOKING_SECRET) {
    return new Response("Invalid or expired booking link.", { status: 401 });
  }

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Confirm booking</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f5f5f5; margin: 0; padding: 40px 20px; color: #222; }
    .card { max-width: 420px; margin: 0 auto; background: #fff;
            border-radius: 12px; padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }
    h2 { margin: 0 0 24px; font-size: 20px; }
    .detail { display: flex; justify-content: space-between; padding: 10px 0;
              border-bottom: 1px solid #f0f0f0; font-size: 14px; }
    .detail:last-of-type { border: none; }
    .label { color: #888; }
    .value { font-weight: 500; text-align: right; }
    .muscle { color: #059669; }
    .btn { display: block; width: 100%; margin-top: 28px; padding: 14px;
           background: #111; color: #fff; border: none; border-radius: 8px;
           font-size: 15px; font-weight: 600; cursor: pointer; }
    .btn:hover { background: #333; }
    .note { margin-top: 12px; font-size: 11px; color: #aaa; text-align: center; }
    .success { text-align: center; padding: 20px 0; }
    .success h2 { color: #059669; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Confirm booking</h2>
    <div class="detail"><span class="label">Studio</span><span class="value">${studio}</span></div>
    <div class="detail"><span class="label">Date &amp; time</span><span class="value">${dt}</span></div>
    <div class="detail"><span class="label">Instructor</span><span class="value">${instructor}</span></div>
    <div class="detail"><span class="label">Muscle focus</span><span class="value muscle">${muscles}</span></div>
    <form method="POST" action="/book">
      <input type="hidden" name="class_id"  value="${escHtml(classId)}">
      <input type="hidden" name="secret"    value="${escHtml(secret)}">
      <input type="hidden" name="studio"    value="${escHtml(studio)}">
      <input type="hidden" name="instructor" value="${escHtml(instructor)}">
      <input type="hidden" name="dt"        value="${escHtml(dt)}">
      <input type="hidden" name="muscles"   value="${escHtml(muscles)}">
      <button class="btn" type="submit">Book this class</button>
    </form>
    <p class="note">This will book via your Wellhub account.</p>
  </div>
</body>
</html>`;

  return new Response(html, { headers: { "Content-Type": "text/html;charset=utf-8" } });
}

// ── POST: trigger GitHub Actions booking workflow ─────────────────────────

async function handleBook(request, env) {
  const form     = await request.formData();
  const classId  = form.get("class_id");
  const secret   = form.get("secret");
  const studio   = form.get("studio")     || "";
  const instructor = form.get("instructor") || "";
  const dt       = form.get("dt")         || "";
  const muscles  = form.get("muscles")    || "";

  if (!classId || secret !== env.BOOKING_SECRET) {
    return new Response("Unauthorized.", { status: 401 });
  }

  const ghResp = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/book.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "solidcore-tracker",
      },
      body: JSON.stringify({ ref: "main", inputs: { class_ids: classId } }),
    }
  );

  const ok = ghResp.status === 204;

  const html = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>${ok ? "Booked!" : "Booking failed"}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f5f5f5; margin: 0; padding: 40px 20px; }
    .card { max-width: 420px; margin: 0 auto; background: #fff;
            border-radius: 12px; padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,.08);
            text-align: center; }
    h2 { margin: 0 0 12px; color: ${ok ? "#059669" : "#e11d48"}; font-size: 22px; }
    p { color: #555; font-size: 14px; line-height: 1.6; margin: 0; }
    .detail { margin-top: 20px; font-size: 13px; color: #888; }
  </style>
</head>
<body>
  <div class="card">
    ${ok
      ? `<h2>✓ Booking triggered</h2>
         <p>Your class is being booked now via GitHub Actions.<br>
            It usually completes within 2 minutes.</p>
         <div class="detail">${studio} · ${dt} · ${instructor}<br><strong>${muscles}</strong></div>`
      : `<h2>✗ Booking failed</h2>
         <p>Could not trigger the booking workflow. Check GitHub Actions logs.</p>`
    }
  </div>
</body>
</html>`;

  return new Response(html, {
    status: ok ? 200 : 500,
    headers: { "Content-Type": "text/html;charset=utf-8" },
  });
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
