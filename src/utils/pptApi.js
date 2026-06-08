export const GOTENBERG_PROXY_BASE_URL = "/gotenberg";
export const DEFAULT_GOTENBERG_BASE_URL =
  import.meta.env.VITE_GOTENBERG_BASE_URL || GOTENBERG_PROXY_BASE_URL;

const CONVERT_PATH = "/forms/libreoffice/convert";

function normalizeBaseUrl(baseUrl) {
  return baseUrl.replace(/\/$/, "");
}

function buildPdfFileName(fileName) {
  return fileName.replace(/\.(pptx?|odp)$/i, "") + ".pdf";
}

export async function convertPptToPdf({ file, baseUrl = DEFAULT_GOTENBERG_BASE_URL }) {
  const form = new FormData();
  form.append("files", file, file.name);

  const response = await fetch(`${normalizeBaseUrl(baseUrl)}${CONVERT_PATH}`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`PowerPoint to PDF conversion failed: ${text}`);
  }

  const pdfBlob = await response.blob();
  return new File([pdfBlob], buildPdfFileName(file.name), { type: "application/pdf" });
}
