const statLabels = {
  fileName: "File name",
  fileSize: "File size",
  conversionTime: "Conversion time",
  extractorMode: "Extractor",
  extractionCacheStatus: "Extraction cache",
  markdownCharacters: "Markdown chars",
  chunkCount: "Chunks",
  renderedPageCount: "Rendered pages",
  keptImageCount: "Kept slide images",
  visualDescriptionCount: "Visual descriptions",
  cacheHits: "Vision cache hits",
  cacheMisses: "New vision calls",
  visualFailures: "Visual failures",
  imageCount: "Figures",
  tableCount: "Tables",
};

export default function StatsPanel({ stats, markdownSourcePath }) {
  return (
    <section className="rounded border border-zinc-300 bg-white">
      <div className="border-b border-zinc-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-950">Extraction Stats</h2>
      </div>
      <dl className="grid gap-2 px-4 py-3 text-sm">
        {Object.entries(stats).map(([key, value]) => (
          <div key={key} className="grid grid-cols-[140px_1fr] gap-3">
            <dt className="text-zinc-500">{statLabels[key]}</dt>
            <dd className="min-w-0 break-words font-medium text-zinc-900">
              {key === "extractionCacheStatus" ? (
                <span
                  className={`rounded px-2 py-0.5 text-xs font-semibold ${
                    value === "hit"
                      ? "bg-emerald-100 text-emerald-800"
                      : value === "miss"
                        ? "bg-zinc-100 text-zinc-600"
                        : "text-zinc-400"
                  }`}
                >
                  {value === "hit" ? "✓ OCR skipped" : value === "miss" ? "full OCR run" : value}
                </span>
              ) : typeof value === "number" ? (
                value.toLocaleString()
              ) : (
                value
              )}
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
