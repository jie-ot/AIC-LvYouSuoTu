"use client";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Check,
  FileText,
  ImagePlus,
  X,
  ArrowUpRight,
  Images,
  Plus,
  TriangleAlert,
} from "lucide-react";
import { useApp } from "@/components/shared/app-context";
import { TopBar } from "@/components/shared/top-bar";
import { ProgressLoader } from "@/components/shared/progress-loader";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import type { GenerateResult } from "@/lib/api";
import { shortId } from "@/lib/asset";
import { displayPlace } from "@/lib/place";
interface PickedPhoto {
  id: string;
  url: string;
  file: File;
}

interface RequestIdentity {
  signature: string;
  clientRequestId: string;
}

type GenerationBranchStatus = Exclude<NonNullable<GenerateResult["memoryStatus"]>, "skipped">;

function generationStatusLabel(status: GenerationBranchStatus) {
  if (status === "success") return "已完成";
  if (status === "failed") return "未完成";
  if (status === "pending") return "等待重试";
  return "未生成";
}

function generationRequestSignature(input: {
  photos: PickedPhoto[];
  requirements: string;
  memoryRequirements: string;
  postcards: boolean;
  report: boolean;
  postcardCount: number;
  learnPreferences: boolean;
}) {
  return JSON.stringify({
    photos: input.photos.map((photo) => ({
      id: photo.id,
      name: photo.file.name,
      size: photo.file.size,
      lastModified: photo.file.lastModified,
      type: photo.file.type,
    })),
    requirements: input.requirements,
    memoryRequirements: input.memoryRequirements,
    postcards: input.postcards,
    report: input.report,
    postcardCount: input.postcardCount,
    learnPreferences: input.learnPreferences,
  });
}

export function PhotoCreateView() {
  const search = useSearchParams();
  const sourceTripId = search.get("tripId") ?? undefined;
  const entryMode = search.get("mode");
  const {
    generateArtifacts,
    generating,
    generationProgress,
    navigate,
    goBackTo,
    toast,
    registerBackHandler,
  } = useApp();
  const [created, setCreated] = useState<GenerateResult | null>(null);
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [requirements, setRequirements] = useState("");
  const [memoryRequirements, setMemoryRequirements] = useState("");
  const [postcards, setPostcards] = useState(entryMode !== "report");
  const [report, setReport] = useState(entryMode === "report");
  const [postcardCount, setPostcardCount] = useState(3);
  const [learnPreferences, setLearnPreferences] = useState(false);
  const [resolvedTripId, setResolvedTripId] = useState(sourceTripId);
  const [requestIdentity, setRequestIdentity] = useState<RequestIdentity | null>(null);
  const [replayMemoryOnly, setReplayMemoryOnly] = useState(false);
  const [leaveOpen, setLeaveOpen] = useState(false);
  const backHref = sourceTripId
    ? `/trips/detail?tripId=${encodeURIComponent(sourceTripId)}`
    : entryMode === "report"
      ? "/reports"
      : entryMode === "postcard"
        ? "/postcards"
        : "/";
  const backLabel = sourceTripId
    ? "返回这次旅行"
    : entryMode === "report"
      ? "返回旅行报告"
      : entryMode === "postcard"
        ? "返回明信片"
        : "返回我的旅行";
  const fileInput = useRef<HTMLInputElement>(null);
  const livePhotos = useRef<PickedPhoto[]>([]);
  useEffect(() => {
    livePhotos.current = photos;
  }, [photos]);
  useEffect(
    () => () =>
      livePhotos.current.forEach((photo) => URL.revokeObjectURL(photo.url)),
    [],
  );
  const back = () => {
    if (generating) {
      toast("正在生成，请稍候", "info");
      return;
    }
    if (photos.length) setLeaveOpen(true);
    else goBackTo(backHref);
  };
  useEffect(
    () =>
      registerBackHandler(() => {
        if (generating) {
          toast("正在生成，请稍候", "info");
          return;
        }
        if (photos.length) setLeaveOpen(true);
        else goBackTo(backHref);
      }),
    [backHref, registerBackHandler, generating, photos.length, goBackTo, toast],
  );
  function pickFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []);
    const valid = selected.filter((file) =>
      /image\/(jpeg|png|webp)/.test(file.type),
    );
    if (valid.length !== selected.length)
      toast("支持 JPG、PNG 和 WebP 图片", "info");
    const seen = new Set(
      photos.map((photo) => `${photo.file.name}\u0000${photo.file.size}\u0000${photo.file.lastModified}`),
    );
    const unique = valid.filter((file) => {
      const fingerprint = `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
      if (seen.has(fingerprint)) return false;
      seen.add(fingerprint);
      return true;
    });
    if (unique.length !== valid.length)
      toast("已忽略重复选择的照片", "info");
    if (photos.length + unique.length > 50) toast("最多选择50张照片", "info");
    setPhotos((current) => [
      ...current,
      ...unique.slice(0, 50 - current.length).map((file) => ({
        id: shortId("photo"),
        url: URL.createObjectURL(file),
        file,
      })),
    ]);
    event.target.value = "";
  }
  function removePhoto(id: string) {
    setPhotos((current) => {
      const photo = current.find((p) => p.id === id);
      if (photo) URL.revokeObjectURL(photo.url);
      return current.filter((p) => p.id !== id);
    });
  }
  async function generate() {
    if (generating) return;
    if (!photos.length) {
      fileInput.current?.click();
      return;
    }
    if (!postcards && !report) {
      toast("请选择明信片或旅行报告", "info");
      return;
    }
    if (report && photos.length < 10) {
      toast(`旅行人格报告至少需要 10 张照片，还差 ${10 - photos.length} 张`, "info");
      return;
    }
    const normalizedRequirements = requirements.trim();
    const normalizedMemoryRequirements = memoryRequirements.trim();
    if (learnPreferences && !normalizedMemoryRequirements) {
      toast("请填写要保存的旅行要求", "info");
      return;
    }
    const signature = generationRequestSignature({
      photos,
      requirements: normalizedRequirements,
      memoryRequirements: learnPreferences ? normalizedMemoryRequirements : "",
      postcards,
      report,
      postcardCount,
      learnPreferences,
    });
    const matchingIdentity = requestIdentity?.signature === signature ? requestIdentity : null;
    const sameRequest = matchingIdentity !== null;
    const requestId = matchingIdentity?.clientRequestId ?? crypto.randomUUID();
    if (!sameRequest) {
      setRequestIdentity({ signature, clientRequestId: requestId });
      setReplayMemoryOnly(false);
    }
    const result = await generateArtifacts({
      files: photos.map((p) => p.file),
      requirements: normalizedRequirements,
      memoryRequirements: learnPreferences ? normalizedMemoryRequirements : "",
      clientRequestId: requestId,
      replayOnly: replayMemoryOnly && sameRequest,
      tripId: resolvedTripId,
      options: {
        generatePostcards: postcards,
        generateReport: report,
        postcardCount,
        learnPreferences,
      },
    });
    if (!result) {
      return;
    }
    if (result.trip?.id) setResolvedTripId(result.trip.id);
    if (result?.postcardGroup || result?.report) {
      if (result.status === "partial" || (result.warnings?.length ?? 0) > 0) {
        if (result.status !== "partial") {
          setRequestIdentity(null);
          setReplayMemoryOnly(false);
        }
        setCreated(result);
        return;
      }
      setRequestIdentity(null);
      setReplayMemoryOnly(false);
      setPhotos([]);
      livePhotos.current.forEach((p) => URL.revokeObjectURL(p.url));
      livePhotos.current = [];
      if (result.postcardGroup && result.report) setCreated(result);
      else if (result.postcardGroup)
        navigate({
          page: "postcard-collection",
          groupId: result.postcardGroup.id,
          from: result.trip?.id ? "trip" : undefined,
          tripId: result.trip?.id,
        });
      else if (result.report)
        navigate({
          page: "report-detail",
          reportId: result.report.id,
          from: result.trip?.id ? "trip" : undefined,
          tripId: result.trip?.id,
        });
    }
  }
  if (created) {
    const partial = created.status === "partial";
    const hasWarnings = (created.warnings?.length ?? 0) > 0;
    const needsAttention = partial || hasWarnings;
    const retryPostcards =
      created.postcardStatus === "failed" ||
      (!created.postcardGroup && created.postcardStatus == null && postcards);
    const retryReport =
      created.reportStatus === "failed" ||
      (!created.report && created.reportStatus == null && report);
    const retryMemory =
      created.memoryStatus === "failed" ||
      created.memoryStatus === "pending" ||
      (created.memoryStatus == null && learnPreferences);
    const hasFailedArtifact = retryPostcards || retryReport;
    const branchRows = [
      created.postcardStatus && created.postcardStatus !== "skipped"
        ? { label: "明信片", status: created.postcardStatus }
        : null,
      created.reportStatus && created.reportStatus !== "skipped"
        ? { label: "旅行人格报告", status: created.reportStatus }
        : null,
      created.memoryStatus && created.memoryStatus !== "skipped"
        ? { label: "旅行记忆", status: created.memoryStatus }
        : null,
    ].filter(
      (item): item is { label: string; status: GenerationBranchStatus } => item !== null,
    );

    function returnToEditor() {
      if (partial) {
        if (hasFailedArtifact) {
          setPostcards(retryPostcards);
          setReport(retryReport);
          setLearnPreferences(retryMemory);
          setRequestIdentity(null);
          setReplayMemoryOnly(false);
        } else if (retryMemory) {
          setReplayMemoryOnly(true);
        }
      }
      setCreated(null);
    }

    return (
      <div className="create-page">
        <TopBar
          title={partial ? "部分生成完成" : hasWarnings ? "生成完成，有提示" : "生成完成"}
          showUserBadge={false}
          backHref={created.trip?.id || resolvedTripId
            ? `/trips/detail?tripId=${encodeURIComponent(created.trip?.id ?? resolvedTripId ?? "")}`
            : backHref}
          backLabel={created.trip?.id || resolvedTripId ? "返回这次旅行" : backLabel}
        />
        <div className="created-results">
          <span className={`created-check ${needsAttention ? "is-partial" : ""}`}>
            {needsAttention ? <TriangleAlert size={30} /> : <Check size={30} />}
          </span>
          <h2>{created.report?.profileData?.journey?.title
            || displayPlace(created.postcardGroup?.location || created.report?.location, created.trip?.title)}</h2>
          {needsAttention ? (
            <section className="created-partial-panel" aria-live="polite">
              <strong>
                {partial ? "已生成的内容已保存" : "生成完成"}
              </strong>
              <p>
                {partial
                  ? "其余内容可返回后重试。"
                  : "请查看下方处理结果。"}
              </p>
              {branchRows.length ? (
                <div className="created-branch-statuses">
                  {branchRows.map((item) => (
                    <span key={item.label} data-status={item.status}>
                      {item.label} · {generationStatusLabel(item.status)}
                    </span>
                  ))}
                </div>
              ) : null}
              {created.warnings?.length ? (
                <ul>
                  {created.warnings.map((warning, index) => (
                    <li key={`${warning.code}-${warning.itemIndex ?? "all"}-${index}`}>
                      {warning.message}
                      {warning.retryable ? "（可返回后再次尝试）" : ""}
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          ) : null}
          {created.postcardGroup && (
            <button
              onClick={() =>
                navigate({
                  page: "postcard-collection",
                  groupId: created.postcardGroup!.id,
                  from: created.trip?.id || resolvedTripId ? "trip" : undefined,
                  tripId: created.trip?.id ?? resolvedTripId,
                })
              }
            >
              <Images size={23} />
              <span>
                明信片<small>{created.postcardGroup.postcards.length} 张</small>
              </span>
              <ArrowUpRight size={19} />
            </button>
          )}
          {created.report && (
            <button
              onClick={() =>
                navigate({
                  page: "report-detail",
                  reportId: created.report!.id,
                  from: created.trip?.id || resolvedTripId ? "trip" : undefined,
                  tripId: created.trip?.id ?? resolvedTripId,
                })
              }
            >
              <FileText size={23} />
              <span>
                旅行报告
                <small>{created.report.dateLabel}</small>
              </span>
              <ArrowUpRight size={19} />
            </button>
          )}
        </div>
        <footer className="create-footer">
          {needsAttention ? (
            <button
              className="primary-action"
              onClick={returnToEditor}
            >
              {partial && hasFailedArtifact
                ? "仅重试未完成项"
                : partial && retryMemory
                  ? "重试保存旅行记忆"
                  : "返回原照片调整"}
            </button>
          ) : null}
          <button
            className="secondary-action"
            onClick={() => created.trip?.id || resolvedTripId
              ? navigate({ page: "trip-detail", tripId: created.trip?.id ?? resolvedTripId })
              : navigate({ page: "home" })}
          >
            返回旅行
          </button>
        </footer>
      </div>
    );
  }
  return (
    <div className="create-page">
      <TopBar
        title={entryMode === "postcard" ? "制作明信片" : entryMode === "report" ? "生成旅行人格报告" : "用照片创建"}
        onBack={back}
        backLabel={backLabel}
        showUserBadge={false}
      />
      <div className="create-scroll">
        <input
          type="file"
          ref={fileInput}
          onChange={pickFiles}
          accept="image/jpeg,image/png,image/webp"
          multiple
          hidden
          disabled={generating}
        />
        {photos.length ? (
          <section className="selected-photos">
            <div className="section-caption">
              <span>已选照片</span>
              <span>{photos.length} / 50</span>
            </div>
            <div className="selected-photo-grid">
              {photos.map((photo, index) => (
                <figure key={photo.id}>
                  <img src={photo.url} alt={`已选照片${index + 1}`} />
                  <button
                    disabled={generating}
                    aria-label={`移除照片${index + 1}`}
                    onClick={() => removePhoto(photo.id)}
                  >
                    <X size={14} />
                  </button>
                </figure>
              ))}
              {photos.length < 50 && (
                <button
                  className="photo-add-more"
                  disabled={generating}
                  aria-label="继续添加照片"
                  onClick={() => fileInput.current?.click()}
                >
                  <Plus size={23} />
                </button>
              )}
            </div>
          </section>
        ) : (
          <button
            className="upload-zone"
            onClick={() => fileInput.current?.click()}
          >
            <span className="upload-photo-mark">
              <Images size={40} strokeWidth={1.1} />
              <i>+</i>
            </span>
            <strong>选择旅行照片</strong>
            <span>JPG / PNG / WebP · 最多50张</span>
          </button>
        )}
        <p className="cloud-processing-note">
          照片会上传，用于生成你选择的内容。
        </p>
        <section className="output-choice">
          <div className="section-caption">
            <span>生成什么</span>
            <span>可多选</span>
          </div>
          <div className="output-options">
            {[
              {
                name: "明信片",
                benefit: "制作 1–5 张",
                icon: Images,
                value: postcards,
                set: setPostcards,
              },
              {
                name: "旅行人格报告",
                benefit: "至少 10 张照片",
                icon: FileText,
                value: report,
                set: setReport,
              },
            ].map((item) => (
              <button
                key={item.name}
                aria-pressed={item.value}
                disabled={generating}
                onClick={() => item.set(!item.value)}
              >
                <item.icon size={25} strokeWidth={1.4} />
                <span className="output-option-copy">
                  <strong>{item.name}</strong>
                  <small>{item.benefit}</small>
                </span>
                <span className="choice-check">
                  {item.value && <Check size={13} />}
                </span>
              </button>
            ))}
          </div>
          {report && photos.length < 10 ? <p className="memory-observation-note">还需添加 {10 - photos.length} 张照片，才能生成旅行人格报告。</p> : null}
        </section>
        {postcards && (
          <label className="postcard-count-choice">
            <span>明信片数量</span>
            <select
              value={postcardCount}
              disabled={generating}
              onChange={(event) => setPostcardCount(Number(event.target.value))}
            >
              {[1, 2, 3, 4, 5].map((count) => (
                <option key={count} value={count}>{count} 张</option>
              ))}
            </select>
          </label>
        )}
        <label className="create-prompt">
          <span className="section-caption">
            本次制作要求<span>选填</span>
          </span>
          <textarea
            disabled={generating}
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
            placeholder={entryMode === "report"
              ? "例如：重点整理建筑与街区照片"
              : "例如：明信片使用横版，不要裁掉人物"}
            rows={3}
          />
        </label>
        <p className="memory-observation-note">生成后会记录照片中的地点和场景，作为待你确认的旅行线索；可在旅行记忆页清除。</p>
        <label className="memory-consent">
          <input
            type="checkbox"
            checked={learnPreferences}
            disabled={generating}
            onChange={(event) => setLearnPreferences(event.target.checked)}
          />
          <span>
            <strong>保存我填写的旅行要求</strong>
            <small>勾选后，下方要求才会用于后续规划；明信片制作样式不会作为偏好。</small>
          </span>
        </label>
        {learnPreferences ? <label className="create-prompt">
          <span className="section-caption">旅行要求</span>
          <textarea
            disabled={generating}
            value={memoryRequirements}
            onChange={(event) => setMemoryRequirements(event.target.value)}
            placeholder="例如：住宿要安静，步行 10 分钟内到地铁"
            rows={2}
          />
        </label> : null}
        {generating && (
          <div className="generation-state" aria-live="polite">
            <ProgressLoader
              label={
                generationProgress?.phase === "uploading"
                  ? `上传照片 ${generationProgress.completed} / ${generationProgress.total}`
                  : generationProgress?.phase === "preparing"
                    ? "准备照片…"
                    : "正在生成…"
              }
            />
          </div>
        )}
      </div>
      <footer className="create-footer">
        <button
          className="primary-action"
          onClick={() => void generate()}
          disabled={generating || (!postcards && !report)}
        >
          {generating
            ? "正在生成…"
            : photos.length
              ? postcards && report
                ? "生成明信片和旅行人格报告"
                : postcards
                  ? "生成明信片"
                  : "生成旅行人格报告"
              : "选择照片"}
          {!generating &&
            (photos.length ? (
              <ArrowUpRight size={19} />
            ) : (
              <ImagePlus size={19} />
            ))}
        </button>
      </footer>
      <ConfirmDialog
        open={leaveOpen}
        title="离开上传页？"
        description="已选照片和输入内容将不会保留。"
        onClose={() => setLeaveOpen(false)}
        actions={[
          { label: "继续编辑", onClick: () => setLeaveOpen(false) },
          { label: "离开", variant: "ghost", onClick: () => goBackTo(backHref) },
        ]}
      />
    </div>
  );
}
