import { useState } from "react";
import DocumentsPage from "./pages/DocumentsPage.jsx";
import ExtractorDebugPage from "./pages/ExtractorDebugPage.jsx";

const TABS = [
  { id: "documents", label: "Documents" },
  { id: "extractor-debug", label: "Extractor Debug" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("documents");

  return (
    <main className="min-h-screen bg-zinc-100 text-zinc-950">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-3 border-b border-zinc-300 pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm font-medium text-teal-700">SlideVision Adaptive Tutor</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-normal text-zinc-950">
              {activeTab === "documents" ? "Documents" : "SlideVision Markdown Extractor"}
            </h1>
          </div>
          <nav className="flex gap-1 rounded border border-zinc-300 bg-white p-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`rounded px-3 py-1.5 text-sm font-medium transition ${
                  activeTab === tab.id ? "bg-teal-700 text-white" : "text-zinc-700 hover:bg-zinc-100"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </header>

        {activeTab === "documents" ? <DocumentsPage /> : <ExtractorDebugPage />}
      </div>
    </main>
  );
}
