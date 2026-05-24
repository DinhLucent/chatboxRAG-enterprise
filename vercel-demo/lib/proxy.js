const MAX_BODY_BYTES = 128 * 1024;

function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}

function serviceUnavailablePayload(message) {
  return {
    error: "SERVICE_UNAVAILABLE",
    message,
    service_status: {
      state: "offline",
      can_chat: false,
      title: "He thong tam thoi mat ket noi",
      message,
    },
  };
}

function getHeader(req, name) {
  const value = req.headers[name.toLowerCase()];
  return Array.isArray(value) ? value[0] : value;
}

function requireDemoAccess(req, res) {
  const expected = process.env.DEMO_ACCESS_TOKEN;
  if (!expected) {
    return true;
  }

  const bearer = getHeader(req, "authorization") || "";
  const headerToken = getHeader(req, "x-demo-token") || "";
  const token = bearer.toLowerCase().startsWith("bearer ")
    ? bearer.slice(7).trim()
    : headerToken.trim();

  if (token && token === expected) {
    return true;
  }

  sendJson(res, 401, {
    error: "DEMO_ACCESS_REQUIRED",
    message: "Cần có mã truy cập demo.",
  });
  return false;
}

async function readBody(req) {
  if (req.body && typeof req.body === "object") {
    return req.body;
  }
  if (typeof req.body === "string") {
    return req.body ? JSON.parse(req.body) : {};
  }

  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) {
      throw new Error("Request body too large");
    }
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  return raw ? JSON.parse(raw) : {};
}

function backendUrl(path) {
  const base = process.env.KB_BACKEND_BASE_URL;
  if (!base) {
    throw new Error("KB_BACKEND_BASE_URL is not configured");
  }
  return `${base.replace(/\/$/, "")}${path}`;
}

async function forwardJson(req, res, path, options = {}) {
  if (!requireDemoAccess(req, res)) {
    return;
  }

  const method = options.method || req.method || "GET";
  const headers = {
    Accept: "application/json",
  };
  const backendToken = process.env.KB_BACKEND_TOKEN;
  if (backendToken) {
    headers["X-KB-Token"] = backendToken;
  }

  let body;
  if (!["GET", "HEAD"].includes(method.toUpperCase())) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body ?? (await readBody(req)));
  }

  let response;
  try {
    response = await fetch(backendUrl(path), {
      method,
      headers,
      body,
    });
  } catch (error) {
    sendJson(
      res,
      503,
      serviceUnavailablePayload("Khong ket noi duoc may xu ly noi bo. Vui long thu lai sau hoac bao ky thuat."),
    );
    return;
  }

  const text = await response.text();
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { raw: text };
  }

  if (typeof options.transform === "function") {
    payload = options.transform(payload, response);
  }

  sendJson(res, response.status, payload);
}

function handleOptions(req, res) {
  if (req.method !== "OPTIONS") {
    return false;
  }
  res.statusCode = 204;
  res.end();
  return true;
}

module.exports = {
  forwardJson,
  handleOptions,
  readBody,
  sendJson,
  serviceUnavailablePayload,
};
