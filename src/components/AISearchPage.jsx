import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, Bookmark, Image as ImageIcon, Loader2, Send, Sparkles } from "lucide-react";
import { supabase } from "../supabase.js";
import {
  approveDiscoveryCandidate,
  createDiscoveryJob,
  createDiscoverySupplement,
  getDiscoveryJob,
  ignoreDiscoveryCandidate,
  rejectDiscoveryCandidate,
  research,
  saveResearchNote,
} from "../aiApi.js";
import { inputStyle, useIsMobile } from "./shared.jsx";
import ViralPostDrawer from "./ViralPostDrawer.jsx";

const SOURCE_TYPE_LABELS = {
  viral_post: "爆款素材",
  benchmark_account: "对标账号",
  benchmark_post: "对标帖子",
  topic: "选题方向",
  title: "标题灵感",
  team_post: "团队历史",
  account: "账号信息",
  banned_word: "违禁词",
};

function hasValidUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

function sourceToPost(source) {
  const images = Array.isArray(source.image_urls) ? source.image_urls : [];
  return {
    id: source.id,
    title: source.title,
    caption: source.content || source.summary || "",
    images,
    cover_image: images[0],
    likes: source.likes_count || 0,
    saves: source.saves_count || 0,
    comments: source.comments_count || 0,
    views: source.views_count || 0,
    url: hasValidUrl(source.source_url) ? source.source_url : null,
    country: source.country,
    tags: source.tags || [],
    author_name: SOURCE_TYPE_LABELS[source.source_type] || source.source_type,
  };
}

function getEvidenceStatus(answer) {
  const quality = answer?.evidence_quality || (answer?.sparse ? "weak" : "strong");
  const styles = {
    empty: {
      label: "无可用内部证据",
      description: "系统没有把弱相关素材塞进回答，建议创建外部发现任务或补充知识库。",
      color: "#FF5C7A",
      background: "rgba(255,36,66,0.08)",
      border: "rgba(255,36,66,0.22)",
    },
    weak: {
      label: "内部证据较少",
      description: "本次回答只基于筛选后的少量素材，请结合外部发现或人工判断继续收敛。",
      color: "#FF9F43",
      background: "rgba(255,159,67,0.08)",
      border: "rgba(255,159,67,0.22)",
    },
    strong: {
      label: "内部证据充足",
      description: "回答已限制在筛选后的高相关素材范围内生成。",
      color: "#26DE81",
      background: "rgba(38,222,129,0.06)",
      border: "rgba(38,222,129,0.18)",
    },
  };

  return styles[quality] || styles.strong;
}

function SourceCard({ source, onOpen }) {
  const canOpenDetails = Boolean(source.title || source.content || source.summary || source.image_urls?.length);
  const canOpenUrl = hasValidUrl(source.source_url);

  return (
    <div
      onClick={canOpenDetails ? () => onOpen(source) : undefined}
      role={canOpenDetails ? "button" : undefined}
      tabIndex={canOpenDetails ? 0 : undefined}
      onKeyDown={event => {
        if (!canOpenDetails) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(source);
        }
      }}
      style={{
        background: "#111",
        border: "1px solid #1e1e1e",
        borderRadius: 10,
        padding: 12,
        cursor: canOpenDetails ? "pointer" : "default",
      }}
    >
      <div style={{ fontSize: 11, color: "#FF2442", marginBottom: 6 }}>
        {SOURCE_TYPE_LABELS[source.source_type] || source.source_type}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#e0e0e0", marginBottom: 6 }}>
        {source.title || "无标题"}
      </div>
      <div style={{
        fontSize: 12,
        color: "#666",
        lineHeight: 1.6,
        display: "-webkit-box",
        WebkitLineClamp: 3,
        WebkitBoxOrient: "vertical",
        overflow: "hidden",
      }}>
        {source.summary || source.content || "暂无摘要"}
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 10, fontSize: 11, color: "#444", flexWrap: "wrap" }}>
        {source.likes_count != null && <span>赞 {source.likes_count}</span>}
        {source.saves_count != null && <span>藏 {source.saves_count}</span>}
        {source.country && <span>{source.country}</span>}
      </div>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
        {canOpenDetails && (
          <button
            type="button"
            onClick={event => {
              event.stopPropagation();
              onOpen(source);
            }}
            style={{
              border: "none",
              background: "transparent",
              color: "#FF9F43",
              padding: 0,
              fontSize: 11,
              cursor: "pointer",
            }}
          >
            查看详情
          </button>
        )}
        {canOpenUrl && (
          <a
            href={source.source_url}
            target="_blank"
            rel="noreferrer"
            onClick={event => event.stopPropagation()}
            style={{ display: "inline-block", fontSize: 11, color: "#54A0FF", textDecoration: "none" }}
          >
            打开原始链接
          </a>
        )}
      </div>
    </div>
  );
}

function SectionCard({ title, children }) {
  return (
    <section style={{ background: "#111", border: "1px solid #1e1e1e", borderRadius: 10, padding: 16 }}>
      <div style={{ fontSize: 11, color: "#555", marginBottom: 10 }}>{title}</div>
      {children}
    </section>
  );
}

const DISCOVERY_SOURCE_PATH_LABELS = {
  benchmark_expansion: "对标账号扩展",
};

function DiscoveryCandidateCard({ candidate, onReview, isReviewing }) {
  const reviewStatus = candidate.review_status || "pending";
  const statusLabel = {
    pending: "待处理",
    ignored: "已忽略",
    rejected: "已标记不相关",
    approved: "已入库",
  }[reviewStatus] || reviewStatus;
  const isReviewed = reviewStatus !== "pending";
  const isActionDisabled = isReviewed || isReviewing;
  const isApproved = reviewStatus === "approved";
  const sourcePathLabel = DISCOVERY_SOURCE_PATH_LABELS[candidate.source_path] || "关键词搜索";
  const detailText = candidate.caption || candidate.ai_reason || "暂无摘要，建议打开原始链接人工判断。";

  return (
    <div style={{
      background: "#0d0d0d",
      border: "1px solid #222",
      borderRadius: 10,
      padding: 14,
      display: "flex",
      flexDirection: "column",
      gap: 10,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div style={{ display: "flex", gap: 10, minWidth: 0 }}>
          {candidate.cover_image && (
            <img
              src={candidate.cover_image}
              alt=""
              style={{
                width: 58,
                height: 58,
                borderRadius: 8,
                objectFit: "cover",
                border: "1px solid #222",
                background: "#111",
                flexShrink: 0,
              }}
            />
          )}
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#e0e0e0", lineHeight: 1.45 }}>
              {candidate.title || candidate.account_name || "未命名候选素材"}
            </div>
            <div style={{ fontSize: 11, color: "#555", marginTop: 5 }}>
              {sourcePathLabel} · {candidate.platform || "外部来源"} · 候选分 {candidate.candidate_score ?? "-"}
            </div>
          </div>
        </div>
        <span style={{
          flexShrink: 0,
          fontSize: 10,
          color: isApproved ? "#26DE81" : isReviewed ? "#666" : "#FF9F43",
          background: isApproved ? "rgba(38,222,129,0.08)" : isReviewed ? "#151515" : "rgba(255,159,67,0.08)",
          border: `1px solid ${isApproved ? "rgba(38,222,129,0.2)" : isReviewed ? "#242424" : "rgba(255,159,67,0.18)"}`,
          borderRadius: 999,
          padding: "3px 8px",
        }}>
          {statusLabel}
        </span>
      </div>

      <div style={{
        fontSize: 12,
        color: "#888",
        lineHeight: 1.65,
        display: "-webkit-box",
        WebkitLineClamp: 3,
        WebkitBoxOrient: "vertical",
        overflow: "hidden",
      }}>
        {detailText}
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: 11, color: "#444" }}>
        {candidate.likes != null && <span>赞 {candidate.likes}</span>}
        {candidate.saves != null && <span>藏 {candidate.saves}</span>}
        {candidate.comments != null && <span>评 {candidate.comments}</span>}
        {candidate.author_name && <span>{candidate.author_name}</span>}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        {candidate.url && (
          <a
            href={candidate.url}
            target="_blank"
            rel="noreferrer"
            style={{ fontSize: 12, color: "#54A0FF", textDecoration: "none", marginRight: "auto" }}
          >
            打开外部链接
          </a>
        )}
        <button
          type="button"
          disabled={isActionDisabled}
          onClick={() => onReview(candidate, "approve")}
          style={{
            padding: "7px 10px",
            borderRadius: 8,
            border: "1px solid rgba(38,222,129,0.25)",
            background: "rgba(38,222,129,0.08)",
            color: isActionDisabled ? "#444" : "#26DE81",
            cursor: isActionDisabled ? "not-allowed" : "pointer",
            fontSize: 12,
          }}
        >
          {isReviewing ? "处理中…" : "通过并入库"}
        </button>
        <button
          type="button"
          disabled={isActionDisabled}
          onClick={() => onReview(candidate, "ignore")}
          style={{
            padding: "7px 10px",
            borderRadius: 8,
            border: "1px solid #2a2a2a",
            background: "transparent",
            color: isActionDisabled ? "#444" : "#aaa",
            cursor: isActionDisabled ? "not-allowed" : "pointer",
            fontSize: 12,
          }}
        >
          {isReviewing ? "处理中…" : "忽略"}
        </button>
        <button
          type="button"
          disabled={isActionDisabled}
          onClick={() => onReview(candidate, "reject")}
          style={{
            padding: "7px 10px",
            borderRadius: 8,
            border: "1px solid rgba(255,36,66,0.25)",
            background: "rgba(255,36,66,0.06)",
            color: isActionDisabled ? "#444" : "#FF2442",
            cursor: isActionDisabled ? "not-allowed" : "pointer",
            fontSize: 12,
          }}
        >
          不相关
        </button>
      </div>
    </div>
  );
}

function ExternalSupplementCard({ supplement }) {
  if (!supplement) return null;

  return (
    <div style={{
      marginTop: 14,
      background: "linear-gradient(180deg, rgba(255,159,67,0.08), rgba(13,13,13,1) 46%)",
      border: "1px solid rgba(255,159,67,0.18)",
      borderRadius: 12,
      padding: 16,
    }}>
      <div style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 11,
        color: "#FF9F43",
        background: "rgba(255,159,67,0.08)",
        border: "1px solid rgba(255,159,67,0.18)",
        borderRadius: 999,
        padding: "4px 9px",
        marginBottom: 12,
      }}>
        待审核外部素材
      </div>
      {supplement.warning && (
        <div style={{ fontSize: 12, color: "#FF9F43", lineHeight: 1.6, marginBottom: 10 }}>
          {supplement.warning}
        </div>
      )}
      <div style={{ fontSize: 15, fontWeight: 700, color: "#fff", lineHeight: 1.7 }}>
        {supplement.conclusion}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
        {(supplement.recommendations || []).length === 0 && (
          <div style={{ fontSize: 13, color: "#555" }}>暂无可引用的外部补充建议。</div>
        )}
        {(supplement.recommendations || []).map((rec, index) => (
          <div key={index} style={{ background: "#0a0a0a", border: "1px solid #222", borderRadius: 8, padding: 12 }}>
            <div style={{ fontSize: 13, color: "#ddd", lineHeight: 1.65 }}>{rec.text}</div>
            {rec.candidate_ids?.length > 0 && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                {rec.candidate_ids.map(id => (
                  <span key={id} style={{
                    fontSize: 10,
                    color: "#FF9F43",
                    background: "rgba(255,159,67,0.08)",
                    border: "1px solid rgba(255,159,67,0.18)",
                    borderRadius: 999,
                    padding: "2px 7px",
                  }}>
                    候选 {id.slice(0, 8)}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {supplement.general_advice?.length > 0 && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ fontSize: 11, color: "#666" }}>未绑定候选素材的通用提醒</div>
          {supplement.general_advice.map((item, index) => (
            <div key={index} style={{ fontSize: 12, color: "#aaa", lineHeight: 1.6 }}>
              {item.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AnswerView({ answer, onSave, savingNote, isMobile }) {
  const [selectedSource, setSelectedSource] = useState(null);

  if (!answer) return null;

  const evidenceStatus = getEvidenceStatus(answer);
  const citedIds = new Set((answer.cited_sources || []).map(source => source.id));
  const relatedSources = (answer.related_sources || [])
    .filter(source => !citedIds.has(source.id))
    .slice(0, 4);

  return (
    <>
      {selectedSource && (
        <ViralPostDrawer
          post={sourceToPost(selectedSource)}
          onClose={() => setSelectedSource(null)}
        />
      )}

      <div style={{
        display: "grid",
        gridTemplateColumns: isMobile ? "1fr" : "minmax(0, 1.15fr) minmax(300px, 0.85fr)",
        gap: 16,
        alignItems: "start",
      }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{
          background: evidenceStatus.background,
          border: `1px solid ${evidenceStatus.border}`,
          borderRadius: 10,
          padding: 12,
          color: evidenceStatus.color,
          fontSize: 12,
          lineHeight: 1.65,
        }}>
          <div style={{ fontWeight: 700, color: evidenceStatus.color, marginBottom: 2 }}>
            {evidenceStatus.label}
          </div>
          <div>{evidenceStatus.description}</div>
          {answer.trace_id && (
            <div style={{ marginTop: 6, color: "#555", fontSize: 11 }}>
              Trace {answer.trace_id.slice(0, 8)}
            </div>
          )}
        </div>

        {answer.message && (
          <div style={{
            background: "rgba(255,159,67,0.08)",
            border: "1px solid rgba(255,159,67,0.18)",
            borderRadius: 10,
            padding: 12,
            color: "#FF9F43",
            fontSize: 12,
          }}>
            {answer.message}
          </div>
        )}

        <SectionCard title="简明结论">
          <div style={{ fontSize: 16, color: "#fff", lineHeight: 1.75 }}>{answer.conclusion}</div>
        </SectionCard>

        <SectionCard title="推荐方向">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {(answer.recommendations || []).length === 0 && (
              <div style={{ fontSize: 13, color: "#555" }}>暂无可引用的内部推荐方向。</div>
            )}
            {(answer.recommendations || []).map((rec, index) => (
              <div key={index} style={{ background: "#0d0d0d", border: "1px solid #222", borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 13, color: "#ddd", lineHeight: 1.65 }}>{rec.text}</div>
                {rec.source_ids?.length > 0 && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                    {rec.source_ids.map(id => (
                      <span key={id} style={{
                        fontSize: 10,
                        color: "#54A0FF",
                        background: "rgba(84,160,255,0.08)",
                        border: "1px solid rgba(84,160,255,0.18)",
                        borderRadius: 999,
                        padding: "2px 7px",
                      }}>
                        引用 {id.slice(0, 8)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </SectionCard>

        {answer.general_advice?.length > 0 && (
          <SectionCard title="通用建议">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {answer.general_advice.map((item, index) => (
                <div key={index} style={{ fontSize: 13, color: "#aaa", lineHeight: 1.6 }}>
                  {item.text}
                </div>
              ))}
            </div>
          </SectionCard>
        )}

        <button
          onClick={onSave}
          disabled={savingNote}
          style={{
            alignSelf: "flex-start",
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "9px 14px",
            borderRadius: 8,
            border: "none",
            background: savingNote ? "#333" : "#FF2442",
            color: "#fff",
            cursor: savingNote ? "not-allowed" : "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          <Bookmark size={15} />
          {savingNote ? "保存中…" : "保存结论"}
        </button>
      </div>

      <aside style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {answer.image_analysis && (
          <SectionCard title="图片分析">
            <div style={{ fontSize: 12, color: "#aaa", lineHeight: 1.7 }}>
              {[
                answer.image_analysis.subject,
                answer.image_analysis.scene,
                answer.image_analysis.mood,
                answer.image_analysis.visual_style,
                answer.image_analysis.content_direction,
              ].filter(Boolean).join(" · ") || "暂无图片分析"}
            </div>
          </SectionCard>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 11, color: "#555" }}>本次回答引用的素材</div>
          {(answer.cited_sources || []).length === 0
            ? <div style={{ fontSize: 12, color: "#333" }}>暂无引用来源</div>
            : answer.cited_sources.map(source => (
              <SourceCard key={source.id} source={source} onOpen={setSelectedSource} />
            ))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 11, color: "#555" }}>其他精准匹配素材</div>
          {relatedSources.length === 0
            ? <div style={{ fontSize: 12, color: "#333" }}>暂无更多精准匹配素材</div>
            : relatedSources.map(source => (
              <SourceCard key={source.id} source={source} onOpen={setSelectedSource} />
            ))}
        </div>
      </aside>
      </div>
    </>
  );
}

export default function AISearchPage() {
  const isMobile = useIsMobile();
  const [question, setQuestion] = useState("");
  const [imageFile, setImageFile] = useState(null);
  const [lastImageUrl, setLastImageUrl] = useState(null);
  const [answer, setAnswer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [error, setError] = useState("");
  const [discoveryJob, setDiscoveryJob] = useState(null);
  const [discoveryCandidates, setDiscoveryCandidates] = useState([]);
  const [discoveryLoading, setDiscoveryLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const [reviewingCandidateId, setReviewingCandidateId] = useState(null);
  const [externalSupplement, setExternalSupplement] = useState(null);
  const [supplementLoading, setSupplementLoading] = useState(false);
  const discoveryRequestSeqRef = useRef(0);
  const activeDiscoveryJobIdRef = useRef(null);
  const supplementRequestSeqRef = useRef(0);

  const uploadImage = async () => {
    if (!imageFile) return null;

    const researchId = crypto.randomUUID();
    const ext = imageFile.name.split(".").pop() || "jpg";
    const path = `ai-research/${researchId}/${Date.now()}.${ext}`;
    const { error: uploadError } = await supabase.storage.from("post-images").upload(path, imageFile);
    if (uploadError) {
      throw new Error("图片上传失败：" + uploadError.message);
    }
    const { data: { publicUrl } } = supabase.storage.from("post-images").getPublicUrl(path);
    return publicUrl;
  };

  const handleSubmit = async () => {
    if (!question.trim()) {
      alert("请先输入问题");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const imageUrl = await uploadImage();
      setLastImageUrl(imageUrl);
      const result = await research(question.trim(), {
        imageUrl,
        previousAnswerSummary: answer?.conclusion || null,
        previousCitationIds: answer?.cited_sources?.map(source => source.id) || [],
      });
      discoveryRequestSeqRef.current += 1;
      supplementRequestSeqRef.current += 1;
      activeDiscoveryJobIdRef.current = null;
      setAnswer(result);
      setDiscoveryJob(null);
      setDiscoveryCandidates([]);
      setDiscoveryLoading(false);
      setDiscoveryError("");
      setReviewingCandidateId(null);
      setExternalSupplement(null);
      setSupplementLoading(false);
    } catch (err) {
      setError(err.message || "AI 服务暂时不可用，请稍后再试。");
    } finally {
      setLoading(false);
    }
  };

  const refreshDiscoveryJob = useCallback(async (jobId, expectedSeq = discoveryRequestSeqRef.current) => {
    const payload = await getDiscoveryJob(jobId);
    if (discoveryRequestSeqRef.current !== expectedSeq || activeDiscoveryJobIdRef.current !== jobId) {
      return null;
    }
    setDiscoveryJob(payload.job);
    setDiscoveryCandidates(payload.candidates || []);
    return payload.job;
  }, []);

  const handleCreateDiscovery = async () => {
    if (!answer) return;

    const requestSeq = discoveryRequestSeqRef.current + 1;
    discoveryRequestSeqRef.current = requestSeq;
    supplementRequestSeqRef.current += 1;
    activeDiscoveryJobIdRef.current = null;
    setDiscoveryLoading(true);
    setDiscoveryError("");
    setExternalSupplement(null);
    setSupplementLoading(false);
    try {
      const { job } = await createDiscoveryJob({
        user_question: answer.question,
        task_type: answer.task_type || "mixed",
        trigger_reason: answer.discovery_trigger_reason || "user_requested",
        internal_answer_payload: answer,
        search_queries: answer.suggested_search_queries?.length ? answer.suggested_search_queries : null,
        benchmark_account_ids: [],
      });
      if (discoveryRequestSeqRef.current !== requestSeq) return;
      activeDiscoveryJobIdRef.current = job.id;
      setDiscoveryJob(job);
      setDiscoveryCandidates([]);
      setExternalSupplement(null);
    } catch (err) {
      if (discoveryRequestSeqRef.current !== requestSeq) return;
      setDiscoveryError(err.message || "创建外部发现任务失败，请稍后重试。");
    } finally {
      if (discoveryRequestSeqRef.current === requestSeq) {
        setDiscoveryLoading(false);
      }
    }
  };

  const handleCreateSupplement = async () => {
    if (!discoveryJob?.id) return;
    const jobId = discoveryJob.id;
    const expectedSeq = discoveryRequestSeqRef.current;
    const supplementSeq = supplementRequestSeqRef.current + 1;
    supplementRequestSeqRef.current = supplementSeq;
    setSupplementLoading(true);
    try {
      const result = await createDiscoverySupplement(jobId);
      if (
        activeDiscoveryJobIdRef.current !== jobId
        || discoveryRequestSeqRef.current !== expectedSeq
        || supplementRequestSeqRef.current !== supplementSeq
      ) {
        return;
      }
      setExternalSupplement(result);
    } catch (err) {
      if (
        activeDiscoveryJobIdRef.current !== jobId
        || discoveryRequestSeqRef.current !== expectedSeq
        || supplementRequestSeqRef.current !== supplementSeq
      ) {
        return;
      }
      alert(err.message || "生成外部补充回答失败，请稍后重试。");
    } finally {
      if (
        activeDiscoveryJobIdRef.current === jobId
        && discoveryRequestSeqRef.current === expectedSeq
        && supplementRequestSeqRef.current === supplementSeq
      ) {
        setSupplementLoading(false);
      }
    }
  };

  const handleCandidateReview = async (candidate, action) => {
    if ((candidate.review_status || "pending") !== "pending" || reviewingCandidateId) return;

    setReviewingCandidateId(candidate.id);
    try {
      let resp;
      if (action === "approve") {
        resp = await approveDiscoveryCandidate(candidate.id);
      } else if (action === "ignore") {
        resp = await ignoreDiscoveryCandidate(candidate.id);
      } else {
        resp = await rejectDiscoveryCandidate(candidate.id, "不相关");
      }
      const updated = resp.candidate;
      setDiscoveryCandidates(prev => prev.map(item => item.id === candidate.id ? { ...item, ...updated } : item));
      supplementRequestSeqRef.current += 1;
      setExternalSupplement(null);
      setSupplementLoading(false);
    } catch (err) {
      alert(err.message || "操作失败，请稍后重试。");
    } finally {
      setReviewingCandidateId(null);
    }
  };

  const handleSave = async () => {
    if (!answer) return;

    setSavingNote(true);
    try {
      await saveResearchNote({
        user_question: answer.question,
        image_url: lastImageUrl || null,
        conclusion: answer.conclusion,
        recommendations: answer.recommendations || [],
        material_references: answer.material_references || [],
        team_history_references: answer.team_history_references || [],
        image_analysis: answer.image_analysis || null,
        full_payload: answer,
        visibility: "team",
      });
      alert("已保存为研究笔记");
    } catch (err) {
      alert(err.message || "保存失败，请稍后重试。");
    } finally {
      setSavingNote(false);
    }
  };

  useEffect(() => {
    if (!discoveryJob?.id || !["pending", "running"].includes(discoveryJob.status)) return;

    const expectedSeq = discoveryRequestSeqRef.current;
    const jobId = discoveryJob.id;
    const timer = window.setInterval(() => {
      refreshDiscoveryJob(jobId, expectedSeq).catch(err => {
        if (discoveryRequestSeqRef.current === expectedSeq && activeDiscoveryJobIdRef.current === jobId) {
          setDiscoveryError(err.message || "刷新外部发现任务失败");
        }
      });
    }, 5000);

    return () => window.clearInterval(timer);
  }, [discoveryJob?.id, discoveryJob?.status, refreshDiscoveryJob]);

  const canCreateDiscovery = answer?.can_external_discover;
  const discoveryStatusText = {
    pending: "等待开始",
    running: "正在发现",
    completed: "已完成",
    failed: "失败",
  }[discoveryJob?.status] || discoveryJob?.status;

  return (
    <div style={{ padding: isMobile ? 16 : 32, maxWidth: 1220, margin: isMobile ? 0 : "0 auto" }}>
      <div style={{ marginBottom: 22 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "#fff", margin: "0 0 6px" }}>AI 搜索中心</h1>
        <p style={{ fontSize: 13, color: "#555", margin: 0 }}>找素材 · 找经验 · 看图找参考</p>
      </div>

      <div style={{
        background: "linear-gradient(180deg, rgba(255,36,66,0.06), rgba(17,17,17,1) 36%)",
        border: "1px solid #1e1e1e",
        borderRadius: 12,
        padding: 16,
        marginBottom: 20,
      }}>
        <label style={{ display: "block", fontSize: 12, color: "#666", marginBottom: 8 }}>输入你的素材或经验检索问题</label>
        <textarea
          rows={3}
          value={question}
          onChange={e => setQuestion(e.target.value)}
          placeholder="例如：帮我找适合英国留学申请焦虑方向的素材；或者，我们过去写过哪些文书相关内容容易出收藏？"
          style={{ ...inputStyle, resize: "vertical", lineHeight: 1.6, minHeight: 92 }}
        />
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 12,
          marginTop: 12,
          flexWrap: "wrap",
        }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, color: "#666", fontSize: 13, cursor: "pointer" }}>
            <ImageIcon size={15} />
            <span>{imageFile ? imageFile.name : "上传图片（可选）"}</span>
            <input
              type="file"
              accept="image/*"
              style={{ display: "none" }}
              onChange={e => setImageFile(e.target.files?.[0] || null)}
            />
          </label>
          {imageFile && (
            <button
              onClick={() => setImageFile(null)}
              type="button"
              style={{
                padding: "7px 10px",
                borderRadius: 8,
                border: "1px solid #2a2a2a",
                background: "transparent",
                color: "#666",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              移除图片
            </button>
          )}
          <button
            onClick={handleSubmit}
            disabled={loading}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "10px 18px",
              borderRadius: 8,
              border: "none",
              background: loading ? "#333" : "#FF2442",
              color: "#fff",
              cursor: loading ? "not-allowed" : "pointer",
              fontSize: 13,
              fontWeight: 700,
            }}
          >
            {loading ? <Loader2 size={15} /> : <Send size={15} />}
            {loading ? "研究中…" : "提问"}
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          background: "rgba(255,36,66,0.08)",
          border: "1px solid rgba(255,36,66,0.2)",
          color: "#FF2442",
          borderRadius: 10,
          padding: 12,
          marginBottom: 16,
          fontSize: 13,
        }}>
          {error}
        </div>
      )}

      {!answer && !loading && (
        <div style={{
          border: "1px dashed #222",
          borderRadius: 12,
          padding: "42px 20px",
          textAlign: "center",
          color: "#444",
          background: "radial-gradient(circle at top, rgba(255,36,66,0.06), transparent 55%)",
        }}>
          <Bot size={26} />
          <div style={{ fontSize: 13, marginTop: 10 }}>输入问题后，AI 会从素材库和团队历史内容里找依据。</div>
        </div>
      )}

      {loading && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#555", fontSize: 13, marginBottom: 16 }}>
          <Sparkles size={16} />
          正在检索知识库并整理回答…
        </div>
      )}

      <AnswerView answer={answer} onSave={handleSave} savingNote={savingNote} isMobile={isMobile} />

      {answer && canCreateDiscovery && (
        <section style={{
          marginTop: 18,
          background: "linear-gradient(180deg, rgba(84,160,255,0.07), rgba(17,17,17,1) 42%)",
          border: "1px solid #1e1e1e",
          borderRadius: 12,
          padding: 16,
        }}>
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 14,
            alignItems: isMobile ? "stretch" : "center",
            flexDirection: isMobile ? "column" : "row",
          }}>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: "#fff", marginBottom: 6 }}>继续发现外部素材</div>
              <div style={{ fontSize: 12, color: "#777", lineHeight: 1.65 }}>
                内部知识库已经回答完毕，可以基于本次问题继续创建外部发现任务，补充新的对标账号或内容线索。
              </div>
              {answer.suggested_search_queries?.length > 0 && (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
                  {answer.suggested_search_queries.map(query => (
                    <span key={query} style={{
                      fontSize: 10,
                      color: "#54A0FF",
                      background: "rgba(84,160,255,0.08)",
                      border: "1px solid rgba(84,160,255,0.18)",
                      borderRadius: 999,
                      padding: "3px 8px",
                    }}>
                      {query}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={handleCreateDiscovery}
              disabled={discoveryLoading || ["pending", "running"].includes(discoveryJob?.status)}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                padding: "10px 14px",
                borderRadius: 8,
                border: "none",
                background: discoveryLoading || ["pending", "running"].includes(discoveryJob?.status) ? "#333" : "#FF2442",
                color: "#fff",
                cursor: discoveryLoading || ["pending", "running"].includes(discoveryJob?.status) ? "not-allowed" : "pointer",
                fontSize: 13,
                fontWeight: 700,
                whiteSpace: "nowrap",
              }}
            >
              {discoveryLoading ? <Loader2 size={15} /> : <Sparkles size={15} />}
              {discoveryJob ? "重新发现" : "创建发现任务"}
            </button>
          </div>

          {discoveryError && (
            <div style={{
              marginTop: 14,
              background: "rgba(255,36,66,0.08)",
              border: "1px solid rgba(255,36,66,0.2)",
              color: "#FF2442",
              borderRadius: 10,
              padding: 12,
              fontSize: 13,
            }}>
              {discoveryError}
            </div>
          )}

          {discoveryJob && (
            <div style={{
              marginTop: 14,
              background: "#0d0d0d",
              border: "1px solid #222",
              borderRadius: 10,
              padding: 12,
              display: "flex",
              justifyContent: "space-between",
              gap: 10,
              alignItems: "center",
              flexWrap: "wrap",
            }}>
              <div style={{ fontSize: 12, color: "#aaa" }}>
                任务状态：<span style={{ color: "#fff" }}>{discoveryStatusText}</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  const expectedSeq = discoveryRequestSeqRef.current;
                  const jobId = discoveryJob.id;
                  refreshDiscoveryJob(jobId, expectedSeq).catch(err => {
                    if (discoveryRequestSeqRef.current === expectedSeq && activeDiscoveryJobIdRef.current === jobId) {
                      setDiscoveryError(err.message || "刷新外部发现任务失败");
                    }
                  });
                }}
                style={{
                  padding: "7px 10px",
                  borderRadius: 8,
                  border: "1px solid #2a2a2a",
                  background: "transparent",
                  color: "#aaa",
                  cursor: "pointer",
                  fontSize: 12,
                }}
              >
                手动刷新
              </button>
            </div>
          )}

          {discoveryCandidates.length > 0 && (
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, minmax(0, 1fr))", gap: 12, marginTop: 14 }}>
              {discoveryCandidates.map(candidate => (
                <DiscoveryCandidateCard
                  key={candidate.id}
                  candidate={candidate}
                  onReview={handleCandidateReview}
                  isReviewing={Boolean(reviewingCandidateId)}
                />
              ))}
            </div>
          )}

          {discoveryJob?.status === "completed" && discoveryCandidates.length > 0 && (
            <button
              type="button"
              onClick={handleCreateSupplement}
              disabled={supplementLoading}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                marginTop: 14,
                padding: "10px 14px",
                borderRadius: 8,
                border: "1px solid rgba(255,159,67,0.25)",
                background: supplementLoading ? "#333" : "rgba(255,159,67,0.1)",
                color: supplementLoading ? "#777" : "#FF9F43",
                cursor: supplementLoading ? "not-allowed" : "pointer",
                fontSize: 13,
                fontWeight: 700,
              }}
            >
              {supplementLoading ? <Loader2 size={15} /> : <Sparkles size={15} />}
              {supplementLoading ? "生成外部补充中…" : "生成待审核外部补充回答"}
            </button>
          )}

          <ExternalSupplementCard supplement={externalSupplement} />
        </section>
      )}
    </div>
  );
}
