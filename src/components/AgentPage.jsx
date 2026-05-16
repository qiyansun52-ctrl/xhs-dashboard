import { useEffect, useRef, useState } from "react";
import {
  Bot, Loader2, Send, Sparkles, ClipboardList, CheckCircle2, XCircle,
  CalendarPlus, FileText, Layers, ShieldCheck, MessageSquareText, Search,
} from "lucide-react";
import {
  approveAgentReviewAction,
  createAgentReviewAction,
  createAgentRun,
  getAgentRun,
  listAgentReviewActions,
  rejectAgentReviewAction,
  subscribeAgentRunEvents,
} from "../agentApi.js";
import {
  inputStyle, useIsMobile, Card, EmptyState, useToast,
  createGlassCardStyle, createPrimaryButtonStyle, designTokens,
} from "./shared.jsx";

const STEP_LABELS = {
  plan: "理解任务",
  tool_call: "内部检索",
  answer: "整理回答",
  observation: "记录观察",
  decision: "做出决策",
};

const STEP_STATUS_STYLES = {
  pending: { color: "#FF9F43", background: "rgba(255,159,67,0.08)", border: "rgba(255,159,67,0.18)" },
  completed: { color: "#26DE81", background: "rgba(38,222,129,0.08)", border: "rgba(38,222,129,0.18)" },
  failed: { color: "#FF5C7A", background: "rgba(255,36,66,0.08)", border: "rgba(255,36,66,0.18)" },
};

const EVIDENCE_STYLES = {
  empty: { label: "无可用内部证据", color: "#FF5C7A", background: "rgba(255,36,66,0.08)", border: "rgba(255,36,66,0.18)" },
  weak: { label: "内部证据较少", color: "#FF9F43", background: "rgba(255,159,67,0.08)", border: "rgba(255,159,67,0.18)" },
  strong: { label: "内部证据充足", color: "#26DE81", background: "rgba(38,222,129,0.08)", border: "rgba(38,222,129,0.18)" },
};

const ACTION_LABELS = {
  save_note: "保存研究笔记",
  add_calendar_item: "写入日历",
  save_draft: "保存草稿",
  mark_template: "存为团队模板",
  approve_candidate: "候选素材入库",
};

const REJECT_REASONS = ["不相关", "低质量", "疑似广告", "重复素材", "不适合团队调性", "数据异常", "已入库"];

const WORKFLOW_TEMPLATES = [
  { icon: <CalendarPlus size={14} />, text: "帮我规划下周英国账号内容", actionType: "add_calendar_item" },
  { icon: <Search size={14} />, text: "给我几个英国春天能出收藏的选题", actionType: "save_note" },
  { icon: <FileText size={14} />, text: "用 Jasper_Page 的口吻写 5 个标题", actionType: "save_draft" },
  { icon: <ShieldCheck size={14} />, text: "检查这段发布文案有没有风险", actionType: "save_note" },
  { icon: <MessageSquareText size={14} />, text: "总结评论区痛点并给追更选题", actionType: "save_note" },
  { icon: <Layers size={14} />, text: "拆解这篇爆款的标题钩子和结构", actionType: "mark_template" },
];

function SectionCard({ title, children, sectionRef }) {
  return (
    <section ref={sectionRef} style={{ ...createGlassCardStyle({ padding: 16 }) }}>
      <div style={{ fontSize: 11, color: "#777", marginBottom: 10 }}>{title}</div>
      {children}
    </section>
  );
}

function mergeStepList(prev, nextStep) {
  const index = prev.findIndex(step => step.id === nextStep.id);
  if (index === -1) {
    return [...prev, nextStep].sort((a, b) => (a.step_index || 0) - (b.step_index || 0));
  }

  return prev.map(step => (step.id === nextStep.id ? nextStep : step));
}

function TimelineStep({ step }) {
  const style = STEP_STATUS_STYLES[step.status] || STEP_STATUS_STYLES.pending;
  const answer = step.output_payload?.final_answer || step.output_payload?.answer || step.output_payload || {};
  const skillChain = (step.output_payload?.skill_chain || [])
    .map(item => item.skill_name || item)
    .join(" -> ");

  return (
    <div style={{ position: "relative", paddingLeft: 22 }}>
      <div style={{
        position: "absolute",
        left: 0,
        top: 6,
        width: 10,
        height: 10,
        borderRadius: "50%",
        background: style.color,
        boxShadow: `0 0 0 4px ${style.background}`,
        animation: step.status === "pending" ? "glowPulse 1.6s ease-in-out infinite" : "none",
      }} />
      <div style={{
        ...createGlassCardStyle({ padding: 12, radius: 10 }),
        borderRadius: 10,
        animation: "timelineEnter 200ms ease",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
          <div style={{ fontSize: 13, color: "#e8e8e8", fontWeight: 700 }}>
            {STEP_LABELS[step.step_type] || step.step_type}
          </div>
          <span style={{
            fontSize: 10,
            color: style.color,
            background: style.background,
            border: `1px solid ${style.border}`,
            borderRadius: 999,
            padding: "3px 8px",
            flexShrink: 0,
          }}>
            {step.status === "completed" ? "已完成" : step.status === "failed" ? "失败" : "进行中"}
          </span>
        </div>

        {step.step_type === "plan" && (
          <div style={{ marginTop: 8, fontSize: 12, color: "#888", lineHeight: 1.7 }}>
            意图：{step.output_payload?.intent || "general_qa"} · Skill：{skillChain || "content_research"}
            {step.output_payload?.fallback_used ? " · 已启用低延迟方案" : ""}
            {step.output_payload?.cache_hit ? " · 命中历史计划" : ""}
          </div>
        )}

        {step.step_type === "tool_call" && (
          <div style={{ marginTop: 8, fontSize: 12, color: "#888", lineHeight: 1.7 }}>
            {answer?.conclusion || "正在从内部知识库筛选证据。"}
          </div>
        )}

        {step.step_type === "answer" && (
          <div style={{ marginTop: 8, fontSize: 12, color: "#888", lineHeight: 1.7 }}>
            {step.output_payload?.final_answer?.conclusion || "回答已整理完成。"}
          </div>
        )}

        {step.error_message && (
          <div style={{ marginTop: 8, fontSize: 12, color: "#FF5C7A", lineHeight: 1.6 }}>
            {step.error_message}
          </div>
        )}
      </div>
    </div>
  );
}

function ReviewQueue({ actions, reviewingId, onApprove, onReject }) {
  if (actions.length === 0) {
    return (
      <EmptyState
        title="暂无待确认动作"
        description="Agent 产出的写库、排期、存草稿等动作会先进入这里。"
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {actions.map(action => (
        <div key={action.id} style={{ ...createGlassCardStyle({ padding: 12, radius: 10 }) }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "flex-start", marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 13, color: "#fff", fontWeight: 700 }}>
                {ACTION_LABELS[action.action_type] || action.action_type}
              </div>
              <div style={{ fontSize: 11, color: designTokens.color.textMuted, marginTop: 4 }}>
                证据分 {action.evidence_score == null ? "-" : Math.round(action.evidence_score * 100)}
              </div>
            </div>
            <span style={{
              fontSize: 10,
              color: "#FF9F43",
              background: "rgba(255,159,67,0.08)",
              border: "1px solid rgba(255,159,67,0.18)",
              borderRadius: 999,
              padding: "3px 8px",
            }}>
              待确认
            </span>
          </div>
          <div style={{ fontSize: 12, color: "#aaa", lineHeight: 1.65, marginBottom: 8 }}>
            {action.payload?.preview || action.payload?.title || action.rationale || "等待人工审核后再执行。"}
          </div>
          {action.rationale && (
            <div style={{ fontSize: 11, color: designTokens.color.textMuted, lineHeight: 1.55, marginBottom: 8 }}>
              Agent 判断：{action.rationale}
            </div>
          )}
          {action.duplicate_warning && (
            <div style={{ fontSize: 11, color: "#FF9F43", lineHeight: 1.55, marginBottom: 8 }}>
              {action.duplicate_warning}
            </div>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              disabled={reviewingId === action.id}
              onClick={() => onApprove(action)}
              style={{
                ...createPrimaryButtonStyle({ disabled: reviewingId === action.id }),
                padding: "7px 10px",
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              <CheckCircle2 size={13} /> 通过
            </button>
            <select
              disabled={reviewingId === action.id}
              defaultValue=""
              onChange={event => {
                if (!event.target.value) return;
                onReject(action, event.target.value);
                event.target.value = "";
              }}
              style={{
                ...inputStyle,
                width: "auto",
                padding: "7px 10px",
                color: reviewingId === action.id ? "#555" : "#FF5C7A",
              }}
            >
              <option value="">拒绝原因</option>
              {REJECT_REASONS.map(reason => <option key={reason} value={reason}>{reason}</option>)}
            </select>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function AgentPage() {
  const isMobile = useIsMobile();
  const toast = useToast();
  const streamRef = useRef(null);
  const reviewQueueRef = useRef(null);
  const [prompt, setPrompt] = useState("");
  const [targetActionType, setTargetActionType] = useState("save_note");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [currentRun, setCurrentRun] = useState(null);
  const [steps, setSteps] = useState([]);
  const [events, setEvents] = useState([]);
  const [reviewActions, setReviewActions] = useState([]);
  const [reviewingActionId, setReviewingActionId] = useState(null);

  useEffect(() => {
    return () => {
      streamRef.current?.abort();
    };
  }, []);

  const loadReviewActions = async () => {
    try {
      const payload = await listAgentReviewActions({ status: "pending" });
      setReviewActions(payload.actions || []);
    } catch (reviewError) {
      setError(reviewError.message || "读取待确认队列失败，请稍后重试。");
    }
  };

  const scrollToReviewQueue = () => {
    reviewQueueRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const syncSnapshot = async runId => {
    const snapshot = await getAgentRun(runId);
    setCurrentRun(snapshot.run);
    setSteps(snapshot.steps || []);
  };

  const handleEvent = async payload => {
    setEvents(prev => [...prev.slice(-19), payload]);
    const { event, data } = payload;

    if (data?.step) {
      setSteps(prev => mergeStepList(prev, data.step));
    }

    if (event === "run.completed" || event === "run.failed") {
      setCurrentRun(prev => ({
        ...(prev || {}),
        id: data.run_id || prev?.id,
        status: data.status || prev?.status,
        final_answer: data.final_answer || prev?.final_answer,
        error_message: data.error_message || prev?.error_message || null,
      }));
      if (data.run_id) {
        try {
          await syncSnapshot(data.run_id);
        } catch (snapshotError) {
          setError(snapshotError.message || "同步运营助手结果失败，请手动刷新后再试。");
        }
      }
    }
  };

  const handleSubmit = async () => {
    if (!prompt.trim() || creating) return;

    streamRef.current?.abort();
    setCreating(true);
    setError("");
    setEvents([]);
    setSteps([]);
    setCurrentRun(null);

    try {
      const created = await createAgentRun({ message: prompt.trim() });
      setCurrentRun(created.run);
      setSteps(created.steps || []);
      streamRef.current = subscribeAgentRunEvents(created.run.id, {
        onEvent: handleEvent,
        onError: streamError => setError(streamError.message || "运营助手进度已中断，请稍后重试。"),
        onDone: () => {
          streamRef.current = null;
        },
      });
    } catch (submitError) {
      setError(submitError.message || "创建运营助手任务失败，请稍后重试。");
    } finally {
      setCreating(false);
    }
  };

  const handleCreateReviewAction = async (actionType = targetActionType) => {
    if (!currentRun?.id || !answer) {
      setError("请先等待 Agent 产出结果，再创建待确认动作。");
      return;
    }
    try {
      const evidenceScore = { empty: 0.15, weak: 0.48, strong: 0.86 }[answer.evidence_quality || "strong"] || 0.7;
      const resp = await createAgentReviewAction({
        run_id: currentRun.id,
        action_type: actionType,
        payload: {
          title: ACTION_LABELS[actionType] || "Agent 产出",
          preview: answer.conclusion || prompt,
          recommendations: answer.recommendations || [],
          trace_id: answer.trace_id || null,
        },
        rationale: "Agent 已生成可落地内容，按产品边界需人工确认后再写库或进入排期。",
        evidence_score: evidenceScore,
        duplicate_warning: answer.evidence_quality === "weak" ? "内部证据较少，建议确认素材是否足够贴合。" : null,
      });
      setReviewActions(prev => [resp.action, ...prev]);
      toast("已加入待确认队列");
    } catch (actionError) {
      setError(actionError.message || "创建待确认动作失败，请稍后重试。");
    }
  };

  const handleApproveAction = async action => {
    setReviewingActionId(action.id);
    try {
      const resp = await approveAgentReviewAction(action.id);
      setReviewActions(prev => prev.filter(item => item.id !== resp.action.id));
      toast("已通过待确认动作");
    } catch (actionError) {
      setError(actionError.message || "操作失败，请稍后重试。");
    } finally {
      setReviewingActionId(null);
    }
  };

  const handleRejectAction = async (action, reason) => {
    setReviewingActionId(action.id);
    try {
      const resp = await rejectAgentReviewAction(action.id, { reason });
      setReviewActions(prev => prev.filter(item => item.id !== resp.action.id));
      toast("已拒绝待确认动作");
    } catch (actionError) {
      setError(actionError.message || "操作失败，请稍后重试。");
    } finally {
      setReviewingActionId(null);
    }
  };

  const answer = currentRun?.final_answer || null;
  const evidence = EVIDENCE_STYLES[answer?.evidence_quality || "strong"] || EVIDENCE_STYLES.strong;

  return (
    <div style={{ padding: isMobile ? 16 : 24, display: "flex", flexDirection: "column", gap: 16 }}>
      <SectionCard title="目标输入">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
          <div style={{
            width: 34,
            height: 34,
            borderRadius: 10,
            background: "linear-gradient(135deg, rgba(255,36,66,0.16), rgba(255,159,67,0.14))",
            border: "1px solid rgba(255,36,66,0.18)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#FF2442",
          }}>
            <Sparkles size={16} />
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#fff" }}>运营助手</div>
            <div style={{ fontSize: 12, color: "#777", marginTop: 3 }}>
              目标 → 规划 → 调工具 → 产出 → 人工确认。
            </div>
          </div>
          <button
            type="button"
            onClick={scrollToReviewQueue}
            disabled={reviewActions.length === 0}
            style={{
            marginLeft: "auto",
            fontSize: 11,
            color: reviewActions.length ? "#FF2442" : "#777",
            background: reviewActions.length ? "rgba(255,36,66,0.12)" : "rgba(255,255,255,0.04)",
            border: `1px solid ${reviewActions.length ? "rgba(255,36,66,0.28)" : designTokens.color.cardBorder}`,
            borderRadius: 999,
            padding: "4px 9px",
            animation: reviewActions.length ? "glowPulse 1.6s ease-in-out infinite" : "none",
            cursor: reviewActions.length ? "pointer" : "default",
            opacity: reviewActions.length ? 1 : 0.75,
          }}
          >
            待确认 {reviewActions.length}{reviewActions.length ? " · 去审批" : ""}
          </button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {WORKFLOW_TEMPLATES.map(item => (
              <button
                key={item.text}
                type="button"
                onClick={() => {
                  setPrompt(item.text);
                  setTargetActionType(item.actionType);
                }}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "7px 10px",
                  borderRadius: 999,
                  border: `1px solid ${targetActionType === item.actionType && prompt === item.text ? "rgba(255,36,66,0.36)" : designTokens.color.cardBorder}`,
                  background: targetActionType === item.actionType && prompt === item.text ? "rgba(255,36,66,0.1)" : "rgba(255,255,255,0.025)",
                  color: targetActionType === item.actionType && prompt === item.text ? "#FF2442" : designTokens.color.textMuted,
                  cursor: "pointer",
                  fontSize: 11,
                }}
              >
                {item.icon} {item.text}
              </button>
            ))}
          </div>
          <textarea
            value={prompt}
            onChange={event => setPrompt(event.target.value)}
            placeholder="例如：找最近适合英国留学账号的春天标题素材"
            style={{
              ...inputStyle,
              minHeight: isMobile ? 120 : 110,
              resize: "vertical",
              lineHeight: 1.7,
            }}
          />
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ fontSize: 11, color: "#666", lineHeight: 1.6 }}>
              适合找素材、拆方向、整理账号历史经验。
            </div>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={creating || !prompt.trim()}
              style={{
                ...createPrimaryButtonStyle({ disabled: creating || !prompt.trim() }),
                padding: "10px 14px",
                borderRadius: 10,
                fontSize: 13,
                fontWeight: 700,
              }}
            >
              {creating ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
              {creating ? "启动中…" : "开始研究"}
            </button>
          </div>
        </div>
      </SectionCard>

      {error && (
        <div style={{
          background: "rgba(255,36,66,0.08)",
          border: "1px solid rgba(255,36,66,0.18)",
          borderRadius: 10,
          padding: 12,
          color: "#FF5C7A",
          fontSize: 12,
          lineHeight: 1.65,
        }}>
          {error}
        </div>
      )}

      <div style={{
        display: "grid",
        gridTemplateColumns: isMobile ? "1fr" : "minmax(240px, 0.7fr) minmax(0, 1.15fr) minmax(320px, 0.9fr)",
        gap: 16,
        alignItems: "start",
      }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SectionCard title="上下文">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {["英国账号", "下周", "素材库", "团队历史", "人工确认"].map(chip => (
                <span key={chip} style={{
                  fontSize: 11,
                  color: chip === "人工确认" ? "#FF2442" : designTokens.color.textMuted,
                  background: chip === "人工确认" ? "rgba(255,36,66,0.1)" : "rgba(255,255,255,0.035)",
                  border: `1px solid ${chip === "人工确认" ? "rgba(255,36,66,0.25)" : designTokens.color.cardBorder}`,
                  borderRadius: 999,
                  padding: "5px 9px",
                }}>{chip}</span>
              ))}
            </div>
            <div style={{ fontSize: 12, color: designTokens.color.textMuted, lineHeight: 1.65, marginTop: 12 }}>
              所有写库、排期、存草稿、入库动作都会先进入待确认队列。
            </div>
          </SectionCard>

          <SectionCard title="待办">
            {reviewActions.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ fontSize: 13, color: "#FF2442", lineHeight: 1.7 }}>
                  有 {reviewActions.length} 个动作等待处理，优先审核高证据分项目。
                </div>
                <button
                  type="button"
                  onClick={scrollToReviewQueue}
                  style={{
                    ...createPrimaryButtonStyle(),
                    alignSelf: "flex-start",
                    padding: "8px 11px",
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  <CheckCircle2 size={13} /> 去审批
                </button>
              </div>
            ) : (
              <div style={{ fontSize: 13, color: "#666", lineHeight: 1.7 }}>
                暂无主动提醒。对标监控和周复盘接入后会出现在这里。
              </div>
            )}
          </SectionCard>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SectionCard title="当前任务">
            {!currentRun && (
              <div style={{ fontSize: 13, color: "#666", lineHeight: 1.7 }}>
                还没有运行中的任务。开始研究后，这里会展示状态、证据质量和最终回答。
              </div>
            )}

            {currentRun && (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Bot size={16} color="#FF2442" />
                    <span style={{ fontSize: 14, color: "#fff", fontWeight: 700 }}>
                      任务 {currentRun.id?.slice(0, 8)}
                    </span>
                  </div>
                  <span style={{
                    fontSize: 10,
                    color: currentRun.status === "failed" ? "#FF5C7A" : currentRun.status === "completed" ? "#26DE81" : "#FF9F43",
                    background: currentRun.status === "failed" ? "rgba(255,36,66,0.08)" : currentRun.status === "completed" ? "rgba(38,222,129,0.08)" : "rgba(255,159,67,0.08)",
                    border: `1px solid ${currentRun.status === "failed" ? "rgba(255,36,66,0.18)" : currentRun.status === "completed" ? "rgba(38,222,129,0.18)" : "rgba(255,159,67,0.18)"}`,
                    borderRadius: 999,
                    padding: "4px 9px",
                  }}>
                    {currentRun.status === "completed" ? "已完成" : currentRun.status === "failed" ? "失败" : "运行中"}
                  </span>
                </div>

                <div style={{
                  background: evidence.background,
                  border: `1px solid ${evidence.border}`,
                  borderRadius: 10,
                  padding: 12,
                  color: evidence.color,
                }}>
                  <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>{evidence.label}</div>
                  <div style={{ fontSize: 11, color: "#777", lineHeight: 1.6 }}>
                    {answer?.trace_id ? `追踪号 ${answer.trace_id.slice(0, 8)}` : "回答完成后会显示证据质量和追踪号。"}
                  </div>
                </div>

                {answer?.conclusion && (
                  <div style={{ fontSize: 14, color: "#e8e8e8", lineHeight: 1.8 }}>
                    {answer.conclusion}
                  </div>
                )}

                {answer?.recommendations?.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {answer.recommendations.map((item, index) => (
                      <div key={index} style={{
                        ...createGlassCardStyle({ padding: 12, radius: 10 }),
                        borderRadius: 10,
                        fontSize: 13,
                        color: "#ddd",
                        lineHeight: 1.65,
                      }}>
                        {item.text}
                      </div>
                    ))}
                  </div>
                )}

                {answer && currentRun.status === "completed" && (
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {[
                      ["save_note", "存为笔记", <ClipboardList size={13} />],
                      ["save_draft", "存草稿", <FileText size={13} />],
                      ["add_calendar_item", "进日历", <CalendarPlus size={13} />],
                      ["mark_template", "存模板", <Layers size={13} />],
                    ].map(([type, label, icon]) => (
                      <button
                        key={type}
                        type="button"
                        onClick={() => handleCreateReviewAction(type)}
                        style={{
                          ...createPrimaryButtonStyle(),
                          padding: "8px 10px",
                          fontSize: 12,
                          fontWeight: 700,
                        }}
                      >
                        {icon} {label}
                      </button>
                    ))}
                  </div>
                )}

                {currentRun.error_message && (
                  <div style={{ fontSize: 12, color: "#FF5C7A", lineHeight: 1.6 }}>
                    {currentRun.error_message}
                  </div>
                )}
              </div>
            )}
          </SectionCard>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SectionCard title="待确认队列" sectionRef={reviewQueueRef}>
            <button
              type="button"
              onClick={loadReviewActions}
              style={{
                marginBottom: 10,
                padding: "7px 10px",
                borderRadius: 8,
                border: `1px solid ${designTokens.color.cardBorder}`,
                background: "rgba(255,255,255,0.03)",
                color: designTokens.color.textMuted,
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              刷新队列
            </button>
            <ReviewQueue
              actions={reviewActions}
              reviewingId={reviewingActionId}
              onApprove={handleApproveAction}
              onReject={handleRejectAction}
            />
          </SectionCard>

          <SectionCard title="任务进度">
            {steps.length === 0 ? (
              <div style={{ fontSize: 13, color: "#666", lineHeight: 1.7 }}>
                开始研究后，这里会依次显示理解任务、内部检索和整理回答。
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {steps.map(step => (
                  <TimelineStep key={step.id} step={step} />
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title="运行记录">
            {events.length === 0 ? (
              <div style={{ fontSize: 12, color: "#666", lineHeight: 1.7 }}>
                任务启动后，这里会记录每一步的状态变化。
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {events.map((item, index) => (
                  <div key={`${item.event}-${index}`} style={{
                    ...createGlassCardStyle({ padding: "9px 10px", radius: 8 }),
                    fontSize: 12,
                    color: "#888",
                    borderRadius: 8,
                  }}>
                    <span style={{ color: "#FF9F43" }}>{item.event}</span>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </div>
      </div>
    </div>
  );
}
