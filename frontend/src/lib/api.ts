const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const IS_LOCAL = typeof window !== "undefined" && window.location.hostname === "localhost";

export async function ingestInstagram(username: string, maxPosts: number = 10, force?: boolean) {
  const shouldForce = force ?? IS_LOCAL;
  const url = new URL(`${API_BASE}/api/ingest/instagram`);
  if (shouldForce) url.searchParams.set("force", "true");
  const res = await fetch(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, max_posts: maxPosts, include_reels: true }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Ingest failed (${res.status})`);
  }
  return res.json();
}

export async function ingestVoice(userId: string, audioBlob: Blob) {
  const form = new FormData();
  form.append("user_id", userId);
  form.append("audio", audioBlob, "recording.webm");
  const res = await fetch(`${API_BASE}/api/ingest/voice`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error("Voice ingest failed");
  return res.json();
}

export async function getJobStatus(jobId: string) {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
  if (!res.ok) throw new Error("Job not found");
  return res.json();
}

export async function getMatches(userId: string) {
  const res = await fetch(`${API_BASE}/api/discover/matches?user_id=${userId}`);
  if (!res.ok) throw new Error("Matches failed");
  return res.json();
}

export async function getGraphData(userId: string, extraIds: string[] = []) {
  const params = new URLSearchParams({ user_id: userId });
  for (const id of extraIds) params.append("extra_ids", id);
  const res = await fetch(`${API_BASE}/api/discover/graph?${params}`);
  if (!res.ok) throw new Error("Graph failed");
  return res.json();
}

export async function getIcebreaker(userId: string, targetUserId: string) {
  const res = await fetch(`${API_BASE}/api/chat/icebreaker`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, target_user_id: targetUserId }),
  });
  if (!res.ok) throw new Error("Icebreaker failed");
  return res.json();
}

export async function getEnrichmentStatus(jobId: string) {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/enrichment`);
  if (!res.ok) throw new Error("Enrichment status failed");
  return res.json();
}

export async function getSession(userId: string) {
  const res = await fetch(`${API_BASE}/api/discover/session?user_id=${userId}`);
  if (!res.ok) throw new Error("Session restore failed");
  return res.json();
}
