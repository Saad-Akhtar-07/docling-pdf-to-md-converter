import { useMemo, useState } from "react";
import ChunksViewer from "./components/ChunksViewer.jsx";
import FileUploader from "./components/FileUploader.jsx";
import ImageDebugPanel from "./components/ImageDebugPanel.jsx";
import MarkdownViewer from "./components/MarkdownViewer.jsx";
import RawJsonViewer from "./components/RawJsonViewer.jsx";
import StatsPanel from "./components/StatsPanel.jsx";
import {
  DEFAULT_LOCAL_EXTRACTOR_BASE_URL,
  convertFileWithLocalExtractor,
} from "./utils/localExtractorApi.js";
import { appendVisualDescriptionsToMarkdown } from "./utils/imagePipeline.js";
import { describeVisualSlides } from "./utils/visualDescriptionApi.js";

const EXTRACTOR_LABEL = "Local PyMuPDF4LLM + RapidOCR";

function formatFileSize(bytes) {
  if (!bytes) return "0 B";

  const units = ["B", "KB", "MB", "GB"];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** unitIndex;

  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function downloadMarkdown(markdown, fileName) {
  const baseName = fileName?.replace(/\.(pdf|pptx?|odp)$/i, "") || "slidevision-output";
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
  const [visualDescriptions, setVisualDescriptions] = useState([]);
  const [visualRun, setVisualRun] = useState(null);
  const [visualError, setVisualError] = useState("");
  const [extractionCacheStatus, setExtractionCacheStatus] = useState("");
  const [conversionTimeMs, setConversionTimeMs] = useState(null);
  const [error, setError] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);
  const [isDescribingVisuals, setIsDescribingVisuals] = useState(false);
  const [conversionStage, setConversionStage] = useState("");
  const [copyState, setCopyState] = useState("idle");
  const isBusy = isExtracting || isDescribingVisuals;

  const finalMarkdown = useMemo(
    () => appendVisualDescriptionsToMarkdown(markdown, visualDescriptions),
    [markdown, visualDescriptions],
  );
  const keptImageCount = useMemo(
    () => imageDecisions.filter((decision) => decision.isKept).length,
    [imageDecisions],
  );
  const visualDescriptionCount = useMemo(
    () => visualDescriptions.filter((description) => !description.error).length,
    [visualDescriptions],
  );
  const failedVisualDescriptionCount = useMemo(
    () => visualDescriptions.filter((description) => description.error).length,
    [visualDescriptions],
  );
  const allImagesAnalyzed = useMemo(
    () =>
      debugImages.length > 0 &&
      imageDecisions.length === debugImages.length &&
      imageDecisions.every(
        (decision) => decision.analysis?.status === "ready" || decision.analysis?.status === "error",
      ),
    [debugImages.length, imageDecisions],
  );
  const pageTextByNumber = useMemo(() => {
    const pages = new Map();

    chunks.forEach((chunk) => {
      const pageKey = chunk.pageNo ? String(chunk.pageNo) : "Unknown";
      const current = pages.get(pageKey) || [];
      current.push(chunk.content);
      pages.set(pageKey, current);
    });

    return Object.fromEntries(
      Array.from(pages.entries()).map(([pageNumber, contents]) => [pageNumber, contents.join("\n\n")]),
    );
  }, [chunks]);

  const stats = useMemo(
    () => ({
      fileName: file?.name || "-",
      fileSize: file ? formatFileSize(file.size) : "-",
      conversionTime:
        typeof conversionTimeMs === "number" ? `${(conversionTimeMs / 1000).toFixed(2)} s` : "-",
      extractorMode: EXTRACTOR_LABEL,
      extractionCacheStatus: extractionCacheStatus || "-",
      markdownCharacters: finalMarkdown.length,
      chunkCount: chunks.length,
      renderedPageCount: debugImages.length,
      keptImageCount,
      visualDescriptionCount,
      cacheHits: visualRun?.cache?.hits ?? 0,
      cacheMisses: visualRun?.cache?.misses ?? 0,
      visualFailures: failedVisualDescriptionCount,
      imageCount: figures.length,
      tableCount,
    }),
    [
      chunks.length,
      conversionTimeMs,
      debugImages.length,
      extractionCacheStatus,
      figures.length,
      file,
      finalMarkdown.length,
      failedVisualDescriptionCount,
      keptImageCount,
      tableCount,
      visualDescriptionCount,
      visualRun,
    ],
  );

  function clearExtractionResults() {
    setMarkdown("");
    setRawResponse(null);
    setMarkdownSourcePath("");
    setChunks([]);
    setWarnings([]);
    setFigures([]);
    setDebugImages([]);
    setImageDecisions([]);
    setVisualDescriptions([]);
    setVisualRun(null);
    setVisualError("");
    setExtractionCacheStatus("");
    setTableCount(0);
    setConversionTimeMs(null);
    setConversionStage("");
  }

  function handleFileChange(nextFile) {
    setError("");
    setVisualError("");
    setCopyState("idle");
    setFile(nextFile);
    clearExtractionResults();
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
    const isSupported =
      file.type === "application/pdf" ||
      lower.endsWith(".pdf") ||
      lower.endsWith(".ppt") ||
      lower.endsWith(".pptx") ||
      lower.endsWith(".odp") ||
      file.type === "application/vnd.ms-powerpoint" ||
      file.type === "application/vnd.openxmlformats-officedocument.presentationml.presentation";

    if (!isSupported) {
      setError("Only PDF, PowerPoint, or ODP files are supported.");
      return;
    }

    setIsExtracting(true);
    const startedAt = performance.now();

    try {
      setConversionStage("Extracting locally with PyMuPDF4LLM and RapidOCR...");
      const response = await convertFileWithLocalExtractor({ file });
      const elapsed = performance.now() - startedAt;
      const nextMarkdown = response.markdown || "";

      setRawResponse(response);
      setMarkdown(nextMarkdown);
      setMarkdownSourcePath(response.sourcePath || "local_pymupdf4llm");
      setChunks(response.chunks || []);
      setWarnings(response.warnings || []);
      setFigures(response.figures || []);
      setDebugImages(response.embeddedImages || []);
      setImageDecisions([]);
      setVisualDescriptions([]);
      setVisualRun(null);
      setVisualError("");
      setExtractionCacheStatus(response.metadata?.cacheStatus || "");
      setTableCount(response.tableCount || 0);
      setConversionTimeMs(elapsed);

      if (!nextMarkdown) {
        setError(
          "The local extractor responded successfully, but no page-aware Markdown was extracted. Inspect the raw JSON below.",
        );
      }
    } catch (requestError) {
      setError(requestError.message);
      setConversionTimeMs(performance.now() - startedAt);
    } finally {
      setIsExtracting(false);
      setConversionStage("");
    }
  }

  async function handleGenerateTeachingMarkdown() {
    setVisualError("");
    setCopyState("idle");

    const keptDecisions = imageDecisions.filter((decision) => decision.isKept);

    if (!markdown) {
      setVisualError("Extract slides before generating teaching-ready visual descriptions.");
      return;
    }

    if (!allImagesAnalyzed) {
      setVisualError("Wait until visual slide analysis finishes.");
      return;
    }

    if (!keptDecisions.length) {
      setVisualDescriptions([]);
      setVisualRun({
        provider: "opencode-go",
        model: "",
        requested: 0,
        completed: 0,
        failed: 0,
        cache: { hits: 0, misses: 0, failures: 0 },
      });
      return;
    }

    setIsDescribingVisuals(true);
    setConversionStage("Generating teaching-ready visual descriptions with OpenCode Go...");

    try {
      const result = await describeVisualSlides({
        decisions: keptDecisions,
        pageTextByNumber,
      });
      const descriptions = result.descriptions || [];
      const failedCount = descriptions.filter((description) => description.error).length;

      setVisualDescriptions(descriptions);
      setVisualRun({
        provider: result.provider,
        model: result.model,
        promptVersion: result.promptVersion,
        namespaceId: result.namespaceId,
        requested: keptDecisions.length,
        completed: descriptions.length - failedCount,
        failed: failedCount,
        cache: result.cache,
        elapsedMs: result.elapsedMs,
      });

      if (failedCount) {
        const firstError = descriptions.find((description) => description.error)?.error;
        setVisualError(
          `${failedCount} visual description request(s) failed. Cache hits were still used.${
            firstError ? ` First error: ${firstError}` : ""
          }`,
        );
      }
    } catch (requestError) {
      setVisualError(requestError.message);
      setVisualRun({
        provider: "opencode-go",
        model: "",
        requested: keptDecisions.length,
        completed: 0,
        failed: keptDecisions.length,
        cache: { hits: 0, misses: 0, failures: keptDecisions.length },
      });
    } finally {
      setIsDescribingVisuals(false);
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
            <p className="text-sm font-medium text-teal-700">Docker-free local pipeline</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-zinc-950">
              SlideVision Markdown Extractor
            </h1>
          </div>
          <div className="rounded border border-zinc-300 bg-white px-3 py-2 font-mono text-xs text-zinc-700">
            {DEFAULT_LOCAL_EXTRACTOR_BASE_URL}/v1/convert/file
            <br />
            {EXTRACTOR_LABEL}
          </div>
        </header>

        <section className="grid gap-5 lg:grid-cols-[minmax(300px,380px)_1fr]">
          <div className="flex flex-col gap-5">
            <FileUploader file={file} onFileChange={handleFileChange} />

            <section className="rounded border border-zinc-300 bg-white">
              <div className="border-b border-zinc-200 px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-950">Local Extractor</h2>
              </div>
              <div className="grid gap-2 px-4 py-3 text-sm text-zinc-700">
                <p>PDF files are extracted directly. PPT, PPTX, and ODP files are converted with local LibreOffice first.</p>
                <p>Large visual slides can be described once with OpenCode Go and cached by slide hash.</p>
              </div>
            </section>

            <button
              type="button"
              onClick={handleConvert}
              disabled={isBusy}
              className="inline-flex h-11 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            >
              {isExtracting ? "Extracting..." : "Extract Slides Locally"}
            </button>
            <button
              type="button"
              onClick={handleGenerateTeachingMarkdown}
              disabled={isBusy || !markdown || !allImagesAnalyzed}
              className="inline-flex h-11 items-center justify-center rounded border border-teal-700 bg-white px-4 text-sm font-semibold text-teal-800 shadow-sm transition hover:bg-teal-50 disabled:cursor-not-allowed disabled:border-zinc-300 disabled:text-zinc-400"
            >
              {isDescribingVisuals ? "Generating..." : "Generate Teaching-Ready Markdown"}
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
            {visualRun ? (
              <div className="rounded border border-zinc-300 bg-white px-4 py-3 text-sm text-zinc-700">
                Visual descriptions: {visualRun.completed}/{visualRun.requested} ready
                {visualRun.failed ? `, ${visualRun.failed} failed` : ""}. Cache hits:{" "}
                {visualRun.cache?.hits ?? 0}, new calls: {visualRun.cache?.misses ?? 0}.
              </div>
            ) : null}
            {visualError ? (
              <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
                {visualError}
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
              isLoading={isExtracting}
              copyState={copyState}
              onCopy={handleCopyMarkdown}
              onDownload={() => downloadMarkdown(finalMarkdown, file?.name)}
              title="Slide-Aware Markdown"
            />

            <section className="rounded border border-zinc-300 bg-white">
              <div className="border-b border-zinc-200 px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-950">Visual Region References</h2>
              </div>
              {figures.length ? (
                <div className="divide-y divide-zinc-200">
                  {figures.map((figure, index) => (
                    <article key={`${figure.id}-${index}`} className="grid gap-2 px-4 py-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-zinc-950">
                          {figure.type || "visual"} {index + 1}
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
                <p className="px-4 py-5 text-sm text-zinc-600">No large visual regions detected.</p>
              )}
            </section>

            <ImageDebugPanel images={debugImages} onDecisionsChange={setImageDecisions} />

            <ChunksViewer chunks={chunks} />
            <RawJsonViewer data={rawResponse} />
          </div>
        </section>
      </div>
    </main>
  );
}
