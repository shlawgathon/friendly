"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser, SyncedAccount } from "@/lib/user-context";
import { ingestInstagram, ingestVoice, getJobStatus } from "@/lib/api";

type Step = "landing" | "instagram" | "voice" | "processing";

export default function Home() {
  const router = useRouter();
  const { user, login, addAccount, updateAccountStatus } = useUser();
  const [step, setStep] = useState<Step>("landing");
  const [username, setUsername] = useState("");
  const [currentJobId, setCurrentJobId] = useState("");
  const [error, setError] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [mediaRecorder, setMediaRecorder] = useState<MediaRecorder | null>(null);
  const [progress, setProgress] = useState("");

  // Redirect logged-in users to dashboard
  useEffect(() => {
    if (user && user.accounts.length > 0 && step === "landing") {
      router.push(`/dashboard`);
    }
  }, [user, step, router]);

  // ── Instagram Sync ──
  const handleInstagramSync = async () => {
    if (!username.trim()) return;
    setError("");
    try {
      const trimmed = username.trim().replace(/^@/, "");
      const session = user || login(trimmed);
      const res = await ingestInstagram(trimmed);
      setCurrentJobId(res.job_id);

      addAccount({
        username: trimmed,
        syncedAt: new Date().toISOString(),
        jobId: res.job_id,
        status: "syncing",
      });

      setStep("voice");
    } catch (e: any) {
      setError(e.message || "Failed to start sync");
    }
  };

  // ── Voice Recording ──
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      const chunks: Blob[] = [];

      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: "audio/webm" });
        setStep("processing");
        try {
          if (user) await ingestVoice(user.userId, blob);
        } catch {}
        await pollJob();
      };

      recorder.start();
      setMediaRecorder(recorder);
      setIsRecording(true);
      setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, 30000);
    } catch {
      setError("Microphone access denied");
    }
  };

  const stopRecording = () => {
    if (mediaRecorder?.state === "recording") {
      mediaRecorder.stop();
      setIsRecording(false);
    }
  };

  const skipVoice = () => {
    setStep("processing");
    pollJob();
  };

  // ── Job Polling ──
  const pollJob = async () => {
    if (!currentJobId) {
      router.push(`/dashboard`);
      return;
    }
    const poll = setInterval(async () => {
      try {
        const job = await getJobStatus(currentJobId);
        setProgress(job.progress?.step || job.status);
        if (job.status === "completed" || job.status === "failed") {
          clearInterval(poll);
          updateAccountStatus(username.trim().replace(/^@/, ""), job.status === "completed" ? "completed" : "failed");
          router.push(`/dashboard`);
        }
      } catch {
        clearInterval(poll);
        router.push(`/dashboard`);
      }
    }, 2000);
  };

  return (
    <main className="min-h-screen flex items-center justify-center relative overflow-hidden">
      {/* Background */}
      <div className="fixed inset-0 z-0">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-purple-600/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-cyan-600/8 rounded-full blur-3xl" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-violet-600/5 rounded-full blur-3xl" />
      </div>

      <div className="relative z-10 w-full max-w-lg mx-auto px-6">
        {/* ── Landing ── */}
        {step === "landing" && (
          <div className="text-center animate-fade-in">
            <div className="mb-8">
              <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-violet-600 to-cyan-500 flex items-center justify-center glow">
                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </div>
              <h1 className="text-5xl font-bold mb-4 bg-gradient-to-r from-white via-violet-200 to-cyan-200 bg-clip-text text-transparent">
                Friendly
              </h1>
              <p className="text-lg text-gray-400 max-w-md mx-auto leading-relaxed">
                Skip the awkward small talk. Find friends who share your
                <span className="text-violet-400 font-medium"> real passions</span>.
              </p>
            </div>
            <button onClick={() => setStep("instagram")} className="btn-primary text-lg px-10 py-4" id="discover-cta">
              Discover Your People
            </button>
            <p className="mt-6 text-sm text-gray-500">No forms. No profiles. Just passions.</p>
          </div>
        )}

        {/* ── Instagram Sync ── */}
        {step === "instagram" && (
          <div className="animate-fade-in">
            <div className="glass p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-pink-500 to-purple-600 flex items-center justify-center">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="white">
                    <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-xl font-semibold">Connect Your Context</h2>
                  <p className="text-sm text-gray-400">We&apos;ll analyze your posts to find your passions</p>
                </div>
              </div>

              <div className="flex gap-3 mb-4">
                <span className="text-gray-500 text-lg mt-2.5">@</span>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="your_instagram_handle"
                  className="input-field flex-1"
                  id="instagram-input"
                  onKeyDown={(e) => e.key === "Enter" && handleInstagramSync()}
                />
              </div>

              {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

              <button
                onClick={handleInstagramSync}
                disabled={!username.trim()}
                className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
                id="sync-btn"
              >
                Sync & Analyze
              </button>

              <p className="text-xs text-gray-500 mt-4 text-center">
                We analyze public post data to map your interests.
              </p>
            </div>
          </div>
        )}

        {/* ── Voice Recording ── */}
        {step === "voice" && (
          <div className="animate-fade-in text-center">
            <div className="glass p-8">
              <h2 className="text-xl font-semibold mb-2">The Vibe Check</h2>
              <p className="text-gray-400 mb-8">
                Tell us what you&apos;re obsessed with right now. Speak freely for 30 seconds.
              </p>

              <div className="relative inline-block mb-8">
                {isRecording && (
                  <>
                    <div className="absolute inset-0 rounded-full bg-violet-500/20 pulse-ring" style={{ width: 128, height: 128, margin: "-16px" }} />
                    <div className="absolute inset-0 rounded-full bg-violet-500/10 pulse-ring" style={{ width: 128, height: 128, margin: "-16px", animationDelay: "0.5s" }} />
                  </>
                )}
                <button
                  onMouseDown={startRecording}
                  onMouseUp={stopRecording}
                  onTouchStart={startRecording}
                  onTouchEnd={stopRecording}
                  className={`w-24 h-24 rounded-full flex items-center justify-center transition-all ${
                    isRecording ? "bg-red-500 scale-110 glow" : "bg-gradient-to-br from-violet-600 to-purple-700 hover:scale-105"
                  }`}
                  id="record-btn"
                >
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="white">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" stroke="white" strokeWidth="2" fill="none" />
                    <line x1="12" y1="19" x2="12" y2="23" stroke="white" strokeWidth="2" />
                    <line x1="8" y1="23" x2="16" y2="23" stroke="white" strokeWidth="2" />
                  </svg>
                </button>
              </div>

              <p className="text-sm text-gray-500 mb-6">
                {isRecording ? "Recording... release to stop" : "Hold to record"}
              </p>

              <button onClick={skipVoice} className="text-gray-500 hover:text-gray-300 text-sm underline" id="skip-voice">
                Skip this step →
              </button>
            </div>
          </div>
        )}

        {/* ── Processing ── */}
        {step === "processing" && (
          <div className="animate-fade-in text-center">
            <div className="relative w-48 h-48 mx-auto mb-8">
              {[0, 1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="absolute top-1/2 left-1/2 w-3 h-3 -mt-1.5 -ml-1.5 rounded-full orbit-particle"
                  style={{
                    background: `hsl(${260 + i * 30}, 80%, ${60 + i * 5}%)`,
                    animationDuration: `${2 + i * 0.5}s`,
                    animationDelay: `${i * 0.3}s`,
                    boxShadow: `0 0 10px hsl(${260 + i * 30}, 80%, 60%)`,
                  }}
                />
              ))}
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-16 rounded-full bg-gradient-to-br from-violet-500 to-cyan-400 glow float" />
            </div>
            <h2 className="text-2xl font-bold mb-2 glow-text">Building your world...</h2>
            <p className="text-gray-400 capitalize">{progress || "Analyzing your passions"}</p>
          </div>
        )}
      </div>
    </main>
  );
}
