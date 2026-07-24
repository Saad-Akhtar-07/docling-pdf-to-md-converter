import { useEffect, useRef, useState } from "react";
import DocumentBlocksViewer from "../components/DocumentBlocksViewer.jsx";
import FileUploader from "../components/FileUploader.jsx";
import { buildPlan, getDocument, getDocumentBlocks, getPlan, uploadDocument } from "../api/client.ts";

const STATUS_STYLES = {
  uploaded: "bg-sky-100 text-sky-800 border-sky-300",
  extracting: "bg-amber-100 text-amber-800 border-amber-300",
  ready: "bg-emerald-100 text-emerald-800 border-emerald-300",
  failed: "bg-red-100 text-red-800 border-red-300",
};

const POLL_INTERVAL_MS = 1500;
const PLAN_POLL_INTERVAL_MS = 2000;
const IN_PROGRESS_STATUSES = new Set(["uploaded", "extracting"]);

// Mirrors apps/api/jobs/plan_build.py::is_incomplete -- same "still
// mid-build" signal, computed client-side so the progress panel can tell
// the user what's still missing instead of just spinning.
function planProgress(plan) {
  const units = plan?.units ?? [];
  const objectives = units.flatMap((u) => u.objectives);
  const objectivesWithEvidence = objectives.filter(
    (o) => o.expected_ideas.length > 0 || o.misconceptions.length > 0,
  );
  const unitsWithObjectives = units.filter((u) => u.objectives.length > 0);
  return {
    unitCount: units.length,
    unitsWithObjectivesCount: unitsWithObjectives.length,
    objectiveCount: objectives.length,
    objectivesWithEvidenceCount: objectivesWithEvidence.length,
    isIncomplete:
      units.length === 0 ||
      unitsWithObjectives.length < units.length ||
      objectivesWithEvidence.length < objectives.length,
    canReview: objectives.length > 0,
  };
}

export default function DocumentsPage({ onNavigateToReview }) {
  const [file, setFile] = useState(null);
  const [document, setDocument] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState("");
  const pollTimeoutRef = useRef(null);

  const [plan, setPlan] = useState(null);
  const [isBuildingPlan, setIsBuildingPlan] = useState(false);
  const [planError, setPlanError] = useState("");
  const planPollTimeoutRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollTimeoutRef.current) window.clearTimeout(pollTimeoutRef.current);
      if (planPollTimeoutRef.current) window.clearTimeout(planPollTimeoutRef.current);
    };
  }, []);

  function schedulePlanPoll(planId) {
    planPollTimeoutRef.current = window.setTimeout(async () => {
      try {
        const latest = await getPlan(planId);
        setPlan(latest);
        if (planProgress(latest).isIncomplete) {
          schedulePlanPoll(planId);
        }
      } catch (pollError) {
        setPlanError(pollError.message);
      }
    }, PLAN_POLL_INTERVAL_MS);
  }

  async function handleBuildPlan() {
    if (!document) return;
    setPlanError("");
    setIsBuildingPlan(true);
    try {
      const response = await buildPlan(document.id);
      const latest = await getPlan(response.plan_id);
      setPlan(latest);
      if (planProgress(latest).isIncomplete) {
        schedulePlanPoll(response.plan_id);
      }
    } catch (buildError) {
      setPlanError(buildError.message);
    } finally {
      setIsBuildingPlan(false);
    }
  }

  function schedulePoll(documentId) {
    pollTimeoutRef.current = window.setTimeout(async () => {
      try {
        const latest = await getDocument(documentId);
        setDocument(latest);
        if (IN_PROGRESS_STATUSES.has(latest.status)) {
          schedulePoll(documentId);
        } else if (latest.status === "ready") {
          const blocksResponse = await getDocumentBlocks(documentId);
          setBlocks(blocksResponse.blocks);
        }
      } catch (pollError) {
        setError(pollError.message);
      }
    }, POLL_INTERVAL_MS);
  }

  async function handleUpload() {
    if (!file) {
      setError("Choose a PDF, PPT, PPTX, or ODP file first.");
      return;
    }

    setError("");
    setBlocks([]);
    setDocument(null);
    setIsUploading(true);
    if (planPollTimeoutRef.current) window.clearTimeout(planPollTimeoutRef.current);
    setPlan(null);
    setPlanError("");

    try {
      const created = await uploadDocument(file);
      const detail = await getDocument(created.document_id);
      setDocument(detail);
      if (IN_PROGRESS_STATUSES.has(detail.status)) {
        schedulePoll(created.document_id);
      } else if (detail.status === "ready") {
        const blocksResponse = await getDocumentBlocks(created.document_id);
        setBlocks(blocksResponse.blocks);
      }
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(300px,380px)_1fr]">
      <div className="flex flex-col gap-5">
        <FileUploader file={file} onFileChange={setFile} />

        <button
          type="button"
          onClick={handleUpload}
          disabled={isUploading}
          className="inline-flex h-11 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
        >
          {isUploading ? "Uploading..." : "Upload Document"}
        </button>

        {error ? (
          <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        ) : null}

        {document ? (
          <section className="rounded border border-zinc-300 bg-white">
            <div className="border-b border-zinc-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-zinc-950">Document</h2>
            </div>
            <div className="grid gap-2 px-4 py-3 text-sm text-zinc-700">
              <div className="flex items-center justify-between">
                <span className="font-medium text-zinc-950">{document.title}</span>
                <span
                  className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${
                    STATUS_STYLES[document.status] || "bg-zinc-100 text-zinc-700 border-zinc-300"
                  }`}
                >
                  {document.status}
                </span>
              </div>
              <p className="break-all font-mono text-xs text-zinc-500">{document.id}</p>
              {document.error ? (
                <p className="rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-800">
                  {document.error}
                </p>
              ) : null}
            </div>
          </section>
        ) : null}

        {document?.status === "ready" ? (
          <section className="rounded border border-zinc-300 bg-white">
            <div className="border-b border-zinc-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-zinc-950">Learning Plan</h2>
            </div>
            <div className="grid gap-3 px-4 py-3 text-sm text-zinc-700">
              {!plan ? (
                <>
                  <p className="text-zinc-600">
                    Extraction is done. Build a learning plan from this document to continue.
                  </p>
                  <button
                    type="button"
                    onClick={handleBuildPlan}
                    disabled={isBuildingPlan}
                    className="inline-flex h-11 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
                  >
                    {isBuildingPlan ? "Starting..." : "Build Learning Plan"}
                  </button>
                </>
              ) : (
                (() => {
                  const progress = planProgress(plan);
                  return (
                    <>
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-zinc-950">Plan v{plan.version}</span>
                        <span
                          className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-medium ${
                            progress.isIncomplete
                              ? "border-amber-300 bg-amber-100 text-amber-800"
                              : "border-emerald-300 bg-emerald-100 text-emerald-800"
                          }`}
                        >
                          {progress.isIncomplete ? (
                            <span
                              className="h-2 w-2 animate-pulse rounded-full bg-amber-500"
                              aria-hidden="true"
                            />
                          ) : null}
                          {progress.isIncomplete ? "Building..." : "Ready to review"}
                        </span>
                      </div>
                      <ul className="grid gap-1 text-xs text-zinc-600">
                        <li>
                          Units: {progress.unitsWithObjectivesCount}/{progress.unitCount || "?"} with objectives
                        </li>
                        <li>
                          Objectives: {progress.objectivesWithEvidenceCount}/{progress.objectiveCount} with evidence
                        </li>
                      </ul>
                      {progress.isIncomplete ? (
                        <p className="text-xs text-zinc-500">
                          This can take a few minutes for a full deck. You can continue to review as soon as
                          objectives exist below — evidence for the rest keeps building in the background.
                        </p>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => onNavigateToReview?.(plan.id)}
                        disabled={!progress.canReview}
                        className="inline-flex h-11 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
                      >
                        {progress.canReview ? "Continue to Review →" : "Waiting for the first objectives..."}
                      </button>
                    </>
                  );
                })()
              )}
              {planError ? (
                <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800">
                  {planError}
                </div>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>

      <div className="min-w-0">
        <DocumentBlocksViewer blocks={blocks} />
      </div>
    </div>
  );
}
