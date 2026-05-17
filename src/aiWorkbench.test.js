import test from "node:test";
import assert from "node:assert/strict";

import {
  buildBriefRequest,
  getConversationTitle,
  mergeConversationMessages,
  summarizeJobStatus,
} from "./aiWorkbench.js";

test("getConversationTitle uses explicit title before first message", () => {
  assert.equal(getConversationTitle({ title: "英国素材调研" }, []), "英国素材调研");
  assert.equal(
    getConversationTitle({ title: "新对话" }, [{ role: "user", content: "帮我找英国方面的素材" }]),
    "帮我找英国方面的素材",
  );
});

test("mergeConversationMessages appends new messages without duplicating ids", () => {
  const result = mergeConversationMessages(
    [{ id: "m1", content: "old" }],
    [{ id: "m1", content: "old updated" }, { id: "m2", content: "new" }],
  );

  assert.deepEqual(result.map(item => item.id), ["m1", "m2"]);
  assert.equal(result[0].content, "old updated");
});

test("mergeConversationMessages preserves insertion order when timestamps are missing", () => {
  const result = mergeConversationMessages(
    [
      { id: "optimistic", content: "local pending" },
      { id: "server-old", content: "old", created_at: "2026-05-17T01:00:00Z" },
    ],
    [
      { id: "server-new", content: "new", created_at: "2026-05-17T02:00:00Z" },
      { id: "optimistic", content: "server confirmed" },
    ],
  );

  assert.deepEqual(result.map(item => item.id), ["optimistic", "server-old", "server-new"]);
  assert.equal(result[0].content, "server confirmed");
});

test("buildBriefRequest preserves selections and free text", () => {
  const result = buildBriefRequest({
    originalRequest: "帮我找英国方面的素材",
    selections: { content_scene: ["life"], expression_type: ["experience"] },
    freeText: "不要机构广告",
  });

  assert.equal(result.original_request, "帮我找英国方面的素材");
  assert.deepEqual(result.selections.content_scene, ["life"]);
  assert.equal(result.free_text, "不要机构广告");
});

test("summarizeJobStatus treats partial as usable", () => {
  assert.equal(summarizeJobStatus("partial").label, "部分完成");
  assert.equal(summarizeJobStatus("partial").canReviewCandidates, true);
  assert.equal(summarizeJobStatus("failed").canReviewCandidates, false);
});
