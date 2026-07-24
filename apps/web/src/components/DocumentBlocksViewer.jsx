import ProvenanceBadge from "./ProvenanceBadge.jsx";

function groupBySlide(blocks) {
  const bySlide = new Map();
  for (const block of blocks) {
    const list = bySlide.get(block.slide_no) || [];
    list.push(block);
    bySlide.set(block.slide_no, list);
  }
  return [...bySlide.entries()].sort(([a], [b]) => a - b);
}

export default function DocumentBlocksViewer({ blocks }) {
  if (!blocks.length) {
    return <p className="px-4 py-5 text-sm text-zinc-600">No blocks yet.</p>;
  }

  const slides = groupBySlide(blocks);

  return (
    <div className="flex flex-col gap-4">
      {slides.map(([slideNo, slideBlocks]) => (
        <section key={slideNo} className="rounded border border-zinc-300 bg-white">
          <div className="border-b border-zinc-200 px-4 py-2">
            <h3 className="text-sm font-semibold text-zinc-950">Slide {slideNo}</h3>
          </div>
          <div className="divide-y divide-zinc-100">
            {slideBlocks
              .sort((a, b) => a.order_index - b.order_index)
              .map((block) => (
                <article key={block.id} className="grid gap-1.5 px-4 py-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <ProvenanceBadge provenance={block.provenance} />
                    {block.ocr_confidence != null ? (
                      <span className="text-xs text-zinc-500">
                        confidence {(block.ocr_confidence * 100).toFixed(0)}%
                      </span>
                    ) : null}
                    {block.producer ? (
                      <span className="text-xs text-zinc-500">via {block.producer}</span>
                    ) : null}
                  </div>
                  <p className="whitespace-pre-wrap text-zinc-800">{block.text}</p>
                </article>
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}
