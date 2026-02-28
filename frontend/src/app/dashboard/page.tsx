"use client";

import { useEffect, useRef, useState, useCallback, Suspense, useMemo } from "react";
import { useRouter } from "next/navigation";
import * as d3 from "d3";
import { useUser } from "@/lib/user-context";
import { getGraphData, getMatches, getIcebreaker, ingestInstagram, getJobStatus, getEnrichmentStatus, getTopicEnrichment } from "@/lib/api";

interface GraphNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  type: "self" | "user" | "hobby" | "brand" | "event" | "community" | "meetup";
  pic?: string;
  weight?: number;
  isSyncedAccount?: boolean;
}

interface GraphEdge extends d3.SimulationLinkDatum<GraphNode> {
  type: string;
  weight: number;
}

interface EnrichmentData {
  tier2: any | null;
  tier3: any | null;
  status: string;
}

interface TierStatus {
  tier1: "pending" | "running" | "done";
  tier2: "pending" | "running" | "done";
  tier3: "pending" | "running" | "done";
}

interface TopicEnrichmentResult {
  events: any[];
  communities: any[];
  meetups: any[];
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
  const [settingsTab, setSettingsTab] = useState<"account" | "interests">("account");
  const [newUsername, setNewUsername] = useState("");
  const [addError, setAddError] = useState("");
  const [addingAccount, setAddingAccount] = useState(false);
  const [enrichment, setEnrichment] = useState<EnrichmentData | null>(null);
  const [tierStatus, setTierStatus] = useState<TierStatus>({ tier1: "pending", tier2: "pending", tier3: "pending" });
  const [showTimeline, setShowTimeline] = useState(false);
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [topicEnrichmentByNode, setTopicEnrichmentByNode] = useState<Record<string, TopicEnrichmentResult>>({});
  const [topicLoadingNodeId, setTopicLoadingNodeId] = useState<string | null>(null);
  const [topicError, setTopicError] = useState("");
  const [expandedUserInterests, setExpandedUserInterests] = useState<Record<string, boolean>>({});
  const [expandedSettingsProfiles, setExpandedSettingsProfiles] = useState<Record<string, boolean>>({});
  const [expandedSettingsInterests, setExpandedSettingsInterests] = useState<Record<string, boolean>>({});

  // Redirect to landing if no user
  useEffect(() => {
    if (!user) router.push("/");
  }, [user, router]);

  const userId = user?.userId || "";
  const syncedAccountIds = useMemo(
    () => new Set((user?.accounts || []).map((a) => `ig:${a.username.toLowerCase()}`)),
    [user?.accounts]
  );

  const loadGraph = useCallback(async () => {
    if (!userId) return;
    try {
      // Include all synced accounts so their interests show in the graph
      const extraIds = (user?.accounts || [])
        .filter((a) => a.status === "completed")
        .map((a) => `ig:${a.username}`)
        .filter((id) => id !== userId);

      const [gData, matchData] = await Promise.all([
        getGraphData(userId, extraIds),
        getMatches(userId),
      ]);

      const graphWithSyncFlags = {
        ...gData,
        nodes: (gData.nodes || []).map((node: GraphNode) => (
          node.type === "user" && syncedAccountIds.has(node.id)
            ? { ...node, isSyncedAccount: true }
            : node
        )),
      };

      setMatches(matchData.matches || []);
      setGraphData(graphWithSyncFlags);
      renderGraph(graphWithSyncFlags);
    } catch (e) {
      console.error("Graph load error:", e);
    } finally {
      setLoading(false);
    }
  }, [userId, user?.accounts, syncedAccountIds]);

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

      setShowTimeline(true);
      setTierStatus({ tier1: "running", tier2: "pending", tier3: "pending" });

      // Poll job — show graph after tier1_done, continue polling enrichment
      const poll = setInterval(async () => {
        try {
          const job = await getJobStatus(res.job_id);
          if (job.status === "tier1_done" || job.status === "enriching" || job.status === "completed") {
            // Tier 1 done — load graph immediately
            if (tierStatus.tier1 !== "done") {
              setTierStatus((prev) => ({ ...prev, tier1: "done", tier2: "running", tier3: "running" }));
              updateAccountStatus(trimmed, "completed");
              loadGraph();
            }

            // Poll enrichment
            try {
              const enr = await getEnrichmentStatus(res.job_id);
              setEnrichment(enr);
              const t2Done = enr.tier2 !== null;
              const t3Done = enr.tier3 !== null;
              setTierStatus((prev) => ({
                ...prev,
                tier2: t2Done ? "done" : "running",
                tier3: t3Done ? "done" : "running",
              }));
            } catch {}

            if (job.status === "completed") {
              clearInterval(poll);
              setTierStatus({ tier1: "done", tier2: "done", tier3: "done" });
              // Auto-hide timeline after 5s
              setTimeout(() => setShowTimeline(false), 8000);
            }
          } else if (job.status === "failed") {
            clearInterval(poll);
            updateAccountStatus(trimmed, "failed");
            setShowTimeline(false);
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
    setExpandedUserInterests({});
    setTopicError("");
    if (node.type === "user" && userId) {
      try {
        const res = await getIcebreaker(userId, node.id);
        setIcebreaker(res.icebreaker);
        setSharedContext(res.shared_context);
      } catch {
        setIcebreaker("Start by asking about their shared interests!");
        setSharedContext([]);
      }
    } else {
      setIcebreaker("");
      setSharedContext([]);
    }

    if (node.type === "hobby" || node.type === "brand") {
      await loadTopicForInterest(node);
    }
  };

  const handleLogout = () => {
    logout();
    router.push("/");
  };

  const getEdgeNodeId = (nodeOrId: string | GraphNode) =>
    typeof nodeOrId === "string" ? nodeOrId : nodeOrId.id;

  const loadTopicForInterest = async (node: GraphNode) => {
    if (!userId || (node.type !== "hobby" && node.type !== "brand")) return;
    if (topicEnrichmentByNode[node.id]) return;

    setTopicLoadingNodeId(node.id);
    try {
      const res = await getTopicEnrichment(userId, node.label);
      setTopicEnrichmentByNode((prev) => ({
        ...prev,
        [node.id]: {
          events: res.events || [],
          communities: res.communities || [],
          meetups: res.meetups || [],
        },
      }));
    } catch {
      setTopicError("Could not fetch live results. Showing saved graph links.");
    } finally {
      setTopicLoadingNodeId((curr) => (curr === node.id ? null : curr));
    }
  };

  const getGraphTopicChildren = (topicId: string, edgeType: string) => {
    if (!graphData) return [];
    return graphData.edges
      .filter((e) => getEdgeNodeId(e.source as string | GraphNode) === topicId && e.type === edgeType)
      .map((e) => {
        const targetId = getEdgeNodeId(e.target as string | GraphNode);
        return graphData.nodes.find((n) => n.id === targetId);
      })
      .filter(Boolean);
  };

  const selectedUserInterestItems = useMemo(() => {
    if (!selectedNode || (selectedNode.type !== "user" && selectedNode.type !== "self") || !graphData) return [];

    const linkedInterestIds = new Set<string>();
    for (const e of graphData.edges) {
      const srcId = getEdgeNodeId(e.source as string | GraphNode);
      const tgtId = getEdgeNodeId(e.target as string | GraphNode);
      if (srcId === selectedNode.id) linkedInterestIds.add(tgtId);
      if (tgtId === selectedNode.id) linkedInterestIds.add(srcId);
    }

    const selfInterestIds = new Set<string>();
    for (const e of graphData.edges) {
      const srcId = getEdgeNodeId(e.source as string | GraphNode);
      const tgtId = getEdgeNodeId(e.target as string | GraphNode);
      if (srcId === userId) selfInterestIds.add(tgtId);
      if (tgtId === userId) selfInterestIds.add(srcId);
    }

    const sharedSet = new Set(sharedContext.map((s) => s.toLowerCase().trim()));
    return graphData.nodes
      .filter((n) => (n.type === "hobby" || n.type === "brand") && linkedInterestIds.has(n.id))
      .map((n) => ({
        node: n,
        isShared: selfInterestIds.has(n.id) || sharedSet.has(n.label.toLowerCase().trim()),
      }))
      .sort((a, b) => {
        if (a.isShared !== b.isShared) return a.isShared ? -1 : 1;
        return a.node.label.localeCompare(b.node.label);
      });
  }, [selectedNode, graphData, userId, sharedContext]);

  const settingsProfileInterestItems = useMemo(() => {
    if (!graphData) return [];

    const nodeById = new Map(graphData.nodes.map((n) => [n.id, n] as const));
    const selfInterestIds = new Set<string>();
    for (const e of graphData.edges) {
      const srcId = getEdgeNodeId(e.source as string | GraphNode);
      const tgtId = getEdgeNodeId(e.target as string | GraphNode);
      if (srcId === userId) selfInterestIds.add(tgtId);
      if (tgtId === userId) selfInterestIds.add(srcId);
    }

    const profiles = graphData.nodes
      .filter((n) => n.type === "self" || n.type === "user")
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === "self" ? -1 : 1;
        return a.label.localeCompare(b.label);
      });

    return profiles.map((profile) => {
      const interestIds = new Set<string>();
      for (const e of graphData.edges) {
        const srcId = getEdgeNodeId(e.source as string | GraphNode);
        const tgtId = getEdgeNodeId(e.target as string | GraphNode);
        if (srcId === profile.id) {
          const target = nodeById.get(tgtId);
          if (target && (target.type === "hobby" || target.type === "brand")) interestIds.add(target.id);
        }
        if (tgtId === profile.id) {
          const source = nodeById.get(srcId);
          if (source && (source.type === "hobby" || source.type === "brand")) interestIds.add(source.id);
        }
      }

      const interests = Array.from(interestIds)
        .map((id) => nodeById.get(id))
        .filter((n): n is GraphNode => !!n)
        .map((n) => ({ node: n, isMatch: selfInterestIds.has(n.id) }))
        .sort((a, b) => {
          if (a.isMatch !== b.isMatch) return a.isMatch ? -1 : 1;
          return a.node.label.localeCompare(b.node.label);
        });

      return { profile, interests };
    });
  }, [graphData, userId]);

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
        case "event": return "#f43f5e";
        case "community": return "#3b82f6";
        case "meetup": return "#14b8a6";
        default: return "#6b7280";
      }
    };

    const nodeSize = (type: string) => {
      switch (type) {
        case "self": return 28;
        case "user": return 18;
        case "hobby": return 12;
        case "brand": return 14;
        case "event": return 8;
        case "community": return 8;
        case "meetup": return 8;
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
      .attr("class", "graph-node-label")
      .attr("dy", (d) => nodeSize(d.type) + 16)
      .attr("text-anchor", "middle")
      .attr("fill", (d) => sharedNodeIds.has(d.id) ? "#86efac" : "#9ca3af")
      .attr("font-size", (d) => d.type === "hobby" ? "10px" : "12px")
      .attr("font-weight", (d) => d.type === "self" || sharedNodeIds.has(d.id) ? "600" : "400")
      .attr("pointer-events", "none");

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
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-cyan-500" /> Synced Friends</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-sky-400" /> Suggested People</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-amber-500" /> Interests</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-green-500" /> Shared</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-rose-500" /> Events</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-blue-500" /> Communities</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-teal-500" /> Meetups</span>
            </div>

            {/* Account button */}
            <button
              onClick={() => {
                const nextOpen = !showSettings;
                setShowSettings(nextOpen);
                if (nextOpen) setSettingsTab("account");
                setSelectedNode(null);
              }}
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
              <h2 className="text-lg font-semibold">Settings</h2>
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

            <div className="mb-6 p-1 rounded-xl bg-white/5 border border-white/10 flex gap-1">
              <button
                type="button"
                onClick={() => setSettingsTab("account")}
                className={`flex-1 px-3 py-2 text-xs rounded-lg transition-colors ${
                  settingsTab === "account"
                    ? "bg-violet-500/20 text-violet-200 border border-violet-400/30"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Account
              </button>
              <button
                type="button"
                onClick={() => setSettingsTab("interests")}
                className={`flex-1 px-3 py-2 text-xs rounded-lg transition-colors ${
                  settingsTab === "interests"
                    ? "bg-cyan-500/20 text-cyan-200 border border-cyan-400/30"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                Interest Explorer
              </button>
            </div>

            {settingsTab === "account" && (
              <>
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
              </>
            )}

            {/* Interest Explorer */}
            {settingsTab === "interests" && (
            <div className="mb-8">
              <h3 className="text-sm font-medium text-gray-400 mb-3">Interest Explorer</h3>
              <p className="text-xs text-gray-500 mb-3">
                Browse profiles and interests from the sidebar, no graph clicks needed.
              </p>
              <div className="space-y-2">
                {settingsProfileInterestItems.length === 0 && (
                  <div className="glass p-3 text-xs text-gray-500">No profile interests loaded yet.</div>
                )}
                {settingsProfileInterestItems.map(({ profile, interests }) => {
                  const profileOpen = !!expandedSettingsProfiles[profile.id];
                  return (
                    <div key={profile.id} className="glass p-2 rounded-xl">
                      <button
                        type="button"
                        onClick={() => setExpandedSettingsProfiles((prev) => ({ ...prev, [profile.id]: !profileOpen }))}
                        className="w-full flex items-center justify-between px-2 py-1.5 text-left"
                      >
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${profile.type === "self" ? "bg-violet-400" : "bg-cyan-400"}`} />
                          <span className="text-sm font-medium">
                            {profile.type === "self" ? "You" : `@${profile.label}`}
                          </span>
                        </div>
                        <span className="text-xs text-gray-400">
                          {interests.length} interests {profileOpen ? "▾" : "▸"}
                        </span>
                      </button>

                      {profileOpen && (
                        <div className="mt-2 space-y-2 px-1 pb-1">
                          {interests.length === 0 && (
                            <p className="text-[11px] text-gray-500 px-2">No interests found.</p>
                          )}
                          {interests.map((interestItem) => {
                            const interest = interestItem.node;
                            const interestKey = `${profile.id}:${interest.id}`;
                            const interestOpen = !!expandedSettingsInterests[interestKey];
                            const online = topicEnrichmentByNode[interest.id];
                            const events = (online?.events?.length || 0) > 0
                              ? online.events
                              : getGraphTopicChildren(interest.id, "HAS_EVENT");
                            const communities = (online?.communities?.length || 0) > 0
                              ? online.communities
                              : getGraphTopicChildren(interest.id, "HAS_COMMUNITY");
                            const meetups = (online?.meetups?.length || 0) > 0
                              ? online.meetups
                              : getGraphTopicChildren(interest.id, "HAS_MEETUP");

                            return (
                              <div key={interestKey} className="rounded-lg border border-white/10 px-2 py-1.5">
                                <button
                                  type="button"
                                  onClick={() => {
                                    const willExpand = !interestOpen;
                                    setExpandedSettingsInterests((prev) => ({ ...prev, [interestKey]: willExpand }));
                                    if (willExpand) void loadTopicForInterest(interest);
                                  }}
                                  className="w-full flex items-center justify-between text-left"
                                >
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium">{interest.label}</span>
                                    {profile.type !== "self" && interestItem.isMatch && (
                                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                        Interest Match
                                      </span>
                                    )}
                                  </div>
                                  <span className="text-[11px] text-gray-400">{interestOpen ? "▾" : "▸"}</span>
                                </button>

                                {interestOpen && (
                                  <div className="mt-2 space-y-2">
                                    {topicLoadingNodeId === interest.id && !online && (
                                      <p className="text-[11px] text-cyan-400">Loading live results...</p>
                                    )}
                                    {topicError && (
                                      <p className="text-[11px] text-amber-400">{topicError}</p>
                                    )}

                                    <details className="rounded-md border border-white/10 px-2 py-1.5">
                                      <summary className="cursor-pointer text-[11px] text-gray-300">Events ({events.length})</summary>
                                      <div className="mt-1 space-y-1">
                                        {events.length === 0 && <p className="text-[10px] text-gray-500">No events yet.</p>}
                                        {events.slice(0, 3).map((evt: any, i: number) => (
                                          <a
                                            key={i}
                                            href={evt.url || evt.id}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="block text-[11px] text-gray-300 hover:text-rose-300"
                                          >
                                            {evt.title || evt.label}
                                          </a>
                                        ))}
                                      </div>
                                    </details>

                                    <details className="rounded-md border border-white/10 px-2 py-1.5">
                                      <summary className="cursor-pointer text-[11px] text-gray-300">
                                        Communities ({communities.length})
                                      </summary>
                                      <div className="mt-1 space-y-1">
                                        {communities.length === 0 && <p className="text-[10px] text-gray-500">No communities yet.</p>}
                                        {communities.slice(0, 3).map((comm: any, i: number) => (
                                          <a
                                            key={i}
                                            href={comm.url || comm.id}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="block text-[11px] text-gray-300 hover:text-blue-300"
                                          >
                                            {comm.name || comm.label}
                                          </a>
                                        ))}
                                      </div>
                                    </details>

                                    <details className="rounded-md border border-white/10 px-2 py-1.5">
                                      <summary className="cursor-pointer text-[11px] text-gray-300">Meetups ({meetups.length})</summary>
                                      <div className="mt-1 space-y-1">
                                        {meetups.length === 0 && <p className="text-[10px] text-gray-500">No meetups yet.</p>}
                                        {meetups.slice(0, 3).map((mt: any, i: number) => (
                                          <a
                                            key={i}
                                            href={mt.url || mt.id}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="block text-[11px] text-gray-300 hover:text-teal-300"
                                          >
                                            {mt.name || mt.label}
                                          </a>
                                        ))}
                                      </div>
                                    </details>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
            )}

            {settingsTab === "account" && (
              <>
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
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Timeline Overlay ── */}
      {showTimeline && (
        <div className="absolute bottom-6 left-6 z-20 glass p-4 rounded-2xl w-80 animate-fade-in">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Pipeline Progress</h3>
            <button onClick={() => setShowTimeline(false)} className="text-gray-500 hover:text-white text-xs">✕</button>
          </div>
          <div className="space-y-3">
            {/* Tier 1 */}
            <div className="flex items-center gap-3">
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                tierStatus.tier1 === "done" ? "bg-emerald-500/30 text-emerald-400" :
                tierStatus.tier1 === "running" ? "bg-amber-500/30 text-amber-400 animate-pulse" :
                "bg-gray-600/30 text-gray-500"
              }`}>
                {tierStatus.tier1 === "done" ? "✓" : "1"}
              </div>
              <div className="flex-1">
                <p className="text-xs font-medium">Profile Analysis</p>
                <p className="text-[10px] text-gray-500">
                  {tierStatus.tier1 === "done" ? "Scraped, analyzed, entities extracted" :
                   tierStatus.tier1 === "running" ? "Scraping & analyzing..." : "Waiting"}
                </p>
              </div>
            </div>
            {/* Tier 2 */}
            <div className="flex items-center gap-3">
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                tierStatus.tier2 === "done" ? "bg-emerald-500/30 text-emerald-400" :
                tierStatus.tier2 === "running" ? "bg-cyan-500/30 text-cyan-400 animate-pulse" :
                "bg-gray-600/30 text-gray-500"
              }`}>
                {tierStatus.tier2 === "done" ? "✓" : "2"}
              </div>
              <div className="flex-1">
                <p className="text-xs font-medium">Events & Communities</p>
                <p className="text-[10px] text-gray-500">
                  {tierStatus.tier2 === "done"
                    ? `${enrichment?.tier2?.events?.length || 0} events, ${enrichment?.tier2?.communities?.length || 0} communities`
                    : tierStatus.tier2 === "running" ? "Searching Eventbrite, Reddit, Meetup..." : "Waiting"}
                </p>
              </div>
            </div>
            {/* Tier 3 */}
            <div className="flex items-center gap-3">
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                tierStatus.tier3 === "done" ? "bg-emerald-500/30 text-emerald-400" :
                tierStatus.tier3 === "running" ? "bg-violet-500/30 text-violet-400 animate-pulse" :
                "bg-gray-600/30 text-gray-500"
              }`}>
                {tierStatus.tier3 === "done" ? "✓" : "3"}
              </div>
              <div className="flex-1">
                <p className="text-xs font-medium">Vibe Fingerprint</p>
                <p className="text-[10px] text-gray-500">
                  {tierStatus.tier3 === "done"
                    ? `Mood: ${enrichment?.tier3?.vibe?.mood || "—"} · Energy: ${((enrichment?.tier3?.vibe?.energy || 0) * 100).toFixed(0)}%`
                    : tierStatus.tier3 === "running" ? "Analyzing profile vibes..." : "Waiting"}
                </p>
              </div>
            </div>
          </div>
          {/* Progress bar */}
          <div className="mt-3 w-full h-1 rounded-full bg-gray-700 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-violet-500 via-cyan-400 to-emerald-400 transition-all duration-700"
              style={{ width: `${([tierStatus.tier1, tierStatus.tier2, tierStatus.tier3].filter((s) => s === "done").length / 3) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* ── Connection Detail Panel ── */}
      {selectedNode && !showSettings && (
        <div className="w-96 border-l border-white/5 bg-surface/80 backdrop-blur-xl p-6 animate-fade-in overflow-y-auto" style={{ maxHeight: "100vh" }}>
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold">{selectedNode.label}</h2>
            <button onClick={() => setSelectedNode(null)} className="text-gray-500 hover:text-white">✕</button>
          </div>

          {(selectedNode.type === "user" || selectedNode.type === "self") && (
            <>
              {selectedNode.type === "user" && sharedContext.length > 0 && (
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

              <div className="mb-6">
                <h3 className="text-sm font-medium text-gray-400 mb-3">Connected Interests</h3>
                <div className="space-y-2">
                  {selectedUserInterestItems.length === 0 && (
                    <div className="glass p-3 text-xs text-gray-500">No connected interests found yet.</div>
                  )}
                  {selectedUserInterestItems.map((item) => {
                    const isExpanded = !!expandedUserInterests[item.node.id];
                    const online = topicEnrichmentByNode[item.node.id];
                    const events = (online?.events?.length || 0) > 0
                      ? online.events
                      : getGraphTopicChildren(item.node.id, "HAS_EVENT");
                    const communities = (online?.communities?.length || 0) > 0
                      ? online.communities
                      : getGraphTopicChildren(item.node.id, "HAS_COMMUNITY");
                    const meetups = (online?.meetups?.length || 0) > 0
                      ? online.meetups
                      : getGraphTopicChildren(item.node.id, "HAS_MEETUP");

                    return (
                      <div key={item.node.id} className="glass p-2 rounded-xl">
                        <button
                          type="button"
                          onClick={() => {
                            const willExpand = !isExpanded;
                            setExpandedUserInterests((prev) => ({ ...prev, [item.node.id]: willExpand }));
                            if (willExpand) void loadTopicForInterest(item.node);
                          }}
                          className="w-full flex items-center justify-between px-2 py-1.5 text-left"
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">{item.node.label}</span>
                            {item.isShared && (
                              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                                Interest Match
                              </span>
                            )}
                          </div>
                          <span className="text-xs text-gray-400">{isExpanded ? "▾" : "▸"}</span>
                        </button>

                        {isExpanded && (
                          <div className="mt-2 space-y-2 px-1 pb-1">
                            {topicLoadingNodeId === item.node.id && !online && (
                              <p className="text-[11px] text-cyan-400">Loading live results...</p>
                            )}
                            {topicError && (
                              <p className="text-[11px] text-amber-400">{topicError}</p>
                            )}

                            <details className="rounded-lg border border-white/10 px-3 py-2">
                              <summary className="cursor-pointer text-xs font-medium text-gray-300">
                                Events ({events.length})
                              </summary>
                              <div className="mt-2 space-y-2">
                                {events.length === 0 && (
                                  <p className="text-[11px] text-gray-500">No events yet.</p>
                                )}
                                {events.slice(0, 4).map((evt: any, i: number) => (
                                  <a
                                    key={i}
                                    href={evt.url || evt.id}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block rounded-lg border border-white/10 p-2 hover:border-rose-500/30"
                                  >
                                    <p className="text-xs font-medium">{evt.title || evt.label}</p>
                                    <p className="text-[10px] text-gray-500">{evt.date || ""} {evt.location ? `· ${evt.location}` : ""}</p>
                                  </a>
                                ))}
                              </div>
                            </details>

                            <details className="rounded-lg border border-white/10 px-3 py-2">
                              <summary className="cursor-pointer text-xs font-medium text-gray-300">
                                Communities ({communities.length})
                              </summary>
                              <div className="mt-2 space-y-2">
                                {communities.length === 0 && (
                                  <p className="text-[11px] text-gray-500">No communities yet.</p>
                                )}
                                {communities.slice(0, 4).map((comm: any, i: number) => (
                                  <a
                                    key={i}
                                    href={comm.url || comm.id}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block rounded-lg border border-white/10 p-2 hover:border-blue-500/30"
                                  >
                                    <p className="text-xs font-medium">{comm.name || comm.label}</p>
                                    {(comm.subscriber_count || comm.subs || 0) > 0 && (
                                      <p className="text-[10px] text-gray-500">
                                        {(((comm.subscriber_count || comm.subs) as number) / 1000).toFixed(1)}k members
                                      </p>
                                    )}
                                  </a>
                                ))}
                              </div>
                            </details>

                            <details className="rounded-lg border border-white/10 px-3 py-2">
                              <summary className="cursor-pointer text-xs font-medium text-gray-300">
                                Meetups ({meetups.length})
                              </summary>
                              <div className="mt-2 space-y-2">
                                {meetups.length === 0 && (
                                  <p className="text-[11px] text-gray-500">No meetups yet.</p>
                                )}
                                {meetups.slice(0, 4).map((mt: any, i: number) => (
                                  <a
                                    key={i}
                                    href={mt.url || mt.id}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="block rounded-lg border border-white/10 p-2 hover:border-teal-500/30"
                                  >
                                    <p className="text-xs font-medium">{mt.name || mt.label}</p>
                                    <p className="text-[10px] text-gray-500">{mt.date || ""} {mt.location ? `· ${mt.location}` : ""}</p>
                                  </a>
                                ))}
                              </div>
                            </details>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {selectedNode.type === "user" && (
                <div className="gradient-border p-px rounded-xl mb-6">
                  <div className="bg-surface rounded-xl p-4">
                    <h3 className="text-sm font-medium text-gray-400 mb-2">💬 Conversation Starter</h3>
                    <p className="text-sm leading-relaxed">{icebreaker || "Loading..."}</p>
                  </div>
                </div>
              )}

              {/* Vibe info from Tier 3 */}
              {enrichment?.tier3?.vibe?.mood && (
                <div className="glass p-4 rounded-xl mb-4">
                  <h3 className="text-sm font-medium text-gray-400 mb-2">✨ Vibe</h3>
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-lg">{enrichment.tier3.vibe.mood}</span>
                    <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div className="h-full bg-gradient-to-r from-violet-500 to-cyan-400 rounded-full" style={{ width: `${(enrichment.tier3.vibe.energy || 0) * 100}%` }} />
                    </div>
                    <span className="text-xs text-gray-400">{((enrichment.tier3.vibe.energy || 0) * 100).toFixed(0)}%</span>
                  </div>
                  {enrichment.tier3.vibe.aesthetic_tags?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {enrichment.tier3.vibe.aesthetic_tags.map((tag: string) => (
                        <span key={tag} className="px-2 py-0.5 rounded-full text-[10px] bg-violet-500/15 text-violet-300">{tag}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {/* ── Interest / Brand node: show connected profiles ── */}
          {(selectedNode.type === "hobby" || selectedNode.type === "brand") && (
            <div>
              {/* Connected profiles */}
              <h3 className="text-sm font-medium text-gray-400 mb-3">Connected Profiles</h3>
              <div className="space-y-2 mb-6">
                {graphData?.edges
                  .filter((e: any) => {
                    const srcId = typeof e.source === "string" ? e.source : e.source.id;
                    const tgtId = typeof e.target === "string" ? e.target : e.target.id;
                    return srcId === selectedNode.id || tgtId === selectedNode.id;
                  })
                  .map((e: any) => {
                    const srcId = typeof e.source === "string" ? e.source : e.source.id;
                    const tgtId = typeof e.target === "string" ? e.target : e.target.id;
                    const linkedId = srcId === selectedNode.id ? tgtId : srcId;
                    const linkedNode = graphData.nodes.find((n) => n.id === linkedId);
                    if (!linkedNode || (linkedNode.type !== "self" && linkedNode.type !== "user")) return null;
                    return (
                      <div key={linkedId} className="glass p-3 flex items-center gap-3 cursor-pointer hover:border-violet-500/30 transition-colors"
                        onClick={() => handleNodeClick(linkedNode)}>
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                          linkedNode.type === "self"
                            ? "bg-violet-500/20 text-violet-400"
                            : linkedNode.isSyncedAccount
                              ? "bg-cyan-500/20 text-cyan-400"
                              : "bg-sky-500/20 text-sky-400"
                        }`}>
                          {linkedNode.label[0]?.toUpperCase()}
                        </div>
                        <div>
                          <p className="text-sm font-medium">{linkedNode.label}</p>
                          <p className="text-[10px] text-gray-500">
                            {linkedNode.type === "self"
                              ? "You"
                              : linkedNode.isSyncedAccount
                                ? "Synced Friend"
                                : "Suggested Match"}
                          </p>
                        </div>
                      </div>
                    );
                  })}
              </div>

              {topicLoadingNodeId === selectedNode.id && (
                <p className="text-xs text-cyan-400 mb-4">Finding live events, communities, and meetups...</p>
              )}
              {topicError && (
                <p className="text-xs text-amber-400 mb-4">{topicError}</p>
              )}

              {/* Events */}
              {(() => {
                const online = topicEnrichmentByNode[selectedNode.id]?.events || [];
                const connectedEvents = graphData?.edges
                  .filter((e: any) => {
                    const srcId = typeof e.source === "string" ? e.source : e.source.id;
                    return srcId === selectedNode.id && e.type === "HAS_EVENT";
                  })
                  .map((e: any) => {
                    const tgtId = typeof e.target === "string" ? e.target : e.target.id;
                    return graphData.nodes.find((n) => n.id === tgtId);
                  })
                  .filter(Boolean) || [];
                const eventsToShow = online.length > 0 ? online : connectedEvents;
                return eventsToShow.length > 0 ? (
                  <div className="mb-6">
                    <h3 className="text-sm font-medium text-gray-400 mb-3">🎫 Events</h3>
                    <div className="space-y-2">
                      {eventsToShow.slice(0, 5).map((evt: any, i: number) => (
                        <a
                          key={i}
                          href={evt.url || evt.id}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="glass p-3 block hover:border-rose-500/30 transition-colors group"
                        >
                          <p className="text-sm font-medium group-hover:text-rose-400 transition-colors">
                            {evt.title || evt.label}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            {(evt.date || "").trim() && <span className="text-[10px] text-amber-400">📅 {evt.date}</span>}
                            {(evt.location || "").trim() && <span className="text-[10px] text-gray-500">📍 {evt.location}</span>}
                          </div>
                          {(evt.description || evt.desc) && (
                            <p className="text-[10px] text-gray-500 mt-1 line-clamp-2">{evt.description || evt.desc}</p>
                          )}
                        </a>
                      ))}
                    </div>
                  </div>
                ) : null;
              })()}

              {/* Communities */}
              {(() => {
                const online = topicEnrichmentByNode[selectedNode.id]?.communities || [];
                const connectedComms = graphData?.edges
                  .filter((e: any) => {
                    const srcId = typeof e.source === "string" ? e.source : e.source.id;
                    return srcId === selectedNode.id && e.type === "HAS_COMMUNITY";
                  })
                  .map((e: any) => {
                    const tgtId = typeof e.target === "string" ? e.target : e.target.id;
                    return graphData.nodes.find((n) => n.id === tgtId);
                  })
                  .filter(Boolean) || [];
                const communitiesToShow = online.length > 0 ? online : connectedComms;
                return communitiesToShow.length > 0 ? (
                  <div className="mb-6">
                    <h3 className="text-sm font-medium text-gray-400 mb-3">💬 Communities</h3>
                    <div className="space-y-2">
                      {communitiesToShow.slice(0, 4).map((comm: any, i: number) => (
                        <a
                          key={i}
                          href={comm.url || comm.id}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="glass p-3 block hover:border-blue-500/30 transition-colors group"
                        >
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-medium group-hover:text-blue-400 transition-colors">{comm.name || comm.label}</p>
                            {(comm.subscriber_count || comm.subs || 0) > 0 && (
                              <span className="text-[10px] text-gray-500">
                                {(((comm.subscriber_count || comm.subs) as number) / 1000).toFixed(1)}k
                              </span>
                            )}
                          </div>
                          {(comm.description || comm.desc) && (
                            <p className="text-[10px] text-gray-500 mt-1 line-clamp-2">{comm.description || comm.desc}</p>
                          )}
                        </a>
                      ))}
                    </div>
                  </div>
                ) : null;
              })()}

              {/* Meetups */}
              {(() => {
                const online = topicEnrichmentByNode[selectedNode.id]?.meetups || [];
                const connectedMeetups = graphData?.edges
                  .filter((e: any) => {
                    const srcId = typeof e.source === "string" ? e.source : e.source.id;
                    return srcId === selectedNode.id && e.type === "HAS_MEETUP";
                  })
                  .map((e: any) => {
                    const tgtId = typeof e.target === "string" ? e.target : e.target.id;
                    return graphData.nodes.find((n) => n.id === tgtId);
                  })
                  .filter(Boolean) || [];
                const meetupsToShow = online.length > 0 ? online : connectedMeetups;
                return meetupsToShow.length > 0 ? (
                  <div className="mb-6">
                    <h3 className="text-sm font-medium text-gray-400 mb-3">🤝 Meetups</h3>
                    <div className="space-y-2">
                      {meetupsToShow.slice(0, 4).map((mt: any, i: number) => (
                        <a
                          key={i}
                          href={mt.url || mt.id}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="glass p-3 block hover:border-teal-500/30 transition-colors group"
                        >
                          <p className="text-sm font-medium group-hover:text-teal-400 transition-colors">{mt.name || mt.label}</p>
                          <div className="flex items-center gap-2 mt-1">
                            {(mt.date || "").trim() && <span className="text-[10px] text-amber-400">📅 {mt.date}</span>}
                            {(mt.location || "").trim() && <span className="text-[10px] text-gray-500">📍 {mt.location}</span>}
                            {(mt.attendees || 0) > 0 && <span className="text-[10px] text-gray-500">👥 {mt.attendees}</span>}
                          </div>
                        </a>
                      ))}
                    </div>
                  </div>
                ) : null;
              })()}
            </div>
          )}
        </div>
      )}

      {!showSettings && !selectedNode && (
        <div className="absolute bottom-6 right-6 z-20 glass p-3 rounded-xl text-xs text-gray-300 max-w-xs">
          <p className="font-medium text-white mb-1">Quick tips</p>
          <p>Drag to move nodes, scroll to zoom, click any node for details and live links.</p>
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
