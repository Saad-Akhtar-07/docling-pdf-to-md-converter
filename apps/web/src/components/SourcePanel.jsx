import { useEffect, useState } from "react";
import { getSelectionOffsetsWithin } from "../utils/textSelection.js";

function renderHighlighted(text, spans) {
  if (!spans.length) return text;
  const sorted = [...spans].sort((a, b) => a.char_start - b.char_start);
  const nodes = [];
  let cursor = 0;
  for (const span of sorted) {
    const start = Math.max(span.char_start, cursor);
    if (start >= text.length || start < cursor) continue;
    const end = Math.min(Math.max(span.char_end, start), text.length);
    if (start > cursor) nodes.push(text.slice(cursor, start));
    nodes.push(
      <mark
        key={span.key}
        className={span.active ? "rounded bg-amber-300 px-0.5 ring-2 ring-amber-600" : "rounded bg-amber-100 px-0.5"}
      >
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

export default function SourcePanel({ blocks, objective, armedIdeaId, readOnly, onReanchorIdea, onAddIdea }) {
  const [pendingSelection, setPendingSelection] = useState(null);
  const [newIdeaText, setNewIdeaText] = useState("");

  useEffect(() => {
    setNewIdeaText(pendingSelection?.text ?? "");
  }, [pendingSelection]);

  function handleMouseUp(blockId, event) {
    if (readOnly) return;
    const offsets = getSelectionOffsetsWithin(event.currentTarget);
    setPendingSelection(offsets ? { blockId, ...offsets } : null);
  }

  function clearSelection() {
    setPendingSelection(null);
    window.getSelection()?.removeAllRanges();
  }

  if (!blocks.length) {
    return <p className="px-4 py-5 text-sm text-zinc-600">No source slides loaded for this unit.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      {pendingSelection ? (
        <div className="sticky top-0 z-10 flex flex-col gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm">
          <span className="truncate text-amber-900">Selected: &ldquo;{pendingSelection.text}&rdquo;</span>
          <div className="flex flex-wrap items-center gap-2">
            {armedIdeaId ? (
              <button
                type="button"
                onClick={() => {
                  onReanchorIdea(armedIdeaId, pendingSelection);
                  clearSelection();
                }}
                className="rounded bg-teal-700 px-2 py-1 text-xs font-semibold text-white hover:bg-teal-800"
              >
                Set as anchor for selected idea
              </button>
            ) : null}
            {objective ? (
              <>
                <input
                  type="text"
                  value={newIdeaText}
                  onChange={(e) => setNewIdeaText(e.target.value)}
                  placeholder="New idea's short statement..."
                  className="min-w-[10rem] flex-1 rounded border border-zinc-300 px-2 py-1 text-xs"
                />
                <button
                  type="button"
                  disabled={!newIdeaText.trim()}
                  onClick={() => {
                    onAddIdea(pendingSelection, newIdeaText.trim());
                    clearSelection();
                  }}
                  className="rounded bg-teal-700 px-2 py-1 text-xs font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
                >
                  Add as new idea
                </button>
              </>
            ) : null}
            <button
              type="button"
              onClick={clearSelection}
              className="rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-700 hover:bg-white"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {blocks.map((block) => {
        const spans = (objective?.expected_ideas ?? [])
          .filter((idea) => idea.block_id === block.id)
          .map((idea) => ({
            key: idea.id,
            char_start: idea.char_start,
            char_end: idea.char_end,
            active: idea.id === armedIdeaId,
          }));
        return (
          <section key={block.id} className="rounded border border-zinc-300 bg-white">
            <div className="border-b border-zinc-200 px-4 py-2">
              <h3 className="text-sm font-semibold text-zinc-950">Slide {block.slide_no}</h3>
            </div>
            <p
              className="select-text whitespace-pre-wrap px-4 py-3 text-sm text-zinc-800"
              onMouseUp={(event) => handleMouseUp(block.id, event)}
            >
              {renderHighlighted(block.text, spans)}
            </p>
          </section>
        );
      })}
    </div>
  );
}
