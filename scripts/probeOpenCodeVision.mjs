import { readFileSync } from "node:fs";
import { request } from "node:https";

const DEFAULT_MODELS = ["mimo-v2.5", "mimo-v2-omni", "mimo-v2.5-pro"];
const API_URL = process.env.OPENCODE_API_URL || "https://opencode.ai/zen/go/v1/chat/completions";
const TEST_IMAGE_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

function loadDotEnv() {
  for (const fileName of [".env", ".env.local"]) {
    let content = "";
    try {
      content = readFileSync(fileName, "utf8");
    } catch {
      continue;
    }

    for (const line of content.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;

      const separatorIndex = trimmed.indexOf("=");
      if (separatorIndex === -1) continue;

      const key = trimmed.slice(0, separatorIndex).trim();
      const value = trimmed.slice(separatorIndex + 1).trim().replace(/^['"]|['"]$/g, "");
      if (key && process.env[key] === undefined) {
        process.env[key] = value;
      }
    }
  }
}

function postJson(payload) {
  const body = JSON.stringify(payload);
  const apiKey = process.env.OPENCODE_API_KEY || "";

  return new Promise((resolve) => {
    const startedAt = performance.now();
    const req = request(
      API_URL,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${apiKey}`,
          "content-type": "application/json",
          "content-length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => {
          data += chunk;
        });
        res.on("end", () => {
          resolve({
            status: res.statusCode,
            elapsedMs: Math.round(performance.now() - startedAt),
            body: data,
          });
        });
      },
    );

    req.on("error", (error) => {
      resolve({
        status: 0,
        elapsedMs: Math.round(performance.now() - startedAt),
        body: error.message,
      });
    });

    req.write(body);
    req.end();
  });
}

async function testModel(model) {
  const payload = {
    model,
    messages: [
      {
        role: "user",
        content: [
          {
            type: "text",
            text: "Answer in English. What color is this 1x1 pixel image?",
          },
          {
            type: "image_url",
            image_url: {
              url: `data:image/png;base64,${TEST_IMAGE_BASE64}`,
            },
          },
        ],
      },
    ],
    max_tokens: 80,
    temperature: 0.1,
  };

  const result = await postJson(payload);
  console.log(`\n--- ${model} ---`);
  console.log(`Status: ${result.status}`);
  console.log(`Latency: ${result.elapsedMs} ms`);

  try {
    const json = JSON.parse(result.body);
    const content = json.choices?.[0]?.message?.content;
    console.log(content ? `Response: ${content}` : JSON.stringify(json, null, 2));
  } catch {
    console.log(`Raw Body: ${result.body.slice(0, 500)}`);
  }
}

loadDotEnv();

if (!process.env.OPENCODE_API_KEY) {
  console.error("OPENCODE_API_KEY is missing. Add it to .env.local first.");
  process.exit(1);
}

const models = process.argv.slice(2);
for (const model of models.length ? models : DEFAULT_MODELS) {
  await testModel(model);
}
