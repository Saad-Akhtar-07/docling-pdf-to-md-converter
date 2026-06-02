export default function MarkdownViewer({
  markdown,
  isLoading,
  copyState,
  onCopy,
  onDownload,
  title = "Markdown Output",
}) {
  const hasMarkdown = Boolean(markdown);

  return (
    <section className="rounded border border-zinc-300 bg-white">
      <div className="flex flex-col gap-3 border-b border-zinc-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-zinc-950">{title}</h2>
          <p className="text-xs text-zinc-500">{markdown.length.toLocaleString()} characters</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onCopy}
            disabled={!hasMarkdown}
            className="h-9 rounded border border-zinc-300 px-3 text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 disabled:cursor-not-allowed disabled:text-zinc-400"
          >
            {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy Markdown"}
          </button>
          <button
            type="button"
            onClick={onDownload}
            disabled={!hasMarkdown}
            className="h-9 rounded bg-zinc-950 px-3 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          >
            Download .md
          </button>
        </div>
      </div>
      <textarea
        value={isLoading ? "Conversion running..." : markdown}
        readOnly
        spellCheck="false"
        className="min-h-[420px] w-full resize-y rounded-b bg-white p-4 font-mono text-sm leading-6 text-zinc-900 outline-none"
        placeholder="Markdown will appear here after conversion."
      />
    </section>
  );
}
