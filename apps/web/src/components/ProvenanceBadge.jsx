const PROVENANCE_STYLES = {
  verbatim: "bg-emerald-100 text-emerald-800 border-emerald-300",
  ocr: "bg-amber-100 text-amber-800 border-amber-300",
  model_generated: "bg-purple-100 text-purple-800 border-purple-300",
};

const PROVENANCE_LABELS = {
  verbatim: "verbatim",
  ocr: "ocr",
  model_generated: "model generated",
};

export default function ProvenanceBadge({ provenance }) {
  const style = PROVENANCE_STYLES[provenance] || "bg-zinc-100 text-zinc-700 border-zinc-300";
  const label = PROVENANCE_LABELS[provenance] || provenance;

  return (
    <span
      className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${style}`}
    >
      {label}
    </span>
  );
}
