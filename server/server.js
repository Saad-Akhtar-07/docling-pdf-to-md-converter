import express from "express";
import multer from "multer";
import FormData from "form-data";
import axios from "axios";

const upload = multer();
const app = express();

const GOTENBERG_URL = process.env.GOTENBERG_URL || "http://localhost:3000";
const DOCLING_URL = process.env.DOCLING_URL || "http://localhost:5001";
const PORT = process.env.PORT || 3001;

app.post("/api/convert-ppt", upload.single("file"), async (req, res) => {
  if (!req.file) return res.status(400).send("No file uploaded");

  try {
    // 1) PPT/PPTX → Gotenberg → PDF
    const gForm = new FormData();
    gForm.append("files", req.file.buffer, { filename: req.file.originalname });

    const gResp = await axios.post(`${GOTENBERG_URL}/forms/libreoffice/convert`, gForm, {
      headers: gForm.getHeaders(),
      responseType: "arraybuffer",
      maxContentLength: Infinity,
      maxBodyLength: Infinity,
      timeout: 120000,
    });

    const pdfBuffer = Buffer.from(gResp.data);

    // 2) PDF → Docling Serve → structured JSON + Markdown
    //
    // Parse user options forwarded from the frontend (sent as a JSON string in
    // the "options" form field by pptApi.js). Fall back to safe defaults.
    let userOptions = {};
    if (req.body && req.body.options) {
      try {
        userOptions = JSON.parse(req.body.options);
      } catch {
        // ignore malformed options
      }
    }

    const dForm = new FormData();
    dForm.append("files", pdfBuffer, { filename: "converted.pdf" });
    dForm.append("file",  pdfBuffer, { filename: "converted.pdf" });

    // ---------- Always request BOTH output formats ----------
    // Docling Serve reads repeated form fields for array values.
    // Sending only a JSON blob in "options" is unreliable across versions.
    dForm.append("to_formats", "md");
    dForm.append("to_formats", "json");

    // PPT slides rendered by Gotenberg/LibreOffice become raster image pages,
    // so OCR must be enabled to recover any text from them.
    dForm.append("do_ocr",           String(userOptions.do_ocr    ?? true));
    dForm.append("force_ocr",        String(userOptions.force_ocr ?? true));
    dForm.append("do_table_structure", String(userOptions.do_table_structure ?? true));

    if (userOptions.table_mode)         dForm.append("table_mode",         userOptions.table_mode);
    if (userOptions.image_export_mode)  dForm.append("image_export_mode",  userOptions.image_export_mode);
    if (userOptions.include_images   != null) dForm.append("include_images",  String(userOptions.include_images));
    if (userOptions.images_scale     != null) dForm.append("images_scale",    String(userOptions.images_scale));

    // Also send as a JSON blob; some Docling Serve builds prefer this.
    const doclingPayload = {
      to_formats:          ["md", "json"],
      do_ocr:              userOptions.do_ocr    ?? true,
      force_ocr:           userOptions.force_ocr ?? true,
      do_table_structure:  userOptions.do_table_structure ?? true,
      image_export_mode:   userOptions.image_export_mode  || "embedded",
      include_images:      userOptions.include_images      ?? true,
      images_scale:        userOptions.images_scale        ?? 2,
      ...(userOptions.table_mode ? { table_mode: userOptions.table_mode } : {}),
    };
    dForm.append("options", JSON.stringify(doclingPayload));

    const dResp = await axios.post(`${DOCLING_URL}/v1/convert/file`, dForm, {
      headers: dForm.getHeaders(),
      responseType: "text",       // receive as text so we can inspect before parsing
      maxContentLength: Infinity,
      maxBodyLength: Infinity,
      timeout: 600000,
    });

    const contentType = dResp.headers["content-type"] || "";
    const textBody    = dResp.data;

    if (!/^2/.test(String(dResp.status))) {
      return res.status(502).send(`Docling returned ${dResp.status}: ${textBody}`);
    }

    // If Docling responded with JSON (structured document), forward it directly.
    if (contentType.includes("application/json") || textBody.trim().startsWith("{")) {
      try {
        return res.json(JSON.parse(textBody));
      } catch {
        // JSON parse failed — fall through to markdown wrapper below
      }
    }

    // Last resort: Docling returned raw markdown / plain text.
    return res.json({ markdown: textBody });
  } catch (err) {
    console.error(err?.response?.data || err.message || err);
    const message = err?.response?.data || err.message || String(err);
    return res.status(500).send(`Conversion server error: ${message}`);
  }
});

app.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`PPT->Gotenberg server listening on http://localhost:${PORT}`);
});
