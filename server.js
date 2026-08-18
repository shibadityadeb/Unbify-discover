/* UNBIFY Discover — static site + Experience Orchestrator API.
   Run: node server.js  (LITELLM_KEY in env or .env enables the AI director;
   without it, the curated fallback library drives the full journey.) */

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { newState, nextInteraction, applyResponse } from "./discover/orchestrator.js";
import { getSession, saveSession } from "./discover/store.js";
import { aiAvailable } from "./discover/ai.js";

const ROOT = join(fileURLToPath(import.meta.url), "..");
const PORT = process.env.PORT || 4574;

const MIME = {
  ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8", ".json": "application/json",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2",
};

const CHAPTER_ORDER = ["self_discovery", "reflection", "alignment", "transformation"];

async function handleApi(req, res, path) {
  const body = await readBody(req);
  if (path === "/api/health") return sendJson(res, 200, { ok: true, ai: aiAvailable() });

  if (path === "/api/discover/session" && req.method === "POST") {
    let state = body.sessionId ? getSession(body.sessionId) : null;
    if (!state) state = newState();
    /* entering via a chapter opener may fast-forward (never rewind) the chapter */
    if (body.chapter && CHAPTER_ORDER.includes(body.chapter)) {
      if (CHAPTER_ORDER.indexOf(body.chapter) > CHAPTER_ORDER.indexOf(state.chapter)) {
        state.chapter = body.chapter;
        state.sinceReveal = 0;
        state.revealsThisChapter = 0;
        state.pending = null;
      }
    }
    const next = await nextInteraction(state);
    saveSession(state);
    return sendJson(res, 200, { sessionId: state.sessionId, ...next });
  }

  if (path === "/api/discover/respond" && req.method === "POST") {
    const state = getSession(body.sessionId);
    if (!state) return sendJson(res, 404, { error: "unknown session" });
    const result = await applyResponse(state, body.interactionId, body.response || {}, body.elapsedMs);
    if (!result.ok) {
      /* stale double-submit: just re-issue the pending or next interaction */
      const next = await nextInteraction(state);
      saveSession(state);
      return sendJson(res, 200, { sessionId: state.sessionId, ...next });
    }
    const next = await nextInteraction(state);
    saveSession(state);
    return sendJson(res, 200, { sessionId: state.sessionId, ...next });
  }

  return sendJson(res, 404, { error: "not found" });
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://localhost");
    const path = url.pathname;
    if (path.startsWith("/api/")) return await handleApi(req, res, path);

    /* static */
    let file = path === "/" ? "/index.html" : path;
    file = normalize(file).replace(/^(\.\.[/\\])+/, "");
    if (file.includes("..")) { res.writeHead(403); return res.end(); }
    try {
      const data = await readFile(join(ROOT, file));
      res.writeHead(200, { "Content-Type": MIME[extname(file)] || "application/octet-stream", "Cache-Control": "no-cache" });
      res.end(data);
    } catch {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("not found");
    }
  } catch (e) {
    console.error(e);
    sendJson(res, 500, { error: "server error" });
  }
});

function readBody(req) {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", c => { data += c; if (data.length > 100000) req.destroy(); });
    req.on("end", () => { try { resolve(JSON.parse(data || "{}")); } catch { resolve({}); } });
    req.on("error", () => resolve({}));
  });
}

function sendJson(res, code, obj) {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(obj));
}

server.listen(PORT, () => {
  console.log(`UNBIFY Discover on http://localhost:${PORT}  (AI director: ${aiAvailable() ? "live" : "fallback library"})`);
});
