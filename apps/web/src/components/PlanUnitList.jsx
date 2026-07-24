export default function PlanUnitList({ units, selectedUnitId, onSelectUnit }) {
  if (!units.length) {
    return <p className="px-3 py-4 text-sm text-zinc-600">No units yet.</p>;
  }

  return (
    <nav className="flex flex-col gap-1 rounded border border-zinc-300 bg-white p-2">
      {units.map((unit) => {
        const unreviewedCount = unit.objectives.filter((o) => o.low_confidence && !o.reviewed).length;
        const isSelected = unit.id === selectedUnitId;
        return (
          <button
            key={unit.id}
            type="button"
            onClick={() => onSelectUnit(unit.id)}
            className={`flex items-center justify-between gap-2 rounded px-3 py-2 text-left text-sm transition ${
              isSelected ? "bg-teal-700 text-white" : "text-zinc-800 hover:bg-zinc-100"
            }`}
          >
            <span className="truncate">
              <span className="font-medium">{unit.order_index + 1}.</span> {unit.title}
            </span>
            <span className="flex shrink-0 items-center gap-1">
              <span
                className={`rounded-full px-1.5 py-0.5 text-xs ${
                  isSelected ? "bg-teal-900/40 text-white" : "bg-zinc-100 text-zinc-600"
                }`}
              >
                {unit.objectives.length}
              </span>
              {unreviewedCount > 0 ? (
                <span
                  title={`${unreviewedCount} low-confidence objective(s) awaiting review`}
                  className="rounded-full bg-amber-200 px-1.5 py-0.5 text-xs font-semibold text-amber-900"
                >
                  {unreviewedCount}
                </span>
              ) : null}
            </span>
          </button>
        );
      })}
    </nav>
  );
}
