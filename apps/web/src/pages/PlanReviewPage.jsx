import { useEffect, useMemo, useState } from "react";
import ObjectiveEditor from "../components/ObjectiveEditor.jsx";
import PlanUnitList from "../components/PlanUnitList.jsx";
import SourcePanel from "../components/SourcePanel.jsx";
import { approvePlan, deleteObjective, getDocumentBlocks, getPlan, updateObjective } from "../api/client.ts";

function toIdeaIn(idea) {
  return { id: idea.id, idea: idea.idea, block_id: idea.block_id, char_start: idea.char_start, char_end: idea.char_end };
}

export default function PlanReviewPage({ planId }) {
  const [plan, setPlan] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [selectedUnitId, setSelectedUnitId] = useState(null);
  const [selectedObjectiveId, setSelectedObjectiveId] = useState(null);
  const [armedIdeaId, setArmedIdeaId] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isApproving, setIsApproving] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setIsLoading(true);
      setError("");
      try {
        const latest = await getPlan(planId);
        if (cancelled) return;
        setPlan(latest);
        if (latest.units.length) setSelectedUnitId(latest.units[0].id);
        const blocksResponse = await getDocumentBlocks(latest.document_id);
        if (!cancelled) setBlocks(blocksResponse.blocks);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [planId]);

  async function reload() {
    const latest = await getPlan(planId);
    setPlan(latest);
    return latest;
  }

  // Mirrors apps/api/jobs/plan_build.py::is_incomplete -- the build job
  // persists incrementally, so a reviewer can land here while it's still
  // running in the background (apps/web/src/pages/DocumentsPage.jsx lets
  // them move on as soon as the first objectives exist).
  const isBuildIncomplete = plan
    ? plan.units.length === 0 ||
      plan.units.some(
        (u) =>
          u.objectives.length === 0 ||
          u.objectives.some((o) => o.expected_ideas.length === 0 && o.misconceptions.length === 0),
      )
    : false;

  const readOnly = plan ? plan.status !== "draft" : true;
  const selectedUnit = plan?.units.find((u) => u.id === selectedUnitId) ?? null;
  const selectedObjective = selectedUnit?.objectives.find((o) => o.id === selectedObjectiveId) ?? null;

  const allObjectives = plan ? plan.units.flatMap((u) => u.objectives) : [];
  const unreviewedLowConfidence = allObjectives.filter((o) => o.low_confidence && !o.reviewed);
  const canApprove = plan?.status === "draft" && unreviewedLowConfidence.length === 0;

  const sortedObjectives = useMemo(() => {
    if (!selectedUnit) return [];
    return [...selectedUnit.objectives].sort((a, b) => {
      if (a.low_confidence !== b.low_confidence) return a.low_confidence ? -1 : 1;
      return a.order_index - b.order_index;
    });
  }, [selectedUnit]);

  const unitBlocks = useMemo(() => {
    if (!selectedUnit) return [];
    const slideSet = new Set(selectedUnit.slide_ids);
    return blocks
      .filter((b) => slideSet.has(b.slide_no))
      .sort((a, b) => a.slide_no - b.slide_no || a.order_index - b.order_index);
  }, [selectedUnit, blocks]);

  function selectUnit(unitId) {
    setSelectedUnitId(unitId);
    setSelectedObjectiveId(null);
    setArmedIdeaId(null);
  }

  function selectObjective(objectiveId) {
    setSelectedObjectiveId(objectiveId);
    setArmedIdeaId(null);
  }

  async function withErrorHandling(action) {
    try {
      await action();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleSaveStatement(objectiveId, statement) {
    await withErrorHandling(async () => {
      await updateObjective(objectiveId, { statement });
      await reload();
    });
  }

  async function handleToggleReviewed(objectiveId, reviewed) {
    await withErrorHandling(async () => {
      await updateObjective(objectiveId, { reviewed });
      await reload();
    });
  }

  async function handleDeleteIdea(objective, ideaId) {
    await withErrorHandling(async () => {
      const remaining = objective.expected_ideas.filter((idea) => idea.id !== ideaId).map(toIdeaIn);
      await updateObjective(objective.id, { expected_ideas: remaining });
      if (armedIdeaId === ideaId) setArmedIdeaId(null);
      await reload();
    });
  }

  function handleArmReanchor(objectiveId, ideaId) {
    setSelectedObjectiveId(objectiveId);
    setArmedIdeaId((current) => (current === ideaId ? null : ideaId));
  }

  async function handleReanchorIdea(objective, ideaId, selection) {
    await withErrorHandling(async () => {
      const updated = objective.expected_ideas.map((idea) =>
        idea.id === ideaId
          ? { id: idea.id, idea: idea.idea, block_id: selection.blockId, char_start: selection.start, char_end: selection.end }
          : toIdeaIn(idea),
      );
      await updateObjective(objective.id, { expected_ideas: updated });
      setArmedIdeaId(null);
      await reload();
    });
  }

  async function handleAddIdea(objective, selection, ideaText) {
    await withErrorHandling(async () => {
      const updated = [
        ...objective.expected_ideas.map(toIdeaIn),
        { idea: ideaText, block_id: selection.blockId, char_start: selection.start, char_end: selection.end },
      ];
      await updateObjective(objective.id, { expected_ideas: updated });
      await reload();
    });
  }

  async function handleDeleteObjective(objectiveId) {
    await withErrorHandling(async () => {
      await deleteObjective(objectiveId);
      if (selectedObjectiveId === objectiveId) {
        setSelectedObjectiveId(null);
        setArmedIdeaId(null);
      }
      await reload();
    });
  }

  async function handleRefresh() {
    setIsRefreshing(true);
    await withErrorHandling(async () => {
      await reload();
    });
    setIsRefreshing(false);
  }

  async function handleApprove() {
    setIsApproving(true);
    await withErrorHandling(async () => {
      const approved = await approvePlan(planId);
      setPlan(approved);
    });
    setIsApproving(false);
  }

  if (isLoading) {
    return <p className="px-4 py-6 text-sm text-zinc-600">Loading plan…</p>;
  }

  if (!plan) {
    return (
      <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
        {error || "Plan not found."}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-zinc-300 bg-white px-4 py-3">
        <div>
          <p className="text-sm text-zinc-600">
            Plan v{plan.version} · {plan.units.length} units · {allObjectives.length} objectives
          </p>
          <p
            className={`text-xs font-semibold uppercase tracking-wide ${
              plan.status === "approved" ? "text-emerald-700" : "text-amber-700"
            }`}
          >
            {plan.status}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {unreviewedLowConfidence.length > 0 ? (
            <span className="text-xs text-amber-800">
              {unreviewedLowConfidence.length} low-confidence objective(s) still need review
            </span>
          ) : null}
          {isBuildIncomplete ? (
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="inline-flex h-10 items-center justify-center rounded border border-zinc-300 bg-white px-3 text-sm font-medium text-zinc-700 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
            >
              {isRefreshing ? "Refreshing…" : "Refresh"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={handleApprove}
            disabled={!canApprove || isApproving}
            className="inline-flex h-10 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          >
            {plan.status === "approved" ? "Approved" : isApproving ? "Approving…" : "Approve plan"}
          </button>
        </div>
      </div>

      {isBuildIncomplete ? (
        <div className="flex items-center gap-2 rounded border border-amber-300 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          <span className="h-2 w-2 animate-pulse rounded-full bg-amber-500" aria-hidden="true" />
          This plan is still being built in the background (some units/objectives/evidence are not in yet).
          Click Refresh to pull in anything new.
        </div>
      ) : null}

      {error ? (
        <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[220px_1fr_1fr]">
        <PlanUnitList units={plan.units} selectedUnitId={selectedUnitId} onSelectUnit={selectUnit} />

        <div className="flex flex-col gap-3">
          {sortedObjectives.map((objective) => (
            <ObjectiveEditor
              key={objective.id}
              objective={objective}
              readOnly={readOnly}
              isFocused={objective.id === selectedObjectiveId}
              armedIdeaId={objective.id === selectedObjectiveId ? armedIdeaId : null}
              onSelect={() => selectObjective(objective.id)}
              onSaveStatement={(statement) => handleSaveStatement(objective.id, statement)}
              onToggleReviewed={(reviewed) => handleToggleReviewed(objective.id, reviewed)}
              onDeleteIdea={(ideaId) => handleDeleteIdea(objective, ideaId)}
              onArmReanchor={(ideaId) => handleArmReanchor(objective.id, ideaId)}
              onDeleteObjective={() => handleDeleteObjective(objective.id)}
            />
          ))}
          {!sortedObjectives.length ? (
            <p className="rounded border border-zinc-300 bg-white px-4 py-5 text-sm text-zinc-600">
              This unit has no objectives.
            </p>
          ) : null}
        </div>

        <SourcePanel
          blocks={unitBlocks}
          objective={selectedObjective}
          armedIdeaId={armedIdeaId}
          readOnly={readOnly}
          onReanchorIdea={(ideaId, selection) => handleReanchorIdea(selectedObjective, ideaId, selection)}
          onAddIdea={(selection, ideaText) => handleAddIdea(selectedObjective, selection, ideaText)}
        />
      </div>
    </div>
  );
}
