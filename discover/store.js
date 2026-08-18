/* File-backed session store: a returning user continues; the profile evolves. */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const DATA_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "data");
const FILE = join(DATA_DIR, "sessions.json");

let cache = null;
let writeTimer = null;

function loadAll() {
  if (cache) return cache;
  try { cache = JSON.parse(readFileSync(FILE, "utf8")); }
  catch { cache = {}; }
  return cache;
}

export function getSession(id) {
  return loadAll()[id] || null;
}

export function saveSession(state) {
  const all = loadAll();
  all[state.sessionId] = state;
  /* keep the store bounded */
  const ids = Object.keys(all);
  if (ids.length > 500) {
    ids.sort((a, b) => (all[a].engagementSignals?.startedAt || 0) - (all[b].engagementSignals?.startedAt || 0));
    for (const id of ids.slice(0, ids.length - 500)) delete all[id];
  }
  clearTimeout(writeTimer);
  writeTimer = setTimeout(() => {
    try {
      if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });
      writeFileSync(FILE, JSON.stringify(all));
    } catch (e) { console.error("session write failed:", e.message); }
  }, 150);
}
