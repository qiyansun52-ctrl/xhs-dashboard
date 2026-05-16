import { resolveAiApiConfig } from "./runtimeConfig.js";

function getApiConfig() {
  return resolveAiApiConfig();
}

async function readErrorMessage(resp) {
  let message = "";
  try {
    const data = await resp.json();
    message = data?.detail || data?.message || "";
  } catch {
    message = await resp.text().catch(() => "");
  }
  return message;
}

async function requestJson(path, options = {}) {
  const { baseUrl, apiKey } = getApiConfig();
  const resp = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
      ...(options.headers || {}),
    },
  });

  if (!resp.ok) {
    throw new Error((await readErrorMessage(resp)) || "运营助手服务暂时不可用，请稍后再试。");
  }

  return resp.json();
}

function parseSseBlock(block) {
  const lines = block.split("\n");
  let event = "message";
  const dataLines = [];

  for (const line of lines) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) return null;

  try {
    return {
      event,
      data: JSON.parse(dataLines.join("\n")),
    };
  } catch {
    return null;
  }
}

export async function createAgentRun(payload) {
  return requestJson("/agent/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getAgentRun(runId) {
  const { baseUrl, apiKey } = getApiConfig();
  const resp = await fetch(`${baseUrl}/agent/runs/${runId}`, {
    method: "GET",
    headers: { "X-API-Key": apiKey },
  });

  if (!resp.ok) {
    throw new Error((await readErrorMessage(resp)) || "读取运营助手任务失败，请稍后重试。");
  }

  return resp.json();
}

export async function listAgentReviewActions({ status, runId } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (runId) params.set("run_id", runId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return requestJson(`/agent/review-actions${suffix}`, { method: "GET" });
}

export async function createAgentReviewAction(payload) {
  return requestJson("/agent/review-actions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function approveAgentReviewAction(actionId, payload = {}) {
  return requestJson(`/agent/review-actions/${actionId}/approve`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function rejectAgentReviewAction(actionId, payload = {}) {
  return requestJson(`/agent/review-actions/${actionId}/reject`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function subscribeAgentRunEvents(runId, { onEvent, onError, onDone } = {}) {
  const { baseUrl, apiKey } = getApiConfig();
  const controller = new AbortController();

  (async () => {
    try {
      const resp = await fetch(`${baseUrl}/agent/runs/${runId}/events`, {
        method: "GET",
        headers: { "X-API-Key": apiKey },
        signal: controller.signal,
      });

      if (!resp.ok) {
        throw new Error((await readErrorMessage(resp)) || "连接运营助手进度失败，请稍后重试。");
      }

      const reader = resp.body?.getReader();
      if (!reader) {
        throw new Error("当前浏览器不支持实时读取运营助手进度。");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const parsed = parseSseBlock(block);
          if (parsed) onEvent?.(parsed);
        }
      }

      if (buffer.trim()) {
        const parsed = parseSseBlock(buffer);
        if (parsed) onEvent?.(parsed);
      }

      onDone?.();
    } catch (error) {
      if (controller.signal.aborted) {
        onDone?.();
        return;
      }
      onError?.(error instanceof Error ? error : new Error("运营助手进度已中断"));
    }
  })();

  return controller;
}
