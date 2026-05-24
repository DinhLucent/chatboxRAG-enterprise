const { forwardJson, handleOptions, sendJson } = require("../lib/proxy");

module.exports = async function handler(req, res) {
  if (handleOptions(req, res)) return;
  if (req.method !== "GET") {
    sendJson(res, 405, { error: "METHOD_NOT_ALLOWED" });
    return;
  }

  await forwardJson(req, res, "/api/health", {
    method: "GET",
    transform: (data) => ({
      status: "ok",
      auth_required: Boolean(data.auth?.required),
      llm_configured: Boolean(data.llm?.configured),
      active_documents: Number(data.manifest?.active ?? 0),
      pending_review: Number(data.manifest?.pending_review ?? 0),
      open_gaps: Number(data.quality?.open_gap_count ?? 0),
      open_incidents: Number(data.incidents?.open ?? data.quality?.open_incident_count ?? 0),
      critical_incidents: Number(data.incidents?.critical ?? data.quality?.critical_incident_count ?? 0),
      service_status: data.service_status || {
        state: "unknown",
        can_chat: false,
        title: "Chua xac dinh trang thai",
        message: "Chua nhan duoc trang thai he thong.",
      },
      ragflow_configured: Boolean(data.ragflow?.configured),
      readiness_ready: Boolean(data.readiness?.ready),
      latest_evaluation_pass: Boolean(data.evaluation?.pass),
      total_cases: data.evaluation?.metrics?.total_cases ?? null,
      passed_cases: data.evaluation?.metrics?.passed_cases ?? null,
    }),
  });
};
