import { request } from "node:https";

const API_URL = process.env.OPENCODE_API_URL || "https://opencode.ai/zen/go/v1/chat/completions";
const API_KEY = process.env.OPENCODE_API_KEY || "";

function readStdin() {
  return new Promise((resolve, reject) => {
    let body = "";

    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      body += chunk;
    });
    process.stdin.on("end", () => resolve(body));
    process.stdin.on("error", reject);
  });
}

function postJson(payload) {
  const body = JSON.stringify(payload);

  return new Promise((resolve) => {
    const req = request(
      API_URL,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${API_KEY}`,
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
            body: data,
          });
        });
      },
    );

    req.on("error", (error) => {
      resolve({
        status: 0,
        body: JSON.stringify({
          error: error.message,
        }),
      });
    });

    req.write(body);
    req.end();
  });
}

if (!API_KEY) {
  console.log(
    JSON.stringify({
      status: 0,
      body: JSON.stringify({
        error: "OPENCODE_API_KEY is not set.",
      }),
    }),
  );
  process.exit(0);
}

try {
  const payload = JSON.parse(await readStdin());
  const result = await postJson(payload);
  console.log(JSON.stringify(result));
} catch (error) {
  console.log(
    JSON.stringify({
      status: 0,
      body: JSON.stringify({
        error: error.message || "OpenCode helper failed.",
      }),
    }),
  );
}
