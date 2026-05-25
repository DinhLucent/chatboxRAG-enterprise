const { forwardJson, handleOptions, readBody, sendJson } = require("../lib/proxy");

function userFacingError(data) {
  const message =
    data.message ||
    data.detail ||
    "He thong tam thoi khong xu ly duoc cau hoi. Vui long thu lai sau.";
  return {
    error: data.error || "CHAT_UNAVAILABLE",
    message,
    service_status: data.service_status || {
      state: "unavailable",
      can_chat: false,
      title: "Chua the tra loi",
      message,
    },
  };
}

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

  const payload = {
    query: body.query,
    template_id: body.template_id || null,
    answer_style: body.answer_style || "brief",
    session_id: body.session_id || null,
    device_id: body.device_id || "vercel-demo",
    use_llm: body.use_llm !== false,
  };

  if (!payload.query || typeof payload.query !== "string") {
    sendJson(res, 400, { error: "QUERY_REQUIRED", message: "Cần nhập câu hỏi." });
    return;
  }

  await forwardJson(req, res, "/api/user/chat", {
    method: "POST",
    body: payload,
    transform: (data, response) => {
      if (!response.ok) {
        return userFacingError(data);
      }
      return {
        answer: data.answer,
        citations: Array.isArray(data.citations)
          ? data.citations.map((citation) => ({
              doc_id: citation.doc_id,
              version: citation.version,
              display_code: citation.display_code,
              display_version: citation.display_version,
              title: citation.title,
              excerpt: citation.excerpt || "",
              anchor_id: citation.anchor_id || "",
            }))
          : [],
        trace: data.trace,
        trace_steps: data.trace_steps || (data.trace ? data.trace.steps : []),
        query_log_id: data.query_log_id || data.log_id,
        knowledge_gap_id: data.knowledge_gap_id,
        latency_ms: data.latency_ms,
        provider: data.provider,
        llm_used: Boolean(data.llm_used),
        session_id: data.session_id,
        session: data.session,
      };
    },
  });
};
