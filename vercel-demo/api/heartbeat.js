const { forwardJson, handleOptions, sendJson } = require("../lib/proxy");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  if (req.method !== "POST") {
    sendJson(res, 405, { error: "METHOD_NOT_ALLOWED" });
    return;
  }

  await forwardJson(req, res, "/api/user/session/heartbeat", {
    method: "POST"
  });
};
