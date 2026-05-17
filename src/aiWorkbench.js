export function getConversationTitle(conversation, messages = []) {
  const title = conversation?.title?.trim();
  if (title && title !== "新对话") return title;
  const firstUser = messages.find(message => message.role === "user" && message.content?.trim());
  return firstUser?.content?.trim()?.slice(0, 28) || "新对话";
}

export function mergeConversationMessages(prev = [], next = []) {
  const map = new Map(prev.map(message => [message.id, message]));
  for (const message of next) {
    map.set(message.id, { ...(map.get(message.id) || {}), ...message });
  }
  return [...map.values()].sort((a, b) =>
    String(a.created_at || "").localeCompare(String(b.created_at || "")),
  );
}

export function buildBriefRequest({ originalRequest, selections, freeText }) {
  return {
    original_request: originalRequest,
    selections: selections || {},
    free_text: freeText || "",
  };
}

export function summarizeJobStatus(status) {
  const map = {
    pending: { label: "等待开始", tone: "muted", canReviewCandidates: false },
    running: { label: "正在发现", tone: "info", canReviewCandidates: false },
    completed: { label: "已完成", tone: "success", canReviewCandidates: true },
    partial: { label: "部分完成", tone: "warning", canReviewCandidates: true },
    failed: { label: "失败", tone: "danger", canReviewCandidates: false },
    cancelled: { label: "已取消", tone: "muted", canReviewCandidates: false },
  };
  return map[status] || { label: status || "未知", tone: "muted", canReviewCandidates: false };
}
