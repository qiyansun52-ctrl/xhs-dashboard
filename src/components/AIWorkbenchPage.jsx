import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Clock3,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Send,
  Sparkles,
} from "lucide-react";
import {
  buildCrawlerBrief,
  clarifyConversation,
  createConversation,
  getConversation,
  listConversations,
} from "../aiWorkbenchApi.js";
import { buildBriefRequest, getConversationTitle, summarizeJobStatus } from "../aiWorkbench.js";
import {
  approveDiscoveryCandidate,
  createDiscoveryJob,
  getDiscoveryJob,
  ignoreDiscoveryCandidate,
  rejectDiscoveryCandidate,
} from "../aiApi.js";
import {
  Card,
  EmptyState,
  createGlassCardStyle,
  createPrimaryButtonStyle,
  designTokens,
  inputStyle,
  useIsMobile,
  useToast,
} from "./shared.jsx";
import DiscoveryCandidateCard from "./DiscoveryCandidateCard.jsx";

const STATUS_TONES = {
  muted: { color: designTokens.color.textMuted, background: "rgba(255,255,255,0.05)", border: designTokens.color.cardBorder },
  info: { color: designTokens.color.info, background: "rgba(84,160,255,0.08)", border: "rgba(84,160,255,0.22)" },
  success: { color: designTokens.color.success, background: "rgba(38,222,129,0.08)", border: "rgba(38,222,129,0.22)" },
  warning: { color: designTokens.color.warning, background: "rgba(255,159,67,0.08)", border: "rgba(255,159,67,0.22)" },
  danger: { color: designTokens.color.danger, background: "rgba(255,36,66,0.08)", border: "rgba(255,36,66,0.22)" },
};

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function normalizeBrief(brief) {
  return isPlainObject(brief) && Object.keys(brief).length > 0 ? brief : null;
}

function getPayloadObject(message) {
  return isPlainObject(message?.payload) ? message.payload : {};
}

function getLatestCrawlerBrief(context, messages) {
  const contextBrief = normalizeBrief(context?.latest_crawler_brief);
  if (contextBrief) return contextBrief;

  for (const message of [...messages].reverse()) {
    const brief = normalizeBrief(getPayloadObject(message).crawler_brief);
    if (brief) return brief;
  }
  return null;
}

function getLatestClarification(messages) {
  const latestAction = [...messages]
    .reverse()
    .find(message => ["clarification", "crawler_brief"].includes(message.message_type));
  const payload = getPayloadObject(latestAction);
  return latestAction?.message_type === "clarification" && payload.needs_clarification ? payload : null;
}

function formatDate(value) {
  if (!value) return "";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return "";
  }
}

function getMessageText(message) {
  const payload = getPayloadObject(message);
  if (message.content) return message.content;
  if (payload.question) return payload.question;
  if (payload.crawler_brief?.goal) return payload.crawler_brief.goal;
  return message.message_type || "消息";
}

function FieldTags({ label, values, tone = "muted" }) {
  const items = Array.isArray(values) ? values.filter(Boolean) : values ? [values] : [];
  if (!items.length) return null;
  const toneStyle = STATUS_TONES[tone] || STATUS_TONES.muted;

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 11, color: designTokens.color.textFaint, marginBottom: 6 }}>{label}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map(item => (
          <span
            key={`${label}-${item}`}
            style={{
              border: `1px solid ${toneStyle.border}`,
              background: toneStyle.background,
              color: toneStyle.color,
              borderRadius: 999,
              padding: "4px 8px",
              fontSize: 11,
              lineHeight: 1.2,
            }}
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const summary = summarizeJobStatus(status);
  const tone = STATUS_TONES[summary.tone] || STATUS_TONES.muted;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        border: `1px solid ${tone.border}`,
        background: tone.background,
        color: tone.color,
        borderRadius: 999,
        padding: "3px 8px",
        fontSize: 11,
        lineHeight: 1.2,
        whiteSpace: "nowrap",
      }}
    >
      {summary.label}
    </span>
  );
}

function RailPanel({ title, icon, action, children }) {
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ color: designTokens.color.brand, display: "flex", flexShrink: 0 }}>{icon}</span>
          <div style={{ fontSize: 13, fontWeight: 800, color: designTokens.color.textStrong, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {title}
          </div>
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}

function ConversationItem({ conversation, active, disabled, onOpen }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onOpen}
      style={{
        width: "100%",
        textAlign: "left",
        border: `1px solid ${active ? "rgba(255,36,66,0.38)" : designTokens.color.cardBorder}`,
        background: active ? "rgba(255,36,66,0.1)" : "rgba(255,255,255,0.025)",
        color: active ? designTokens.color.textPrimary : designTokens.color.textMuted,
        borderRadius: 8,
        padding: 10,
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: 12,
        display: "block",
      }}
    >
      <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: active ? 700 : 500 }}>
        {conversation.title || "新对话"}
      </div>
      {conversation.updated_at && (
        <div style={{ marginTop: 5, fontSize: 10, color: designTokens.color.textFaint }}>
          {formatDate(conversation.updated_at)}
        </div>
      )}
    </button>
  );
}

function ChatMessage({ message }) {
  const isUser = message.role === "user";
  const payload = getPayloadObject(message);
  const brief = normalizeBrief(payload.crawler_brief);

  return (
    <div
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        gap: 8,
      }}
    >
      {!isUser && (
        <div style={{
          width: 26,
          height: 26,
          borderRadius: 8,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: designTokens.color.brand,
          background: "rgba(255,36,66,0.08)",
          border: "1px solid rgba(255,36,66,0.16)",
          flexShrink: 0,
        }}>
          <Bot size={14} />
        </div>
      )}
      <div
        style={{
          maxWidth: "78%",
          background: isUser ? "rgba(255,36,66,0.14)" : "rgba(255,255,255,0.04)",
          border: `1px solid ${isUser ? "rgba(255,36,66,0.22)" : designTokens.color.cardBorder}`,
          borderRadius: 12,
          padding: 12,
          color: designTokens.color.textPrimary,
          fontSize: 13,
          lineHeight: 1.7,
          whiteSpace: "pre-wrap",
          overflowWrap: "anywhere",
        }}
      >
        {getMessageText(message)}
        {brief && (
          <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${designTokens.color.cardBorder}` }}>
            <FieldTags label="搜索词" values={brief.search_queries} tone="info" />
          </div>
        )}
      </div>
    </div>
  );
}

function ClarificationCard({ clarification, selections, freeText, loading, onToggleSelection, onFreeTextChange, onGenerateBrief }) {
  if (!clarification?.needs_clarification) return null;
  const groups = Array.isArray(clarification.option_groups) ? clarification.option_groups : [];

  return (
    <section style={{
      ...createGlassCardStyle({ padding: 14, radius: 12 }),
      borderColor: "rgba(84,160,255,0.24)",
      background: "linear-gradient(180deg, rgba(84,160,255,0.08), rgba(255,255,255,0.03))",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 10 }}>
        <div style={{
          width: 28,
          height: 28,
          borderRadius: 8,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: designTokens.color.info,
          background: "rgba(84,160,255,0.09)",
          border: "1px solid rgba(84,160,255,0.18)",
          flexShrink: 0,
        }}>
          <Search size={15} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: designTokens.color.textStrong, fontWeight: 800, fontSize: 14, lineHeight: 1.5 }}>
            {clarification.question || "先收窄一下搜索范围"}
          </div>
          {clarification.detected_country && (
            <div style={{ color: designTokens.color.textMuted, fontSize: 11, marginTop: 4 }}>
              识别国家：{clarification.detected_country}
            </div>
          )}
        </div>
      </div>

      {groups.map(group => {
        const maxSelect = Number(group.max_select) || 1;
        const selectedIds = selections[group.id] || [];
        return (
          <div key={group.id} style={{ marginTop: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
              <div style={{ fontSize: 11, color: designTokens.color.textMuted }}>{group.label}</div>
              <div style={{ fontSize: 10, color: designTokens.color.textFaint }}>最多 {maxSelect} 项</div>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {(group.options || []).map(option => {
                const selected = selectedIds.includes(option.id);
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => onToggleSelection(group.id, option.id, maxSelect)}
                    style={{
                      border: `1px solid ${selected ? "rgba(255,36,66,0.45)" : designTokens.color.cardBorder}`,
                      background: selected ? "rgba(255,36,66,0.13)" : "rgba(255,255,255,0.035)",
                      color: selected ? designTokens.color.brand : designTokens.color.textMuted,
                      borderRadius: 999,
                      padding: "7px 10px",
                      cursor: "pointer",
                      fontSize: 12,
                      lineHeight: 1.2,
                    }}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}

      <textarea
        value={freeText}
        onChange={event => onFreeTextChange(event.target.value)}
        placeholder={clarification.free_text_prompt || "补充不想要的内容、目标账号或风格偏好。"}
        aria-label={clarification.free_text_prompt || "补充搜索偏好"}
        style={{ ...inputStyle, marginTop: 14, minHeight: 76, resize: "vertical", lineHeight: 1.6 }}
      />
      <button
        type="button"
        onClick={onGenerateBrief}
        disabled={loading}
        style={{
          ...createPrimaryButtonStyle({ disabled: loading }),
          marginTop: 10,
          padding: "9px 12px",
          fontSize: 12,
          fontWeight: 800,
        }}
      >
        {loading ? <Loader2 size={14} className="spin" /> : <CheckCircle2 size={14} />}
        生成搜索 brief
      </button>
    </section>
  );
}

function BriefPanel({ crawlerBrief, loading, contextUpdatedAt, onStartDiscovery }) {
  if (!crawlerBrief) {
    return (
      <EmptyState
        icon={<Sparkles size={18} />}
        title="暂无 brief"
        description="输入泛需求后，工作台会先通过反问生成更精准的抓取 brief。"
      />
    );
  }

  return (
    <div style={{ fontSize: 12, color: designTokens.color.textMuted, lineHeight: 1.65 }}>
      <div style={{ color: designTokens.color.textStrong, fontWeight: 800, fontSize: 13, lineHeight: 1.5 }}>
        {crawlerBrief.goal || "已生成精准发现 brief"}
      </div>
      {crawlerBrief.country && (
        <div style={{ marginTop: 8 }}>国家：<span style={{ color: designTokens.color.textPrimary }}>{crawlerBrief.country}</span></div>
      )}
      <FieldTags label="搜索词" values={crawlerBrief.search_queries} tone="info" />
      <FieldTags label="内容场景" values={crawlerBrief.content_scenes} />
      <FieldTags label="表达类型" values={crawlerBrief.expression_types} />
      <FieldTags label="质量目标" values={crawlerBrief.quality_targets} tone="success" />
      <FieldTags label="排除项" values={crawlerBrief.exclusions} tone="warning" />
      {crawlerBrief.candidate_scoring_hint && (
        <div style={{ marginTop: 10, color: designTokens.color.textMuted }}>
          评分提示：{crawlerBrief.candidate_scoring_hint}
        </div>
      )}
      {contextUpdatedAt && (
        <div style={{ marginTop: 10, fontSize: 10, color: designTokens.color.textFaint }}>
          上下文更新：{formatDate(contextUpdatedAt)}
        </div>
      )}
      <button
        type="button"
        onClick={onStartDiscovery}
        disabled={loading}
        style={{
          ...createPrimaryButtonStyle({ disabled: loading }),
          width: "100%",
          marginTop: 12,
          padding: "10px 12px",
          fontSize: 12,
          fontWeight: 800,
        }}
      >
        {loading ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
        确认并启动精准发现
      </button>
    </div>
  );
}

function DiscoveryPanel({ discoveryJob, candidates, loading, refreshing, onRefresh }) {
  const summary = summarizeJobStatus(discoveryJob?.status);
  const canRefresh = Boolean(discoveryJob?.id) && !refreshing;

  if (!discoveryJob) {
    return (
      <EmptyState
        icon={<Clock3 size={18} />}
        title="未启动"
        description="确认 brief 后开始抓取候选素材，结果会在这里审核。"
      />
    );
  }

  return (
    <div style={{ fontSize: 12, color: designTokens.color.textMuted, lineHeight: 1.65 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <StatusBadge status={discoveryJob.status} />
        <button
          type="button"
          onClick={onRefresh}
          disabled={!canRefresh}
          style={{
            ...createGlassCardStyle({ padding: "6px 8px", radius: 8 }),
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: canRefresh ? designTokens.color.textMuted : designTokens.color.textFaint,
            cursor: canRefresh ? "pointer" : "not-allowed",
            fontSize: 11,
          }}
        >
          {refreshing ? <Loader2 size={12} className="spin" /> : <RefreshCw size={12} />}
          刷新
        </button>
      </div>
      <div>任务 ID：<span style={{ color: designTokens.color.textFaint }}>{String(discoveryJob.id).slice(0, 8)}</span></div>
      {Array.isArray(discoveryJob.search_queries) && discoveryJob.search_queries.length > 0 && (
        <FieldTags label="执行搜索词" values={discoveryJob.search_queries} tone="info" />
      )}
      <div style={{ marginTop: 10 }}>
        候选数：<span style={{ color: designTokens.color.textPrimary }}>{candidates.length}</span>
      </div>
      {loading && (
        <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8, color: designTokens.color.textMuted }}>
          <Loader2 size={13} className="spin" />
          正在处理请求
        </div>
      )}
      {summary.canReviewCandidates && candidates.length === 0 && (
        <div style={{ marginTop: 10, color: designTokens.color.textFaint }}>
          当前没有可审核候选，刷新后如果仍为空，说明这轮抓取没有命中合格素材。
        </div>
      )}
    </div>
  );
}

export default function AIWorkbenchPage() {
  const isMobile = useIsMobile();
  const toast = useToast();
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  const [context, setContext] = useState({});
  const [prompt, setPrompt] = useState("");
  const [clarification, setClarification] = useState(null);
  const [selections, setSelections] = useState({});
  const [freeText, setFreeText] = useState("");
  const [crawlerBrief, setCrawlerBrief] = useState(null);
  const [discoveryJob, setDiscoveryJob] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [reviewingCandidateId, setReviewingCandidateId] = useState(null);
  const [error, setError] = useState("");
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [openingConversationId, setOpeningConversationId] = useState(null);
  const [refreshingDiscovery, setRefreshingDiscovery] = useState(false);
  const discoveryRequestSeqRef = useRef(0);
  const activeDiscoveryJobIdRef = useRef(null);

  const activeTitle = useMemo(
    () => getConversationTitle(activeConversation, messages),
    [activeConversation, messages],
  );
  const latestUserRequest = useMemo(
    () => [...messages].reverse().find(message => message.role === "user" && message.content?.trim())?.content || "",
    [messages],
  );
  const isDiscoveryRunning = ["pending", "running"].includes(discoveryJob?.status);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      setLoadingHistory(true);
      try {
        const payload = await listConversations();
        if (cancelled) return;
        const rows = payload.conversations || [];
        setConversations(rows);
        if (rows[0]?.id) {
          const snapshot = await getConversation(rows[0].id);
          if (!cancelled) applyConversationSnapshot(snapshot);
        }
      } catch (err) {
        if (!cancelled) setError(err.message || "读取历史对话失败");
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  const refreshDiscovery = useCallback(async ({
    quiet = false,
    jobId = discoveryJob?.id,
    expectedSeq = discoveryRequestSeqRef.current,
  } = {}) => {
    if (!jobId) return null;
    if (!quiet) setRefreshingDiscovery(true);
    try {
      const payload = await getDiscoveryJob(jobId);
      if (discoveryRequestSeqRef.current !== expectedSeq || activeDiscoveryJobIdRef.current !== jobId) {
        return null;
      }
      setDiscoveryJob(payload.job);
      setCandidates(payload.candidates || []);
      return payload.job;
    } catch (err) {
      if (!quiet && discoveryRequestSeqRef.current === expectedSeq && activeDiscoveryJobIdRef.current === jobId) {
        setError(err.message || "刷新外部发现任务失败");
      }
      return null;
    } finally {
      if (!quiet) setRefreshingDiscovery(false);
    }
  }, [discoveryJob?.id]);

  useEffect(() => {
    if (!discoveryJob?.id || !["pending", "running"].includes(discoveryJob.status)) return undefined;
    const jobId = discoveryJob.id;
    const expectedSeq = discoveryRequestSeqRef.current;
    const timer = window.setInterval(() => {
      refreshDiscovery({ quiet: true, jobId, expectedSeq }).catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [discoveryJob?.id, discoveryJob?.status, refreshDiscovery]);

  function resetDiscoveryState() {
    discoveryRequestSeqRef.current += 1;
    activeDiscoveryJobIdRef.current = null;
    setDiscoveryJob(null);
    setCandidates([]);
    setReviewingCandidateId(null);
    setRefreshingDiscovery(false);
  }

  function restoreDiscoveryJob(jobId) {
    if (!jobId) return;
    const requestSeq = discoveryRequestSeqRef.current + 1;
    discoveryRequestSeqRef.current = requestSeq;
    activeDiscoveryJobIdRef.current = jobId;
    setDiscoveryJob({ id: jobId, status: "running" });
    setCandidates([]);
    setReviewingCandidateId(null);
    refreshDiscovery({ jobId, expectedSeq: requestSeq }).catch(() => {});
  }

  function applyConversationSnapshot(snapshot) {
    const nextMessages = snapshot.messages || [];
    const nextContext = snapshot.context || {};
    setActiveConversation(snapshot.conversation);
    setMessages(nextMessages);
    setContext(nextContext);
    setCrawlerBrief(getLatestCrawlerBrief(nextContext, nextMessages));
    setClarification(getLatestClarification(nextMessages));
    setSelections({});
    setFreeText("");
    setPrompt("");
    resetDiscoveryState();
    restoreDiscoveryJob(nextContext.active_discovery_job_id);
  }

  async function loadConversations() {
    const payload = await listConversations();
    const rows = payload.conversations || [];
    setConversations(rows);
    return rows;
  }

  async function openConversation(conversationId) {
    if (!conversationId || openingConversationId) return;
    setOpeningConversationId(conversationId);
    setError("");
    try {
      const snapshot = await getConversation(conversationId);
      applyConversationSnapshot(snapshot);
    } catch (err) {
      setError(err.message || "读取对话失败");
    } finally {
      setOpeningConversationId(null);
    }
  }

  async function startNewConversation() {
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      const created = await createConversation({ title: "新对话" });
      setConversations(prev => [created.conversation, ...prev.filter(item => item.id !== created.conversation.id)]);
      setActiveConversation(created.conversation);
      setMessages([]);
      setContext({});
      setPrompt("");
      setClarification(null);
      setSelections({});
      setFreeText("");
      setCrawlerBrief(null);
      resetDiscoveryState();
    } catch (err) {
      setError(err.message || "创建新对话失败");
    } finally {
      setLoading(false);
    }
  }

  async function ensureConversation() {
    if (activeConversation?.id) return activeConversation;
    const created = await createConversation({ title: "新对话" });
    setConversations(prev => [created.conversation, ...prev.filter(item => item.id !== created.conversation.id)]);
    setActiveConversation(created.conversation);
    setMessages([]);
    setContext({});
    return created.conversation;
  }

  async function submitPrompt() {
    const trimmedPrompt = prompt.trim();
    if (!trimmedPrompt || loading) return;
    setLoading(true);
    setError("");
    setClarification(null);
    setCrawlerBrief(null);
    resetDiscoveryState();
    try {
      const conversation = await ensureConversation();
      const result = await clarifyConversation(conversation.id, trimmedPrompt);
      const snapshot = await getConversation(conversation.id);
      applyConversationSnapshot(snapshot);

      if (result.clarification?.needs_clarification) {
        setClarification(result.clarification);
        setCrawlerBrief(null);
      } else {
        setClarification(null);
        setCrawlerBrief(normalizeBrief(result.clarification?.crawler_brief));
      }

      setPrompt("");
      setSelections({});
      setFreeText("");
      await loadConversations();
    } catch (err) {
      setError(err.message || "提交失败");
    } finally {
      setLoading(false);
    }
  }

  function toggleSelection(groupId, optionId, maxSelect) {
    setSelections(prev => {
      const current = prev[groupId] || [];
      const exists = current.includes(optionId);
      const next = exists
        ? current.filter(id => id !== optionId)
        : [...current, optionId].slice(-Math.max(Number(maxSelect) || 1, 1));
      return { ...prev, [groupId]: next };
    });
  }

  async function generateBrief() {
    if (!activeConversation?.id || !clarification || loading) return;
    setLoading(true);
    setError("");
    resetDiscoveryState();
    try {
      const result = await buildCrawlerBrief(
        activeConversation.id,
        buildBriefRequest({
          originalRequest: latestUserRequest || activeTitle,
          selections,
          freeText,
        }),
      );
      const brief = normalizeBrief(result.brief?.crawler_brief);
      setCrawlerBrief(brief);
      setClarification(null);
      const snapshot = await getConversation(activeConversation.id);
      const nextMessages = snapshot.messages || [];
      const nextContext = snapshot.context || {};
      setActiveConversation(snapshot.conversation);
      setMessages(nextMessages);
      setContext(nextContext);
      setSelections({});
      setFreeText("");
      await loadConversations();
    } catch (err) {
      setError(err.message || "生成 brief 失败");
    } finally {
      setLoading(false);
    }
  }

  async function startDiscovery() {
    if (!crawlerBrief || loading || isDiscoveryRunning) return;
    const requestSeq = discoveryRequestSeqRef.current + 1;
    discoveryRequestSeqRef.current = requestSeq;
    activeDiscoveryJobIdRef.current = null;
    setLoading(true);
    setError("");
    setRefreshingDiscovery(false);
    try {
      const jobResp = await createDiscoveryJob({
        user_question: crawlerBrief.goal || latestUserRequest || activeTitle,
        task_type: "material",
        trigger_reason: "user_requested",
        internal_answer_payload: { source: "ai_workbench", crawler_brief: crawlerBrief },
        search_queries: Array.isArray(crawlerBrief.search_queries) ? crawlerBrief.search_queries : undefined,
        crawler_brief: crawlerBrief,
        conversation_id: activeConversation?.id || null,
      });
      if (discoveryRequestSeqRef.current !== requestSeq) return;
      activeDiscoveryJobIdRef.current = jobResp.job.id;
      setDiscoveryJob(jobResp.job);
      setCandidates([]);
      toast("已启动精准发现");
    } catch (err) {
      if (discoveryRequestSeqRef.current === requestSeq) {
        setError(err.message || "启动外部发现失败");
      }
    } finally {
      setLoading(false);
    }
  }

  async function reviewCandidate(candidate, action) {
    if ((candidate.review_status || "pending") !== "pending" || reviewingCandidateId) return;
    setReviewingCandidateId(candidate.id);
    setError("");
    try {
      let resp;
      if (action === "approve") {
        resp = await approveDiscoveryCandidate(candidate.id);
      } else if (action === "ignore") {
        resp = await ignoreDiscoveryCandidate(candidate.id);
      } else {
        resp = await rejectDiscoveryCandidate(candidate.id, "不相关");
      }
      setCandidates(prev => prev.map(item => item.id === candidate.id ? { ...item, ...resp.candidate } : item));
      toast(action === "approve" ? "候选素材已入库" : "候选状态已更新");
    } catch (err) {
      setError(err.message || "候选操作失败");
    } finally {
      setReviewingCandidateId(null);
    }
  }

  return (
    <div
      style={{
        padding: isMobile ? 12 : 18,
        display: "grid",
        gridTemplateColumns: isMobile ? "minmax(0, 1fr)" : "240px minmax(420px, 1fr) 360px",
        gap: 14,
        alignItems: "stretch",
      }}
    >
      <aside
        style={{
          ...createGlassCardStyle({ padding: 14, radius: 12 }),
          minHeight: isMobile ? "auto" : "calc(100vh - 36px)",
          maxHeight: isMobile ? "none" : "calc(100vh - 36px)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <button
          type="button"
          onClick={startNewConversation}
          disabled={loading}
          style={{
            ...createPrimaryButtonStyle({ disabled: loading }),
            width: "100%",
            padding: "10px 12px",
            marginBottom: 12,
            fontSize: 13,
            fontWeight: 800,
          }}
        >
          {loading && !activeConversation ? <Loader2 size={14} className="spin" /> : <Plus size={14} />}
          新对话
        </button>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
          <div style={{ fontSize: 11, color: designTokens.color.textFaint, fontWeight: 700 }}>历史对话</div>
          {loadingHistory && <Loader2 size={12} className="spin" color={designTokens.color.textFaint} />}
        </div>
        <div style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          overflowY: "auto",
          maxHeight: isMobile ? 220 : "none",
          paddingRight: 2,
        }}>
          {!loadingHistory && conversations.length === 0 && (
            <div style={{ fontSize: 12, color: designTokens.color.textFaint, lineHeight: 1.6, padding: "8px 2px" }}>
              暂无历史。直接在中间输入需求即可创建对话。
            </div>
          )}
          {conversations.map(conversation => (
            <ConversationItem
              key={conversation.id}
              conversation={conversation}
              active={activeConversation?.id === conversation.id}
              disabled={openingConversationId === conversation.id}
              onOpen={() => openConversation(conversation.id)}
            />
          ))}
        </div>
      </aside>

      <main
        style={{
          ...createGlassCardStyle({ padding: 0, radius: 12 }),
          minHeight: isMobile ? 560 : "calc(100vh - 36px)",
          maxHeight: isMobile ? "none" : "calc(100vh - 36px)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{
          padding: "14px 16px",
          borderBottom: `1px solid ${designTokens.color.cardBorder}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{
              fontSize: 17,
              fontWeight: 900,
              color: designTokens.color.textStrong,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}>
              {activeTitle}
            </div>
            <div style={{ marginTop: 3, fontSize: 11, color: designTokens.color.textFaint }}>
              对话式收窄需求 · 生成 brief · 启动候选素材发现
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, color: designTokens.color.brand, flexShrink: 0 }}>
            <Sparkles size={16} />
          </div>
        </div>

        {error && (
          <div style={{
            margin: "12px 16px 0",
            background: "rgba(255,36,66,0.08)",
            border: "1px solid rgba(255,36,66,0.2)",
            color: designTokens.color.danger,
            borderRadius: 10,
            padding: 10,
            fontSize: 12,
            display: "flex",
            gap: 8,
            alignItems: "flex-start",
          }}>
            <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
            <span>{error}</span>
          </div>
        )}

        <div style={{
          flex: 1,
          overflowY: "auto",
          padding: 16,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}>
          {messages.length === 0 && !clarification && (
            <EmptyState
              icon={<Bot size={18} />}
              title="开始一个 AI 工作台对话"
              description="例如：帮我找英国留学生活方向的真实经验素材，排除机构广告。"
            />
          )}
          {messages.map(message => (
            <ChatMessage key={message.id} message={message} />
          ))}
          <ClarificationCard
            clarification={clarification}
            selections={selections}
            freeText={freeText}
            loading={loading}
            onToggleSelection={toggleSelection}
            onFreeTextChange={setFreeText}
            onGenerateBrief={generateBrief}
          />
        </div>

        <div style={{
          padding: 14,
          borderTop: `1px solid ${designTokens.color.cardBorder}`,
          background: "rgba(0,0,0,0.12)",
        }}>
          <div style={{ display: "flex", gap: 10, alignItems: "stretch" }}>
            <textarea
              value={prompt}
              onChange={event => setPrompt(event.target.value)}
              onKeyDown={event => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submitPrompt();
                }
              }}
              aria-label="输入运营目标或素材需求"
              placeholder="输入运营目标或素材需求，按 Enter 发送，Shift+Enter 换行"
              style={{ ...inputStyle, minHeight: 56, resize: "vertical", lineHeight: 1.6 }}
            />
            <button
              type="button"
              onClick={submitPrompt}
              disabled={loading || !prompt.trim()}
              style={{
                ...createPrimaryButtonStyle({ disabled: loading || !prompt.trim() }),
                alignSelf: "stretch",
                width: 48,
                flexShrink: 0,
              }}
              aria-label="发送"
            >
              {loading ? <Loader2 size={16} className="spin" /> : <Send size={16} />}
            </button>
          </div>
        </div>
      </main>

      <aside style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        minWidth: 0,
      }}>
        <RailPanel title="爬虫 Brief" icon={<Sparkles size={15} />}>
          <BriefPanel
            crawlerBrief={crawlerBrief}
            loading={loading || isDiscoveryRunning}
            contextUpdatedAt={context?.updated_at}
            onStartDiscovery={startDiscovery}
          />
        </RailPanel>

        <RailPanel
          title="外部发现"
          icon={<Search size={15} />}
          action={discoveryJob?.status ? <StatusBadge status={discoveryJob.status} /> : null}
        >
          <DiscoveryPanel
            discoveryJob={discoveryJob}
            candidates={candidates}
            loading={loading}
            refreshing={refreshingDiscovery}
            onRefresh={() => refreshDiscovery()}
          />
        </RailPanel>

        {candidates.length > 0 && (
          <RailPanel title="候选审核" icon={<CheckCircle2 size={15} />}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {candidates.map(candidate => (
                <DiscoveryCandidateCard
                  key={candidate.id}
                  candidate={candidate}
                  onReview={reviewCandidate}
                  isReviewing={reviewingCandidateId === candidate.id}
                />
              ))}
            </div>
          </RailPanel>
        )}
      </aside>
    </div>
  );
}
