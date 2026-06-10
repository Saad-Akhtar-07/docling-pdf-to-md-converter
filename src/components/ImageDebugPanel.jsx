import { useEffect, useMemo, useState } from "react";
import { getVisionSkipReasons, normalizeVisionFilters } from "../utils/imagePipeline.js";

const percentFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

function mapBboxToCanvas(bbox, pageSize, imageWidth, imageHeight, padding) {
  if (!bbox || !pageSize?.width || !pageSize?.height) return null;

  const scaleX = imageWidth / pageSize.width;
  const scaleY = imageHeight / pageSize.height;
  const left = Math.min(bbox.l, bbox.r) * scaleX;
  const width = Math.abs(bbox.r - bbox.l) * scaleX;
  const height = Math.abs(bbox.t - bbox.b) * scaleY;
  const origin = String(bbox.coordOrigin || "BOTTOMLEFT").toUpperCase();
  const top =
    origin.includes("BOTTOM")
      ? (pageSize.height - Math.max(bbox.t, bbox.b)) * scaleY
      : Math.min(bbox.t, bbox.b) * scaleY;

  return {
    x: Math.max(0, left - padding),
    y: Math.max(0, top - padding),
    width: Math.min(imageWidth, width + padding * 2),
    height: Math.min(imageHeight, height + padding * 2),
  };
}

function calculateResidualScores(canvas) {
  const context = canvas.getContext("2d");
  const { width, height } = canvas;
  const pixels = context.getImageData(0, 0, width, height).data;
  let nonWhitePixels = 0;
  let edgePixels = 0;
  const totalPixels = width * height;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = (y * width + x) * 4;
      const red = pixels[index];
      const green = pixels[index + 1];
      const blue = pixels[index + 2];
      const alpha = pixels[index + 3];

      if (alpha > 0 && (red < 245 || green < 245 || blue < 245)) {
        nonWhitePixels += 1;
      }

      if (x < width - 1 && y < height - 1) {
        const rightIndex = index + 4;
        const bottomIndex = index + width * 4;
        const luma = red * 0.299 + green * 0.587 + blue * 0.114;
        const rightLuma =
          pixels[rightIndex] * 0.299 + pixels[rightIndex + 1] * 0.587 + pixels[rightIndex + 2] * 0.114;
        const bottomLuma =
          pixels[bottomIndex] * 0.299 +
          pixels[bottomIndex + 1] * 0.587 +
          pixels[bottomIndex + 2] * 0.114;

        if (Math.abs(luma - rightLuma) > 35 || Math.abs(luma - bottomLuma) > 35) {
          edgePixels += 1;
        }
      }
    }
  }

  return {
    residualRatio: nonWhitePixels / totalPixels,
    edgeRatio: edgePixels / totalPixels,
  };
}

function analyzeImage(image, filters) {
  return new Promise((resolve) => {
    const preview = new Image();

    preview.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = preview.naturalWidth;
      canvas.height = preview.naturalHeight;

      const context = canvas.getContext("2d");
      context.drawImage(preview, 0, 0);
      context.fillStyle = "#ffffff";

      const pageSize = image.pageSize || {
        width: preview.naturalWidth,
        height: preview.naturalHeight,
      };

      const maskedBoxes = image.textAreas
        .map((area) =>
          mapBboxToCanvas(
            area.bbox,
            pageSize,
            preview.naturalWidth,
            preview.naturalHeight,
            filters.textMaskPadding,
          ),
        )
        .filter(Boolean);

      maskedBoxes.forEach((box) => {
        context.fillRect(box.x, box.y, box.width, box.height);
      });

      const pictureBoxes = image.pictureAreas
        .map((area) => mapBboxToCanvas(area.bbox, pageSize, preview.naturalWidth, preview.naturalHeight, 0))
        .filter(Boolean);
      const pictureArea = pictureBoxes.reduce((sum, box) => sum + box.width * box.height, 0);

      const scores = calculateResidualScores(canvas);

      resolve({
        status: "ready",
        width: preview.naturalWidth,
        height: preview.naturalHeight,
        maskedSource: canvas.toDataURL("image/png"),
        textBoxCount: maskedBoxes.length,
        pictureBoxCount: pictureBoxes.length,
        pictureAreaRatio: pictureArea / (preview.naturalWidth * preview.naturalHeight),
        pictureBoxes,
        ...scores,
      });
    };

    preview.onerror = () => {
      resolve({
        status: "error",
        width: 0,
        height: 0,
        maskedSource: "",
        textBoxCount: 0,
        pictureBoxCount: 0,
        pictureAreaRatio: 0,
        pictureBoxes: [],
        residualRatio: 0,
        edgeRatio: 0,
      });
    };

    preview.src = image.source;
  });
}

function useVisualAnalyses(images, filters) {
  const [analyses, setAnalyses] = useState({});

  useEffect(() => {
    let isActive = true;
    setAnalyses({});

    images.forEach((image) => {
      analyzeImage(image, filters).then((analysis) => {
        if (!isActive) return;

        setAnalyses((current) => ({
          ...current,
          [image.id]: analysis,
        }));
      });
    });

    return () => {
      isActive = false;
    };
  }, [filters, images]);

  return analyses;
}

function PictureOverlay({ boxes }) {
  if (!boxes?.length) return null;

  return (
    <div className="pointer-events-none absolute inset-0">
      {boxes.map((box, index) => (
        <div
          key={`${box.x}-${box.y}-${index}`}
          className="absolute border-2 border-emerald-500 bg-emerald-400/10"
          style={{
            left: `${box.x}%`,
            top: `${box.y}%`,
            width: `${box.width}%`,
            height: `${box.height}%`,
          }}
        />
      ))}
    </div>
  );
}

function scaleBoxesForPreview(boxes, imageWidth, imageHeight) {
  if (!boxes?.length || !imageWidth || !imageHeight) return [];

  return boxes.map((box) => ({
    x: (box.x / imageWidth) * 100,
    y: (box.y / imageHeight) * 100,
    width: (box.width / imageWidth) * 100,
    height: (box.height / imageHeight) * 100,
  }));
}

export default function ImageDebugPanel({ images, onDecisionsChange }) {
  const activeFilters = useMemo(() => normalizeVisionFilters(), []);
  const analyses = useVisualAnalyses(images, activeFilters);
  const repeatCounts = useMemo(() => {
    const counts = new Map();

    images.forEach((image) => {
      counts.set(image.fingerprint, (counts.get(image.fingerprint) || 0) + 1);
    });

    return counts;
  }, [images]);

  const decisions = useMemo(
    () =>
      images.map((image) => {
        const analysis = analyses[image.id];
        const repeatCount = repeatCounts.get(image.fingerprint) || 1;
        const skipReasons = getVisionSkipReasons({ analysis, repeatCount, filters: activeFilters });

        return {
          image,
          analysis,
          repeatCount,
          skipReasons,
          isKept: skipReasons.length === 0,
        };
      }),
    [activeFilters, analyses, images, repeatCounts],
  );

  const keptCount = decisions.filter((decision) => decision.isKept).length;

  useEffect(() => {
    onDecisionsChange?.(decisions);
  }, [decisions, onDecisionsChange]);

  return (
    <section className="rounded border border-zinc-300 bg-white">
      <div className="border-b border-zinc-200 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-zinc-950">Vision Candidate Pages</h2>
          <span className="text-xs font-medium text-zinc-600">
            {keptCount} send / {images.length} pages
          </span>
        </div>
      </div>

      {images.length ? (
        <div className="grid gap-3 p-4 xl:grid-cols-2">
          {decisions.map(({ image, analysis, repeatCount, skipReasons, isKept }) => {
            const overlayBoxes = scaleBoxesForPreview(
              analysis?.pictureBoxes,
              analysis?.width,
              analysis?.height,
            );

            return (
              <article key={image.id} className="grid gap-3 rounded border border-zinc-200 bg-zinc-50 p-3">
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="grid gap-1">
                  <span className="text-xs font-medium text-zinc-500">Original</span>
                  <div className="relative flex h-44 items-center justify-center overflow-hidden rounded border border-zinc-200 bg-white">
                    <img
                      src={image.source}
                      alt={image.caption || image.reference || "Extracted page"}
                      className="max-h-full max-w-full object-contain"
                    />
                    <PictureOverlay boxes={overlayBoxes} />
                  </div>
                </div>
                <div className="grid gap-1">
                  <span className="text-xs font-medium text-zinc-500">Text Masked</span>
                  <div className="flex h-44 items-center justify-center overflow-hidden rounded border border-zinc-200 bg-white">
                    {analysis?.maskedSource ? (
                      <img
                        src={analysis.maskedSource}
                        alt="Text masked page"
                        className="max-h-full max-w-full object-contain"
                      />
                    ) : (
                      <span className="text-xs text-zinc-500">{analysis?.status || "analyzing"}</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="grid gap-2 text-xs text-zinc-700">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded px-2 py-0.5 font-semibold ${
                      isKept ? "bg-emerald-100 text-emerald-800" : "bg-zinc-200 text-zinc-700"
                    }`}
                  >
                    {isKept ? "Send to Vision" : "Skip"}
                  </span>
                  {image.pageNumber ? (
                    <span className="rounded bg-sky-100 px-2 py-0.5 font-medium text-sky-800">
                      page {image.pageNumber}
                    </span>
                  ) : null}
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
                  <dt className="text-zinc-500">Size</dt>
                  <dd className="text-right font-medium text-zinc-800">
                    {analysis?.status === "ready" ? `${analysis.width} x ${analysis.height}` : "-"}
                  </dd>
                  <dt className="text-zinc-500">Text boxes</dt>
                  <dd className="text-right font-medium text-zinc-800">{analysis?.textBoxCount ?? "-"}</dd>
                  <dt className="text-zinc-500">Picture boxes</dt>
                  <dd className="text-right font-medium text-zinc-800">
                    {analysis?.pictureBoxCount ?? "-"}
                  </dd>
                  <dt className="text-zinc-500">Picture area</dt>
                  <dd className="text-right font-medium text-zinc-800">
                    {analysis ? `${percentFormatter.format(analysis.pictureAreaRatio * 100)}%` : "-"}
                  </dd>
                  <dt className="text-zinc-500">Residue</dt>
                  <dd className="text-right font-medium text-zinc-800">
                    {analysis ? `${percentFormatter.format(analysis.residualRatio * 100)}%` : "-"}
                  </dd>
                  <dt className="text-zinc-500">Edges</dt>
                  <dd className="text-right font-medium text-zinc-800">
                    {analysis ? `${percentFormatter.format(analysis.edgeRatio * 100)}%` : "-"}
                  </dd>
                  <dt className="text-zinc-500">Repeated</dt>
                  <dd className="text-right font-medium text-zinc-800">{repeatCount}x</dd>
                </dl>
                {skipReasons.length ? (
                  <p className="rounded bg-white px-2 py-1 text-zinc-600">{skipReasons.join(", ")}</p>
                ) : null}
                <code className="break-all rounded bg-white px-2 py-1 font-mono text-[11px] text-zinc-500">
                  {image.reference || image.sourcePath}
                </code>
              </div>
            </article>
            );
          })}
        </div>
      ) : (
        <p className="px-4 py-5 text-sm text-zinc-600">No embedded page images detected.</p>
      )}
    </section>
  );
}
