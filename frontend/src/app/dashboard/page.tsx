"use client";

import { useEffect, useRef, useState, useCallback, Suspense } from "react";
import { useRouter } from "next/navigation";
import * as d3 from "d3";
import { useUser, SyncedAccount } from "@/lib/user-context";
import { getGraphData, getMatches, getIcebreaker, ingestInstagram, getJobStatus } from "@/lib/api";

interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  type: "self" | "user" | "hobby" | "brand";
  pic?: string;
  weight?: number;
}

interface GraphEdge extends d3.SimulationLinkDatum<GraphNode> {
  type: string;
  weight: number;
}

function DashboardContent() {
  const router = useRouter();
  const { user, logout, addAccount, updateAccountStatus, removeAccount } = useUser();
  const svgRef = useRef<SVGSVGElement>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [icebreaker, setIcebreaker] = useState("");
  const [sharedContext, setSharedContext] = useState<string[]>([]);
  const [matches, setMatches] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [addError, setAddError] = useState("");
  const [addingAccount, setAddingAccount] = useState(false);

  // Redirect to landing if no user
  useEffect(() => {
    if (!user) router.push("/");
  }, [user, router]);

  const userId = user?.userId || "";

  const loadGraph = useCallback(async () => {
    if (!userId) return;
    try {
      // Include all synced accounts so their interests show in the graph
      const extraIds = (user?.accounts || [])
        .filter((a) => a.status === "completed")
        .map((a) => `ig:${a.username}`)
        .filter((id) => id !== userId);

      const [graphData, matchData] = await Promise.all([
        getGraphData(userId, extraIds),
        getMatches(userId),
      ]);
      setMatches(matchData.matches || []);
      renderGraph(graphData);
    } catch (e) {
      console.error("Graph load error:", e);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // ── Add Another Account ──
  const handleAddAccount = async () => {
    const trimmed = newUsername.trim().replace(/^@/, "").toLowerCase();
    if (!trimmed) return;

    // Duplicate check
    if (user?.accounts.some((a) => a.username === trimmed)) {
      setAddError(`@${trimmed} is already synced`);
      return;
    }

    setAddError("");
    setAddingAccount(true);

    try {
      const res = await ingestInstagram(trimmed, 10, true);
      addAccount({
        username: trimmed,
        syncedAt: new Date().toISOString(),
        jobId: res.job_id,
        status: "syncing",
      });
      setNewUsername("");

      // Poll this job in the background
      const poll = setInterval(async () => {
        try {
          const job = await getJobStatus(res.job_id);
          if (job.status === "completed" || job.status === "failed") {
            clearInterval(poll);
            updateAccountStatus(trimmed, job.status === "completed" ? "completed" : "failed");
            loadGraph(); // Refresh graph with new data
          }
        } catch {
          clearInterval(poll);
        }
      }, 3000);
    } catch (e: any) {
      setAddError(e.message || "Failed to add account");
    } finally {
      setAddingAccount(false);
    }
  };

  const handleNodeClick = async (node: GraphNode) => {
    setSelectedNode(node);
    setShowSettings(false);
    if (node.type === "user" && userId) {
      try {
        const res = await getIcebreaker(userId, node.id);
        setIcebreaker(res.icebreaker);
        setSharedContext(res.shared_context);
      } catch {
        setIcebreaker("Start by asking about their shared interests!");
        setSharedContext([]);
      }
    }
  };

  const handleLogout = () => {
    logout();
    router.push("/");
  };

  const renderGraph = (data: { nodes: GraphNode[]; edges: GraphEdge[] }) => {
    if (!svgRef.current || !data.nodes.length) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;
    const g = svg.append("g");

    svg.call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 3])
        .on("zoom", (e) => g.attr("transform", e.transform)) as any
    );

    // Detect shared nodes: interests/brands connected to 2+ different users
    const userTypes = new Set(["self", "user"]);
    const nodeConnections = new Map<string, Set<string>>(); // nodeId → set of user IDs
    for (const edge of data.edges) {
      const src = typeof edge.source === "string" ? edge.source : (edge.source as any).id;
      const tgt = typeof edge.target === "string" ? edge.target : (edge.target as any).id;
      const srcNode = data.nodes.find((n) => n.id === src);
      const tgtNode = data.nodes.find((n) => n.id === tgt);
      if (srcNode && userTypes.has(srcNode.type)) {
        if (!nodeConnections.has(tgt)) nodeConnections.set(tgt, new Set());
        nodeConnections.get(tgt)!.add(src);
      }
      if (tgtNode && userTypes.has(tgtNode.type)) {
        if (!nodeConnections.has(src)) nodeConnections.set(src, new Set());
        nodeConnections.get(src)!.add(tgt);
      }
    }
    const sharedNodeIds = new Set<string>();
    for (const [nodeId, users] of nodeConnections) {
      if (users.size >= 2) sharedNodeIds.add(nodeId);
    }

    const typeColor = (d: GraphNode) => {
      if ((d.type === "hobby" || d.type === "brand") && sharedNodeIds.has(d.id)) return "#22c55e";
      switch (d.type) {
        case "self": return "#7c3aed";
        case "user": return "#06b6d4";
        case "hobby": return "#f59e0b";
        case "brand": return "#f59e0b";
        default: return "#6b7280";
      }
    };

    const nodeSize = (type: string) => {
      switch (type) {
        case "self": return 28;
        case "user": return 18;
        case "hobby": return 12;
        case "brand": return 14;
        default: return 10;
      }
    };

    // Check if an edge touches a shared node
    const isSharedEdge = (edge: any) => {
      const tgtId = typeof edge.target === "string" ? edge.target : edge.target.id;
      const srcId = typeof edge.source === "string" ? edge.source : edge.source.id;
      return sharedNodeIds.has(tgtId) || sharedNodeIds.has(srcId);
    };

    const simulation = d3.forceSimulation<GraphNode>(data.nodes)
      .force("link", d3.forceLink<GraphNode, GraphEdge>(data.edges)
        .id((d) => d.id).distance(120).strength((d) => (d.weight || 0.5) * 0.3))
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius((d: any) => nodeSize(d.type) + 10));

    const link = g.append("g").selectAll("line").data(data.edges).join("line")
      .attr("stroke", (d: any) => isSharedEdge(d) ? "rgba(255, 255, 255, 0.35)" : "rgba(124, 58, 237, 0.2)")
      .attr("stroke-width", (d: any) => isSharedEdge(d) ? Math.max(2, (d.weight || 0.5) * 4) : Math.max(1, (d.weight || 0.5) * 3));

    const node = g.append("g").selectAll("g").data(data.nodes).join("g")
      .style("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, GraphNode>()
          .on("start", (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on("end", (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }) as any
      )
      .on("click", (_, d) => handleNodeClick(d));

    const defs = svg.append("defs");
    const filter = defs.append("filter").attr("id", "glow");
    filter.append("feGaussianBlur").attr("stdDeviation", "4").attr("result", "blur");
    filter.append("feMerge").selectAll("feMergeNode")
      .data(["blur", "SourceGraphic"]).join("feMergeNode").attr("in", (d) => d);

    node.append("circle")
      .attr("r", (d) => nodeSize(d.type))
      .attr("fill", (d) => typeColor(d))
      .attr("filter", (d) => d.type === "self" || sharedNodeIds.has(d.id) ? "url(#glow)" : "none")
      .attr("opacity", 0.9);

    node.append("text")
      .text((d) => d.label)
      .attr("dy", (d) => nodeSize(d.type) + 16)
      .attr("text-anchor", "middle")
      .attr("fill", (d) => sharedNodeIds.has(d.id) ? "#86efac" : "#9ca3af")
      .attr("font-size", (d) => d.type === "hobby" ? "10px" : "12px")
      .attr("font-weight", (d) => d.type === "self" || sharedNodeIds.has(d.id) ? "600" : "400");

    node.on("mouseover", function (_, d) {
      d3.select(this).select("circle").transition().duration(200)
        .attr("r", nodeSize(d.type) * 1.3).attr("filter", "url(#glow)");
      link.attr("stroke", (l: any) =>
        l.source.id === d.id || l.target.id === d.id ? "rgba(255, 255, 255, 0.7)" : isSharedEdge(l) ? "rgba(255, 255, 255, 0.15)" : "rgba(124, 58, 237, 0.1)"
      ).attr("stroke-width", (l: any) =>
        l.source.id === d.id || l.target.id === d.id ? 3 : 1
      );
    }).on("mouseout", function (_, d) {
      d3.select(this).select("circle").transition().duration(200)
        .attr("r", nodeSize(d.type))
        .attr("filter", d.type === "self" || sharedNodeIds.has(d.id) ? "url(#glow)" : "none");
      link.attr("stroke", (l: any) => isSharedEdge(l) ? "rgba(255, 255, 255, 0.35)" : "rgba(124, 58, 237, 0.2)")
        .attr("stroke-width", (l: any) => isSharedEdge(l) ? Math.max(2, ((l as GraphEdge).weight || 0.5) * 4) : Math.max(1, ((l as GraphEdge).weight || 0.5) * 3));
    });

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x).attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x).attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });
  };

  if (!user) return null;

  return (
    <div className="min-h-screen flex">
      {/* Graph area */}
      <div className="flex-1 relative">
        {/* Header */}
        <div className="absolute top-0 left-0 right-0 z-10 p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600 to-cyan-500 flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
            </div>
            <h1 className="text-lg font-semibold">Friendly</h1>
          </div>

          <div className="flex items-center gap-3">
            {/* Legend */}
            <div className="glass px-4 py-2 flex gap-4 text-xs">
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-violet-600" /> You</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-cyan-500" /> People</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-amber-500" /> Interests</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-green-500" /> Shared</span>
            </div>

            {/* Account button */}
            <button
              onClick={() => { setShowSettings(!showSettings); setSelectedNode(null); }}
              className="glass w-10 h-10 rounded-full flex items-center justify-center hover:border-violet-500/50 transition-colors"
              id="account-btn"
            >
              <span className="text-sm font-semibold text-violet-400">
                {user.displayName[0]?.toUpperCase()}
              </span>
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-violet-600/20 animate-pulse" />
              <p className="text-gray-400">Loading your world...</p>
            </div>
          </div>
        ) : (
          <svg ref={svgRef} className="w-full h-screen" />
        )}
      </div>

      {/* ── Settings Panel ── */}
      {showSettings && (
        <div className="w-96 border-l border-white/5 bg-surface/80 backdrop-blur-xl animate-fade-in overflow-y-auto">
          <div className="p-6">
            {/* Profile header */}
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold">Account</h2>
              <button onClick={() => setShowSettings(false)} className="text-gray-500 hover:text-white">✕</button>
            </div>

            <div className="flex items-center gap-3 mb-8">
              <div className="w-12 h-12 rounded-full bg-gradient-to-br from-violet-600 to-cyan-500 flex items-center justify-center text-lg font-bold">
                {user.displayName[0]?.toUpperCase()}
              </div>
              <div>
                <p className="font-medium">@{user.displayName}</p>
                <p className="text-xs text-gray-500">Joined {new Date(user.createdAt).toLocaleDateString()}</p>
              </div>
            </div>

            {/* Synced Accounts */}
            <div className="mb-8">
              <h3 className="text-sm font-medium text-gray-400 mb-3">Synced Accounts</h3>
              <div className="space-y-2">
                {user.accounts.length === 0 && (
                  <p className="text-sm text-gray-500">No accounts synced yet</p>
                )}
                {user.accounts.map((acc) => (
                  <div key={acc.username} className="glass p-3 flex items-center justify-between group">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-pink-500 to-purple-600 flex items-center justify-center">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="white">
                          <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069z" />
                        </svg>
                      </div>
                      <div>
                        <p className="text-sm font-medium">@{acc.username}</p>
                        <p className="text-xs text-gray-500">
                          {new Date(acc.syncedAt).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        acc.status === "completed" ? "bg-emerald-500/20 text-emerald-400" :
                        acc.status === "syncing" ? "bg-amber-500/20 text-amber-400" :
                        "bg-red-500/20 text-red-400"
                      }`}>
                        {acc.status === "syncing" ? "Syncing..." : acc.status === "completed" ? "Synced" : "Failed"}
                      </span>
                      <button
                        onClick={() => removeAccount(acc.username)}
                        className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400 transition-all text-sm"
                        title="Remove account"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Add Another Account */}
            <div className="mb-8">
              <h3 className="text-sm font-medium text-gray-400 mb-3">Add Another Account</h3>
              <div className="flex gap-2">
                <div className="flex-1 flex gap-2 items-center">
                  <span className="text-gray-500 text-sm">@</span>
                  <input
                    type="text"
                    value={newUsername}
                    onChange={(e) => setNewUsername(e.target.value)}
                    placeholder="username"
                    className="input-field flex-1 text-sm py-2"
                    id="add-account-input"
                    onKeyDown={(e) => e.key === "Enter" && handleAddAccount()}
                  />
                </div>
                <button
                  onClick={handleAddAccount}
                  disabled={!newUsername.trim() || addingAccount}
                  className="btn-primary py-2 px-4 text-sm disabled:opacity-50"
                  id="add-account-btn"
                >
                  {addingAccount ? "..." : "Sync"}
                </button>
              </div>
              {addError && <p className="text-red-400 text-xs mt-2">{addError}</p>}
              <p className="text-xs text-gray-500 mt-2">
                Add a friend&apos;s account to find shared interests
              </p>
            </div>

            {/* Actions */}
            <div className="space-y-2">
              <button
                onClick={loadGraph}
                className="btn-secondary w-full text-sm py-2.5"
                id="refresh-btn"
              >
                ↻ Refresh Graph
              </button>
              <button
                onClick={handleLogout}
                className="w-full text-sm py-2.5 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-xl transition-colors"
                id="logout-btn"
              >
                Sign Out
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Connection Detail Panel ── */}
      {selectedNode && !showSettings && (
        <div className="w-96 border-l border-white/5 bg-surface/80 backdrop-blur-xl p-6 animate-fade-in overflow-y-auto">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold">{selectedNode.label}</h2>
            <button onClick={() => setSelectedNode(null)} className="text-gray-500 hover:text-white">✕</button>
          </div>

          {selectedNode.type === "user" && (
            <>
              {sharedContext.length > 0 && (
                <div className="mb-6">
                  <h3 className="text-sm font-medium text-gray-400 mb-3">Shared Interests</h3>
                  <div className="flex flex-wrap gap-2">
                    {sharedContext.map((s) => (
                      <span key={s} className="px-3 py-1 rounded-full text-xs bg-violet-500/20 text-violet-300 border border-violet-500/30">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div className="gradient-border p-px rounded-xl">
                <div className="bg-surface rounded-xl p-4">
                  <h3 className="text-sm font-medium text-gray-400 mb-2">💬 Conversation Starter</h3>
                  <p className="text-sm leading-relaxed">{icebreaker || "Loading..."}</p>
                </div>
              </div>
            </>
          )}

          {selectedNode.type === "hobby" && (
            <div>
              <h3 className="text-sm font-medium text-gray-400 mb-3">People who share this interest</h3>
              <div className="space-y-2">
                {matches
                  .filter((m) => m.shared_interests?.includes(selectedNode.label))
                  .map((m) => (
                    <div key={m.user_id} className="glass p-3 flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-cyan-500/20 flex items-center justify-center text-sm">
                        {m.username?.[0]?.toUpperCase() || "?"}
                      </div>
                      <div>
                        <p className="text-sm font-medium">{m.username}</p>
                        <p className="text-xs text-gray-500">Affinity: {(m.affinity * 100).toFixed(0)}%</p>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-400">Loading...</p>
      </div>
    }>
      <DashboardContent />
    </Suspense>
  );
}
