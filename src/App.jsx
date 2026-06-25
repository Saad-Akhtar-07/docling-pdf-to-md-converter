import { useEffect, useMemo, useRef, useState } from "react";
import ChunksViewer from "./components/ChunksViewer.jsx";
import FileUploader from "./components/FileUploader.jsx";
import ImageDebugPanel from "./components/ImageDebugPanel.jsx";
import MarkdownViewer from "./components/MarkdownViewer.jsx";
import RawJsonViewer from "./components/RawJsonViewer.jsx";
import StatsPanel from "./components/StatsPanel.jsx";
import { DEFAULT_DOCLING_BASE_URL, convertPdfWithDocling } from "./utils/doclingApi.js";
import {
  DEFAULT_LANGCHAIN_EXTRACTOR_BASE_URL,
  convertPdfWithLangChainExtractor,
} from "./utils/langchainExtractorApi.js";
import { DEFAULT_GOTENBERG_BASE_URL, convertPptToPdf } from "./utils/pptApi.js";
import {
  appendVisionDescriptionsToMarkdown,
  extractEmbeddedImages,
} from "./utils/imagePipeline.js";
import { buildStructuredPageOutput } from "./utils/responseParser.js";
import { describeVisionCandidates } from "./utils/visionApi.js";

const EXTRACTOR_MODES = {
  docling: {
    label: "Docling",
    stage: "Extracting Markdown with Docling...",
    endpoint: `${DEFAULT_DOCLING_BASE_URL}/v1/convert/file`,
  },
  langchain: {
    label: "LangChain/PyMuPDF",
    stage: "Extracting Markdown with LangChain/PyMuPDF...",
    endpoint: `${DEFAULT_LANGCHAIN_EXTRACTOR_BASE_URL}/v1/convert/file`,
  },
};

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
  const [extractorMode, setExtractorMode] = useState("docling");
  const [markdown, setMarkdown] = useState("");
  const [rawResponse, setRawResponse] = useState(null);
  const [markdownSourcePath, setMarkdownSourcePath] = useState("");
  const [chunks, setChunks] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [figures, setFigures] = useState([]);
  const [debugImages, setDebugImages] = useState([]);
  const [imageDecisions, setImageDecisions] = useState([]);
  const [visionDescriptions, setVisionDescriptions] = useState([]);
  const [visionError, setVisionError] = useState("");
  const [visionRun, setVisionRun] = useState(null);
  const [isDescribingImages, setIsDescribingImages] = useState(false);
  const [tableCount, setTableCount] = useState(0);
  const [conversionTimeMs, setConversionTimeMs] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [conversionStage, setConversionStage] = useState("");
  const [copyState, setCopyState] = useState("idle");
  const lastVisionJobRef = useRef("");

  const finalMarkdown = useMemo(
    () => appendVisionDescriptionsToMarkdown(markdown, visionDescriptions),
    [markdown, visionDescriptions],
  );
  const visionCandidateCount = useMemo(
    () => imageDecisions.filter((decision) => decision.isKept).length,
    [imageDecisions],
  );
  const visionDescriptionCount = useMemo(
    () => visionDescriptions.filter((description) => !description.error).length,
    [visionDescriptions],
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
      extractorMode: EXTRACTOR_MODES[extractorMode].label,
      markdownCharacters: finalMarkdown.length,
      chunkCount: chunks.length,
      imageCount: figures.length,
      visionCandidateCount,
      visionDescriptionCount,
      tableCount,
    }),
    [
      chunks.length,
      conversionTimeMs,
      extractorMode,
      figures.length,
      file,
      finalMarkdown.length,
      tableCount,
      visionCandidateCount,
      visionDescriptionCount,
    ],
  );

  useEffect(() => {
    const keptDecisions = imageDecisions.filter((decision) => decision.isKept);
    const allImagesAnalyzed =
      debugImages.length > 0 &&
      imageDecisions.length === debugImages.length &&
      imageDecisions.every(
        (decision) => decision.analysis?.status === "ready" || decision.analysis?.status === "error",
      );

    if (!markdown || !keptDecisions.length || !allImagesAnalyzed) return;

    const visionJobKey = keptDecisions
      .map((decision) => `${decision.image.pageNumber || "Unknown"}:${decision.image.fingerprint}`)
      .join("|");

    if (!visionJobKey || lastVisionJobRef.current === visionJobKey) return;

    lastVisionJobRef.current = visionJobKey;
    setVisionError("");
    setVisionDescriptions([]);
    setVisionRun(null);
    setIsDescribingImages(true);

    describeVisionCandidates({
      decisions: keptDecisions,
      pageTextByNumber,
    })
      .then((result) => {
        const descriptions = result.descriptions || [];
        const failedCount = descriptions.filter((description) => description.error).length;

        setVisionDescriptions(descriptions);
        setVisionRun({
          provider: result.provider,
          model: result.model,
          requested: keptDecisions.length,
          completed: descriptions.length - failedCount,
          failed: failedCount,
        });

        if (failedCount) {
          setVisionError(`${failedCount} image description request(s) failed. Inspect the Vision status.`);
        }
      })
      .catch((requestError) => {
        setVisionError(requestError.message);
        setVisionRun({
          provider: "groq",
          model: "",
          requested: keptDecisions.length,
          completed: 0,
          failed: keptDecisions.length,
        });
      })
      .finally(() => setIsDescribingImages(false));
  }, [debugImages.length, imageDecisions, markdown, pageTextByNumber]);

  function clearExtractionResults() {
    setMarkdown("");
    setRawResponse(null);
    setMarkdownSourcePath("");
    setChunks([]);
    setWarnings([]);
    setFigures([]);
    setDebugImages([]);
    setImageDecisions([]);
    setVisionDescriptions([]);
    setVisionError("");
    setVisionRun(null);
    setIsDescribingImages(false);
    setTableCount(0);
    setConversionTimeMs(null);
    setConversionStage("");
    lastVisionJobRef.current = "";
  }

  function handleFileChange(nextFile) {
    setError("");
    setCopyState("idle");
    setFile(nextFile);
    clearExtractionResults();
  }

  function handleExtractorModeChange(nextMode) {
    if (nextMode === extractorMode) return;

    setExtractorMode(nextMode);
    setError("");
    setCopyState("idle");
    clearExtractionResults();
  }

  async function handleConvert() {
    setError("");
    setCopyState("idle");
    setConversionStage("");
    setVisionError("");
    setVisionDescriptions([]);
    setVisionRun(null);
    lastVisionJobRef.current = "";

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
      const activeExtractor = EXTRACTOR_MODES[extractorMode];

      setConversionStage(
        isPpt ? "Converting PowerPoint to PDF..." : `Sending PDF to ${activeExtractor.label}...`,
      );
      const pdfFile = isPpt ? await convertPptToPdf({ file }) : file;
      setConversionStage(activeExtractor.stage);
      const response =
        extractorMode === "langchain"
          ? await convertPdfWithLangChainExtractor({
              file: pdfFile,
              baseUrl: DEFAULT_LANGCHAIN_EXTRACTOR_BASE_URL,
            })
          : await convertPdfWithDocling({
              file: pdfFile,
              baseUrl: DEFAULT_DOCLING_BASE_URL,
            });

      const elapsed = performance.now() - startedAt;
      const structuredOutput =
        extractorMode === "langchain"
          ? {
              markdown: response.markdown || "",
              chunks: response.chunks || [],
              figures: response.figures || [],
              tableCount: response.tableCount || 0,
              sourcePath: response.sourcePath || "langchain_pymupdf4llm",
              warnings: response.warnings || [],
            }
          : buildStructuredPageOutput(response, file.name);
      const normalizedFigures = prepareFigureSummariesForFutureVision(structuredOutput.figures);
      const embeddedImages =
        extractorMode === "langchain" ? response.embeddedImages || [] : extractEmbeddedImages(response);

      setRawResponse(response);
      setMarkdown(structuredOutput.markdown);
      setMarkdownSourcePath(structuredOutput.sourcePath);
      setChunks(structuredOutput.chunks);
      setWarnings(structuredOutput.warnings);
      setFigures(normalizedFigures);
      setDebugImages(embeddedImages);
      setImageDecisions([]);
      setVisionDescriptions([]);
      setVisionError("");
      setVisionRun(null);
      setTableCount(structuredOutput.tableCount);
      setConversionTimeMs(elapsed);

      if (!structuredOutput.markdown) {
        setError(
          `${activeExtractor.label} responded successfully, but no page-aware content was extracted. Inspect the raw JSON below to update the parser.`,
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
            {EXTRACTOR_MODES[extractorMode].endpoint}
            <br />
            {DEFAULT_GOTENBERG_BASE_URL}/forms/libreoffice/convert
          </div>
        </header>

        <section className="grid gap-5 lg:grid-cols-[minmax(300px,380px)_1fr]">
          <div className="flex flex-col gap-5">
            <FileUploader file={file} onFileChange={handleFileChange} />
            <section className="rounded border border-zinc-300 bg-white">
              <div className="border-b border-zinc-200 px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-950">Extractor Pipeline</h2>
              </div>
              <div className="grid grid-cols-2 gap-2 p-4">
                {Object.entries(EXTRACTOR_MODES).map(([mode, config]) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => handleExtractorModeChange(mode)}
                    disabled={isLoading}
                    className={`rounded border px-3 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
                      extractorMode === mode
                        ? "border-teal-700 bg-teal-700 text-white"
                        : "border-zinc-300 bg-white text-zinc-700 hover:border-teal-600"
                    }`}
                  >
                    {config.label}
                  </button>
                ))}
              </div>
              <div className="border-t border-zinc-200 px-4 py-3 text-xs text-zinc-600">
                {extractorMode === "langchain"
                  ? "Experimental path: native PDF text/tables first, rendered page images for Vision candidates, OCR disabled."
                  : "Current path: Docling Serve OCR/table/layout extraction with embedded images."}
              </div>
            </section>
            <button
              type="button"
              onClick={handleConvert}
              disabled={isLoading}
              className="inline-flex h-11 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            >
              {isLoading ? "Extracting..." : `Extract Slides with ${EXTRACTOR_MODES[extractorMode].label}`}
            </button>
            {conversionStage ? (
              <div className="rounded border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
                {conversionStage}
              </div>
            ) : null}
            {isDescribingImages ? (
              <div className="rounded border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
                Describing selected slide images with Groq Vision...
              </div>
            ) : null}
            {visionRun ? (
              <div className="rounded border border-zinc-300 bg-white px-4 py-3 text-sm text-zinc-700">
                Vision: {visionRun.completed}/{visionRun.requested} described
                {visionRun.failed ? `, ${visionRun.failed} failed` : ""} via {visionRun.provider}
                {visionRun.model ? ` (${visionRun.model})` : ""}.
              </div>
            ) : null}
            {error ? (
              <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
                {error}
              </div>
            ) : null}
            {visionError ? (
              <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
                {visionError}
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
                <h2 className="text-sm font-semibold text-zinc-950">
                  {EXTRACTOR_MODES[extractorMode].label} Figure References
                </h2>
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
