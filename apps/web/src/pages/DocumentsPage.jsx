import { useEffect, useRef, useState } from "react";
import DocumentBlocksViewer from "../components/DocumentBlocksViewer.jsx";
import FileUploader from "../components/FileUploader.jsx";
import { getDocument, getDocumentBlocks, uploadDocument } from "../api/client.ts";

const STATUS_STYLES = {
  uploaded: "bg-sky-100 text-sky-800 border-sky-300",
  extracting: "bg-amber-100 text-amber-800 border-amber-300",
  ready: "bg-emerald-100 text-emerald-800 border-emerald-300",
  failed: "bg-red-100 text-red-800 border-red-300",
};

const POLL_INTERVAL_MS = 1500;
const IN_PROGRESS_STATUSES = new Set(["uploaded", "extracting"]);

export default function DocumentsPage() {
  const [file, setFile] = useState(null);
  const [document, setDocument] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState("");
  const pollTimeoutRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollTimeoutRef.current) window.clearTimeout(pollTimeoutRef.current);
    };
  }, []);

  function schedulePoll(documentId) {
    pollTimeoutRef.current = window.setTimeout(async () => {
      try {
        const latest = await getDocument(documentId);
        setDocument(latest);
        if (IN_PROGRESS_STATUSES.has(latest.status)) {
          schedulePoll(documentId);
        } else if (latest.status === "ready") {
          const blocksResponse = await getDocumentBlocks(documentId);
          setBlocks(blocksResponse.blocks);
        }
      } catch (pollError) {
        setError(pollError.message);
      }
    }, POLL_INTERVAL_MS);
  }

  async function handleUpload() {
    if (!file) {
      setError("Choose a PDF, PPT, PPTX, or ODP file first.");
      return;
    }

    setError("");
    setBlocks([]);
    setDocument(null);
    setIsUploading(true);

    try {
      const created = await uploadDocument(file);
      const detail = await getDocument(created.document_id);
      setDocument(detail);
      if (IN_PROGRESS_STATUSES.has(detail.status)) {
        schedulePoll(created.document_id);
      } else if (detail.status === "ready") {
        const blocksResponse = await getDocumentBlocks(created.document_id);
        setBlocks(blocksResponse.blocks);
      }
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(300px,380px)_1fr]">
      <div className="flex flex-col gap-5">
        <FileUploader file={file} onFileChange={setFile} />

        <button
          type="button"
          onClick={handleUpload}
          disabled={isUploading}
          className="inline-flex h-11 items-center justify-center rounded bg-teal-700 px-4 text-sm font-semibold text-white shadow-sm transition hover:bg-teal-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
        >
          {isUploading ? "Uploading..." : "Upload Document"}
        </button>

        {error ? (
          <div className="rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        ) : null}

        {document ? (
          <section className="rounded border border-zinc-300 bg-white">
            <div className="border-b border-zinc-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-zinc-950">Document</h2>
            </div>
            <div className="grid gap-2 px-4 py-3 text-sm text-zinc-700">
              <div className="flex items-center justify-between">
                <span className="font-medium text-zinc-950">{document.title}</span>
                <span
                  className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${
                    STATUS_STYLES[document.status] || "bg-zinc-100 text-zinc-700 border-zinc-300"
                  }`}
                >
                  {document.status}
                </span>
              </div>
              <p className="break-all font-mono text-xs text-zinc-500">{document.id}</p>
              {document.error ? (
                <p className="rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-800">
                  {document.error}
                </p>
              ) : null}
            </div>
          </section>
        ) : null}
      </div>

      <div className="min-w-0">
        <DocumentBlocksViewer blocks={blocks} />
      </div>
    </div>
  );
}
