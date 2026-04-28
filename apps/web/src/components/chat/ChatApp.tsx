"use client";

import { useEffect, useState } from "react";

import {
  getProviderBranches,
  getProviderProjects,
  getWorkerHealth,
  LocalWorkerClientError,
  openRepository,
  runAgentTask,
  type AgentRunPayload,
  type ProviderBranchSummary,
  type ProviderProjectSummary,
  type RepoOpenPayload,
} from "@/lib/local-worker-client";

import { ChatLayout } from "./ChatLayout";
import { ChatSidebar } from "./ChatSidebar";
import { ChatHeader } from "./ChatHeader";
import { ChatMessages, type ChatMessage } from "./ChatMessages";
import { ChatComposer } from "./ChatComposer";

type ConnectionState = "checking" | "connected" | "unavailable";

export type ChatThread = {
  id: string;
  title: string;
  repoResult: RepoOpenPayload;
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
};

export function ChatApp() {
  // ── Worker / model connection state ──────────────────────────────────────
  const [connectionState, setConnectionState] = useState<ConnectionState>("checking");
  const [configuredRepositorySource, setConfiguredRepositorySource] = useState("");
  const [configuredModelConnectionMode, setConfiguredModelConnectionMode] = useState("");
  const [configuredModelProvider, setConfiguredModelProvider] = useState("");
  const [configuredModelName, setConfiguredModelName] = useState("");

  // ── Provider / project / branch selection ────────────────────────────────
  const [gitProvider, setGitProvider] = useState("gitlab");
  const [selectedProjectPath, setSelectedProjectPath] = useState("");
  const [selectedBranch, setSelectedBranch] = useState("");
  const [useAdvanced, setUseAdvanced] = useState(false);
  const [manualProjectPath, setManualProjectPath] = useState("");
  const [manualBranch, setManualBranch] = useState("");

  const [projectsPending, setProjectsPending] = useState(false);
  const [branchesPending, setBranchesPending] = useState(false);
  const [repoPending, setRepoPending] = useState(false);
  const [questionPending, setQuestionPending] = useState(false);

  const [repoError, setRepoError] = useState<string | null>(null);

  const [projects, setProjects] = useState<ProviderProjectSummary[]>([]);
  const [recentProjects, setRecentProjects] = useState<ProviderProjectSummary[]>([]);
  const [branches, setBranches] = useState<ProviderBranchSummary[]>([]);

  // ── Repository + chat state ───────────────────────────────────────────────
  const [repoResult, setRepoResult] = useState<RepoOpenPayload | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");

  // ── Health check ─────────────────────────────────────────────────────────
  async function refreshHealthCheck(options: { syncProvider?: boolean } = {}) {
    setConnectionState("checking");
    try {
      const payload = await getWorkerHealth();
      setConnectionState("connected");
      const nextSource =
        payload.configured_repository_source || payload.configured_git_provider || "";
      setConfiguredRepositorySource(nextSource);
      setConfiguredModelConnectionMode(payload.configured_model_connection_mode || "");
      setConfiguredModelProvider(payload.configured_model_provider || "");
      setConfiguredModelName(payload.configured_model_name || "");
      if (options.syncProvider && nextSource) setGitProvider(nextSource);
      if (payload.recent_projects?.length) {
        setManualProjectPath((cur) => cur || payload.recent_projects?.[0] || "");
      }
    } catch {
      setConnectionState("unavailable");
      setConfiguredRepositorySource("");
      setConfiguredModelConnectionMode("");
      setConfiguredModelProvider("");
      setConfiguredModelName("");
    }
  }

  useEffect(() => {
    void refreshHealthCheck({ syncProvider: true });
  }, []);

  useEffect(() => {
    if (!activeThreadId || !repoResult) return;
    setThreads((prev) =>
      prev.map((thread) =>
        thread.id === activeThreadId
          ? {
              ...thread,
              repoResult,
              messages,
              updatedAt: new Date(),
            }
          : thread,
      ),
    );
  }, [activeThreadId, messages, repoResult]);

  // ── Load projects when provider changes ──────────────────────────────────
  useEffect(() => {
    if (connectionState !== "connected") return;

    let cancelled = false;
    async function loadProjects() {
      setProjectsPending(true);
      try {
        const payload = await getProviderProjects({ git_provider: gitProvider });
        if (cancelled) return;
        setProjects(payload.projects);
        setRecentProjects(payload.recent_projects);
        const availablePaths = new Set([
          ...payload.projects.map((p) => p.project_path),
          ...payload.recent_projects.map((p) => p.project_path),
        ]);
        if (!selectedProjectPath || !availablePaths.has(selectedProjectPath)) {
          const preferred =
            payload.recent_projects[0]?.project_path ||
            payload.projects[0]?.project_path ||
            "";
          setSelectedProjectPath(preferred);
          setSelectedBranch("");
          setBranches([]);
          setManualBranch("");
          setManualProjectPath(preferred);
        }
      } catch {
        if (cancelled) return;
        setProjects([]);
        setRecentProjects([]);
        setSelectedProjectPath("");
        setSelectedBranch("");
        setBranches([]);
        setManualBranch("");
      } finally {
        if (!cancelled) setProjectsPending(false);
      }
    }
    void loadProjects();
    return () => {
      cancelled = true;
    };
  }, [connectionState, gitProvider]);

  // ── Load branches when project changes ───────────────────────────────────
  useEffect(() => {
    if (connectionState !== "connected" || !selectedProjectPath || useAdvanced) return;

    let cancelled = false;
    async function loadBranches() {
      setBranchesPending(true);
      try {
        const payload = await getProviderBranches({
          git_provider: gitProvider,
          project_path: selectedProjectPath,
        });
        if (cancelled) return;
        setBranches(payload.branches);
        const nextBranch =
          payload.default_branch ||
          payload.branches.find((b) => b.is_default)?.name ||
          payload.branches[0]?.name ||
          "";
        setSelectedBranch(nextBranch);
        setManualBranch((cur) => cur || nextBranch);
      } catch {
        if (cancelled) return;
        setBranches([]);
        setSelectedBranch("");
      } finally {
        if (!cancelled) setBranchesPending(false);
      }
    }
    void loadBranches();
    return () => {
      cancelled = true;
    };
  }, [connectionState, gitProvider, selectedProjectPath, useAdvanced]);

  // ── Derived values ───────────────────────────────────────────────────────
  const effectiveProjectPath = useAdvanced ? manualProjectPath.trim() : selectedProjectPath.trim();
  const effectiveBranch = useAdvanced ? manualBranch.trim() : selectedBranch.trim();
  const branchRequired = gitProvider !== "local";

  function appendMessages(updater: (current: ChatMessage[]) => ChatMessage[]) {
    setMessages(updater);
  }

  function buildThreadTitle(payload: RepoOpenPayload): string {
    const repoName = payload.project_path.split(/[\\/]/).filter(Boolean).at(-1);
    return repoName || payload.project_path;
  }

  function buildSwitchMessage(payload: RepoOpenPayload): ChatMessage {
    return {
      id: `${Date.now()}-context`,
      role: "system",
      content: `Repository switched. New chat started for ${payload.git_provider}:${payload.project_path}${
        payload.branch ? ` @ ${payload.branch}` : ""
      }.`,
      timestamp: new Date(),
    };
  }

  // ── Handlers ─────────────────────────────────────────────────────────────
  async function handleOpenRepo() {
    setRepoPending(true);
    setRepoError(null);

    if (!effectiveProjectPath || (branchRequired && !effectiveBranch)) {
      setRepoPending(false);
      setRepoError(
        branchRequired
          ? "Choose a project and branch, or use the Advanced override fields."
          : "Enter a local project path.",
      );
      return;
    }

    try {
      const payload = await openRepository({
        project_path: effectiveProjectPath,
        branch: effectiveBranch || undefined,
        git_provider: gitProvider.trim() || undefined,
      });
      const nextMessages = [buildSwitchMessage(payload)];
      const nextThread: ChatThread = {
        id: `${Date.now()}-${payload.git_provider}-${payload.project_path}`,
        title: buildThreadTitle(payload),
        repoResult: payload,
        messages: nextMessages,
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      setRepoResult(payload);
      setMessages(nextMessages);
      setActiveThreadId(nextThread.id);
      setThreads((prev) => [nextThread, ...prev]);
      await refreshHealthCheck();
    } catch (error) {
      setRepoResult(null);
      setRepoError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to open the repository through the local worker.",
      );
    } finally {
      setRepoPending(false);
    }
  }

  async function handleQuestionSubmit() {
    if (!question.trim() || questionPending || !repoResult) return;

    const userMessage: ChatMessage = {
      id: `${Date.now()}-user`,
      role: "user",
      content: question.trim(),
      timestamp: new Date(),
    };
    appendMessages((prev) => [...prev, userMessage]);
    setQuestion("");
    setQuestionPending(true);

    try {
      const payload = await runAgentTask({
        project_path: repoResult.project_path,
        git_provider: repoResult.git_provider,
        branch: repoResult.branch || undefined,
        task: userMessage.content,
      });
      appendMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          content: payload.response,
          timestamp: new Date(),
          metadata: payload,
        },
      ]);
    } catch (error) {
      const msg =
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to run the task through the local worker.";
      appendMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-error`,
          role: "assistant",
          content: `Error: ${msg}`,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setQuestionPending(false);
    }
  }

  function handleNewChat() {
    setQuestion("");
    if (!repoResult) {
      setMessages([]);
      setActiveThreadId(null);
      return;
    }
    const nextMessages: ChatMessage[] = [
      {
        id: `${Date.now()}-new-chat`,
        role: "system",
        content: `New chat started for ${repoResult.git_provider}:${repoResult.project_path}${
          repoResult.branch ? ` @ ${repoResult.branch}` : ""
        }.`,
        timestamp: new Date(),
      },
    ];
    const nextThread: ChatThread = {
      id: `${Date.now()}-${repoResult.git_provider}-${repoResult.project_path}`,
      title: buildThreadTitle(repoResult),
      repoResult,
      messages: nextMessages,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    setMessages(nextMessages);
    setActiveThreadId(nextThread.id);
    setThreads((prev) => [nextThread, ...prev]);
  }

  async function handleSelectThread(threadId: string) {
    const thread = threads.find((item) => item.id === threadId);
    if (!thread) return;
    setRepoPending(true);
    setRepoError(null);
    try {
      const reopened = await openRepository({
        project_path: thread.repoResult.project_path,
        git_provider: thread.repoResult.git_provider,
        branch: thread.repoResult.branch || undefined,
      });
      setActiveThreadId(thread.id);
      setRepoResult(reopened);
      setMessages(thread.messages);
      setQuestion("");
    } catch (error) {
      setRepoError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to restore the repository for this thread.",
      );
    } finally {
      setRepoPending(false);
    }
  }

  function handleGitProviderChange(nextProvider: string) {
    setGitProvider(nextProvider);
    setSelectedProjectPath("");
    setSelectedBranch("");
    setBranches([]);
    setProjects([]);
    setRepoResult(null);
    setUseAdvanced(nextProvider === "local");
    if (nextProvider === "local") setManualProjectPath("");
  }

  function handleProjectChange(path: string) {
    setUseAdvanced(false);
    setSelectedProjectPath(path);
    setSelectedBranch("");
    setBranches([]);
    setManualProjectPath(path);
    setRepoResult(null);
  }

  function handleBranchChange(branch: string) {
    setUseAdvanced(false);
    setSelectedBranch(branch);
    setManualBranch(branch);
    setRepoResult(null);
  }

  function handleToggleAdvanced() {
    const next = !useAdvanced;
    setUseAdvanced(next);
    if (next) {
      setManualProjectPath(selectedProjectPath);
      setManualBranch(selectedBranch);
    }
  }

  function handleManualProjectPathChange(v: string) {
    setManualProjectPath(v);
    if (gitProvider === "local") setUseAdvanced(true);
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <ChatLayout
      sidebar={
        <ChatSidebar
          recentProjects={recentProjects}
          threads={threads}
          activeThreadId={activeThreadId}
          onNewChat={handleNewChat}
          onSelectThread={handleSelectThread}
        />
      }
      header={
        <ChatHeader
          connectionState={connectionState}
          configuredModelName={configuredModelName}
          configuredModelProvider={configuredModelProvider}
          gitProvider={gitProvider}
          onGitProviderChange={handleGitProviderChange}
          projects={projects}
          recentProjects={recentProjects}
          projectsPending={projectsPending}
          selectedProjectPath={selectedProjectPath}
          onProjectChange={handleProjectChange}
          branches={branches}
          branchesPending={branchesPending}
          selectedBranch={selectedBranch}
          onBranchChange={handleBranchChange}
          useAdvanced={useAdvanced}
          manualProjectPath={manualProjectPath}
          manualBranch={manualBranch}
          onManualProjectPathChange={handleManualProjectPathChange}
          onManualBranchChange={setManualBranch}
          onToggleAdvanced={handleToggleAdvanced}
          repoPending={repoPending}
          repoError={repoError}
          onOpenRepo={handleOpenRepo}
        />
      }
      messages={
        <ChatMessages
          messages={messages}
          repoResult={repoResult}
          questionPending={questionPending}
          gitProvider={gitProvider}
        />
      }
      composer={
        <ChatComposer
          value={question}
          onChange={setQuestion}
          onSubmit={handleQuestionSubmit}
          disabled={!repoResult}
          pending={questionPending}
        />
      }
    />
  );
}
