"use client";

import { useEffect, useRef, useState } from "react";

import {
  getProviderBranches,
  getProviderProjects,
  getRecentProjects,
  getRepositoryOpenPlan,
  getWorkerHealth,
  listThreads,
  LocalWorkerClientError,
  openRepository,
  proposeFileEdit,
  runAgentTask,
  saveThread,
  type AgentRunPayload,
  type ProviderBranchSummary,
  type ProviderProjectSummary,
  type RepoOpenPayload,
  type ThreadRecordPayload,
} from "@/lib/local-worker-client";
import {
  proposalFromPayload,
  type ChangeProposal,
  type ProposalStatus,
} from "./ProposalCard";

import { ChatLayout } from "./ChatLayout";
import { ChatSidebar } from "./ChatSidebar";
import { ChatHeader } from "./ChatHeader";
import { ChatMessages, type ChatMessage } from "./ChatMessages";
import { ChatComposer } from "./ChatComposer";

type ConnectionState = "checking" | "connected" | "unavailable";
type ThreadStoreState = "loading" | "connected" | "saving" | "unavailable";
export type RepositoryOpenMode = "clone" | "refresh" | "local" | "unknown";
export type RepositoryOpenProgress = {
  requestId: string;
  mode: RepositoryOpenMode;
  projectPath: string;
  gitProvider: string;
  branch: string;
  startedAt: number;
};

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
  const [repositoryOpenProgress, setRepositoryOpenProgress] =
    useState<RepositoryOpenProgress | null>(null);
  const [questionPending, setQuestionPending] = useState(false);

  const [repoError, setRepoError] = useState<string | null>(null);

  const [projects, setProjects] = useState<ProviderProjectSummary[]>([]);
  const [recentProjects, setRecentProjects] = useState<ProviderProjectSummary[]>([]);
  const [recentProjectHistory, setRecentProjectHistory] = useState<ProviderProjectSummary[]>([]);
  const [branches, setBranches] = useState<ProviderBranchSummary[]>([]);

  // ── Repository + chat state ───────────────────────────────────────────────
  const [repoResult, setRepoResult] = useState<RepoOpenPayload | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [threadStoreState, setThreadStoreState] = useState<ThreadStoreState>("loading");
  const [question, setQuestion] = useState("");
  const [proposePending, setProposePending] = useState(false);
  const [writeMode, setWriteMode] = useState<"read-only" | "write-with-approval">("read-only");
  const activeRepositoryOpenRequestIdRef = useRef<string | null>(null);

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
      setWriteMode(payload.write_mode ?? "read-only");
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
      setWriteMode("read-only");
    }
  }

  useEffect(() => {
    void refreshHealthCheck({ syncProvider: true });
  }, []);

  useEffect(() => {
    if (connectionState !== "connected") return;

    let cancelled = false;
    async function loadThreadHistory() {
      setThreadStoreState("loading");
      try {
        const payload = await listThreads();
        if (cancelled) return;
        setThreads(payload.threads.map(threadFromRecord));
        setThreadStoreState("connected");
      } catch {
        if (!cancelled) setThreadStoreState("unavailable");
      }
    }

    void loadThreadHistory();
    return () => {
      cancelled = true;
    };
  }, [connectionState]);

  useEffect(() => {
    if (connectionState !== "connected") return;

    let cancelled = false;
    async function loadRecentProjectHistory() {
      try {
        const payload = await getRecentProjects({ limit: 20 });
        if (!cancelled) setRecentProjectHistory(payload.projects);
      } catch {
        if (!cancelled) setRecentProjectHistory([]);
      }
    }

    void loadRecentProjectHistory();
    return () => {
      cancelled = true;
    };
  }, [connectionState]);

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
  const repoPending = repositoryOpenProgress !== null;

  function getRepositoryOpenMode(
    projectPath: string,
    provider = gitProvider,
  ): RepositoryOpenMode {
    if (provider === "local") return "local";
    if (!projectPath) return "unknown";
    const seenRecently = recentProjects.some(
      (project) =>
        project.git_provider === provider && project.project_path === projectPath,
    );
    return seenRecently ? "refresh" : "clone";
  }

  function createRepositoryOpenRequestId(): string {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  function isActiveRepositoryOpenRequest(requestId: string): boolean {
    return activeRepositoryOpenRequestIdRef.current === requestId;
  }

  function startRepositoryOpenProgress(input: {
    projectPath: string;
    gitProvider: string;
    branch: string;
    mode: RepositoryOpenMode;
  }): string {
    const requestId = createRepositoryOpenRequestId();
    activeRepositoryOpenRequestIdRef.current = requestId;
    setRepositoryOpenProgress({
      requestId,
      mode: input.mode,
      projectPath: input.projectPath,
      gitProvider: input.gitProvider,
      branch: input.branch,
      startedAt: Date.now(),
    });
    return requestId;
  }

  function updateRepositoryOpenMode(requestId: string, mode: RepositoryOpenMode) {
    if (!isActiveRepositoryOpenRequest(requestId)) return;
    setRepositoryOpenProgress((current) =>
      current?.requestId === requestId ? { ...current, mode } : current,
    );
  }

  function clearRepositoryOpenProgress(requestId: string) {
    if (!isActiveRepositoryOpenRequest(requestId)) return;
    activeRepositoryOpenRequestIdRef.current = null;
    setRepositoryOpenProgress(null);
  }

  function threadFromRecord(record: ThreadRecordPayload): ChatThread {
    return {
      id: record.id,
      title: record.title,
      repoResult: record.repo,
      messages: record.messages.map((message) => ({
        ...message,
        timestamp: new Date(message.timestamp),
        metadata: message.metadata as AgentRunPayload | undefined,
      })),
      createdAt: new Date(record.created_at),
      updatedAt: new Date(record.updated_at),
    };
  }

  function threadToRecord(thread: ChatThread): ThreadRecordPayload {
    return {
      id: thread.id,
      title: thread.title,
      repo: thread.repoResult,
      messages: thread.messages.map((message) => ({
        ...message,
        timestamp: message.timestamp.toISOString(),
      })),
      created_at: thread.createdAt.toISOString(),
      updated_at: thread.updatedAt.toISOString(),
    };
  }

  function rememberThread(thread: ChatThread) {
    setThreads((prev) => [thread, ...prev.filter((item) => item.id !== thread.id)]);
  }

  async function persistThread(thread: ChatThread) {
    setThreadStoreState("saving");
    try {
      await saveThread(threadToRecord(thread));
      setThreadStoreState("connected");
    } catch {
      setThreadStoreState("unavailable");
    }
  }

  function updateActiveThread(nextMessages: ChatMessage[], nextRepoResult = repoResult) {
    if (!activeThreadId || !nextRepoResult) return;
    const existingThread = threads.find((thread) => thread.id === activeThreadId);
    if (!existingThread) return;
    const updatedThread: ChatThread = {
      ...existingThread,
      repoResult: nextRepoResult,
      messages: nextMessages,
      updatedAt: new Date(),
    };
    setThreads((prev) =>
      prev.map((thread) => (thread.id === activeThreadId ? updatedThread : thread)),
    );
    void persistThread(updatedThread);
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
    if (!effectiveProjectPath || (branchRequired && !effectiveBranch)) {
      setRepoError(
        branchRequired
          ? "Choose a project and branch, or use the Advanced override fields."
          : "Enter a local project path.",
      );
      return;
    }

    const requestGitProvider = gitProvider.trim() || "local";
    const requestId = startRepositoryOpenProgress({
      projectPath: effectiveProjectPath,
      gitProvider: requestGitProvider,
      branch: effectiveBranch,
      mode: getRepositoryOpenMode(effectiveProjectPath, requestGitProvider),
    });
    setRepoError(null);

    const openInput = {
      project_path: effectiveProjectPath,
      branch: effectiveBranch || undefined,
      git_provider: requestGitProvider,
      client_request_id: requestId,
    };

    try {
      const plan = await getRepositoryOpenPlan(openInput);
      updateRepositoryOpenMode(requestId, plan.open_mode);
    } catch {
      // Planning is a UX hint only; the main repository-open flow remains authoritative.
    }

    if (!isActiveRepositoryOpenRequest(requestId)) return;

    try {
      const payload = await openRepository(openInput);
      if (!isActiveRepositoryOpenRequest(requestId)) return;
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
      rememberThread(nextThread);
      void persistThread(nextThread);
      setRecentProjectHistory((prev) => mergeRecentProject(prev, payload));
      clearRepositoryOpenProgress(requestId);
      await refreshHealthCheck();
    } catch (error) {
      if (!isActiveRepositoryOpenRequest(requestId)) return;
      setRepoResult(null);
      setRepoError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to open the repository through the local worker.",
      );
    } finally {
      clearRepositoryOpenProgress(requestId);
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
    const messagesWithUser = [...messages, userMessage];
    setMessages(messagesWithUser);
    updateActiveThread(messagesWithUser);
    setQuestion("");
    setQuestionPending(true);

    try {
      const payload = await runAgentTask({
        project_path: repoResult.project_path,
        git_provider: repoResult.git_provider,
        branch: repoResult.branch || undefined,
        task: userMessage.content,
      });
      const messagesWithAssistant: ChatMessage[] = [
        ...messagesWithUser,
        {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          content: payload.response,
          timestamp: new Date(),
          metadata: payload,
        },
      ];
      setMessages(messagesWithAssistant);
      updateActiveThread(messagesWithAssistant);
    } catch (error) {
      const msg =
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to run the task through the local worker.";
      const messagesWithError: ChatMessage[] = [
        ...messagesWithUser,
        {
          id: `${Date.now()}-error`,
          role: "assistant",
          content: `Error: ${msg}`,
          timestamp: new Date(),
        },
      ];
      setMessages(messagesWithError);
      updateActiveThread(messagesWithError);
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
    rememberThread(nextThread);
    void persistThread(nextThread);
  }

  async function handleSelectThread(threadId: string) {
    const thread = threads.find((item) => item.id === threadId);
    if (!thread) return;
    const requestId = startRepositoryOpenProgress({
      projectPath: thread.repoResult.project_path,
      gitProvider: thread.repoResult.git_provider,
      branch: thread.repoResult.branch || "",
      mode: getRepositoryOpenMode(
        thread.repoResult.project_path,
        thread.repoResult.git_provider,
      ),
    });
    setRepoError(null);
    try {
      const reopened = await openRepository({
        project_path: thread.repoResult.project_path,
        git_provider: thread.repoResult.git_provider,
        branch: thread.repoResult.branch || undefined,
        client_request_id: requestId,
      });
      if (!isActiveRepositoryOpenRequest(requestId)) return;
      const restoredThread = {
        ...thread,
        repoResult: reopened,
        updatedAt: new Date(),
      };
      setActiveThreadId(thread.id);
      setRepoResult(reopened);
      setMessages(thread.messages);
      setThreads((prev) =>
        prev.map((item) => (item.id === thread.id ? restoredThread : item)),
      );
      void persistThread(restoredThread);
      setQuestion("");
    } catch (error) {
      if (!isActiveRepositoryOpenRequest(requestId)) return;
      setRepoError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to restore the repository for this thread.",
      );
    } finally {
      clearRepositoryOpenProgress(requestId);
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

  function mergeRecentProject(
    current: ProviderProjectSummary[],
    payload: RepoOpenPayload,
  ): ProviderProjectSummary[] {
    const nextProject: ProviderProjectSummary = {
      git_provider: payload.git_provider,
      project_path: payload.project_path,
      display_name: payload.project_path.split(/[\\/]/).filter(Boolean).at(-1) || payload.project_path,
      default_branch: payload.branch || null,
      source: "recent",
      is_git_repository: payload.is_git_repository,
    };
    return [
      nextProject,
      ...current.filter(
        (project) =>
          project.git_provider !== nextProject.git_provider ||
          project.project_path !== nextProject.project_path,
      ),
    ].slice(0, 20);
  }

  function handleLocalBranchChange(newBranch: string) {
    if (!repoResult) return;
    const updated: typeof repoResult = { ...repoResult, branch: newBranch };
    setRepoResult(updated);
    // Update the active thread's repo snapshot so the branch is persisted.
    if (activeThreadId) {
      updateActiveThread(messages, updated);
    }
  }

  async function handleProposeChange(relativePath: string, instruction: string) {
    if (!repoResult || proposePending) return;

    const userMessage: ChatMessage = {
      id: `${Date.now()}-user`,
      role: "user",
      content: `Propose change to ${relativePath}:\n${instruction}`,
      timestamp: new Date(),
    };
    const messagesWithUser = [...messages, userMessage];
    setMessages(messagesWithUser);
    updateActiveThread(messagesWithUser);
    setProposePending(true);

    try {
      const payload = await proposeFileEdit({
        project_path: repoResult.project_path,
        relative_path: relativePath,
        instruction,
      });
      const proposal: ChangeProposal = proposalFromPayload(payload, {
        projectPath: repoResult.project_path,
        branch: repoResult.branch,
      });
      const proposalMessage: ChatMessage = {
        id: `${Date.now()}-proposal`,
        role: "assistant",
        content: `Proposed change to \`${relativePath}\`. Review the diff below and apply if it looks correct.`,
        timestamp: new Date(),
        proposal,
      };
      const messagesWithProposal = [...messagesWithUser, proposalMessage];
      setMessages(messagesWithProposal);
      updateActiveThread(messagesWithProposal);
    } catch (error) {
      const msg =
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to generate the file change proposal.";
      const errorMessage: ChatMessage = {
        id: `${Date.now()}-error`,
        role: "assistant",
        content: `Error generating proposal: ${msg}`,
        timestamp: new Date(),
      };
      const messagesWithError = [...messagesWithUser, errorMessage];
      setMessages(messagesWithError);
      updateActiveThread(messagesWithError);
    } finally {
      setProposePending(false);
    }
  }

  function handleProposalStatusChange(id: string, status: ProposalStatus, _message?: string) {
    setMessages((prev) =>
      prev.map((msg) =>
        msg.proposal?.id === id
          ? { ...msg, proposal: { ...msg.proposal, status } }
          : msg,
      ),
    );
    // Persist the updated proposal status in the thread.
    if (activeThreadId) {
      setMessages((current) => {
        updateActiveThread(current);
        return current;
      });
    }
  }

  function handleRecentProjectSelect(project: ProviderProjectSummary) {
    setGitProvider(project.git_provider);
    setUseAdvanced(project.git_provider === "local");
    setRepoResult(null);
    setRepoError(null);
    setSelectedProjectPath(project.project_path);
    setManualProjectPath(project.project_path);
    setSelectedBranch(project.default_branch || "");
    setManualBranch(project.default_branch || "");
    setBranches([]);
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <ChatLayout
      sidebar={
        <ChatSidebar
          recentProjects={recentProjectHistory}
          threads={threads}
          activeThreadId={activeThreadId}
          threadStoreState={threadStoreState}
          onNewChat={handleNewChat}
          onSelectThread={handleSelectThread}
          onSelectRecentProject={handleRecentProjectSelect}
        />
      }
      header={
        <ChatHeader
          connectionState={connectionState}
          configuredModelName={configuredModelName}
          configuredModelProvider={configuredModelProvider}
          writeMode={writeMode}
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
          repositoryOpenProgress={repositoryOpenProgress}
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
          onLocalBranchChange={handleLocalBranchChange}
          writeMode={writeMode}
          onProposalStatusChange={handleProposalStatusChange}
        />
      }
      composer={
        <ChatComposer
          value={question}
          onChange={setQuestion}
          onSubmit={handleQuestionSubmit}
          disabled={!repoResult}
          pending={questionPending}
          writeMode={writeMode}
          onProposeChange={handleProposeChange}
          proposePending={proposePending}
        />
      }
    />
  );
}
