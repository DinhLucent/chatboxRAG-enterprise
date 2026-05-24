const { forwardJson, handleOptions, readBody, sendJson } = require("../lib/proxy");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  if (req.method !== "POST") {
    sendJson(res, 405, { error: "METHOD_NOT_ALLOWED" });
    return;
  }

  let body;
  try {
    body = await readBody(req);
  } catch (error) {
    sendJson(res, 400, { error: "BAD_REQUEST", message: String(error.message || error) });
    return;
  }

  await forwardJson(req, res, "/api/user/feedback", {
    method: "POST",
    body: {
      log_id: body.query_log_id || body.log_id,
      rating: body.feedback || body.rating,
      session_id: body.session_id,
    },
  });
};

