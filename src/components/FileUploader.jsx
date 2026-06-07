export default function FileUploader({ file, onFileChange }) {
  function handleChange(event) {
    const nextFile = event.target.files?.[0] || null;
    onFileChange(nextFile);
  }

  function handleDrop(event) {
    event.preventDefault();
    const nextFile = event.dataTransfer.files?.[0] || null;
    onFileChange(nextFile);
  }

  return (
    <section className="rounded border border-zinc-300 bg-white">
      <div className="border-b border-zinc-200 px-4 py-3">
<<<<<<< HEAD
        <h2 className="text-sm font-semibold text-zinc-950">Upload (PDF or PowerPoint)</h2>
=======
        <h2 className="text-sm font-semibold text-zinc-950">PDF Upload</h2>
>>>>>>> 3a405dd557e8516741103ff68021fac68d9494dd
      </div>
      <label
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
        className="m-4 flex min-h-40 cursor-pointer flex-col items-center justify-center gap-3 rounded border border-dashed border-zinc-400 bg-zinc-50 px-4 py-6 text-center transition hover:border-teal-600 hover:bg-teal-50"
      >
<<<<<<< HEAD
        <input type="file" accept="application/pdf,.pdf,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation,.ppt,.pptx" onChange={handleChange} className="sr-only" />
        <span className="inline-flex h-10 w-10 items-center justify-center rounded bg-teal-700 text-lg font-semibold text-white">
          FILE
        </span>
        <span className="text-sm font-medium text-zinc-800">
          {file ? file.name : "Drop a PDF or PPTX here or choose a file"}
=======
        <input type="file" accept="application/pdf,.pdf" onChange={handleChange} className="sr-only" />
        <span className="inline-flex h-10 w-10 items-center justify-center rounded bg-teal-700 text-lg font-semibold text-white">
          PDF
        </span>
        <span className="text-sm font-medium text-zinc-800">
          {file ? file.name : "Drop a PDF here or choose a file"}
>>>>>>> 3a405dd557e8516741103ff68021fac68d9494dd
        </span>
        {file ? <span className="text-xs text-zinc-500">{file.type || "application/pdf"}</span> : null}
      </label>
    </section>
  );
}
