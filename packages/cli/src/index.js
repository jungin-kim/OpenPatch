const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const readline = require("node:readline/promises");
const net = require("node:net");
const { spawn } = require("node:child_process");
const { stdin, stdout } = require("node:process");
const term = require("./terminal");

const PRODUCT_NAME = "RepoOperator";
const CLI_COMMAND = "repooperator";
const CONFIG_DIR = path.join(os.homedir(), ".repooperator");
const LEGACY_CONFIG_DIR = path.join(os.homedir(), ".openpatch");
const CONFIG_PATH = path.join(CONFIG_DIR, "config.json");
const LEGACY_CONFIG_PATH = path.join(LEGACY_CONFIG_DIR, "config.json");
const RUN_DIR = path.join(CONFIG_DIR, "run");
const LEGACY_RUN_DIR = path.join(LEGACY_CONFIG_DIR, "run");
const LOG_DIR = path.join(CONFIG_DIR, "logs");
const LEGACY_LOG_DIR = path.join(LEGACY_CONFIG_DIR, "logs");
const STATE_PATH = path.join(RUN_DIR, "worker-state.json");
const WEB_STATE_PATH = path.join(RUN_DIR, "web-state.json");
const LEGACY_STATE_PATH = path.join(LEGACY_CONFIG_DIR, "daemon", "state.json");
const LEGACY_RUN_STATE_PATH = path.join(LEGACY_RUN_DIR, "worker-state.json");
const PID_PATH = path.join(RUN_DIR, "worker.pid");
const WEB_PID_PATH = path.join(RUN_DIR, "web.pid");
const WORKER_LOG_PATH = path.join(LOG_DIR, "worker.log");
const WEB_LOG_PATH = path.join(LOG_DIR, "web.log");
const OLLAMA_LOG_PATH = path.join(LOG_DIR, "ollama.log");
const DEFAULT_WORKER_URL = "http://127.0.0.1:8000";
const DEFAULT_WEB_URL = "http://127.0.0.1:3000";
const DEFAULT_REPO_BASE_DIR = path.join(os.homedir(), ".repooperator", "repos");
const DEFAULT_WORKER_HEALTH_TIMEOUT_MS = 1500;
const DEFAULT_WORKER_START_TIMEOUT_MS = 8000;
const DEFAULT_WEB_HEALTH_TIMEOUT_MS = 2000;
const DEFAULT_WEB_START_TIMEOUT_MS = 15000;
const DEFAULT_MODEL_CONNECTIVITY_TIMEOUT_MS = 2000;
const DEFAULT_PORT_CHECK_TIMEOUT_MS = 1000;
const DEFAULT_OLLAMA_TIMEOUT_MS = 1500;
const DEFAULT_OLLAMA_START_TIMEOUT_MS = 10000;
const DEFAULT_LOG_TAIL_LINES = 40;
const OLLAMA_DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1";
const OLLAMA_RECOMMENDED_MODEL = "qwen2.5-coder:7b";
const MODEL_CONNECTION_MODES = [
  "local-runtime",
  "remote-api",
];
const MODEL_PROVIDER_OPTIONS = [
  "openai",
  "anthropic",
  "gemini",
  "ollama",
  "openai-compatible",
];
const MODEL_PROVIDER_CONFIG = {
  openai: {
    label: "OpenAI",
    defaultBaseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4.1-mini",
    prompts: ["apiKey", "model"],
  },
  anthropic: {
    label: "Anthropic",
    defaultBaseUrl: "https://api.anthropic.com",
    defaultModel: "claude-3-7-sonnet-latest",
    prompts: ["apiKey", "model"],
  },
  gemini: {
    label: "Gemini",
    defaultBaseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    defaultModel: "gemini-2.5-pro",
    prompts: ["apiKey", "model"],
  },
  ollama: {
    label: "Ollama",
    defaultBaseUrl: OLLAMA_DEFAULT_BASE_URL,
    defaultApiKey: "ollama",
    defaultModel: OLLAMA_RECOMMENDED_MODEL,
    prompts: ["baseUrl", "model"],
  },
  "openai-compatible": {
    label: "OpenAI-compatible",
    defaultBaseUrl: "",
    defaultModel: "",
    prompts: ["baseUrl", "apiKey", "model"],
  },
};

async function runCli() {
  const command = process.argv[2];
  const subcommand = process.argv[3];

  switch (command) {
    case "onboard":
      await runOnboard();
      return;
    case "up":
      await runUp();
      return;
    case "down":
      await runDown();
      return;
    case "config":
      await runConfigCommand(subcommand);
      return;
    case "doctor":
      await runDoctor();
      return;
    case "status":
      await runStatus();
      return;
    case "worker":
      await runWorkerCommand(subcommand);
      return;
    case "--help":
    case "-h":
    case undefined:
      printHelp();
      return;
    default:
      throw new Error(`Unknown command: ${command}`);
  }
}

async function runConfigCommand(subcommand) {
  switch (subcommand) {
    case "show":
      await showConfig();
      return;
    default:
      throw new Error("Unknown config command. Use show.");
  }
}

async function runWorkerCommand(subcommand) {
  switch (subcommand) {
    case "start":
      await startWorker({ interactive: true });
      return;
    case "stop":
      await stopWorker({ interactive: true });
      return;
    case "restart":
      await restartWorker();
      return;
    case "status":
      await showWorkerStatus();
      return;
    case "logs":
      await showWorkerLogs();
      return;
    default:
      throw new Error("Unknown worker command. Use start, stop, restart, status, or logs.");
  }
}

async function runOnboard() {
  await ensureBaseDirectories();
  const rl = readline.createInterface({ input: stdin, output: stdout });

  try {
    console.log(term.banner());
    term.heading("1/6", "Welcome", "Set up the local RepoOperator runtime on this machine.");
    term.summaryBox("What this wizard will configure", [
      "Model connection for repository questions",
      "Repository source for guided project selection",
      "Local worker runtime and repository storage",
      "A one-command startup flow with repooperator up",
    ]);

    term.heading("2/6", "Environment checks", "RepoOperator checks for the local pieces it can prepare automatically.");
    const workerDetection = await term.spinner("Detect local worker installation", () =>
      detectLocalWorkerInstallation(process.cwd()),
    );
    const webDetection = await term.spinner("Detect web app installation", () =>
      resolveWebInstallation({}, process.cwd()),
    );
    const pythonAvailable = await commandExists("python3");
    const npmAvailable = await commandExists("npm");
    term.summaryBox("Environment", [
      ["Local worker", workerDetection.installed ? workerDetection.summary : workerDetection.summary],
      ["Web app", webDetection.installed ? webDetection.summary : webDetection.summary],
      ["Python", pythonAvailable ? "python3 found" : "python3 not found"],
      ["npm", npmAvailable ? "npm found" : "npm not found"],
    ]);

    term.heading("3/6", "Model connection", "Choose how the worker should reach a model.");
    const modelConfig = await promptModelConfig(rl);

    term.heading("4/6", "Repository source", "Choose where projects should be discovered from.");
    const gitProvider = await promptGitProvider(rl);
    const gitProviderConfig = await promptGitProviderConfig(rl, gitProvider);

    term.heading("5/6", "Local worker setup", "Choose where local checkouts and runtime files should live.");
    const localRepoBaseDir = await promptWithDefault(
      rl,
      "Local repository base directory",
      DEFAULT_REPO_BASE_DIR,
    );

    const config = {
      version: 2,
      createdAt: new Date().toISOString(),
      worker: {
        baseUrl: DEFAULT_WORKER_URL,
        installed: workerDetection.installed,
        installMode: workerDetection.installMode,
        detectedPath: workerDetection.detectedPath,
      },
      web: {
        baseUrl: DEFAULT_WEB_URL,
        installed: webDetection.installed,
        detectedPath: webDetection.detectedPath,
      },
      model: modelConfig,
      gitProvider: gitProviderConfig,
      localRepoBaseDir,
      daemon: {
        prepared: true,
        runDirectory: RUN_DIR,
        logDirectory: LOG_DIR,
        stateFile: STATE_PATH,
        pidFile: PID_PATH,
        launchStrategy: workerDetection.installed ? "repo-source-background-process" : "pending-install",
      },
    };

    await writeJson(CONFIG_PATH, config);
    await writeJson(STATE_PATH, {
      preparedAt: new Date().toISOString(),
      expectedWorkerUrl: DEFAULT_WORKER_URL,
      installMode: workerDetection.installMode,
      workerDetected: workerDetection.installed,
      status: "stopped",
      pidFile: PID_PATH,
      logPath: WORKER_LOG_PATH,
    });

    term.line("success", `${PRODUCT_NAME} configuration written`, CONFIG_PATH);

    let workerStarted = false;
    try {
      await term.spinner("Start local worker", () => startWorker({ interactive: false, quiet: true }));
      workerStarted = true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      term.line("warning", "Worker start needs attention", message);
      term.line("info", "Inspect logs", `${CLI_COMMAND} worker logs`);
    }

    const workerHealth = await term.spinner(
      "Verify worker health",
      () => checkWorkerHealth(
        config.worker.baseUrl,
        DEFAULT_WORKER_HEALTH_TIMEOUT_MS,
      ),
    );
    const modelConnectivity = await term.spinner(
      "Verify model connectivity",
      () => checkModelConnectivity(
        config.model,
        DEFAULT_MODEL_CONNECTIVITY_TIMEOUT_MS,
      ),
    );

    term.heading("6/6", "Final summary", "Your local RepoOperator configuration is ready.");
    term.summaryBox(`${PRODUCT_NAME} setup`, [
      ["Config", CONFIG_PATH],
      ["Worker URL", config.worker.baseUrl],
      ["Web URL", config.web?.baseUrl || DEFAULT_WEB_URL],
      ["Repository source", formatProviderSummary(config.gitProvider)],
      ["Model", formatModelSummary(config.model)],
      ["Worker health", workerHealth.reachable ? "ok" : "needs attention"],
      ["Model connectivity", modelConnectivity.reachable ? "ok" : "needs attention"],
    ]);

    if (workerStarted && workerHealth.reachable && modelConnectivity.reachable) {
      term.summaryBox("Next steps", [
        `Run ${CLI_COMMAND} up`,
        "Open the printed local web URL",
        "Choose a repository and ask a read-only question",
      ]);
      return;
    }

    if (!workerHealth.reachable) {
      term.line("warning", "Worker detail", workerHealth.message);
    }
    if (!modelConnectivity.reachable) {
      term.line("warning", "Model detail", modelConnectivity.message);
    }

    process.exitCode = 1;
  } finally {
    rl.close();
  }
}

async function runDoctor() {
  await ensureMigratedRuntimeHome();
  const checks = [];
  const configExists = await fileExists(CONFIG_PATH);
  checks.push(
    makeCheck(
      "Config file exists",
      configExists,
      configExists ? CONFIG_PATH : `Run \`${CLI_COMMAND} onboard\` first.`,
    ),
  );

  if (!configExists) {
    printChecks(checks);
    process.exitCode = 1;
    return;
  }

  const config = await readConfig();
  const workerDetection = await resolveWorkerInstallation(config, process.cwd());
  const runtimeState = await readState();
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  const workerBinding = parseWorkerBinding(workerUrl);
  const workerRunning = await isWorkerProcessRunning(runtimeState);
  const portState = await checkPortInUse(workerBinding.host, workerBinding.port, DEFAULT_PORT_CHECK_TIMEOUT_MS);
  const workerHealth = portState.inUse || workerRunning.running
    ? await checkWorkerHealth(
      workerUrl,
      DEFAULT_WORKER_HEALTH_TIMEOUT_MS,
    )
    : { reachable: false, message: "Worker is stopped." };
  const modelConnectivity = await checkModelConnectivity(
    config.model,
    DEFAULT_MODEL_CONNECTIVITY_TIMEOUT_MS,
  );
  const urlMatches = runtimeState?.workerUrl
    ? runtimeState.workerUrl === (config.worker?.baseUrl || DEFAULT_WORKER_URL)
    : !workerRunning.running;

  checks.push(
    makeCheck(
      "Local worker installation detected",
      workerDetection.installed,
      workerDetection.summary,
    ),
  );
  checks.push(
    makeCheck(
      "Worker process is running",
      workerRunning.running,
      describeWorkerProcessState(workerRunning, runtimeState),
    ),
  );
  checks.push(
    makeCheck(
      "Local worker reachable",
      workerHealth.reachable,
      describeWorkerHealthState(workerHealth, runtimeState, portState),
    ),
  );
  checks.push(
    makeCheck(
      "Worker port availability",
      !portState.inUse || workerHealth.reachable,
      describePortState(portState, workerUrl, workerHealth.reachable),
    ),
  );
  checks.push(
    makeCheck(
      "Model connectivity",
      modelConnectivity.reachable,
      modelConnectivity.message,
    ),
  );
  checks.push(
    makeCheck(
      "Configured worker URL matches runtime state",
      urlMatches,
      urlMatches
        ? runtimeState?.workerUrl
          ? `Configured URL matches ${runtimeState.workerUrl}.`
          : "No active runtime state is recorded because the worker is stopped."
        : `Configured URL is '${config.worker?.baseUrl || DEFAULT_WORKER_URL}', runtime state is '${runtimeState?.workerUrl || "not available"}'.`,
    ),
  );
  checks.push(
    makeCheck(
      "Model connection config present",
      Boolean(
        MODEL_CONNECTION_MODES.includes(config.model?.connectionMode) &&
        config.model?.provider &&
          config.model?.baseUrl &&
          config.model?.model &&
          hasRequiredModelFields(config.model),
      ),
      config.model?.provider
        ? `Configured model connection: ${formatModelSummary(config.model)}`
        : `No model connection is configured yet. Run \`${CLI_COMMAND} onboard\` to add one.`,
    ),
  );
  checks.push(
    makeCheck(
      "Git provider configured",
      Boolean(config.gitProvider?.provider && config.gitProvider.provider !== "none"),
      config.gitProvider?.provider && config.gitProvider.provider !== "none"
        ? `Configured git provider: ${formatProviderSummary(config.gitProvider)}`
        : "No git provider is configured. Choose gitlab, github, or local during onboarding if you want guided repository access.",
    ),
  );

  printChecks(checks);
  if (checks.some((check) => !check.ok)) {
    process.exitCode = 1;
  }
}

async function runStatus() {
  await ensureMigratedRuntimeHome();
  const configExists = await fileExists(CONFIG_PATH);
  if (!configExists) {
    term.summaryBox(`${PRODUCT_NAME} status`, [
      ["Config", "not found"],
      ["Next step", `Run ${CLI_COMMAND} onboard`],
    ]);
    process.exitCode = 1;
    return;
  }

  const config = await readConfig();
  const runtimeState = await readState();
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  const workerBinding = parseWorkerBinding(workerUrl);
  const workerRunning = await isWorkerProcessRunning(runtimeState);
  const portState = await checkPortInUse(workerBinding.host, workerBinding.port, DEFAULT_PORT_CHECK_TIMEOUT_MS);
  const workerHealth = portState.inUse || workerRunning.running
    ? await checkWorkerHealth(
      workerUrl,
      DEFAULT_WORKER_HEALTH_TIMEOUT_MS,
    )
    : { reachable: false, message: "Worker is stopped." };
  const modelConnectivity = await checkModelConnectivity(
    config.model,
    DEFAULT_MODEL_CONNECTIVITY_TIMEOUT_MS,
  );

  console.log(term.banner());
  term.summaryBox(`${PRODUCT_NAME} status`, [
    ["Config", CONFIG_PATH],
    ["Worker URL", workerUrl],
    ["Worker", workerHealth.reachable ? "reachable" : "not reachable"],
    ["Worker process", workerRunning.running ? "running" : "stopped"],
    ["Model", formatModelSummary(config.model)],
    ["Model connectivity", modelConnectivity.reachable ? "reachable" : "not reachable"],
    ["Git provider", formatProviderSummary(config.gitProvider)],
    ["Repo base dir", config.localRepoBaseDir || "not configured"],
  ]);
  term.summaryBox("Runtime files", [
    ["PID file", runtimeState?.pidFile || PID_PATH],
    ["Worker log", runtimeState?.logPath || WORKER_LOG_PATH],
    ["Prepared", config.daemon?.prepared ? "yes" : "no"],
  ]);
  if (runtimeState?.failureType || runtimeState?.lastError) {
    term.summaryBox("Last startup detail", [
      ["Failure type", runtimeState?.failureType || "none"],
      ["Detail", runtimeState?.lastError || "none"],
    ]);
  }
  term.line(workerHealth.reachable ? "success" : "warning", "Worker detail", describeWorkerHealthState(workerHealth, runtimeState, portState));
  term.line(modelConnectivity.reachable ? "success" : "warning", "Model detail", modelConnectivity.message);
}

async function runUp() {
  await ensureBaseDirectories();
  const config = await requireConfig();
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  const webUrl = config.web?.baseUrl || DEFAULT_WEB_URL;

  console.log(term.banner());
  term.heading("Runtime", "Starting local product runtime", "RepoOperator will start the worker, start the web UI, and verify both endpoints.");
  await term.spinner("Start local worker", () => startWorker({ interactive: false, quiet: true }));

  const workerHealth = await term.spinner(
    "Verify worker health",
    () => checkWorkerHealth(
      workerUrl,
      DEFAULT_WORKER_HEALTH_TIMEOUT_MS,
    ),
  );
  if (!workerHealth.reachable) {
    throw new Error(`Local worker did not become healthy. ${workerHealth.message}`);
  }

  await term.spinner("Start web UI", () => startWeb({ interactive: false, quiet: true, workerUrl, webUrl }));

  const webHealth = await term.spinner("Verify web UI", () => checkWebHealth(webUrl, DEFAULT_WEB_HEALTH_TIMEOUT_MS));
  if (!webHealth.reachable) {
    throw new Error(`Web UI did not become healthy. ${webHealth.message}`);
  }

  term.summaryBox(`${PRODUCT_NAME} is up`, [
    ["Web UI", webUrl],
    ["Worker", workerUrl],
    ["Logs", WEB_LOG_PATH],
  ], "Open the web URL to choose a repository and start chatting.");
}

async function runDown() {
  await ensureMigratedRuntimeHome();
  term.heading("Runtime", "Stopping local product runtime");
  await term.spinner("Stop web UI", () => stopWeb({ interactive: false }));
  await term.spinner("Stop local worker", () => stopWorker({ interactive: false }));
  term.summaryBox(`${PRODUCT_NAME} is down`, [
    ["Web UI", "stopped"],
    ["Worker", "stopped"],
  ]);
}

async function startWorker({ interactive, quiet = false }) {
  await ensureBaseDirectories();
  const config = await requireConfig();
  const workerInstallation = await resolveWorkerInstallation(config, process.cwd());
  let runtimeState = await readState();
  const running = await isWorkerProcessRunning(runtimeState);
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  const workerBinding = parseWorkerBinding(workerUrl);

  if (running.running) {
    if (interactive) {
      term.summaryBox("Local worker", [
        ["Status", "already running"],
        ["Worker URL", workerUrl],
        ["Detail", running.message],
      ]);
    }
    return;
  }

  if (runtimeState?.pid && !running.running) {
    await clearRuntimeStateFiles();
    runtimeState = null;
  }

  if (!workerInstallation.installed || !workerInstallation.detectedPath) {
    throw new Error(
      `Local worker not installed. ${PRODUCT_NAME} could not find apps/local-worker in the current repository tree.`,
    );
  }

  const workerRuntime = await resolveWorkerRuntime(workerInstallation.detectedPath);
  const workerLaunch = await resolveWorkerLaunchConfig(workerInstallation.detectedPath);
  const portState = await checkPortInUse(workerBinding.host, workerBinding.port, DEFAULT_PORT_CHECK_TIMEOUT_MS);
  if (portState.inUse) {
    const occupiedMessage = `Configured worker URL ${workerUrl} is already in use. Stop the existing process or choose a different worker port.`;
    await writeRuntimeState({
      ...(runtimeState || {}),
      status: "failed",
      failedAt: new Date().toISOString(),
      failureType: "port_in_use",
      lastError: occupiedMessage,
      workerUrl,
      pidFile: PID_PATH,
      logPath: WORKER_LOG_PATH,
    });
    throw new Error(occupiedMessage);
  }
  await ensureLogFileExists(WORKER_LOG_PATH);
  const logStream = fs.openSync(WORKER_LOG_PATH, "a");
  const commandArgs = [
    "-m",
    "uvicorn",
    "openpatch_worker.main:app",
    "--host",
    workerBinding.host,
    "--port",
    String(workerBinding.port),
  ];
  const launchedCommand = `${workerRuntime.pythonPath} ${commandArgs.join(" ")}`;

  const env = {
    ...process.env,
    PYTHONPATH: buildPythonPathEnv(workerLaunch.srcPath, process.env.PYTHONPATH),
    REPOOPERATOR_CONFIG_PATH: CONFIG_PATH,
    OPENPATCH_CONFIG_PATH: CONFIG_PATH,
    LOCAL_REPO_BASE_DIR: config.localRepoBaseDir || DEFAULT_REPO_BASE_DIR,
    OPENAI_BASE_URL: config.model?.baseUrl || "",
    OPENAI_API_KEY: config.model?.apiKey || "",
    OPENAI_MODEL: config.model?.model || "",
  };

  if (config.gitProvider?.provider === "gitlab") {
    if (config.gitProvider.baseUrl) {
      env.GITLAB_BASE_URL = config.gitProvider.baseUrl;
    }
    if (config.gitProvider.token) {
      env.GITLAB_TOKEN = config.gitProvider.token;
    }
  }

  if (config.gitProvider?.provider === "github") {
    if (config.gitProvider.baseUrl) {
      env.GITHUB_BASE_URL = config.gitProvider.baseUrl;
    }
    if (config.gitProvider.token) {
      env.GITHUB_TOKEN = config.gitProvider.token;
    }
  }

  if (interactive && !quiet) {
    term.heading("Worker", "Starting local worker");
    term.summaryBox("Launch plan", [
      ["Command", launchedCommand],
      ["Working directory", workerInstallation.detectedPath],
      ["Worker src", workerLaunch.srcPath],
      ["Health URL", `${workerUrl}/health`],
      ["Log file", WORKER_LOG_PATH],
      ["PID file", PID_PATH],
    ]);
  }

  let child;
  try {
    child = spawn(workerRuntime.pythonPath, commandArgs, {
      cwd: workerInstallation.detectedPath,
      detached: true,
      stdio: ["ignore", logStream, logStream],
      env,
    });
  } finally {
    fs.closeSync(logStream);
  }

  if (!child.pid) {
    throw new Error("Worker failed to start. No process id was returned by the launcher.");
  }

  let earlyExit = null;
  let startupErrorMessage = null;
  child.once("exit", (code, signal) => {
    earlyExit = { code, signal };
  });
  child.once("error", (error) => {
    startupErrorMessage = error instanceof Error ? error.message : String(error);
  });

  child.unref();

  await writeRuntimeState({
    ...(runtimeState || {}),
    preparedAt: runtimeState?.preparedAt || new Date().toISOString(),
    startedAt: new Date().toISOString(),
    status: "starting",
    pid: child.pid,
    workerUrl,
    pidFile: PID_PATH,
    logPath: WORKER_LOG_PATH,
    installMode: workerInstallation.installMode,
    workerPath: workerInstallation.detectedPath,
    srcPath: workerLaunch.srcPath,
    pythonPathEnv: env.PYTHONPATH,
    pythonPath: workerRuntime.pythonPath,
    command: launchedCommand,
    failureType: null,
    lastError: null,
  });

  const startupHealth = await waitForWorkerStartup({
    baseUrl: workerUrl,
    pid: child.pid,
    timeoutMs: DEFAULT_WORKER_START_TIMEOUT_MS,
    getEarlyExit: () => earlyExit,
    getStartupError: () => startupErrorMessage,
  });
  if (!startupHealth.reachable) {
    await safeStopWorkerProcess(child.pid);
    const logTail = await readLogTail(WORKER_LOG_PATH, DEFAULT_LOG_TAIL_LINES);
    await writeRuntimeState({
      ...(await readState()),
      status: "failed",
      failedAt: new Date().toISOString(),
      failureType: classifyWorkerStartupFailure(startupHealth, logTail),
      lastError: startupHealth.message,
      lastLogTail: logTail,
      exitCode: startupHealth.exitCode ?? null,
      exitSignal: startupHealth.exitSignal ?? null,
    });
    term.line("error", "Startup failure", startupHealth.message);
    term.line("info", "Process exited", startupHealth.exited ? "yes" : "no");
    term.line("info", "Exit code", String(startupHealth.exitCode ?? "unknown"));
    if (logTail) {
      term.summaryBox("Recent worker log output", logTail.split(/\r?\n/).slice(-12));
    }
    throw new Error(
      `Worker failed to start. ${startupHealth.message} Check logs with \`${CLI_COMMAND} worker logs\`.`,
    );
  }

  await writeRuntimeState({
    ...(await readState()),
    status: "running",
    healthyAt: new Date().toISOString(),
  });

  if (interactive) {
    term.summaryBox("Local worker started", [
      ["Worker URL", workerUrl],
      ["Logs", WORKER_LOG_PATH],
      ["PID file", PID_PATH],
    ]);
  }
}

async function stopWorker({ interactive }) {
  await ensureMigratedRuntimeHome();
  const config = await readConfig().catch(() => null);
  const runtimeState = await readState();
  const workerUrl = config?.worker?.baseUrl || runtimeState?.workerUrl || DEFAULT_WORKER_URL;
  const workerBinding = parseWorkerBinding(workerUrl);
  const running = await isWorkerProcessRunning(runtimeState);
  const stopResult = await stopWorkerProcess(runtimeState?.pid || null);
  const portState = await checkPortInUse(
    workerBinding.host,
    workerBinding.port,
    DEFAULT_PORT_CHECK_TIMEOUT_MS,
  );
  const workerHealth = portState.inUse
    ? await checkWorkerHealth(workerUrl, DEFAULT_WORKER_HEALTH_TIMEOUT_MS)
    : { reachable: false, message: "Worker is stopped." };

  if (!stopResult.exited) {
    throw new Error(
      `${PRODUCT_NAME} could not fully stop the recorded worker process${runtimeState?.pid ? ` ${runtimeState.pid}` : ""}.`,
    );
  }

  if (portState.inUse) {
    const detail = workerHealth.reachable
      ? `Another responding worker or service is still listening on ${workerUrl}.`
      : `Another process is still occupying ${workerUrl}.`;
    const prefix = stopResult.hadPid
      ? `${PRODUCT_NAME} stopped the recorded worker process, but the configured worker port is still in use.`
      : `${PRODUCT_NAME} did not have a running recorded worker process, but the configured worker port is still in use.`;
    throw new Error(
      `${prefix} ${detail}`,
    );
  }

  await clearRuntimeStateFiles();

  if (interactive) {
    if (!runtimeState?.pid || !running.running) {
      term.summaryBox("Local worker", [
        ["Status", "already stopped"],
        ["Cleanup", "stale runtime state removed"],
      ]);
    } else if (stopResult.forced) {
      term.summaryBox("Local worker stopped", [
        ["Status", "force-stopped"],
        ["PID", String(runtimeState.pid)],
      ]);
    } else {
      term.summaryBox("Local worker stopped", [
        ["Status", "stopped cleanly"],
        ["PID", String(runtimeState.pid)],
      ]);
    }
  }
}

async function restartWorker() {
  const config = await requireConfig();
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  term.heading("Worker", "Restarting local worker");
  await term.spinner("Stop local worker", () => stopWorker({ interactive: false }));
  await term.spinner("Start local worker", () => startWorker({ interactive: false, quiet: true }));
  term.summaryBox("Local worker restarted", [
    ["Worker URL", workerUrl],
    ["Logs", WORKER_LOG_PATH],
  ]);
}

async function startWeb({ interactive, quiet = false, workerUrl, webUrl }) {
  await ensureBaseDirectories();
  const config = await requireConfig();
  const webInstallation = await resolveWebInstallation(config, process.cwd());
  let webState = await readWebState();
  const running = await isProcessRunning(webState?.pid);
  const webBinding = parseLocalHttpBinding(webUrl, "web UI URL");

  if (running.running) {
    if (interactive) {
      term.summaryBox("Web UI", [
        ["Status", "already running"],
        ["Web URL", webUrl],
        ["Detail", running.message],
      ]);
    }
    return;
  }

  if (webState?.pid && !running.running) {
    await clearWebRuntimeStateFiles();
    webState = null;
  }

  if (!webInstallation.installed || !webInstallation.detectedPath) {
    throw new Error(
      `Web UI not installed. ${PRODUCT_NAME} could not find apps/web in the current repository tree.`,
    );
  }

  if (!(await commandExists("npm"))) {
    throw new Error("npm is missing. Install Node.js and npm before starting the web UI.");
  }

  const portState = await checkPortInUse(webBinding.host, webBinding.port, DEFAULT_PORT_CHECK_TIMEOUT_MS);
  if (portState.inUse) {
    const webHealth = await checkWebHealth(webUrl, DEFAULT_WEB_HEALTH_TIMEOUT_MS);
    if (webHealth.reachable) {
      await writeWebRuntimeState({
        ...(webState || {}),
        status: "running",
        webUrl,
        workerUrl,
        pidFile: WEB_PID_PATH,
        logPath: WEB_LOG_PATH,
        note: "Web UI was already reachable on the configured URL.",
      });
      if (interactive) {
        term.summaryBox("Web UI", [
          ["Status", "already reachable"],
          ["Web URL", webUrl],
        ]);
      }
      return;
    }
    throw new Error(
      `Configured web URL ${webUrl} is already in use, but the RepoOperator web UI did not respond successfully.`,
    );
  }

  await ensureLogFileExists(WEB_LOG_PATH);
  const logStream = fs.openSync(WEB_LOG_PATH, "a");
  const commandArgs = [
    "run",
    "dev",
    "--",
    "--hostname",
    webBinding.host,
    "--port",
    String(webBinding.port),
  ];
  const launchedCommand = `npm ${commandArgs.join(" ")}`;
  const env = {
    ...process.env,
    NEXT_PUBLIC_LOCAL_WORKER_BASE_URL: workerUrl,
  };

  if (interactive && !quiet) {
    term.heading("Web UI", "Starting web app");
    term.summaryBox("Launch plan", [
      ["Command", launchedCommand],
      ["Working directory", webInstallation.detectedPath],
      ["Web URL", webUrl],
      ["Worker URL", workerUrl],
      ["Log file", WEB_LOG_PATH],
      ["PID file", WEB_PID_PATH],
    ]);
  }

  let child;
  try {
    child = spawn("npm", commandArgs, {
      cwd: webInstallation.detectedPath,
      detached: true,
      stdio: ["ignore", logStream, logStream],
      env,
    });
  } finally {
    fs.closeSync(logStream);
  }

  if (!child.pid) {
    throw new Error("Web UI failed to start. No process id was returned by the launcher.");
  }

  let earlyExit = null;
  let startupErrorMessage = null;
  child.once("exit", (code, signal) => {
    earlyExit = { code, signal };
  });
  child.once("error", (error) => {
    startupErrorMessage = error instanceof Error ? error.message : String(error);
  });

  child.unref();

  await writeWebRuntimeState({
    ...(webState || {}),
    startedAt: new Date().toISOString(),
    status: "starting",
    pid: child.pid,
    webUrl,
    workerUrl,
    pidFile: WEB_PID_PATH,
    logPath: WEB_LOG_PATH,
    webPath: webInstallation.detectedPath,
    command: launchedCommand,
    failureType: null,
    lastError: null,
  });

  const startupHealth = await waitForWebStartup({
    baseUrl: webUrl,
    pid: child.pid,
    timeoutMs: DEFAULT_WEB_START_TIMEOUT_MS,
    getEarlyExit: () => earlyExit,
    getStartupError: () => startupErrorMessage,
  });
  if (!startupHealth.reachable) {
    await safeStopWorkerProcess(child.pid);
    const logTail = await readLogTail(WEB_LOG_PATH, DEFAULT_LOG_TAIL_LINES);
    await writeWebRuntimeState({
      ...(await readWebState()),
      status: "failed",
      failedAt: new Date().toISOString(),
      failureType: startupHealth.exited ? "process_exited" : "health_timeout",
      lastError: startupHealth.message,
      lastLogTail: logTail,
      exitCode: startupHealth.exitCode ?? null,
      exitSignal: startupHealth.exitSignal ?? null,
    });
    term.line("error", "Web startup failure", startupHealth.message);
    if (logTail) {
      term.summaryBox("Recent web log output", logTail.split(/\r?\n/).slice(-12));
    }
    throw new Error(
      `Web UI failed to start. ${startupHealth.message} Check logs at ${WEB_LOG_PATH}.`,
    );
  }

  await writeWebRuntimeState({
    ...(await readWebState()),
    status: "running",
    healthyAt: new Date().toISOString(),
  });

  if (interactive) {
    term.summaryBox("Web UI started", [
      ["Web URL", webUrl],
      ["Worker URL", workerUrl],
      ["Logs", WEB_LOG_PATH],
    ]);
  }
}

async function stopWeb({ interactive }) {
  await ensureMigratedRuntimeHome();
  const webState = await readWebState();
  const config = await readConfig().catch(() => null);
  const webUrl = config?.web?.baseUrl || webState?.webUrl || DEFAULT_WEB_URL;
  const webBinding = parseLocalHttpBinding(webUrl, "web UI URL");
  const running = await isProcessRunning(webState?.pid);
  const stopResult = await stopWorkerProcess(webState?.pid || null);
  const portState = await checkPortInUse(
    webBinding.host,
    webBinding.port,
    DEFAULT_PORT_CHECK_TIMEOUT_MS,
  );

  if (!stopResult.exited) {
    throw new Error(
      `${PRODUCT_NAME} could not fully stop the recorded web UI process${webState?.pid ? ` ${webState.pid}` : ""}.`,
    );
  }

  if (portState.inUse && stopResult.hadPid) {
    throw new Error(
      `${PRODUCT_NAME} stopped the recorded web UI process, but another process is still occupying ${webUrl}.`,
    );
  }

  await clearWebRuntimeStateFiles();

  if (interactive) {
    if (!webState?.pid || !running.running) {
      term.summaryBox("Web UI", [
        ["Status", "already stopped"],
        ["Cleanup", "stale runtime state removed"],
      ]);
    } else if (stopResult.forced) {
      term.summaryBox("Web UI stopped", [
        ["Status", "force-stopped"],
        ["PID", String(webState.pid)],
      ]);
    } else {
      term.summaryBox("Web UI stopped", [
        ["Status", "stopped cleanly"],
        ["PID", String(webState.pid)],
      ]);
    }
  }
}

async function showWorkerLogs() {
  const state = await readState();
  const logPath = state?.logPath || WORKER_LOG_PATH;

  if (!(await fileExists(logPath))) {
    throw new Error(`Worker log file not found at ${logPath}`);
  }

  const logContent = await readLogTail(logPath, 200);
  term.heading("Worker", "Recent local worker logs", logPath);
  process.stdout.write(logContent || "(log file is empty)\n");
}

async function showWorkerStatus() {
  await ensureMigratedRuntimeHome();
  const configExists = await fileExists(CONFIG_PATH);
  if (!configExists) {
    term.summaryBox(`${PRODUCT_NAME} worker status`, [
      ["Config", "not found"],
      ["Next step", `Run ${CLI_COMMAND} onboard`],
    ]);
    process.exitCode = 1;
    return;
  }

  const config = await readConfig();
  const runtimeState = await readState();
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  const workerBinding = parseWorkerBinding(workerUrl);
  const workerRunning = await isWorkerProcessRunning(runtimeState);
  const portState = await checkPortInUse(workerBinding.host, workerBinding.port, DEFAULT_PORT_CHECK_TIMEOUT_MS);
  const workerHealth = portState.inUse || workerRunning.running
    ? await checkWorkerHealth(workerUrl, DEFAULT_WORKER_HEALTH_TIMEOUT_MS)
    : { reachable: false, message: "Worker is stopped." };

  term.summaryBox(`${PRODUCT_NAME} worker status`, [
    ["Worker URL", workerUrl],
    ["PID", runtimeState?.pid ?? "not recorded"],
    ["Process", workerRunning.running ? "running" : "stopped"],
    ["Health", workerHealth.reachable ? "responding" : "not responding"],
    ["Port", portState.inUse ? "in use" : "available"],
    ["Log file", runtimeState?.logPath || WORKER_LOG_PATH],
  ]);
  term.line(workerHealth.reachable ? "success" : "warning", "Health detail", describeWorkerHealthState(workerHealth, runtimeState, portState));
  term.line(workerRunning.running ? "success" : "warning", "Process detail", describeWorkerProcessState(workerRunning, runtimeState));
  term.line(portState.inUse && !workerHealth.reachable ? "warning" : "info", "Port detail", describePortState(portState, workerUrl, workerHealth.reachable));
  if (runtimeState?.failureType) {
    term.line("warning", "Last startup failure", runtimeState.failureType);
  }
  if (runtimeState?.lastError) {
    term.line("warning", "Last startup detail", runtimeState.lastError);
  }
}

async function ensureBaseDirectories() {
  await ensureMigratedRuntimeHome();
  await fsp.mkdir(CONFIG_DIR, { recursive: true });
  await fsp.mkdir(RUN_DIR, { recursive: true });
  await fsp.mkdir(LOG_DIR, { recursive: true });
}

let migrationChecked = false;

async function ensureMigratedRuntimeHome() {
  if (migrationChecked) {
    return;
  }

  await fsp.mkdir(CONFIG_DIR, { recursive: true });
  await fsp.mkdir(RUN_DIR, { recursive: true });
  await fsp.mkdir(LOG_DIR, { recursive: true });

  const repooperatorExists =
    (await fileExists(CONFIG_PATH))
    || (await fileExists(STATE_PATH))
    || (await fileExists(PID_PATH))
    || (await fileExists(WORKER_LOG_PATH));
  const legacyExists =
    (await fileExists(LEGACY_CONFIG_PATH))
    || (await fileExists(LEGACY_RUN_STATE_PATH))
    || (await fileExists(LEGACY_STATE_PATH))
    || (await fileExists(path.join(LEGACY_RUN_DIR, "worker.pid")))
    || (await fileExists(path.join(LEGACY_LOG_DIR, "worker.log")));

  if (!repooperatorExists && legacyExists) {
    await copyFileIfMissing(LEGACY_CONFIG_PATH, CONFIG_PATH);
    await copyFileIfMissing(LEGACY_RUN_STATE_PATH, STATE_PATH);
    await copyFileIfMissing(LEGACY_STATE_PATH, STATE_PATH);
    await copyFileIfMissing(path.join(LEGACY_RUN_DIR, "worker.pid"), PID_PATH);
    await copyFileIfMissing(path.join(LEGACY_LOG_DIR, "worker.log"), WORKER_LOG_PATH);
    await copyFileIfMissing(path.join(LEGACY_LOG_DIR, "ollama.log"), OLLAMA_LOG_PATH);
  }

  migrationChecked = true;
}

async function copyFileIfMissing(sourcePath, targetPath) {
  if (!(await fileExists(sourcePath)) || (await fileExists(targetPath))) {
    return;
  }
  await fsp.mkdir(path.dirname(targetPath), { recursive: true });
  await fsp.copyFile(sourcePath, targetPath);
}

async function resolveWorkerInstallation(config, startDir) {
  if (config?.worker?.detectedPath && (await fileExists(path.join(config.worker.detectedPath, "pyproject.toml")))) {
    return {
      installed: true,
      installMode: config.worker.installMode || "repo-source",
      detectedPath: config.worker.detectedPath,
      summary: `Detected a repo-source local worker at ${config.worker.detectedPath}`,
    };
  }
  return detectLocalWorkerInstallation(startDir);
}

async function detectLocalWorkerInstallation(startDir) {
  const repoRoot = await findRepoRootWithWorker(startDir);
  if (repoRoot) {
    return {
      installed: true,
      installMode: "repo-source",
      detectedPath: path.join(repoRoot, "apps", "local-worker"),
      summary: `Detected a repo-source local worker at ${path.join(repoRoot, "apps", "local-worker")}`,
    };
  }

  return {
    installed: false,
    installMode: "not-detected",
    detectedPath: null,
    summary: "No local worker installation was detected in the current repository tree.",
  };
}

async function resolveWebInstallation(config, startDir) {
  if (config?.web?.detectedPath && (await fileExists(path.join(config.web.detectedPath, "package.json")))) {
    return {
      installed: true,
      detectedPath: config.web.detectedPath,
      summary: `Detected a repo-source web UI at ${config.web.detectedPath}`,
    };
  }

  const repoRoot = await findRepoRootWithWeb(startDir);
  if (repoRoot) {
    return {
      installed: true,
      detectedPath: path.join(repoRoot, "apps", "web"),
      summary: `Detected a repo-source web UI at ${path.join(repoRoot, "apps", "web")}`,
    };
  }

  if (config?.worker?.detectedPath) {
    const candidate = path.resolve(config.worker.detectedPath, "..", "web");
    if (await fileExists(path.join(candidate, "package.json"))) {
      return {
        installed: true,
        detectedPath: candidate,
        summary: `Detected a repo-source web UI at ${candidate}`,
      };
    }
  }

  return {
    installed: false,
    detectedPath: null,
    summary: "No web UI installation was detected in the current repository tree.",
  };
}

async function findRepoRootWithWorker(startDir) {
  let current = path.resolve(startDir);

  while (true) {
    const candidate = path.join(current, "apps", "local-worker", "pyproject.toml");
    if (await fileExists(candidate)) {
      return current;
    }

    const parent = path.dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

async function findRepoRootWithWeb(startDir) {
  let current = path.resolve(startDir);

  while (true) {
    const candidate = path.join(current, "apps", "web", "package.json");
    if (await fileExists(candidate)) {
      return current;
    }

    const parent = path.dirname(current);
    if (parent === current) {
      return null;
    }
    current = parent;
  }
}

async function resolveWorkerRuntime(workerPath) {
  const venvPath = path.join(workerPath, ".venv");
  const pythonPath = path.join(venvPath, "bin", "python");

  if (!(await commandExists("python3"))) {
    throw new Error("Python is missing. Install Python 3.11+ before starting the local worker.");
  }

  if (!(await fileExists(venvPath))) {
    throw new Error(
      `Worker virtual environment is missing at ${venvPath}. Create it with \`cd ${workerPath} && python3 -m venv .venv && source .venv/bin/activate && pip install -e .\`.`,
    );
  }

  if (!(await fileExists(pythonPath))) {
    throw new Error(
      `Worker Python executable is missing at ${pythonPath}. Recreate the virtual environment in ${workerPath}.`,
    );
  }

  return { pythonPath };
}

async function resolveWorkerLaunchConfig(workerPath) {
  const srcPath = path.join(workerPath, "src");
  const moduleEntry = path.join(srcPath, "openpatch_worker", "main.py");

  if (!(await fileExists(moduleEntry))) {
    throw new Error(
      `Worker app entrypoint not found at ${moduleEntry}. ${PRODUCT_NAME} expected a src-layout worker package.`,
    );
  }

  return { srcPath, moduleEntry };
}

async function commandExists(command) {
  const pathValue = process.env.PATH || "";
  for (const segment of pathValue.split(path.delimiter)) {
    const candidate = path.join(segment, command);
    if (await fileExists(candidate)) {
      return true;
    }
  }
  return false;
}

async function runInteractiveCommand(command, args, options = {}) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd || process.cwd(),
      env: options.env || process.env,
      stdio: "inherit",
    });

    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} ${args.join(" ")} exited with code ${code ?? "unknown"}.`));
    });
  });
}

async function runCommandCapture(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd || process.cwd(),
      env: options.env || process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdoutContent = "";
    let stderrContent = "";
    child.stdout.on("data", (chunk) => {
      stdoutContent += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderrContent += chunk.toString();
    });
    child.once("error", (error) => {
      resolve({
        returncode: 1,
        stdout: stdoutContent,
        stderr: error instanceof Error ? error.message : String(error),
      });
    });
    child.once("exit", (code) => {
      resolve({
        returncode: code ?? 0,
        stdout: stdoutContent,
        stderr: stderrContent,
      });
    });
  });
}

async function startOllamaServer(baseUrl) {
  await ensureLogFileExists(OLLAMA_LOG_PATH);
  const logStream = fs.openSync(OLLAMA_LOG_PATH, "a");
  const rootUrl = getOllamaRootUrl(baseUrl);
  const parsedUrl = new URL(rootUrl);

  try {
    const child = spawn("ollama", ["serve"], {
      cwd: process.cwd(),
      detached: true,
      stdio: ["ignore", logStream, logStream],
      env: {
        ...process.env,
        OLLAMA_HOST: `${parsedUrl.hostname}:${parsedUrl.port || "11434"}`,
      },
    });

    if (!child.pid) {
      throw new Error("No process id was returned while starting Ollama.");
    }
    child.unref();
  } finally {
    fs.closeSync(logStream);
  }
}

async function pullOllamaModel(modelName) {
  console.log(`Pulling Ollama model: ${modelName}`);
  await runInteractiveCommand("ollama", ["pull", modelName]);
}

async function checkOllamaServer(baseUrl, timeoutMs) {
  const rootUrl = getOllamaRootUrl(baseUrl);
  const tagsUrl = `${rootUrl}/api/tags`;

  try {
    const response = await fetchWithTimeout(tagsUrl, {
      method: "GET",
      timeoutMs,
    });

    if (!response.ok) {
      return {
        reachable: false,
        models: [],
        message: `Ollama responded with status ${response.status} at ${tagsUrl}.`,
      };
    }

    const payload = await response.json();
    const models = Array.isArray(payload.models)
      ? payload.models
          .map((entry) => entry?.name)
          .filter((name) => typeof name === "string" && name.trim())
      : [];

    return {
      reachable: true,
      models,
      message: `Ollama is reachable at ${tagsUrl}.`,
    };
  } catch (error) {
    return {
      reachable: false,
      models: [],
      message: `${PRODUCT_NAME} could not reach Ollama at ${tagsUrl}: ${formatTimeoutAwareError(error, `Ollama check timed out after ${Math.round(timeoutMs / 1000)} seconds.`)}`,
    };
  }
}

async function waitForOllamaServer(baseUrl, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const status = await checkOllamaServer(baseUrl, DEFAULT_OLLAMA_TIMEOUT_MS);
    if (status.reachable) {
      return status;
    }
    await sleep(500);
  }

  return {
    reachable: false,
    models: [],
    message: `Ollama did not become reachable within ${Math.round(timeoutMs / 1000)} seconds.`,
  };
}

async function checkWorkerHealth(baseUrl, timeoutMs) {
  try {
    const response = await fetchWithTimeout(`${baseUrl}/health`, {
      method: "GET",
      timeoutMs,
    });
    if (!response.ok) {
      return {
        reachable: false,
        message: `Worker responded with status ${response.status}.`,
      };
    }

    const payload = await response.json();
    return {
      reachable: true,
      message: `Worker is reachable and reported status '${payload.status}'.`,
    };
  } catch (error) {
    const message = formatTimeoutAwareError(error, `Worker health check timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
    return {
      reachable: false,
      message: `Worker is not reachable at ${baseUrl}: ${message}`,
    };
  }
}

async function checkWebHealth(baseUrl, timeoutMs) {
  try {
    const response = await fetchWithTimeout(baseUrl, {
      method: "GET",
      timeoutMs,
    });
    if (!response.ok) {
      return {
        reachable: false,
        message: `Web UI responded with status ${response.status}.`,
      };
    }

    return {
      reachable: true,
      message: `Web UI is reachable at ${baseUrl}.`,
    };
  } catch (error) {
    const message = formatTimeoutAwareError(error, `Web UI health check timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
    return {
      reachable: false,
      message: `Web UI is not reachable at ${baseUrl}: ${message}`,
    };
  }
}

async function waitForWorkerStartup({ baseUrl, pid, timeoutMs, getEarlyExit, getStartupError }) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const earlyExit = getEarlyExit();
    if (earlyExit) {
      return {
        reachable: false,
        exited: true,
        exitCode: earlyExit.code,
        exitSignal: earlyExit.signal,
        message: `Worker process exited immediately${earlyExit.code !== null ? ` with code ${earlyExit.code}` : ""}${earlyExit.signal ? ` and signal ${earlyExit.signal}` : ""}.`,
      };
    }

    const startupError = getStartupError();
    if (startupError) {
      return {
        reachable: false,
        exited: false,
        message: `Worker failed to start: ${startupError}`,
      };
    }

    const running = await isWorkerProcessRunning({ pid });
    if (!running.running) {
      return {
        reachable: false,
        exited: true,
        message: "Worker process exited immediately after launch.",
      };
    }

    const health = await checkWorkerHealth(baseUrl, DEFAULT_WORKER_HEALTH_TIMEOUT_MS);
    if (health.reachable) {
      return health;
    }
    await sleep(500);
  }
  return {
    reachable: false,
    exited: false,
    message: `Worker health check timed out after ${Math.round(timeoutMs / 1000)} seconds at ${baseUrl}.`,
  };
}

async function waitForWebStartup({ baseUrl, pid, timeoutMs, getEarlyExit, getStartupError }) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const earlyExit = getEarlyExit();
    if (earlyExit) {
      return {
        reachable: false,
        exited: true,
        exitCode: earlyExit.code,
        exitSignal: earlyExit.signal,
        message: `Web UI process exited immediately${earlyExit.code !== null ? ` with code ${earlyExit.code}` : ""}${earlyExit.signal ? ` and signal ${earlyExit.signal}` : ""}.`,
      };
    }

    const startupError = getStartupError();
    if (startupError) {
      return {
        reachable: false,
        exited: false,
        message: `Web UI failed to start: ${startupError}`,
      };
    }

    const running = await isProcessRunning(pid);
    if (!running.running) {
      return {
        reachable: false,
        exited: true,
        message: "Web UI process exited immediately after launch.",
      };
    }

    const health = await checkWebHealth(baseUrl, DEFAULT_WEB_HEALTH_TIMEOUT_MS);
    if (health.reachable) {
      return health;
    }
    await sleep(500);
  }
  return {
    reachable: false,
    exited: false,
    message: `Web UI health check timed out after ${Math.round(timeoutMs / 1000)} seconds at ${baseUrl}.`,
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function promptGitProviderConfig(rl, provider) {
  if (provider === "gitlab") {
    term.summaryBox("GitLab source", [
      "Use a GitLab personal, project, or group token with repository read access.",
      "RepoOperator stores the base URL and token locally for the worker.",
    ]);
    const baseUrl = await promptWithDefault(
      rl,
      "GitLab base URL",
      "https://gitlab.com",
    );
    const token = await promptWithDefault(rl, "GitLab token", "");
    return { provider: "gitlab", baseUrl, token };
  }

  if (provider === "github") {
    term.summaryBox("GitHub source", [
      "Use a GitHub token that can read the repositories you want to open.",
      "GitHub Enterprise URLs are supported through the base URL prompt.",
    ]);
    const baseUrl = await promptWithDefault(
      rl,
      "GitHub base URL",
      "https://github.com",
    );
    const token = await promptWithDefault(rl, "GitHub token", "");
    return { provider: "github", baseUrl, token };
  }

  if (provider === "local") {
    term.summaryBox("Local project source", [
      "Use absolute filesystem paths for repositories or plain directories.",
      "Recent local projects will appear in the web app after they are opened.",
    ]);
    return { provider: "local" };
  }

  term.line("info", "Repository source skipped", "You can rerun onboarding later to add one.");
  return { provider: "none" };
}

async function promptModelConfig(rl) {
  const connectionMode = await promptModelConnectionMode(rl);

  if (connectionMode === "local-runtime") {
    return promptLocalRuntimeModelConfig(rl);
  }

  return promptRemoteApiModelConfig(rl);
}

async function promptLocalRuntimeModelConfig(rl) {
  const provider = await promptLocalRuntimeProvider(rl);
  if (provider === "ollama") {
    return promptOllamaModelConfig(rl);
  }
  throw new Error(`Unsupported local runtime provider: ${provider}`);
}

async function promptRemoteApiModelConfig(rl) {
  const provider = await promptRemoteApiProvider(rl);

  const providerConfig = MODEL_PROVIDER_CONFIG[provider];

  term.summaryBox(`Remote model API: ${providerConfig.label}`, [
    "RepoOperator will use these settings when the local worker calls your model API.",
    "Secrets are stored locally in ~/.repooperator/config.json.",
  ]);

  let baseUrl = providerConfig.defaultBaseUrl || "";
  let apiKey = providerConfig.defaultApiKey || "";
  let model = providerConfig.defaultModel || "";

  if (providerConfig.prompts.includes("baseUrl")) {
    baseUrl = await promptWithDefault(rl, "Base URL", baseUrl);
  }

  if (providerConfig.prompts.includes("apiKey")) {
    apiKey = await promptWithDefault(rl, "API key", apiKey);
  }

  if (providerConfig.prompts.includes("model")) {
    model = await promptWithDefault(rl, "Model name", model);
  }

  if (!providerConfig.prompts.includes("baseUrl")) {
    baseUrl = providerConfig.defaultBaseUrl;
  }

  if (!providerConfig.prompts.includes("apiKey")) {
    apiKey = providerConfig.defaultApiKey || "";
  }

  return {
    connectionMode: "remote-api",
    provider,
    baseUrl,
    apiKey,
    model,
  };
}

async function promptOllamaModelConfig(rl) {
  term.summaryBox("Local model runtime: Ollama", [
    "RepoOperator will detect the Ollama command, check the local server, and list available models.",
    `Recommended coding model: ${OLLAMA_RECOMMENDED_MODEL}`,
  ]);

  const commandInstalled = await term.spinner("Check ollama command", () => commandExists("ollama"));
  if (!commandInstalled) {
    const installedNow = await ensureOllamaInstalled(rl);
    if (!installedNow) {
      throw new Error(`Ollama is required for the guided local Ollama setup. Install it, then rerun \`${CLI_COMMAND} onboard\`.`);
    }
  }

  const baseUrl = await promptWithDefault(rl, "Ollama base URL", OLLAMA_DEFAULT_BASE_URL);
  const serverState = await ensureOllamaServerReady(rl, baseUrl);
  const listedModels = await listOllamaModels();
  const selectedModel = await chooseOllamaModel(
    rl,
    baseUrl,
    listedModels.length ? listedModels : serverState.models || [],
  );

  return {
    connectionMode: "local-runtime",
    provider: "ollama",
    baseUrl,
    apiKey: "ollama",
    model: selectedModel,
  };
}

async function promptModelConnectionMode(rl) {
  while (true) {
    printOptionList("Choose how RepoOperator should connect to a model", [
      ["1", "Local model runtime", "Ollama on this machine"],
      ["2", "Remote model API", "OpenAI-compatible or hosted provider"],
    ]);
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "local-runtime";
    }
    if (answer === "2") {
      return "remote-api";
    }
    term.line("warning", "Invalid choice", "Please choose 1 or 2.");
  }
}

async function promptLocalRuntimeProvider(rl) {
  while (true) {
    printOptionList("Choose a local model runtime", [
      ["1", "Ollama", "Local OpenAI-compatible model server"],
    ]);
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "ollama";
    }
    term.line("warning", "Invalid choice", "Please choose 1.");
  }
}

async function promptRemoteApiProvider(rl) {
  while (true) {
    printOptionList("Choose a remote model API", [
      ["1", "OpenAI-compatible", "Enterprise gateways and compatible APIs"],
      ["2", "OpenAI", "OpenAI API"],
      ["3", "Anthropic", "Anthropic API"],
      ["4", "Gemini", "Gemini OpenAI-compatible endpoint"],
    ]);
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "openai-compatible";
    }
    if (answer === "2") {
      return "openai";
    }
    if (answer === "3") {
      return "anthropic";
    }
    if (answer === "4") {
      return "gemini";
    }
    term.line("warning", "Invalid choice", "Please choose 1, 2, 3, or 4.");
  }
}

async function promptGitProvider(rl) {
  while (true) {
    printOptionList("Select a repository source", [
      ["1", "GitLab", "Project discovery, clone, fetch, branch selection"],
      ["2", "GitHub", "Repository discovery and clone/fetch support"],
      ["3", "Local project", "Open absolute paths on this machine"],
      ["4", "None for now", "Configure repository access later"],
    ]);
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "gitlab";
    }
    if (answer === "2") {
      return "github";
    }
    if (answer === "3") {
      return "local";
    }
    if (answer === "4") {
      return "none";
    }
    term.line("warning", "Invalid choice", "Please choose 1, 2, 3, or 4.");
  }
}

async function promptWithDefault(rl, label, defaultValue) {
  const suffix = defaultValue ? ` [${defaultValue}]` : "";
  const answer = await rl.question(`${label}${suffix}: `);
  const trimmed = answer.trim();
  return trimmed || defaultValue;
}

async function promptYesNo(rl, prompt, defaultYes) {
  const suffix = defaultYes ? " [Y/n]: " : " [y/N]: ";
  const answer = (await rl.question(`${prompt}${suffix}`)).trim().toLowerCase();
  if (!answer) {
    return defaultYes;
  }
  return answer === "y" || answer === "yes";
}

function printOptionList(title, rows) {
  console.log("");
  term.summaryBox(title, rows.map(([choice, label, detail]) => `${choice}. ${label} - ${detail}`));
}

async function ensureOllamaInstalled(rl) {
  term.line("warning", "Ollama command not found", "RepoOperator can guide installation options.");

  if (process.platform === "darwin") {
    const brewInstalled = await commandExists("brew");
    if (brewInstalled) {
      const installNow = await promptYesNo(
        rl,
        "Homebrew is available. Install Ollama now with `brew install ollama`?",
        true,
      );
      if (installNow) {
        term.line("info", "Installing Ollama", "brew install ollama");
        await runInteractiveCommand("brew", ["install", "ollama"]);
        return commandExists("ollama");
      }
    }

    term.summaryBox("Install Ollama on macOS", [
      "Install Homebrew and run: brew install ollama",
      "Or install Ollama from the official macOS installer.",
      `Then rerun: ${CLI_COMMAND} onboard`,
    ]);
    return false;
  }

  term.summaryBox("Install Ollama", [
    "Use your system package manager if available.",
    "Or install Ollama from the official installer for your platform.",
    `Then rerun: ${CLI_COMMAND} onboard`,
  ]);
  return false;
}

async function listOllamaModels() {
  const result = await term.spinner("Run ollama list", () => runCommandCapture("ollama", ["list"]));
  if (result.returncode !== 0) {
    term.line("warning", "ollama list failed", result.stderr || "Unable to list local models.");
    return [];
  }

  return result.stdout
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.trim().split(/\s+/)[0])
    .filter(Boolean);
}

async function ensureOllamaServerReady(rl, baseUrl) {
  const initialState = await term.spinner("Check Ollama server", () =>
    checkOllamaServer(baseUrl, DEFAULT_OLLAMA_TIMEOUT_MS),
  );
  if (initialState.reachable) {
    term.line("success", "Ollama is reachable", baseUrl);
    return initialState;
  }

  term.line("warning", "Ollama server is not reachable", initialState.message);

  const startNow = await promptYesNo(
    rl,
    "Start the Ollama server now?",
    true,
  );
  if (!startNow) {
    throw new Error(
      `Ollama is not running. Start it with \`ollama serve\`, then rerun \`${CLI_COMMAND} onboard\`.`,
    );
  }

  await term.spinner("Start Ollama server", () => startOllamaServer(baseUrl));
  const startedState = await term.spinner("Wait for Ollama server", () =>
    waitForOllamaServer(baseUrl, DEFAULT_OLLAMA_START_TIMEOUT_MS),
  );
  if (!startedState.reachable) {
    throw new Error(
      `Ollama did not become reachable in time. ${startedState.message} Check ${OLLAMA_LOG_PATH} or run \`ollama serve\` manually.`,
    );
  }

  term.line("success", "Ollama is now reachable", baseUrl);
  return startedState;
}

async function chooseOllamaModel(rl, baseUrl, initialModels) {
  let models = initialModels;

  if (models.length === 0) {
    term.summaryBox("No local Ollama models detected", [
      `Recommended model: ${OLLAMA_RECOMMENDED_MODEL}`,
      "RepoOperator can pull it now, or you can enter another model name.",
    ]);
    const pullNow = await promptYesNo(
      rl,
      `Pull the recommended model now (${OLLAMA_RECOMMENDED_MODEL})?`,
      true,
    );

    if (pullNow) {
      await pullOllamaModel(OLLAMA_RECOMMENDED_MODEL);
      const refreshed = await term.spinner("Refresh Ollama model list", () =>
        checkOllamaServer(baseUrl, DEFAULT_OLLAMA_TIMEOUT_MS),
      );
      models = refreshed.models || [];
    }
  }

  if (models.length === 0) {
    term.line("warning", "No local models detected", "Enter a model name manually.");
    return promptWithDefault(rl, "Model name", OLLAMA_RECOMMENDED_MODEL);
  }

  term.summaryBox("Detected local Ollama models", [
    "Choose an installed model or pull the recommended coding model.",
  ]);
  term.table(
    ["Choice", "Model"],
    [
      ...models.map((modelName, index) => [String(index + 1), modelName]),
      [String(models.length + 1), `Pull recommended model (${OLLAMA_RECOMMENDED_MODEL})`],
      [String(models.length + 2), "Enter a model name manually"],
    ],
  );

  while (true) {
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";
    const choice = Number(answer);

    if (Number.isInteger(choice) && choice >= 1 && choice <= models.length) {
      return models[choice - 1];
    }
    if (choice === models.length + 1) {
      await pullOllamaModel(OLLAMA_RECOMMENDED_MODEL);
      return OLLAMA_RECOMMENDED_MODEL;
    }
    if (choice === models.length + 2) {
      return promptWithDefault(rl, "Model name", OLLAMA_RECOMMENDED_MODEL);
    }
    console.log(`Please choose a number from 1 to ${models.length + 2}.`);
  }
}

async function showConfig() {
  const config = await requireConfig();
  term.heading("Config", `${PRODUCT_NAME} local configuration`);
  console.log(JSON.stringify(redactConfig(config), null, 2));
}

async function requireConfig() {
  await ensureMigratedRuntimeHome();
  if (!(await fileExists(CONFIG_PATH))) {
    throw new Error(`${PRODUCT_NAME} is not configured yet. Run \`${CLI_COMMAND} onboard\` first.`);
  }
  return readConfig();
}

async function readConfig() {
  await ensureMigratedRuntimeHome();
  const raw = await fsp.readFile(CONFIG_PATH, "utf-8");
  return normalizeConfig(JSON.parse(raw));
}

async function readState() {
  await ensureMigratedRuntimeHome();
  if (await fileExists(STATE_PATH)) {
    const raw = await fsp.readFile(STATE_PATH, "utf-8");
    return JSON.parse(raw);
  }
  if (await fileExists(LEGACY_RUN_STATE_PATH)) {
    const raw = await fsp.readFile(LEGACY_RUN_STATE_PATH, "utf-8");
    return JSON.parse(raw);
  }
  if (await fileExists(LEGACY_STATE_PATH)) {
    const raw = await fsp.readFile(LEGACY_STATE_PATH, "utf-8");
    return JSON.parse(raw);
  }
  return null;
}

async function readWebState() {
  await ensureMigratedRuntimeHome();
  if (await fileExists(WEB_STATE_PATH)) {
    const raw = await fsp.readFile(WEB_STATE_PATH, "utf-8");
    return JSON.parse(raw);
  }
  return null;
}

async function writeRuntimeState(state) {
  await writeJson(STATE_PATH, state);
  if (state?.pid) {
    await fsp.writeFile(PID_PATH, `${state.pid}\n`, "utf-8");
  }
}

async function writeWebRuntimeState(state) {
  await writeJson(WEB_STATE_PATH, state);
  if (state?.pid) {
    await fsp.writeFile(WEB_PID_PATH, `${state.pid}\n`, "utf-8");
  }
}

async function clearRuntimeStateFiles() {
  await removeFileIfExists(PID_PATH);
  await removeFileIfExists(STATE_PATH);
  await removeFileIfExists(LEGACY_RUN_STATE_PATH);
  await removeFileIfExists(LEGACY_STATE_PATH);
  await removeFileIfExists(path.join(LEGACY_RUN_DIR, "worker.pid"));
}

async function clearWebRuntimeStateFiles() {
  await removeFileIfExists(WEB_PID_PATH);
  await removeFileIfExists(WEB_STATE_PATH);
}

async function writeJson(filePath, value) {
  await fsp.writeFile(filePath, JSON.stringify(value, null, 2) + "\n", "utf-8");
}

async function ensureLogFileExists(filePath) {
  await fsp.mkdir(path.dirname(filePath), { recursive: true });
  if (!(await fileExists(filePath))) {
    await fsp.writeFile(filePath, "", "utf-8");
  }
}

async function fileExists(filePath) {
  try {
    await fsp.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function isWorkerProcessRunning(runtimeState) {
  if (!runtimeState?.pid) {
    return {
      running: false,
      message: runtimeState?.status === "stopped"
        ? "Worker is stopped."
        : "No worker pid is recorded in the local runtime state.",
    };
  }

  try {
    process.kill(runtimeState.pid, 0);
    return {
      running: true,
      message: `Worker process ${runtimeState.pid} is running.`,
    };
  } catch {
    return {
      running: false,
      message: `Worker process ${runtimeState.pid} is not running.`,
    };
  }
}

async function isProcessRunning(pid) {
  if (!pid) {
    return {
      running: false,
      message: "No process id is recorded.",
    };
  }

  try {
    process.kill(pid, 0);
    return {
      running: true,
      message: `Process ${pid} is running.`,
    };
  } catch {
    return {
      running: false,
      message: `Process ${pid} is not running.`,
    };
  }
}

async function stopWorkerProcess(pid) {
  if (!pid) {
    return {
      hadPid: false,
      exited: true,
      forced: false,
    };
  }

  const initiallyRunning = await isWorkerProcessRunning({ pid });
  if (!initiallyRunning.running) {
    return {
      hadPid: true,
      exited: true,
      forced: false,
      stale: true,
    };
  }

  try {
    process.kill(-pid, "SIGTERM");
  } catch {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      return {
        hadPid: true,
        exited: !(await isWorkerProcessRunning({ pid })).running,
        forced: false,
      };
    }
  }

  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    const running = await isWorkerProcessRunning({ pid });
    if (!running.running) {
      return {
        hadPid: true,
        exited: true,
        forced: false,
      };
    }
    await sleep(200);
  }

  try {
    process.kill(-pid, "SIGKILL");
  } catch {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      const running = await isWorkerProcessRunning({ pid });
      return {
        hadPid: true,
        exited: !running.running,
        forced: true,
      };
    }
  }

  const forceDeadline = Date.now() + 2000;
  while (Date.now() < forceDeadline) {
    const running = await isWorkerProcessRunning({ pid });
    if (!running.running) {
      return {
        hadPid: true,
        exited: true,
        forced: true,
      };
    }
    await sleep(100);
  }

  return {
    hadPid: true,
    exited: false,
    forced: true,
  };
}

async function safeStopWorkerProcess(pid) {
  try {
    await stopWorkerProcess(pid);
  } catch {
    return;
  }
}

async function removePidFile() {
  try {
    await fsp.unlink(PID_PATH);
  } catch {
    return;
  }
}

async function removeFileIfExists(filePath) {
  try {
    await fsp.unlink(filePath);
  } catch {
    return;
  }
}

async function checkPortInUse(host, port, timeoutMs) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let settled = false;

    const finish = (result) => {
      if (settled) {
        return;
      }
      settled = true;
      socket.destroy();
      resolve(result);
    };

    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish({ inUse: true, detail: `Port ${port} on ${host} accepted a connection.` }));
    socket.once("timeout", () => finish({ inUse: false, detail: `Port check to ${host}:${port} timed out.` }));
    socket.once("error", (error) => {
      if (error.code === "ECONNREFUSED") {
        finish({ inUse: false, detail: `No process is listening on ${host}:${port}.` });
        return;
      }
      finish({ inUse: false, detail: `Port check failed for ${host}:${port}: ${error.message}` });
    });
    socket.connect(port, host);
  });
}

async function readLogTail(filePath, lineCount) {
  if (!(await fileExists(filePath))) {
    return "";
  }
  const content = await fsp.readFile(filePath, "utf-8");
  return content.split(/\r?\n/).filter(Boolean).slice(-lineCount).join("\n");
}

async function checkModelConnectivity(modelConfig, timeoutMs) {
  if (!modelConfig?.provider || !modelConfig?.baseUrl) {
    return {
      reachable: false,
      message: "Model provider is not configured.",
    };
  }

  const probe = buildModelConnectivityProbe(modelConfig);
  try {
    const response = await fetchWithTimeout(probe.url, {
      method: probe.method,
      headers: buildModelConnectivityHeaders(modelConfig),
      timeoutMs,
    });
    if (!response.ok) {
      return {
        reachable: false,
        message: formatModelConnectivityFailure(modelConfig, probe, response.status),
      };
    }

    return {
      reachable: true,
      message: `Model endpoint responded successfully at ${probe.url} with status ${response.status}.`,
    };
  } catch (error) {
    const remediation = getModelConnectivityRemediation(modelConfig, probe);
    const message = formatTimeoutAwareError(
      error,
      `Model connectivity timed out after ${Math.round(timeoutMs / 1000)} seconds.`,
    );
    return {
      reachable: false,
      message: `${message} ${remediation}`.trim(),
    };
  }
}

function buildModelConnectivityProbe(modelConfig) {
  const baseUrl = modelConfig.baseUrl.replace(/\/+$/, "");

  if (
    modelConfig.provider === "openai" ||
    modelConfig.provider === "gemini" ||
    modelConfig.provider === "ollama" ||
    modelConfig.provider === "openai-compatible"
  ) {
    return {
      method: "GET",
      url: `${baseUrl}/models`,
    };
  }

  if (modelConfig.provider === "anthropic") {
    return {
      method: "GET",
      url: `${baseUrl}/v1/models`,
    };
  }

  return {
    method: "GET",
    url: baseUrl,
  };
}

function formatModelConnectivityFailure(modelConfig, probe, status) {
  const remediation = getModelConnectivityRemediation(modelConfig, probe);
  if (status === 404) {
    return `Model connectivity failed. ${probe.url} returned HTTP 404. ${remediation}`;
  }
  if (status === 401 || status === 403) {
    return `Model connectivity failed with HTTP ${status}. Check your API key and provider permissions. ${remediation}`;
  }
  return `Model connectivity failed with HTTP ${status} at ${probe.url}. ${remediation}`;
}

function getModelConnectivityRemediation(modelConfig, probe) {
  if (modelConfig.provider === "ollama") {
    return `Expected an Ollama-compatible models endpoint. Confirm Ollama is running and that ${probe.url} is reachable.`;
  }
  if (modelConfig.provider === "openai-compatible") {
    return `Expected an OpenAI-compatible models endpoint. Confirm the base URL is correct and that ${probe.url} returns a models list.`;
  }
  if (modelConfig.provider === "openai") {
    return "Confirm the base URL points at the OpenAI API root and that the API key is valid.";
  }
  if (modelConfig.provider === "anthropic") {
    return "Confirm the base URL points at the Anthropic API root and that the API key is valid.";
  }
  if (modelConfig.provider === "gemini") {
    return "Confirm the base URL points at the Gemini-compatible API root and that the API key is valid.";
  }
  return "Confirm the model provider base URL and credentials are correct.";
}

function getOllamaRootUrl(baseUrl) {
  return baseUrl.replace(/\/v1\/?$/, "").replace(/\/+$/, "");
}

function buildPythonPathEnv(srcPath, existingPythonPath) {
  if (!existingPythonPath) {
    return srcPath;
  }
  const segments = existingPythonPath.split(path.delimiter).filter(Boolean);
  if (segments.includes(srcPath)) {
    return existingPythonPath;
  }
  return [srcPath, ...segments].join(path.delimiter);
}

function buildModelConnectivityHeaders(modelConfig) {
  const headers = {
    "User-Agent": "RepoOperator CLI",
  };

  if (modelConfig?.apiKey) {
    headers.Authorization = `Bearer ${modelConfig.apiKey}`;
  }

  if (modelConfig?.provider === "anthropic" && modelConfig?.apiKey) {
    headers["x-api-key"] = modelConfig.apiKey;
    headers["anthropic-version"] = "2023-06-01";
  }

  return headers;
}

async function fetchWithTimeout(url, { method, headers, timeoutMs }) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      method,
      headers,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

function formatTimeoutAwareError(error, timeoutMessage) {
  if (error && typeof error === "object" && error.name === "AbortError") {
    return timeoutMessage;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function parseWorkerBinding(workerUrl) {
  return parseLocalHttpBinding(workerUrl, "worker URL");
}

function parseLocalHttpBinding(localUrl, label) {
  let parsedUrl;
  try {
    parsedUrl = new URL(localUrl);
  } catch {
    throw new Error(`Configured ${label} is invalid: ${localUrl}`);
  }

  if (parsedUrl.protocol !== "http:") {
    throw new Error(`Configured ${label} must use http for local development: ${localUrl}`);
  }

  const port = parsedUrl.port ? Number(parsedUrl.port) : 80;
  if (!Number.isInteger(port) || port <= 0) {
    throw new Error(`Configured ${label} has an invalid port: ${localUrl}`);
  }

  return {
    host: parsedUrl.hostname,
    port,
  };
}

function describeWorkerProcessState(workerRunning, runtimeState) {
  if (workerRunning.running) {
    return workerRunning.message;
  }
  if (runtimeState?.status === "stopped") {
    return "Worker is stopped and no active runtime state is recorded.";
  }
  if (!runtimeState?.pid && !runtimeState?.failureType) {
    return "Worker is stopped.";
  }
  if (runtimeState?.failureType === "import_failure") {
    return `Worker is not running because startup failed to import the app. ${runtimeState.lastError || ""}`.trim();
  }
  if (runtimeState?.failureType === "port_in_use") {
    return `Worker is not running because the configured port is already in use. ${runtimeState.lastError || ""}`.trim();
  }
  if (runtimeState?.failureType === "health_timeout") {
    return `Worker process started but did not become healthy in time. ${runtimeState.lastError || ""}`.trim();
  }
  if (runtimeState?.failureType === "process_exited") {
    return `Worker process exited during startup. ${runtimeState.lastError || ""}`.trim();
  }
  return workerRunning.message;
}

function describeWorkerHealthState(workerHealth, runtimeState, portState) {
  if (workerHealth.reachable) {
    return workerHealth.message;
  }
  if (runtimeState?.status === "stopped" || (!runtimeState?.failureType && !runtimeState?.pid && !portState?.inUse)) {
    return "Worker is stopped.";
  }
  if (runtimeState?.failureType === "port_in_use") {
    return runtimeState.lastError || workerHealth.message;
  }
  if (runtimeState?.failureType === "import_failure") {
    return runtimeState.lastError || workerHealth.message;
  }
  if (runtimeState?.failureType === "health_timeout") {
    return runtimeState.lastError || workerHealth.message;
  }
  if (runtimeState?.failureType === "process_exited") {
    return runtimeState.lastError || workerHealth.message;
  }
  if (portState?.inUse && !workerHealth.reachable) {
    return `A process is listening on the configured port, but the ${PRODUCT_NAME} health endpoint did not respond successfully. ${workerHealth.message}`;
  }
  return workerHealth.message;
}

function describePortState(portState, workerUrl, workerHealthy) {
  if (portState.inUse && workerHealthy) {
    return `The configured worker port for ${workerUrl} is in use by a responding worker, which is expected.`;
  }
  if (portState.inUse) {
    return `The configured worker port for ${workerUrl} is already occupied by another process or a non-responsive worker.`;
  }
  return portState.detail;
}

function classifyWorkerStartupFailure(startupHealth, logTail) {
  const tail = logTail || "";
  if (tail.includes("ModuleNotFoundError") || tail.includes("No module named 'openpatch_worker'")) {
    return "import_failure";
  }
  if (tail.includes("address already in use")) {
    return "port_in_use";
  }
  if (startupHealth.message?.includes("timed out")) {
    return "health_timeout";
  }
  return "process_exited";
}

function makeCheck(name, ok, detail) {
  return { name, ok, detail };
}

function redactConfig(config) {
  const normalized = normalizeConfig(config);
  const redacted = {
    ...normalized,
    model: {
      ...normalized.model,
      apiKey: normalized.model?.apiKey ? redactSecret(normalized.model.apiKey) : "",
    },
    gitProvider: normalized.gitProvider
      ? {
          ...normalized.gitProvider,
          token: normalized.gitProvider.token
            ? redactSecret(normalized.gitProvider.token)
            : "",
        }
      : normalized.gitProvider,
  };
  delete redacted.modelBackend;
  return redacted;
}

function redactSecret(value) {
  if (!value) {
    return "";
  }
  if (value.length <= 8) {
    return "********";
  }
  return `${value.slice(0, 4)}...${value.slice(-4)}`;
}

function formatProviderSummary(gitProvider) {
  if (!gitProvider?.provider || gitProvider.provider === "none") {
    return "none configured";
  }
  if (gitProvider.provider === "local") {
    return "local project";
  }
  if (gitProvider.baseUrl) {
    return `${gitProvider.provider} (${gitProvider.baseUrl})`;
  }
  return gitProvider.provider;
}

function formatModelSummary(modelConfig) {
  if (!modelConfig?.provider || !modelConfig?.baseUrl || !modelConfig?.model) {
    return "not configured";
  }
  return `${formatModelConnectionMode(modelConfig)} | ${modelConfig.provider} | ${modelConfig.model} | ${modelConfig.baseUrl}`;
}

function formatModelConnectionMode(modelConfig) {
  if (!modelConfig?.connectionMode) {
    return "not configured";
  }
  if (modelConfig.connectionMode === "local-runtime") {
    return "local runtime";
  }
  if (modelConfig.connectionMode === "remote-api") {
    return "remote API";
  }
  return modelConfig.connectionMode;
}

function hasRequiredModelFields(modelConfig) {
  if (
    !modelConfig?.provider ||
    !MODEL_PROVIDER_OPTIONS.includes(modelConfig.provider) ||
    !modelConfig?.connectionMode ||
    !MODEL_CONNECTION_MODES.includes(modelConfig.connectionMode)
  ) {
    return false;
  }

  if (!modelConfig.baseUrl || !modelConfig.model) {
    return false;
  }

  const providerConfig = MODEL_PROVIDER_CONFIG[modelConfig.provider];
  if (providerConfig.prompts.includes("apiKey")) {
    return Boolean(modelConfig.apiKey);
  }

  return true;
}

function normalizeConfig(config) {
  if (!config || typeof config !== "object") {
    return config;
  }

  if (config.model) {
    return {
      ...config,
      model: normalizeModelConfig(config.model),
    };
  }

  if (config.modelBackend) {
    const normalized = {
      ...config,
      model: {
        provider: config.modelBackend.provider || "openai-compatible",
        baseUrl: config.modelBackend.baseUrl || "",
        apiKey: config.modelBackend.apiKey || "",
        model: config.modelBackend.model || "",
      },
    };
    delete normalized.modelBackend;
    return normalized;
  }

  return config;
}

function normalizeModelConfig(modelConfig) {
  if (!modelConfig || typeof modelConfig !== "object") {
    return modelConfig;
  }

  const connectionMode = modelConfig.connectionMode
    || (modelConfig.provider === "ollama" ? "local-runtime" : "remote-api");

  return {
    ...modelConfig,
    connectionMode,
  };
}

function printChecks(checks) {
  console.log(term.banner());
  term.heading("Doctor", "Local runtime diagnostics", "A quick health report for the local RepoOperator setup.");
  for (const check of checks) {
    term.line(check.ok ? "success" : "error", check.name, check.detail);
  }
  const failing = checks.filter((check) => !check.ok);
  term.summaryBox(
    failing.length ? "Doctor summary: needs attention" : "Doctor summary: healthy",
    [
      ["Checks", String(checks.length)],
      ["Passing", String(checks.length - failing.length)],
      ["Failing", String(failing.length)],
      ["Next step", failing.length ? `Run ${CLI_COMMAND} status or inspect logs` : `${CLI_COMMAND} up`],
    ],
  );
}

function printHelp() {
  console.log(term.banner());
  term.summaryBox("Usage", [
    [`${CLI_COMMAND} onboard`, "Guided first-run setup"],
    [`${CLI_COMMAND} up`, "Start worker and web UI"],
    [`${CLI_COMMAND} down`, "Stop worker and web UI"],
    [`${CLI_COMMAND} doctor`, "Run local diagnostics"],
    [`${CLI_COMMAND} status`, "Show runtime status"],
    [`${CLI_COMMAND} config show`, "Print redacted config"],
  ]);
  term.summaryBox("Worker maintenance", [
    [`${CLI_COMMAND} worker start`, "Start only the local worker"],
    [`${CLI_COMMAND} worker stop`, "Stop the local worker"],
    [`${CLI_COMMAND} worker restart`, "Restart the local worker"],
    [`${CLI_COMMAND} worker status`, "Inspect worker runtime state"],
    [`${CLI_COMMAND} worker logs`, "Show recent worker logs"],
  ], `Recommended flow: ${CLI_COMMAND} onboard && ${CLI_COMMAND} up`);
}

module.exports = {
  runCli,
};
