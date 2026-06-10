import { useMemo, useState } from "react";
import ChunksViewer from "./components/ChunksViewer.jsx";
import FileUploader from "./components/FileUploader.jsx";
import ImageDebugPanel from "./components/ImageDebugPanel.jsx";
import MarkdownViewer from "./components/MarkdownViewer.jsx";
import RawJsonViewer from "./components/RawJsonViewer.jsx";
import StatsPanel from "./components/StatsPanel.jsx";
import { DEFAULT_DOCLING_BASE_URL, convertPdfWithDocling } from "./utils/doclingApi.js";
import { DEFAULT_GOTENBERG_BASE_URL, convertPptToPdf } from "./utils/pptApi.js";
import {
  appendKeptImagesToMarkdown,
  extractEmbeddedImages,
} from "./utils/imagePipeline.js";
import { buildStructuredPageOutput } from "./utils/responseParser.js";

function formatFileSize(bytes) {
  if (!bytes) return "0 B";

  const units = ["B", "KB", "MB", "GB"];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** unitIndex;

  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function downloadMarkdown(markdown, fileName) {
  const baseName = fileName?.replace(/\.(pdf|pptx?)$/i, "") || "slidevision-output";
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
  const [markdown, setMarkdown] = useState("");
  const [rawResponse, setRawResponse] = useState(null);
  const [markdownSourcePath, setMarkdownSourcePath] = useState("");
  const [chunks, setChunks] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [figures, setFigures] = useState([]);
  const [debugImages, setDebugImages] = useState([]);
  const [imageDecisions, setImageDecisions] = useState([]);
  const [tableCount, setTableCount] = useState(0);
  const [conversionTimeMs, setConversionTimeMs] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [conversionStage, setConversionStage] = useState("");
  const [copyState, setCopyState] = useState("idle");

  const finalMarkdown = useMemo(
    () => appendKeptImagesToMarkdown(markdown, imageDecisions),
    [imageDecisions, markdown],
  );
  const visionCandidateCount = useMemo(
    () => imageDecisions.filter((decision) => decision.isKept).length,
    [imageDecisions],
  );

  const stats = useMemo(
    () => ({
      fileName: file?.name || "-",
      fileSize: file ? formatFileSize(file.size) : "-",
      conversionTime:
        typeof conversionTimeMs === "number" ? `${(conversionTimeMs / 1000).toFixed(2)} s` : "-",
      markdownCharacters: finalMarkdown.length,
      chunkCount: chunks.length,
      imageCount: figures.length,
      visionCandidateCount,
      tableCount,
    }),
    [
      chunks.length,
      conversionTimeMs,
      figures.length,
      file,
      finalMarkdown.length,
      tableCount,
      visionCandidateCount,
    ],
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
    setDebugImages([]);
    setImageDecisions([]);
    setTableCount(0);
    setConversionTimeMs(null);
    setConversionStage("");
  }

  async function handleConvert() {
    setError("");
    setCopyState("idle");
    setConversionStage("");

    if (!file) {
      setError("Select a file before converting.");
      return;
    }

    const lower = file.name.toLowerCase();
    const isPdf = file.type === "application/pdf" || lower.endsWith(".pdf");
    const isPpt =
      lower.endsWith(".ppt") ||
      lower.endsWith(".pptx") ||
      file.type === "application/vnd.ms-powerpoint" ||
      file.type === "application/vnd.openxmlformats-officedocument.presentationml.presentation";

    if (!isPdf && !isPpt) {
      setError("Only PDF or PowerPoint files are supported.");
      return;
    }

    setIsLoading(true);
    const startedAt = performance.now();

    try {
      setConversionStage(isPpt ? "Converting PowerPoint to PDF..." : "Sending PDF to Docling...");
      const pdfFile = isPpt ? await convertPptToPdf({ file }) : file;
      setConversionStage("Extracting Markdown with Docling...");
      const response = await convertPdfWithDocling({
        file: pdfFile,
        baseUrl: DEFAULT_DOCLING_BASE_URL,
      });

      const elapsed = performance.now() - startedAt;
      const structuredOutput = buildStructuredPageOutput(response, file.name);
      const normalizedFigures = prepareFigureSummariesForFutureVision(structuredOutput.figures);
      const embeddedImages = extractEmbeddedImages(response);

      setRawResponse(response);
      setMarkdown(structuredOutput.markdown);
      setMarkdownSourcePath(structuredOutput.sourcePath);
      setChunks(structuredOutput.chunks);
      setWarnings(structuredOutput.warnings);
      setFigures(normalizedFigures);
      setDebugImages(embeddedImages);
      setImageDecisions([]);
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
      setConversionStage("");
    }
  }

  async function handleCopyMarkdown() {
    if (!finalMarkdown) return;

    try {
      await navigator.clipboard.writeText(finalMarkdown);
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
            <p className="text-sm font-medium text-teal-700">SlideVision pipeline</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-zinc-950">
              SlideVision Markdown Extractor
            </h1>
          </div>
          <div className="rounded border border-zinc-300 bg-white px-3 py-2 font-mono text-xs text-zinc-700">
            {DEFAULT_DOCLING_BASE_URL}/v1/convert/file
            <br />
            {DEFAULT_GOTENBERG_BASE_URL}/forms/libreoffice/convert
          </div>
        </header>

        <section className="grid gap-5 lg:grid-cols-[minmax(300px,380px)_1fr]">
          <div className="flex flex-col gap-5">
            <FileUploader file={file} onFileChange={handleFileChange} />
            <button
              type="button"
              onClick={handleConvert}
              disabled={isLoading}
              className="inline-flex h-11 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            >
              {isLoading ? "Extracting..." : "Extract Slides"}
            </button>
            {conversionStage ? (
              <div className="rounded border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
                {conversionStage}
              </div>
            ) : null}
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
              markdown={finalMarkdown}
              isLoading={isLoading}
              copyState={copyState}
              onCopy={handleCopyMarkdown}
              onDownload={() => downloadMarkdown(finalMarkdown, file?.name)}
              title="Slide-Aware Markdown"
            />

            <section className="rounded border border-zinc-300 bg-white">
              <div className="border-b border-zinc-200 px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-950">Docling Figure References</h2>
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

            <ImageDebugPanel
              images={debugImages}
              onDecisionsChange={setImageDecisions}
            />

            <ChunksViewer chunks={chunks} />
            <RawJsonViewer data={rawResponse} />
          </div>
        </section>
      </div>
    </main>
  );
}
