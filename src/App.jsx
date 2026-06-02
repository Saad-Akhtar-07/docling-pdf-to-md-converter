import { useMemo, useState } from "react";
import ChunksViewer from "./components/ChunksViewer.jsx";
import ConversionOptions from "./components/ConversionOptions.jsx";
import FileUploader from "./components/FileUploader.jsx";
import MarkdownViewer from "./components/MarkdownViewer.jsx";
import RawJsonViewer from "./components/RawJsonViewer.jsx";
import StatsPanel from "./components/StatsPanel.jsx";
import { DEFAULT_DOCLING_BASE_URL, convertPdfWithDocling } from "./utils/doclingApi.js";
import { buildStructuredPageOutput } from "./utils/responseParser.js";

const DEFAULT_OPTIONS = {
  doOcr: true,
  forceOcr: false,
  doTableStructure: true,
  tableMode: "accurate",
  outputFormat: "both",
  imageExportMode: "embedded",
};

function formatFileSize(bytes) {
  if (!bytes) return "0 B";

  const units = ["B", "KB", "MB", "GB"];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** unitIndex;

  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function downloadMarkdown(markdown, fileName) {
  const baseName = fileName?.replace(/\.pdf$/i, "") || "docling-output";
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = `${baseName}.md`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function prepareFigureSummariesForFutureVision(figures) {
  return figures.map((figure) => ({
    ...figure,
    // TODO: send extracted image to vision model
    // TODO: generate image summary
    // TODO: append image summary into final markdown
    imageSummary: "",
  }));
}

export default function App() {
  const [file, setFile] = useState(null);
  const [options, setOptions] = useState(DEFAULT_OPTIONS);
  const [markdown, setMarkdown] = useState("");
  const [rawResponse, setRawResponse] = useState(null);
  const [markdownSourcePath, setMarkdownSourcePath] = useState("");
  const [chunks, setChunks] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [figures, setFigures] = useState([]);
  const [tableCount, setTableCount] = useState(0);
  const [conversionTimeMs, setConversionTimeMs] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [copyState, setCopyState] = useState("idle");

  const stats = useMemo(
    () => ({
      fileName: file?.name || "-",
      fileSize: file ? formatFileSize(file.size) : "-",
      conversionTime:
        typeof conversionTimeMs === "number" ? `${(conversionTimeMs / 1000).toFixed(2)} s` : "-",
      markdownCharacters: markdown.length,
      chunkCount: chunks.length,
      imageCount: figures.length,
      tableCount,
    }),
    [chunks.length, conversionTimeMs, figures.length, file, markdown.length, tableCount],
  );

  function handleFileChange(nextFile) {
    setError("");
    setCopyState("idle");
    setFile(nextFile);
    setMarkdown("");
    setRawResponse(null);
    setMarkdownSourcePath("");
    setChunks([]);
    setWarnings([]);
    setFigures([]);
    setTableCount(0);
    setConversionTimeMs(null);
  }

  async function handleConvert() {
    setError("");
    setCopyState("idle");

    if (!file) {
      setError("Select a PDF file before converting.");
      return;
    }

    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are supported.");
      return;
    }

    setIsLoading(true);
    const startedAt = performance.now();

    try {
      const response = await convertPdfWithDocling({
        file,
        options,
        baseUrl: DEFAULT_DOCLING_BASE_URL,
      });

      const elapsed = performance.now() - startedAt;
      const structuredOutput = buildStructuredPageOutput(response, file.name);
      const normalizedFigures = prepareFigureSummariesForFutureVision(structuredOutput.figures);

      setRawResponse(response);
      setMarkdown(structuredOutput.markdown);
      setMarkdownSourcePath(structuredOutput.sourcePath);
      setChunks(structuredOutput.chunks);
      setWarnings(structuredOutput.warnings);
      setFigures(normalizedFigures);
      setTableCount(structuredOutput.tableCount);
      setConversionTimeMs(elapsed);

      if (!structuredOutput.markdown) {
        setError(
          "Docling responded successfully, but no page-aware content was extracted. Inspect the raw JSON below to update the parser.",
        );
      }
    } catch (requestError) {
      setError(requestError.message);
      setConversionTimeMs(performance.now() - startedAt);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCopyMarkdown() {
    if (!markdown) return;

    try {
      await navigator.clipboard.writeText(markdown);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1500);
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <main className="min-h-screen bg-zinc-100 text-zinc-950">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-3 border-b border-zinc-300 pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm font-medium text-teal-700">Docling Serve tester</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-zinc-950">
              PDF to Markdown Processor
            </h1>
          </div>
          <div className="rounded border border-zinc-300 bg-white px-3 py-2 font-mono text-xs text-zinc-700">
            {DEFAULT_DOCLING_BASE_URL}/v1/convert/file
          </div>
        </header>

        <section className="grid gap-5 lg:grid-cols-[minmax(300px,380px)_1fr]">
          <div className="flex flex-col gap-5">
            <FileUploader file={file} onFileChange={handleFileChange} />
            <ConversionOptions options={options} onChange={setOptions} disabled={isLoading} />
            <button
              type="button"
              onClick={handleConvert}
              disabled={isLoading}
              className="inline-flex h-11 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            >
              {isLoading ? "Converting..." : "Convert PDF"}
            </button>
            {error ? (
              <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
                {error}
              </div>
            ) : null}
            {warnings.length ? (
              <div className="rounded border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                {warnings.map((warning) => (
                  <p key={warning}>{warning}</p>
                ))}
              </div>
            ) : null}
            <StatsPanel stats={stats} markdownSourcePath={markdownSourcePath} />
          </div>

          <div className="flex min-w-0 flex-col gap-5">
            <MarkdownViewer
              markdown={markdown}
              isLoading={isLoading}
              copyState={copyState}
              onCopy={handleCopyMarkdown}
              onDownload={() => downloadMarkdown(markdown, file?.name)}
              title="Page-Aware Markdown"
            />

            <section className="rounded border border-zinc-300 bg-white">
              <div className="border-b border-zinc-200 px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-950">Images and Figures</h2>
              </div>
              {figures.length ? (
                <div className="divide-y divide-zinc-200">
                  {figures.map((figure, index) => (
                    <article key={`${figure.id}-${index}`} className="grid gap-2 px-4 py-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-zinc-950">
                          {figure.type || "figure"} {index + 1}
                        </span>
                        {figure.pageNumber ? (
                          <span className="rounded bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-800">
                            page {figure.pageNumber}
                          </span>
                        ) : null}
                      </div>
                      {figure.caption ? <p className="text-zinc-700">{figure.caption}</p> : null}
                      {figure.reference ? (
                        <code className="break-all rounded bg-zinc-100 px-2 py-1 font-mono text-xs text-zinc-700">
                          {String(figure.reference).slice(0, 360)}
                          {String(figure.reference).length > 360 ? "..." : ""}
                        </code>
                      ) : null}
                    </article>
                  ))}
                </div>
              ) : (
                <p className="px-4 py-5 text-sm text-zinc-600">No image or figure entries detected.</p>
              )}
            </section>

            <ChunksViewer chunks={chunks} />
            <RawJsonViewer data={rawResponse} />
          </div>
        </section>
      </div>
    </main>
  );
}
