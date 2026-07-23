import { useMemo, useState } from "react";

export default function ChunksViewer({ chunks }) {
  const [isOpen, setIsOpen] = useState(true);

  const formattedChunks = useMemo(() => JSON.stringify(chunks || [], null, 2), [chunks]);

  return (
    <section className="rounded border border-zinc-300 bg-white">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 text-left"
      >
        <span>
          <span className="block text-sm font-semibold text-zinc-950">Chunks With Page Metadata</span>
          <span className="text-xs text-zinc-500">{(chunks || []).length.toLocaleString()} chunks</span>
        </span>
        <span className="text-sm font-medium text-teal-700">{isOpen ? "Hide" : "Show"}</span>
      </button>
      {isOpen ? (
        <pre className="max-h-[420px] overflow-auto rounded-b bg-zinc-950 p-4 font-mono text-xs leading-5 text-zinc-100">
          {formattedChunks}
        </pre>
      ) : null}
    </section>
  );
}
