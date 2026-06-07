export async function convertPptWithServer({ file, options, endpoint = "/api/convert-ppt" }) {
  const form = new FormData();
  form.append("file", file, file.name);

  if (options) {
    try {
      form.append("options", JSON.stringify({
        to_formats: ["md", "json"],
        do_ocr: options.doOcr,
        force_ocr: options.forceOcr,
        do_table_structure: options.doTableStructure,
        table_mode: options.tableMode,
        image_export_mode: "embedded",
        include_images: options.includeImages,
        images_scale: options.imagesScale,
      }));
    } catch {}
  }

  const resp = await fetch(endpoint, { method: "POST", body: form });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Server conversion failed: ${text}`);
  }

  const contentType = resp.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await resp.json() : await resp.text();
  return body;
}
