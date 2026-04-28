const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const readline = require("node:readline/promises");
const net = require("node:net");
const { spawn } = require("node:child_process");
const { stdin, stdout } = require("node:process");

const PRODUCT_NAME = "RepoOperator";
const CLI_COMMAND = "repooperator";
const CONFIG_DIR = path.join(os.homedir(), ".repooperator");
const LEGACY_CONFIG_DIR = path.join(os.homedir(), ".repooperator");
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
    console.log(`${PRODUCT_NAME} onboarding`);
    console.log(`Set up ${PRODUCT_NAME} on this machine.`);
    console.log(`We will save your local settings, choose how ${PRODUCT_NAME} should reach a model, choose a repository source, and prepare the local worker runtime.`);
    console.log("");

    const modelConfig = await promptModelConfig(rl);
    const gitProvider = await promptGitProvider(rl);
    const gitProviderConfig = await promptGitProviderConfig(rl, gitProvider);
    const localRepoBaseDir = await promptWithDefault(
      rl,
      "Local repository base directory",
      DEFAULT_REPO_BASE_DIR,
    );

    const workerDetection = await detectLocalWorkerInstallation(process.cwd());
    const config = {
      version: 2,
      createdAt: new Date().toISOString(),
      worker: {
        baseUrl: DEFAULT_WORKER_URL,
        installed: workerDetection.installed,
        installMode: workerDetection.installMode,
        detectedPath: workerDetection.detectedPath,
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

    console.log("");
    console.log(`${PRODUCT_NAME} is now configured.`);
    console.log(`Config file: ${CONFIG_PATH}`);
    console.log(`Worker detection: ${workerDetection.summary}`);
    console.log("");
    console.log("Starting the local worker...");

    let workerStarted = false;
    try {
      await startWorker({ interactive: false });
      workerStarted = true;
      console.log("The local worker has been started.");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.log(`Worker start failed: ${message}`);
      console.log(`You can inspect the worker with \`${CLI_COMMAND} worker logs\` and retry with \`${CLI_COMMAND} worker start\`.`);
    }

    const workerHealth = await checkWorkerHealth(
      config.worker.baseUrl,
      DEFAULT_WORKER_HEALTH_TIMEOUT_MS,
    );
    const modelConnectivity = await checkModelConnectivity(
      config.model,
      DEFAULT_MODEL_CONNECTIVITY_TIMEOUT_MS,
    );

    console.log("");
    console.log(`${PRODUCT_NAME} onboarding summary`);
    console.log(`Worker URL: ${config.worker.baseUrl}`);
    console.log(`Model connection: ${formatModelSummary(config.model)}`);
    console.log(`Worker health: ${workerHealth.reachable ? "ok" : "needs attention"}`);
    console.log(`Model connectivity: ${modelConnectivity.reachable ? "ok" : "needs attention"}`);

    if (workerStarted && workerHealth.reachable && modelConnectivity.reachable) {
      console.log("");
      console.log(`${PRODUCT_NAME} is ready for read-only repository Q&A.`);
      console.log("Next steps:");
      console.log(`  1. Run \`${CLI_COMMAND} up\``);
      console.log("  2. Open the printed local web URL");
      console.log("  3. Choose a repository and ask a read-only question");
      return;
    }

    if (!workerHealth.reachable) {
      console.log(`Worker detail: ${workerHealth.message}`);
    }
    if (!modelConnectivity.reachable) {
      console.log(`Model detail: ${modelConnectivity.message}`);
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
    console.log(`${PRODUCT_NAME} is not configured yet.`);
    console.log(`Run \`${CLI_COMMAND} onboard\` to create the local configuration.`);
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

  console.log(`${PRODUCT_NAME} status`);
  console.log("");
  console.log(`Config file: ${CONFIG_PATH}`);
  console.log(`Configured worker URL: ${workerUrl}`);
  console.log(`Worker install mode: ${config.worker?.installMode || "unknown"}`);
  console.log(`Worker detected path: ${config.worker?.detectedPath || "not detected"}`);
  console.log(`Worker process running: ${workerRunning.running ? "yes" : "no"}`);
  console.log(`Worker process detail: ${describeWorkerProcessState(workerRunning, runtimeState)}`);
  console.log(`Worker port in use: ${portState.inUse ? "yes" : "no"}`);
  console.log(`Worker port detail: ${describePortState(portState, workerUrl, workerHealth.reachable)}`);
  console.log(`Worker reachable: ${workerHealth.reachable ? "yes" : "no"}`);
  console.log(`Worker health detail: ${describeWorkerHealthState(workerHealth, runtimeState, portState)}`);
  if (runtimeState?.failureType) {
    console.log(`Last startup failure: ${runtimeState.failureType}`);
  }
  if (runtimeState?.lastError) {
    console.log(`Last startup detail: ${runtimeState.lastError}`);
  }
  console.log(`Worker pid file: ${runtimeState?.pidFile || PID_PATH}`);
  console.log(`Worker log file: ${runtimeState?.logPath || WORKER_LOG_PATH}`);
  console.log(`Model connection mode: ${formatModelConnectionMode(config.model)}`);
  console.log(`Model provider: ${config.model?.provider || "not configured"}`);
  console.log(`Model summary: ${formatModelSummary(config.model)}`);
  console.log(`Model connectivity: ${modelConnectivity.reachable ? "reachable" : "not reachable"}`);
  console.log(`Model connectivity detail: ${modelConnectivity.message}`);
  console.log(`Git provider: ${formatProviderSummary(config.gitProvider)}`);
  console.log(`Local repo base dir: ${config.localRepoBaseDir || "not configured"}`);
  console.log(`Worker runtime prepared: ${config.daemon?.prepared ? "yes" : "no"}`);
}

async function runUp() {
  await ensureBaseDirectories();
  const config = await requireConfig();
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  const webUrl = config.web?.baseUrl || DEFAULT_WEB_URL;

  console.log(`${PRODUCT_NAME} local product runtime`);
  console.log("");
  console.log("Starting local worker...");
  await startWorker({ interactive: false });

  const workerHealth = await checkWorkerHealth(
    workerUrl,
    DEFAULT_WORKER_HEALTH_TIMEOUT_MS,
  );
  if (!workerHealth.reachable) {
    throw new Error(`Local worker did not become healthy. ${workerHealth.message}`);
  }
  console.log(`Worker ready: ${workerUrl}`);

  console.log("Starting web UI...");
  await startWeb({ interactive: false, workerUrl, webUrl });

  const webHealth = await checkWebHealth(webUrl, DEFAULT_WEB_HEALTH_TIMEOUT_MS);
  if (!webHealth.reachable) {
    throw new Error(`Web UI did not become healthy. ${webHealth.message}`);
  }

  console.log(`Web UI ready: ${webUrl}`);
  console.log("");
  console.log(`${PRODUCT_NAME} is up.`);
  console.log(`Open: ${webUrl}`);
}

async function runDown() {
  await ensureMigratedRuntimeHome();
  console.log(`Stopping ${PRODUCT_NAME} local product runtime...`);
  await stopWeb({ interactive: true });
  await stopWorker({ interactive: true });
}

async function startWorker({ interactive }) {
  await ensureBaseDirectories();
  const config = await requireConfig();
  const workerInstallation = await resolveWorkerInstallation(config, process.cwd());
  let runtimeState = await readState();
  const running = await isWorkerProcessRunning(runtimeState);
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  const workerBinding = parseWorkerBinding(workerUrl);

  if (running.running) {
    if (interactive) {
      console.log(`The local worker is already running. ${running.message}`);
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

  console.log(`Launching ${PRODUCT_NAME} local worker`);
  console.log(`Command: ${launchedCommand}`);
  console.log(`Working directory: ${workerInstallation.detectedPath}`);
  console.log(`Worker src path: ${workerLaunch.srcPath}`);
  console.log(`PYTHONPATH: ${env.PYTHONPATH}`);
  console.log(`Expected health URL: ${workerUrl}/health`);
  console.log(`Log file: ${WORKER_LOG_PATH}`);
  console.log(`PID file: ${PID_PATH}`);

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
    console.log(`Startup failure detail: ${startupHealth.message}`);
    console.log(`Process exited: ${startupHealth.exited ? "yes" : "no"}`);
    console.log(`Exit code: ${startupHealth.exitCode ?? "unknown"}`);
    if (logTail) {
      console.log("Recent worker log output:");
      console.log(logTail);
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
    console.log(`${PRODUCT_NAME} local worker started.`);
    console.log(`Worker URL: ${workerUrl}`);
    console.log(`Logs: ${WORKER_LOG_PATH}`);
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
      console.log(`${PRODUCT_NAME} local worker was already stopped. Cleaned up stale runtime state.`);
    } else if (stopResult.forced) {
      console.log(`${PRODUCT_NAME} local worker did not exit gracefully and was force-stopped.`);
    } else {
      console.log(`${PRODUCT_NAME} local worker stopped cleanly.`);
    }
  }
}

async function restartWorker() {
  await stopWorker({ interactive: false });
  await startWorker({ interactive: true });
  console.log(`${PRODUCT_NAME} local worker restarted.`);
}

async function startWeb({ interactive, workerUrl, webUrl }) {
  await ensureBaseDirectories();
  const config = await requireConfig();
  const webInstallation = await resolveWebInstallation(config, process.cwd());
  let webState = await readWebState();
  const running = await isProcessRunning(webState?.pid);
  const webBinding = parseLocalHttpBinding(webUrl, "web UI URL");

  if (running.running) {
    if (interactive) {
      console.log(`The web UI is already running. ${running.message}`);
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
        console.log(`The web UI is already reachable at ${webUrl}.`);
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

  console.log(`Launching ${PRODUCT_NAME} web UI`);
  console.log(`Command: ${launchedCommand}`);
  console.log(`Working directory: ${webInstallation.detectedPath}`);
  console.log(`Expected web URL: ${webUrl}`);
  console.log(`Worker URL for web UI: ${workerUrl}`);
  console.log(`Log file: ${WEB_LOG_PATH}`);
  console.log(`PID file: ${WEB_PID_PATH}`);

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
    console.log(`Web startup failure detail: ${startupHealth.message}`);
    if (logTail) {
      console.log("Recent web log output:");
      console.log(logTail);
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
    console.log(`${PRODUCT_NAME} web UI started.`);
    console.log(`Web URL: ${webUrl}`);
    console.log(`Logs: ${WEB_LOG_PATH}`);
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
      console.log(`${PRODUCT_NAME} web UI was already stopped. Cleaned up stale runtime state.`);
    } else if (stopResult.forced) {
      console.log(`${PRODUCT_NAME} web UI did not exit gracefully and was force-stopped.`);
    } else {
      console.log(`${PRODUCT_NAME} web UI stopped cleanly.`);
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
  console.log(`${PRODUCT_NAME} worker logs: ${logPath}`);
  console.log("");
  process.stdout.write(logContent || "(log file is empty)\n");
}

async function showWorkerStatus() {
  await ensureMigratedRuntimeHome();
  const configExists = await fileExists(CONFIG_PATH);
  if (!configExists) {
    console.log(`${PRODUCT_NAME} is not configured yet.`);
    console.log(`Run \`${CLI_COMMAND} onboard\` to create the local configuration.`);
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

  console.log(`${PRODUCT_NAME} worker status`);
  console.log("");
  console.log(`Configured worker URL: ${workerUrl}`);
  console.log(`PID: ${runtimeState?.pid ?? "not recorded"}`);
  console.log(`PID file: ${runtimeState?.pidFile || PID_PATH}`);
  console.log(`Process appears alive: ${workerRunning.running ? "yes" : "no"}`);
  console.log(`Process detail: ${describeWorkerProcessState(workerRunning, runtimeState)}`);
  console.log(`Port in use: ${portState.inUse ? "yes" : "no"}`);
  console.log(`Port detail: ${describePortState(portState, workerUrl, workerHealth.reachable)}`);
  console.log(`Health responds: ${workerHealth.reachable ? "yes" : "no"}`);
  console.log(`Health detail: ${describeWorkerHealthState(workerHealth, runtimeState, portState)}`);
  if (runtimeState?.failureType) {
    console.log(`Last startup failure: ${runtimeState.failureType}`);
  }
  if (runtimeState?.lastError) {
    console.log(`Last startup detail: ${runtimeState.lastError}`);
  }
  console.log(`Log file: ${runtimeState?.logPath || WORKER_LOG_PATH}`);
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
    const baseUrl = await promptWithDefault(
      rl,
      "GitLab base URL",
      "https://gitlab.com",
    );
    const token = await promptWithDefault(rl, "GitLab token", "");
    return { provider: "gitlab", baseUrl, token };
  }

  if (provider === "github") {
    const baseUrl = await promptWithDefault(
      rl,
      "GitHub base URL",
      "https://github.com",
    );
    const token = await promptWithDefault(rl, "GitHub token", "");
    return { provider: "github", baseUrl, token };
  }

  if (provider === "local") {
    return { provider: "local" };
  }

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

  console.log("");
  console.log(`Remote model API: ${providerConfig.label}`);
  console.log(`${PRODUCT_NAME} will use these settings when the local worker calls your remote model API.`);

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
  console.log("");
  console.log("Local model runtime: Ollama");
  console.log(`${PRODUCT_NAME} will look for a local Ollama installation, help you start it if needed, and guide model selection.`);

  const commandInstalled = await commandExists("ollama");
  if (!commandInstalled) {
    const installedNow = await ensureOllamaInstalled(rl);
    if (!installedNow) {
      throw new Error(`Ollama is required for the guided local Ollama setup. Install it, then rerun \`${CLI_COMMAND} onboard\`.`);
    }
  }

  const baseUrl = await promptWithDefault(rl, "Ollama base URL", OLLAMA_DEFAULT_BASE_URL);
  const serverState = await ensureOllamaServerReady(rl, baseUrl);
  const selectedModel = await chooseOllamaModel(rl, baseUrl, serverState.models || []);

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
    console.log(`Choose how ${PRODUCT_NAME} should connect to your model:`);
    console.log("  1. Local model runtime");
    console.log("  2. Remote model API");
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "local-runtime";
    }
    if (answer === "2") {
      return "remote-api";
    }
    console.log("Please choose 1 or 2.");
  }
}

async function promptLocalRuntimeProvider(rl) {
  while (true) {
    console.log("Choose a local model runtime:");
    console.log("  1. Ollama");
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "ollama";
    }
    console.log("Please choose 1.");
  }
}

async function promptRemoteApiProvider(rl) {
  while (true) {
    console.log("Choose a remote model API:");
    console.log("  1. OpenAI-compatible");
    console.log("  2. OpenAI");
    console.log("  3. Anthropic");
    console.log("  4. Gemini");
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
    console.log("Please choose 1, 2, 3, or 4.");
  }
}

async function promptGitProvider(rl) {
  while (true) {
    console.log("Select a git provider:");
    console.log("  1. GitLab");
    console.log("  2. GitHub");
    console.log("  3. Local project");
    console.log("  4. None for now");
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
    console.log("Please choose 1, 2, 3, or 4.");
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

async function ensureOllamaInstalled(rl) {
  console.log("");
  console.log("Ollama was not found on this machine.");

  if (process.platform === "darwin") {
    const brewInstalled = await commandExists("brew");
    if (brewInstalled) {
      const installNow = await promptYesNo(
        rl,
        "Homebrew is available. Install Ollama now with `brew install ollama`?",
        true,
      );
      if (installNow) {
        console.log("Installing Ollama with Homebrew...");
        await runInteractiveCommand("brew", ["install", "ollama"]);
        return commandExists("ollama");
      }
    }

    console.log(`Install Ollama on macOS, then rerun \`${CLI_COMMAND} onboard\`.`);
    console.log("Suggested options:");
    console.log("  - install Homebrew and run `brew install ollama`");
    console.log("  - or install Ollama from the official macOS installer");
    return false;
  }

  console.log(`Install Ollama on this machine, then rerun \`${CLI_COMMAND} onboard\`.`);
  console.log("Suggested options:");
  console.log("  - use your system package manager if available");
  console.log("  - or install Ollama from the official installer for your platform");
  return false;
}

async function ensureOllamaServerReady(rl, baseUrl) {
  const initialState = await checkOllamaServer(baseUrl, DEFAULT_OLLAMA_TIMEOUT_MS);
  if (initialState.reachable) {
    console.log(`Ollama is reachable at ${baseUrl}.`);
    return initialState;
  }

  console.log("");
  console.log("Ollama is installed, but the local server is not reachable yet.");
  console.log(initialState.message);

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

  console.log("Starting the Ollama server...");
  await startOllamaServer(baseUrl);
  const startedState = await waitForOllamaServer(baseUrl, DEFAULT_OLLAMA_START_TIMEOUT_MS);
  if (!startedState.reachable) {
    throw new Error(
      `Ollama did not become reachable in time. ${startedState.message} Check ${OLLAMA_LOG_PATH} or run \`ollama serve\` manually.`,
    );
  }

  console.log(`Ollama is now reachable at ${baseUrl}.`);
  return startedState;
}

async function chooseOllamaModel(rl, baseUrl, initialModels) {
  let models = initialModels;

  if (models.length === 0) {
    console.log("");
    console.log("No local Ollama models were detected.");
    const pullNow = await promptYesNo(
      rl,
      `Pull the recommended model now (${OLLAMA_RECOMMENDED_MODEL})?`,
      true,
    );

    if (pullNow) {
      await pullOllamaModel(OLLAMA_RECOMMENDED_MODEL);
      const refreshed = await checkOllamaServer(baseUrl, DEFAULT_OLLAMA_TIMEOUT_MS);
      models = refreshed.models || [];
    }
  }

  if (models.length === 0) {
    console.log("");
    console.log(`${PRODUCT_NAME} could not detect any local Ollama models.`);
    return promptWithDefault(rl, "Model name", OLLAMA_RECOMMENDED_MODEL);
  }

  console.log("");
  console.log("Detected local Ollama models:");
  for (const [index, modelName] of models.entries()) {
    console.log(`  ${index + 1}. ${modelName}`);
  }
  console.log(`  ${models.length + 1}. Pull recommended model (${OLLAMA_RECOMMENDED_MODEL})`);
  console.log(`  ${models.length + 2}. Enter a model name manually`);

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
  console.log(`${PRODUCT_NAME} config`);
  console.log("");
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
  console.log(`${PRODUCT_NAME} doctor`);
  console.log("");
  for (const check of checks) {
    const prefix = check.ok ? "[ok]" : "[fail]";
    console.log(`${prefix} ${check.name}`);
    if (check.detail) {
      console.log(`      ${check.detail}`);
    }
  }
}

function printHelp() {
  console.log(`${PRODUCT_NAME} CLI`);
  console.log("");
  console.log("Usage:");
  console.log(`  ${CLI_COMMAND} onboard`);
  console.log(`  ${CLI_COMMAND} up`);
  console.log(`  ${CLI_COMMAND} down`);
  console.log(`  ${CLI_COMMAND} doctor`);
  console.log(`  ${CLI_COMMAND} status`);
  console.log(`  ${CLI_COMMAND} config show`);
  console.log("");
  console.log("Worker maintenance:");
  console.log(`  ${CLI_COMMAND} worker start`);
  console.log(`  ${CLI_COMMAND} worker stop`);
  console.log(`  ${CLI_COMMAND} worker restart`);
  console.log(`  ${CLI_COMMAND} worker status`);
  console.log(`  ${CLI_COMMAND} worker logs`);
  console.log("");
  console.log(`Recommended local product flow: ${CLI_COMMAND} onboard && ${CLI_COMMAND} up`);
}

module.exports = {
  runCli,
};
