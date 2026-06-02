const statLabels = {
  fileName: "File name",
  fileSize: "File size",
  conversionTime: "Conversion time",
  markdownCharacters: "Markdown chars",
  chunkCount: "Chunks",
  imageCount: "Images/Figures",
  tableCount: "Tables",
};

export default function StatsPanel({ stats, markdownSourcePath }) {
  return (
    <section className="rounded border border-zinc-300 bg-white">
      <div className="border-b border-zinc-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-950">Conversion Stats</h2>
      </div>
      <dl className="grid gap-2 px-4 py-3 text-sm">
        {Object.entries(stats).map(([key, value]) => (
          <div key={key} className="grid grid-cols-[120px_1fr] gap-3">
            <dt className="text-zinc-500">{statLabels[key]}</dt>
            <dd className="min-w-0 break-words font-medium text-zinc-900">
              {typeof value === "number" ? value.toLocaleString() : value}
            </dd>
          </div>
        ))}
      </dl>
      {markdownSourcePath ? (
        <div className="border-t border-zinc-200 px-4 py-3">
          <p className="text-xs text-zinc-500">Markdown source</p>
          <code className="mt-1 block break-all rounded bg-zinc-100 px-2 py-1 font-mono text-xs text-zinc-700">
            {markdownSourcePath}
          </code>
        </div>
      ) : null}
    </section>
  );
}
