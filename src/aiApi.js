const BASE_URL = import.meta.env.VITE_AI_API_URL;
const API_KEY = import.meta.env.VITE_AI_API_KEY;

async function postJson(path, body) {
  if (!BASE_URL || !API_KEY) {
    throw new Error("AI API 未配置，请检查 .env 中的 VITE_AI_API_URL 和 VITE_AI_API_KEY");
  }

  const resp = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    let message = "";
    try {
      const data = await resp.json();
      message = data?.detail || data?.message || "";
    } catch {
      message = await resp.text().catch(() => "");
    }
    throw new Error(message || "AI 服务暂时不可用，请稍后再试。");
  }

  return resp.json();
}

export async function research(question, options = {}) {
  return postJson("/ai/research", {
    question,
    image_url: options.imageUrl || null,
    previous_answer_summary: options.previousAnswerSummary || null,
    previous_citation_ids: options.previousCitationIds || [],
  });
}

export async function saveResearchNote(payload) {
  return postJson("/ai/research-notes", payload);
}

export async function createDiscoveryJob(payload) {
  return postJson("/ai/discovery-jobs", payload);
}

export async function createDiscoverySupplement(jobId) {
  return postJson(`/ai/discovery-jobs/${jobId}/supplement`, {});
}

export async function getDiscoveryJob(jobId) {
  if (!BASE_URL || !API_KEY) {
    throw new Error("AI API 未配置，请检查 .env 中的 VITE_AI_API_URL 和 VITE_AI_API_KEY");
  }

  const resp = await fetch(`${BASE_URL}/ai/discovery-jobs/${jobId}`, {
    method: "GET",
    headers: { "X-API-Key": API_KEY },
  });

  if (!resp.ok) {
    let message = "";
    try {
      const data = await resp.json();
      message = data?.detail || data?.message || "";
    } catch {
      message = await resp.text().catch(() => "");
    }
    throw new Error(message || "读取外部发现任务失败，请稍后重试。");
  }

  return resp.json();
}

export async function ignoreDiscoveryCandidate(candidateId) {
  return postJson(`/ai/discovery-candidates/${candidateId}/ignore`, {});
}

export async function approveDiscoveryCandidate(candidateId) {
  return postJson(`/ai/discovery-candidates/${candidateId}/approve`, {});
}

export async function rejectDiscoveryCandidate(candidateId, reason = "不相关") {
  return postJson(`/ai/discovery-candidates/${candidateId}/reject`, { reason });
}
