import { useMemo, useState } from "react";

export default function RawJsonViewer({ data }) {
  const [isOpen, setIsOpen] = useState(true);

  const formattedJson = useMemo(() => {
    if (!data) return "";
    return JSON.stringify(data, null, 2);
  }, [data]);

  return (
    <section className="rounded border border-zinc-300 bg-white">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 text-left"
      >
        <span>
          <span className="block text-sm font-semibold text-zinc-950">Raw JSON Response</span>
          <span className="text-xs text-zinc-500">
            {data ? `${formattedJson.length.toLocaleString()} characters` : "No response yet"}
          </span>
        </span>
        <span className="text-sm font-medium text-teal-700">{isOpen ? "Hide" : "Show"}</span>
      </button>
      {isOpen ? (
        <pre className="max-h-[520px] overflow-auto rounded-b bg-zinc-950 p-4 font-mono text-xs leading-5 text-zinc-100">
          {formattedJson || "Raw JSON will appear here after conversion."}
        </pre>
      ) : null}
    </section>
  );
}
