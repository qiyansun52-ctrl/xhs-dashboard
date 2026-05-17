import { resolveAiApiConfig } from "./runtimeConfig.js";

async function readErrorMessage(resp) {
  try {
    const data = await resp.json();
    return data?.detail || data?.message || "";
  } catch {
    return resp.text().catch(() => "");
  }
}

async function requestJson(path, options = {}) {
  const { baseUrl, apiKey } = resolveAiApiConfig();
  const resp = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
      ...(options.headers || {}),
    },
  });
  if (!resp.ok) {
    throw new Error((await readErrorMessage(resp)) || "AI 工作台服务暂时不可用，请稍后再试。");
  }
  return resp.json();
}

export function listConversations() {
  return requestJson("/ai/conversations", { method: "GET" });
}

export function createConversation(payload = {}) {
  return requestJson("/ai/conversations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getConversation(conversationId) {
  return requestJson(`/ai/conversations/${encodeURIComponent(conversationId)}`, { method: "GET" });
}

export function clarifyConversation(conversationId, message) {
  return requestJson(`/ai/conversations/${encodeURIComponent(conversationId)}/clarify`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function buildCrawlerBrief(conversationId, payload) {
  return requestJson(`/ai/conversations/${encodeURIComponent(conversationId)}/crawler-brief`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
