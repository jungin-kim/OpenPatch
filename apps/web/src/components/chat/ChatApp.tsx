"use client";

import { useEffect, useRef, useState } from "react";

import {
  checkoutLocalBranch,
  createLocalBranch,
  getProviderBranches,
  getProviderProjects,
  getRecentProjects,
  getRepositoryOpenPlan,
  getWorkerHealth,
  generateApplySummary,
  listLocalBranches,
  listThreads,
  LocalWorkerClientError,
  openRepository,
  streamAgentTask,
  runApprovedCommand,
  saveThread,
  updatePermissionMode,
  type AgentRunPayload,
  type ConversationMessage,
  type PermissionMode,
  type ProviderBranchSummary,
  type ProviderProjectSummary,
  type RepoOpenPayload,
  type ThreadRecordPayload,
} from "@/lib/local-worker-client";
import { ProgressTimeline, type ProgressStep } from "./ProgressTimeline";
import {
  proposalFromRunPayload,
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
  const [writeMode, setWriteMode] = useState<PermissionMode>("basic");
  const [permissionPending, setPermissionPending] = useState(false);
  const [permissionMessage, setPermissionMessage] = useState<string | null>(null);
  const [permissionError, setPermissionError] = useState<string | null>(null);
  const [branchActionPending, setBranchActionPending] = useState(false);
  const [branchActionError, setBranchActionError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [progressSteps, setProgressSteps] = useState<ProgressStep[]>([]);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [streamedReasoning, setStreamedReasoning] = useState("");
  const [queuedMessages, setQueuedMessages] = useState<string[]>([]);
  const activeRepositoryOpenRequestIdRef = useRef<string | null>(null);
  const queuedMessagesRef = useRef<string[]>([]);

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
      setWriteMode(payload.permission_mode ?? "basic");
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
      setWriteMode("basic");
    }
  }

  useEffect(() => {
    void refreshHealthCheck({ syncProvider: true });
  }, []);

  useEffect(() => {
    const savedTheme = window.localStorage.getItem("repooperator-theme");
    const nextTheme =
      savedTheme === "dark" || savedTheme === "light"
        ? savedTheme
        : window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    setTheme(nextTheme);
    document.documentElement.dataset.theme = nextTheme;
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

  async function refreshLocalBranchesForRepo(payload: RepoOpenPayload) {
    if (!payload.is_git_repository) return;
    try {
      const localBranchPayload = await listLocalBranches({
        project_path: payload.project_path,
      });
      const localBranches = localBranchPayload.branches.map((branch) => ({
        name: branch.name,
        is_default: branch.is_current,
      }));
      setBranches(localBranches);
      const currentBranch = localBranchPayload.current_branch || payload.branch || "";
      setSelectedBranch(currentBranch);
      setManualBranch(currentBranch);
    } catch {
      // Branch controls remain available from provider data if local branch inspection fails.
    }
  }

  function handleThemeToggle() {
    const nextTheme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    document.documentElement.dataset.theme = nextTheme;
    window.localStorage.setItem("repooperator-theme", nextTheme);
  }

  async function handlePermissionModeChange(mode: PermissionMode) {
    if (mode === "full_access") {
      const confirmed = window.confirm(
        "Full access can read and modify files outside this repository and run local commands on this computer. Use only in a trusted environment.",
      );
      if (!confirmed) return;
    }
    const previousMode = writeMode;
    setPermissionPending(true);
    setPermissionError(null);
    setPermissionMessage(null);
    try {
      const payload = await updatePermissionMode(mode);
      setWriteMode(payload.mode);
      setPermissionMessage(
        payload.mode === "auto_review"
          ? "Auto review enabled. Elevated actions will use approval cards."
          : payload.mode === "full_access"
            ? "Full access enabled. Risky commands are still logged and previewed where practical."
            : "Basic permissions enabled. Repo sandbox work is allowed with guardrails.",
      );
      window.setTimeout(() => setPermissionMessage(null), 3200);
    } catch (error) {
      setWriteMode(previousMode);
      setPermissionError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to update permission mode.",
      );
    } finally {
      setPermissionPending(false);
    }
  }

  async function handleCommandDecision(
    metadata: AgentRunPayload,
    decision: "yes" | "yes_session" | "no_explain",
  ) {
    if (!metadata.command_approval) return;
    if (decision === "no_explain") {
      const denial: ChatMessage = {
        id: `${Date.now()}-command-denied`,
        role: "assistant",
        content: "I will not run that command. I can continue with repository inspection or suggest a safer manual alternative.",
        timestamp: new Date(),
      };
      setMessages((current) => [...current, denial]);
      return;
    }
    const pendingMessage: ChatMessage = {
      id: `${Date.now()}-command-running`,
      role: "system",
      content: `Running ${metadata.command_approval.display_command}...`,
      timestamp: new Date(),
    };
    setMessages((current) => [...current, pendingMessage]);
    try {
      const result = await runApprovedCommand({
        command: metadata.command_approval.command,
        approval_id: metadata.command_approval.approval_id,
        remember_for_session: decision === "yes_session",
        decision,
      });
      const assistantMessage: ChatMessage = {
        id: `${Date.now()}-command-result`,
        role: "assistant",
        content: `Command completed with exit code ${result.exit_code}.`,
        timestamp: new Date(),
        metadata: {
          ...metadata,
          response_type: "command_result",
          command_result: result,
        },
      };
      const nextApproval = metadata.command_approval.next_command_approval;
      const followupApproval: ChatMessage | null = nextApproval
        ? {
            id: `${Date.now()}-command-next-approval`,
            role: "assistant",
            content: "The first Git step completed. Review the next command before continuing.",
            timestamp: new Date(),
            metadata: {
              ...metadata,
              response: "The first Git step completed. Review the next command before continuing.",
              response_type: "command_approval",
              command_approval: nextApproval,
            },
          }
        : null;
      setMessages((current) => [
        ...current.filter((m) => m.id !== pendingMessage.id),
        assistantMessage,
        ...(followupApproval ? [followupApproval] : []),
      ]);
    } catch (error) {
      const assistantMessage: ChatMessage = {
        id: `${Date.now()}-command-error`,
        role: "assistant",
        content: error instanceof Error ? error.message : "Command failed.",
        timestamp: new Date(),
        metadata: {
          ...metadata,
          response_type: "command_error",
        },
      };
      setMessages((current) => [...current.filter((m) => m.id !== pendingMessage.id), assistantMessage]);
    }
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
      await refreshLocalBranchesForRepo(payload);
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

  async function runQuestion(taskText: string, currentMessages: ChatMessage[]) {
    setQuestionPending(true);
    setProgressSteps([]);
    setStreamedAnswer("");
    setStreamedReasoning("");

    const userMessage: ChatMessage = {
      id: `${Date.now()}-user`,
      role: "user",
      content: taskText,
      timestamp: new Date(),
    };
    const messagesWithUser = [...currentMessages, userMessage];
    setMessages(messagesWithUser);
    updateActiveThread(messagesWithUser);

    // Capture progress steps at end of run for attaching to the message
    let capturedProgressSteps: ProgressStep[] = [];

    // Build conversation history
    const conversationHistory: ConversationMessage[] = messagesWithUser
      .filter((m) => m.role === "user" || m.role === "assistant")
      .slice(-10)
      .map((m) => ({
        role: m.role as "user" | "assistant",
        content: m.content,
        metadata: m.metadata ?? null,
      }));

    try {
      const streamInput = {
        project_path: repoResult!.project_path,
        git_provider: repoResult!.git_provider,
        branch: repoResult!.branch || undefined,
        task: taskText,
        conversation_history: conversationHistory,
      };

      let payload: AgentRunPayload | null = null;

      for await (const event of streamAgentTask(streamInput)) {
        if (event.type === "progress") {
          setProgressSteps((prev) => {
            const next = [
              ...prev,
              {
                phase: "Thinking",
                label: event.message || "Working",
                status: "running",
              },
            ];
            capturedProgressSteps = next;
            return next;
          });
        } else if (event.type === "progress_delta") {
          setProgressSteps((prev) => {
            const next = [
              ...prev,
              {
                id: event.id,
                runId: event.run_id,
                phase: event.phase,
                label: event.label ?? event.message,
                detail: event.detail,
                message: event.message,
                status: event.status,
                startedAt: event.started_at,
                endedAt: event.ended_at,
                durationMs: event.duration_ms,
                elapsedMs: event.elapsed_ms,
                files: event.files,
                command: event.command,
                proposalId: event.proposal_id,
              },
            ];
            capturedProgressSteps = next;
            return next;
          });
        } else if (event.type === "assistant_delta") {
          setStreamedAnswer((prev) => prev + event.delta);
        } else if (event.type === "reasoning_delta") {
          setStreamedReasoning((prev) => prev + event.delta);
        } else if (event.type === "done") {
          payload = event.result;
        } else if (event.type === "final_message") {
          payload = event.result;
        } else if (event.type === "error") {
          throw new Error(event.message);
        }
      }

      if (!payload) throw new Error("No result received from agent.");

      let assistantMessage: ChatMessage;

      if (
        payload.response_type === "change_proposal" &&
        payload.proposal_relative_path
      ) {
        const proposal = proposalFromRunPayload(payload, {
          projectPath: repoResult!.project_path,
          branch: repoResult!.branch,
        });
        assistantMessage = {
          id: `${Date.now()}-proposal`,
          role: "assistant",
          content: payload.response,
          timestamp: new Date(),
          metadata: payload,
          proposal,
          progressSteps: capturedProgressSteps.length > 0 ? capturedProgressSteps : undefined,
        };
      } else if (payload.response_type === "proposal_error") {
        assistantMessage = {
          id: `${Date.now()}-proposal-error`,
          role: "assistant",
          content: payload.response,
          timestamp: new Date(),
          metadata: payload,
          progressSteps: capturedProgressSteps.length > 0 ? capturedProgressSteps : undefined,
        };
      } else {
        assistantMessage = {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          content: payload.response,
          timestamp: new Date(),
          metadata: payload,
          progressSteps: capturedProgressSteps.length > 0 ? capturedProgressSteps : undefined,
        };
      }

      const nextMessages = [...messagesWithUser, assistantMessage];
      setMessages(nextMessages);
      updateActiveThread(nextMessages);
      return nextMessages;
    } catch (error) {
      const msg =
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to run the task through the local worker.";
      const isTimeout = msg.toLowerCase().includes("timed out");
      const messagesWithError: ChatMessage[] = [
        ...messagesWithUser,
        {
          id: `${Date.now()}-error`,
          role: "assistant",
          content: isTimeout
            ? `The request timed out. The model may need more time — retry, or try a shorter request. Details: ${msg}`
            : `Error: ${msg}`,
          timestamp: new Date(),
          progressSteps: capturedProgressSteps.length > 0 ? capturedProgressSteps : undefined,
        },
      ];
      setMessages(messagesWithError);
      updateActiveThread(messagesWithError);
      return messagesWithError;
    } finally {
      setQuestionPending(false);
      // Keep progressSteps visible briefly before the message takes over
      setTimeout(() => {
        setProgressSteps([]);
        setStreamedAnswer("");
        setStreamedReasoning("");
      }, 100);
    }
  }

  async function handleQuestionSubmit() {
    if (!question.trim() || !repoResult) return;

    const taskText = question.trim();
    setQuestion("");

    // If already running, queue the message
    if (questionPending) {
      setQueuedMessages((prev) => {
        const next = [...prev, taskText];
        queuedMessagesRef.current = next;
        return next;
      });
      return;
    }

    // Run the question, then drain the queue
    void (async () => {
      let currentMessages = messages;
      currentMessages = (await runQuestion(taskText, currentMessages)) ?? currentMessages;

      // Drain queue: process each queued message in sequence
      while (queuedMessagesRef.current.length > 0) {
        const [next, ...rest] = queuedMessagesRef.current;
        queuedMessagesRef.current = rest;
        setQueuedMessages(rest);
        currentMessages = (await runQuestion(next, currentMessages)) ?? currentMessages;
      }
    })();
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
      await refreshLocalBranchesForRepo(reopened);
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

  async function handleBranchChange(branch: string) {
    setUseAdvanced(false);
    setSelectedBranch(branch);
    setManualBranch(branch);
    setBranchActionError(null);
    if (!repoResult?.is_git_repository) {
      setRepoResult(null);
      return;
    }
    if (branch === repoResult.branch) return;
    setBranchActionPending(true);
    try {
      const result = await checkoutLocalBranch({
        project_path: repoResult.project_path,
        branch,
      });
      const updated: RepoOpenPayload = {
        ...repoResult,
        branch: result.branch,
        head_sha: result.head_sha || repoResult.head_sha,
      };
      setRepoResult(updated);
      updateActiveThread(messages, updated);
      await refreshLocalBranchesForRepo(updated);
    } catch (error) {
      setBranchActionError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to switch branch.",
      );
    } finally {
      setBranchActionPending(false);
    }
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

  async function handleCreateBranch(branchName: string, baseBranch: string) {
    if (!repoResult) {
      setBranchActionError("Open a repository before creating a branch.");
      return;
    }
    setBranchActionPending(true);
    setBranchActionError(null);
    try {
      const result = await createLocalBranch({
        project_path: repoResult.project_path,
        branch: branchName,
        from_ref: baseBranch || repoResult.branch || "HEAD",
        checkout: true,
      });
      const updated: RepoOpenPayload = {
        ...repoResult,
        branch: result.branch,
        head_sha: result.head_sha,
      };
      setRepoResult(updated);
      setSelectedBranch(result.branch);
      setManualBranch(result.branch);
      updateActiveThread(messages, updated);
      await refreshLocalBranchesForRepo(updated);
    } catch (error) {
      setBranchActionError(
        error instanceof LocalWorkerClientError || error instanceof Error
          ? error.message
          : "Unable to create the branch.",
      );
      throw error;
    } finally {
      setBranchActionPending(false);
    }
  }

  function handleProposalStatusChange(id: string, status: ProposalStatus, _message?: string) {
    let appliedProposal: ChangeProposal | null = null;
    let proposalMetadata: AgentRunPayload | undefined;
    const nextMessages = messages.map((msg) => {
      if (msg.proposal?.id === id) {
        appliedProposal = msg.proposal;
        proposalMetadata = msg.metadata;
        const updatedArchive = msg.metadata?.edit_archive?.map((record) => ({
          ...record,
          status,
          apply_result:
            status === "applied"
              ? `Applied changes to ${msg.proposal?.relativePath}`
              : status === "rejected"
                ? "Proposal rejected."
                : status === "failed"
                  ? "Apply failed."
                  : record.apply_result,
        }));
        return {
          ...msg,
          proposal: { ...msg.proposal, status },
          metadata: msg.metadata
            ? {
                ...msg.metadata,
                edit_archive: updatedArchive ?? msg.metadata.edit_archive,
              }
            : msg.metadata,
        };
      }
      return msg;
    });
    setMessages(nextMessages);
    updateActiveThread(nextMessages);

    if (status === "applied" && appliedProposal && repoResult) {
      void appendApplySummary(appliedProposal, proposalMetadata, nextMessages);
    }
  }

  async function appendApplySummary(
    proposal: ChangeProposal,
    metadata: AgentRunPayload | undefined,
    currentMessages: ChatMessage[],
  ) {
    const lastUserRequest =
      [...currentMessages].reverse().find((msg) => msg.role === "user")?.content || "";
    try {
      const summary = await generateApplySummary({
        project_path: proposal.projectPath,
        branch: proposal.branch,
        relative_path: proposal.relativePath,
        user_request: lastUserRequest,
        proposal_summary: metadata?.proposal_context_summary || metadata?.response || "",
        diff_summary: buildDiffSummary(proposal.originalContent, proposal.proposedContent),
      });
      const summaryMessage: ChatMessage = {
        id: `${Date.now()}-apply-summary`,
        role: "assistant",
        content: summary.response,
        timestamp: new Date(),
        metadata: {
          ...(metadata ?? {}),
          response_type: "assistant_answer",
          response: summary.response,
          reasoning: summary.reasoning ?? null,
          files_read: [proposal.relativePath],
        } as AgentRunPayload,
      };
      setMessages((latest) => {
        const merged = [...latest, summaryMessage];
        updateActiveThread(merged);
        return merged;
      });
    } catch {
      const fallback: ChatMessage = {
        id: `${Date.now()}-apply-summary-fallback`,
        role: "assistant",
        content: `Applied the approved changes to ${proposal.relativePath}. RepoOperator has not committed or pushed anything.`,
        timestamp: new Date(),
      };
      setMessages((latest) => {
        const merged = [...latest, fallback];
        updateActiveThread(merged);
        return merged;
      });
    }
  }

  function buildDiffSummary(original: string, proposed: string): string {
    const oldLines = original.split("\n");
    const newLines = proposed.split("\n");
    let added = 0;
    let removed = 0;
    const max = Math.max(oldLines.length, newLines.length);
    for (let i = 0; i < max; i++) {
      if (oldLines[i] !== newLines[i]) {
        if (newLines[i] !== undefined) added += 1;
        if (oldLines[i] !== undefined) removed += 1;
      }
    }
    return `${proposalLineLabel(added, "line")} added or changed, ${proposalLineLabel(removed, "line")} removed or changed.`;
  }

  function proposalLineLabel(count: number, noun: string): string {
    return `${count} ${noun}${count === 1 ? "" : "s"}`;
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
          permissionPending={permissionPending}
          permissionMessage={permissionMessage}
          permissionError={permissionError}
          onPermissionModeChange={handlePermissionModeChange}
          theme={theme}
          onThemeToggle={handleThemeToggle}
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
          onBranchChange={(branch) => void handleBranchChange(branch)}
          openedRepository={repoResult}
          branchActionPending={branchActionPending}
          branchActionError={branchActionError}
          onCreateBranch={handleCreateBranch}
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
          progressSteps={progressSteps}
          streamedAnswer={streamedAnswer}
          streamedReasoning={streamedReasoning}
          gitProvider={gitProvider}
          writeMode={writeMode}
          onProposalStatusChange={handleProposalStatusChange}
          onClarificationSelect={(candidate) => setQuestion(candidate)}
          onCommandDecision={handleCommandDecision}
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
          queuedCount={queuedMessages.length}
        />
      }
    />
  );
}
