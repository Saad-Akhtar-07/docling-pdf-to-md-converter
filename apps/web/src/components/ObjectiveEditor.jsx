import { useEffect, useState } from "react";

export default function ObjectiveEditor({
  objective,
  readOnly,
  isFocused,
  armedIdeaId,
  onSelect,
  onSaveStatement,
  onToggleReviewed,
  onDeleteIdea,
  onArmReanchor,
  onDeleteObjective,
}) {
  const [draftStatement, setDraftStatement] = useState(objective.statement);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  // Resyncs after a reload triggered by *this* save (harmless no-op) or by a
  // sibling edit elsewhere on the page (keeps this card's textarea from
  // going stale) -- component identity persists across reloads since
  // PlanReviewPage keys each card by objective.id.
  useEffect(() => {
    setDraftStatement(objective.statement);
  }, [objective.statement]);

  const statementDirty = draftStatement.trim() !== objective.statement && draftStatement.trim().length > 0;

  return (
    <article
      onClick={onSelect}
      className={`cursor-pointer rounded border bg-white p-4 transition ${
        isFocused ? "border-teal-600 ring-1 ring-teal-600" : "border-zinc-300"
      }`}
    >
      {objective.low_confidence ? (
        <div className="mb-2 flex items-center justify-between gap-2 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900">
          <span className="font-semibold">⚠ Low confidence — fewer than 2 anchored ideas</span>
          <label className="flex items-center gap-1.5 font-medium" onClick={(e) => e.stopPropagation()}>
            <input
              type="checkbox"
              checked={objective.reviewed}
              disabled={readOnly}
              onChange={(e) => onToggleReviewed(e.target.checked)}
            />
            Reviewed
          </label>
        </div>
      ) : null}

      <textarea
        className="w-full resize-none rounded border border-zinc-300 px-2 py-1.5 text-sm text-zinc-900 disabled:bg-zinc-50 disabled:text-zinc-500"
        rows={2}
        value={draftStatement}
        disabled={readOnly}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => setDraftStatement(e.target.value)}
        onBlur={() => {
          if (statementDirty) onSaveStatement(draftStatement.trim());
        }}
      />

      <ul className="mt-3 flex flex-col gap-1.5">
        {objective.expected_ideas.map((idea) => (
          <li
            key={idea.id}
            className={`flex items-center justify-between gap-2 rounded border px-2 py-1 text-xs ${
              armedIdeaId === idea.id ? "border-amber-400 bg-amber-50" : "border-zinc-200 bg-zinc-50"
            }`}
          >
            <span className="truncate text-zinc-700">{idea.idea}</span>
            {!readOnly ? (
              <span className="flex shrink-0 gap-1">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onArmReanchor(idea.id);
                  }}
                  className="rounded border border-zinc-300 px-1.5 py-0.5 text-zinc-700 hover:bg-white"
                >
                  {armedIdeaId === idea.id ? "Cancel re-anchor" : "Re-anchor"}
                </button>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteIdea(idea.id);
                  }}
                  className="rounded border border-red-300 px-1.5 py-0.5 text-red-700 hover:bg-red-50"
                >
                  Remove
                </button>
              </span>
            ) : null}
          </li>
        ))}
        {!objective.expected_ideas.length ? (
          <li className="text-xs italic text-zinc-500">No anchored ideas yet.</li>
        ) : null}
      </ul>

      {!readOnly ? (
        <div className="mt-3 flex justify-end">
          {confirmingDelete ? (
            <span className="flex items-center gap-2 text-xs" onClick={(e) => e.stopPropagation()}>
              <span className="text-zinc-600">Delete this objective?</span>
              <button
                type="button"
                onClick={onDeleteObjective}
                className="rounded bg-red-700 px-2 py-1 font-semibold text-white hover:bg-red-800"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setConfirmingDelete(false)}
                className="rounded border border-zinc-300 px-2 py-1 text-zinc-700 hover:bg-zinc-100"
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setConfirmingDelete(true);
              }}
              className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
            >
              Delete objective
            </button>
          )}
        </div>
      ) : null}
    </article>
  );
}
