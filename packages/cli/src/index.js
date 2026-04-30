const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const readline = require("node:readline/promises");
const net = require("node:net");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const { stdin, stdout } = require("node:process");
const term = require("./terminal");

const PRODUCT_NAME = "RepoOperator";
const CLI_COMMAND = "repooperator";
const CONFIG_DIR = path.join(os.homedir(), ".repooperator");
const CONFIG_PATH = path.join(CONFIG_DIR, "config.json");
const RUN_DIR = path.join(CONFIG_DIR, "run");
const LOG_DIR = path.join(CONFIG_DIR, "logs");
const STATE_PATH = path.join(RUN_DIR, "worker-state.json");
const WEB_STATE_PATH = path.join(RUN_DIR, "web-state.json");
const PID_PATH = path.join(RUN_DIR, "worker.pid");
const WEB_PID_PATH = path.join(RUN_DIR, "web.pid");
const WORKER_LOG_PATH = path.join(LOG_DIR, "worker.log");
const WEB_LOG_PATH = path.join(LOG_DIR, "web.log");
const OLLAMA_LOG_PATH = path.join(LOG_DIR, "ollama.log");
const DEFAULT_WORKER_URL = "http://127.0.0.1:8000";
const DEFAULT_WEB_URL = "http://localhost:3000";
const DEFAULT_REPO_BASE_DIR = path.join(os.homedir(), ".repooperator", "repos");
const RUNTIME_DIR = path.join(CONFIG_DIR, "runtime");
const RUNTIME_WORKER_DIR = path.join(RUNTIME_DIR, "local-worker");
const RUNTIME_VENV_DIR = path.join(RUNTIME_DIR, "worker-venv");
const RUNTIME_WEB_DIR = path.join(RUNTIME_DIR, "web");
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
const VLLM_DEFAULT_BASE_URL = "http://127.0.0.1:8001/v1";
const MIN_PYTHON_MAJOR = 3;
const MIN_PYTHON_MINOR = 11;
const PYTHON_CANDIDATES = ["python3.13", "python3.12", "python3.11", "python3", "python"];
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
  "vllm",
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
  vllm: {
    label: "vLLM",
    defaultBaseUrl: VLLM_DEFAULT_BASE_URL,
    defaultApiKey: "",
    defaultModel: "",
    prompts: ["baseUrl", "apiKeyOptional", "model"],
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
    case "_setup-runtime":
      await runSetupRuntime();
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
  await ensureRuntimeInstalled();
  const rl = readline.createInterface({ input: stdin, output: stdout });

  try {
    const existingConfig = await readOptionalConfig();
    const isReonboarding = Boolean(existingConfig);
    console.log(term.banner());
    term.heading(
      "1/6",
      isReonboarding ? "Welcome back" : "Welcome",
      isReonboarding
        ? "Update your local RepoOperator setup without losing working settings."
        : "Set up the local RepoOperator runtime on this machine.",
    );

    if (existingConfig) {
      term.summaryBox("Current setup", [
        ["Config", CONFIG_PATH],
        ["Model", formatModelSummary(existingConfig.model)],
        ["Default repository source", formatProviderSummary(existingConfig.gitProvider)],
        ["Saved repository sources", formatRepositorySourcesSummary(existingConfig)],
        ["Local repo base dir", existingConfig.localRepoBaseDir || DEFAULT_REPO_BASE_DIR],
        ["Worker URL", existingConfig.worker?.baseUrl || DEFAULT_WORKER_URL],
        ["Web URL", existingConfig.web?.baseUrl || DEFAULT_WEB_URL],
      ]);
    } else {
      term.summaryBox("What this wizard will configure", [
        "Model connection for repository questions",
        "Repository source for guided project selection",
        "Local worker runtime and repository storage",
        "A one-command startup flow with repooperator up",
      ]);
    }

    const updatePlan = existingConfig
      ? await promptReonboardingPlan(rl)
      : {
          updateModel: true,
          updateRepositories: true,
          updateRuntime: true,
          fullReconfigure: true,
        };

    term.heading("2/6", "Environment checks", "RepoOperator checks for the local pieces it can prepare automatically.");
    const workerDetection = await term.spinner("Detect local worker installation", () =>
      resolveWorkerInstallation({}, process.cwd()),
    );
    const webDetection = await term.spinner("Detect web app installation", () =>
      resolveWebInstallation({}, process.cwd()),
    );
    const npmAvailable = await commandExists("npm");
    const selectedPython = await findCompatiblePython();
    let pythonLabel;
    if (selectedPython) {
      const ver = await getPythonVersion(selectedPython);
      pythonLabel = ver ? `${selectedPython} (${ver.major}.${ver.minor})` : selectedPython;
    } else {
      pythonLabel = `Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ not found`;
    }
    term.summaryBox("Environment", [
      ["Local worker", workerDetection.installed ? workerDetection.summary : workerDetection.summary],
      ["Web app", webDetection.installed ? webDetection.summary : webDetection.summary],
      ["Python", pythonLabel],
      ["npm", npmAvailable ? "npm found" : "npm not found"],
    ]);

    term.heading("3/6", "Model connection", "Choose how the worker should reach a model.");
    const modelConfig = updatePlan.updateModel
      ? await promptModelConfig(rl, existingConfig?.model)
      : existingConfig?.model;

    term.heading("4/6", "Repository source", "Choose where projects should be discovered from.");
    const repositoryConfig = updatePlan.updateRepositories
      ? await promptRepositorySourceConfig(rl, existingConfig)
      : preserveRepositorySourceConfig(existingConfig);

    term.heading("5/6", "Local worker setup", "Choose where local checkouts and runtime files should live.");
    const localRepoBaseDir = updatePlan.updateRuntime
      ? await promptWithDefault(
          rl,
          "Local repository base directory",
          existingConfig?.localRepoBaseDir || DEFAULT_REPO_BASE_DIR,
        )
      : existingConfig?.localRepoBaseDir || DEFAULT_REPO_BASE_DIR;

    const config = {
      ...existingConfig,
      version: 2,
      createdAt: existingConfig?.createdAt || new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      worker: {
        ...(existingConfig?.worker || {}),
        baseUrl: existingConfig?.worker?.baseUrl || DEFAULT_WORKER_URL,
        installed: workerDetection.installed,
        installMode: workerDetection.installMode,
        detectedPath: workerDetection.detectedPath,
      },
      web: {
        ...(existingConfig?.web || {}),
        baseUrl: existingConfig?.web?.baseUrl || DEFAULT_WEB_URL,
        installed: webDetection.installed,
        detectedPath: webDetection.detectedPath,
      },
      model: modelConfig,
      gitProvider: repositoryConfig.gitProvider,
      repositorySources: repositoryConfig.repositorySources,
      localRepoBaseDir,
      daemon: {
        ...(existingConfig?.daemon || {}),
        prepared: true,
        runDirectory: RUN_DIR,
        logDirectory: LOG_DIR,
        stateFile: STATE_PATH,
        pidFile: PID_PATH,
        launchStrategy: workerDetection.installed ? "repo-source-background-process" : "pending-install",
      },
    };

    const runtimeConfigChanged = hasRuntimeRelevantConfigChanged(existingConfig, config);
    await writeJson(CONFIG_PATH, config);
    const previousRuntimeState = await readState();
    await writeJson(STATE_PATH, {
      ...(previousRuntimeState || {}),
      preparedAt: new Date().toISOString(),
      workerUrl: config.worker.baseUrl,
      expectedWorkerUrl: config.worker.baseUrl,
      installMode: workerDetection.installMode,
      workerDetected: workerDetection.installed,
      status: previousRuntimeState?.status || "stopped",
      pidFile: PID_PATH,
      logPath: WORKER_LOG_PATH,
    });

    term.line("success", `${PRODUCT_NAME} configuration written`, CONFIG_PATH);

    const shouldRestartRuntime = existingConfig
      ? await promptYesNo(rl, "Restart or reload the local worker now?", true)
      : true;
    let workerRuntimeState = shouldRestartRuntime ? "not started" : "restart skipped";
    if (shouldRestartRuntime) {
      if (existingConfig) {
        const existingWorkerHealth = await term.spinner(
          "Check existing worker",
          () => checkWorkerHealth(config.worker.baseUrl, DEFAULT_WORKER_HEALTH_TIMEOUT_MS),
        );
        if (existingWorkerHealth.reachable && !runtimeConfigChanged) {
          workerRuntimeState = "reused existing healthy worker";
          term.line("success", "A healthy worker is already running", "Reusing the existing worker.");
        } else {
          if (existingWorkerHealth.reachable && runtimeConfigChanged) {
            term.line("info", "Configuration changed", "Restarting the worker so the new model/runtime settings take effect.");
          }
          workerRuntimeState = await restartWorkerForOnboarding();
        }
      } else {
        try {
          await term.spinner("Start local worker", () => startWorker({ interactive: false, quiet: true }));
          workerRuntimeState = "started";
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          workerRuntimeState = "start needs attention";
          term.line("warning", "Worker start needs attention", message);
          term.line("info", "Inspect logs", `${CLI_COMMAND} worker logs`);
        }
      }
    } else {
      term.line("info", "Runtime restart skipped", `Run ${CLI_COMMAND} worker restart when you want the worker to reload config.`);
    }

    const workerHealth = await term.spinner(
      "Verify worker health",
      () => checkWorkerHealth(
        config.worker.baseUrl,
        DEFAULT_WORKER_HEALTH_TIMEOUT_MS,
      ),
    );
    if (workerHealth.reachable) {
      const recordedPid = await readPidFile(PID_PATH);
      await writeRuntimeState({
        ...((await readState()) || {}),
        status: "running",
        ...(recordedPid ? { pid: recordedPid } : {}),
        healthyAt: new Date().toISOString(),
        workerUrl: config.worker.baseUrl,
        expectedWorkerUrl: config.worker.baseUrl,
        pidFile: PID_PATH,
        logPath: WORKER_LOG_PATH,
      });
    }
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
      ["Saved repository sources", formatRepositorySourcesSummary(config)],
      ["Model", formatModelSummary(config.model)],
      ["Worker runtime", workerRuntimeState],
      ["Config changed", runtimeConfigChanged ? "yes - worker reload required" : "no runtime-relevant changes"],
      ["Worker health", workerHealth.reachable ? "ok" : "needs attention"],
      ["Model connectivity", modelConnectivity.reachable ? "ok" : "needs attention"],
    ]);

    if (workerHealth.reachable && modelConnectivity.reachable) {
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

async function restartWorkerForOnboarding() {
  try {
    await term.spinner("Restart local worker", async () => {
      await stopWorker({ interactive: false });
      await startWorker({ interactive: false, quiet: true });
    });
    return "restarted";
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    term.line("warning", "Worker restart needs attention", message);
    term.line("info", "Inspect logs", `${CLI_COMMAND} worker logs`);
    return "restart needs attention";
  }
}

async function runDoctor() {
  await ensureBaseDirectories();
  const checks = [];
  const cliPackageRoot = path.resolve(__dirname, "..");
  checks.push(makeCheck("CLI install location", true, cliPackageRoot));
  checks.push(makeCheck("Config path", true, CONFIG_PATH));
  checks.push(makeCheck("Runtime path", true, RUNTIME_DIR));
  checks.push(makeCheck("Worker venv path", true, RUNTIME_VENV_DIR));

  const workerVenvPython = path.join(RUNTIME_VENV_DIR, "bin", "python");
  const webPackageJson = path.join(RUNTIME_WEB_DIR, "package.json");
  const webNextBin = path.join(RUNTIME_WEB_DIR, "node_modules", ".bin", "next");

  const systemPython = await findCompatiblePython();
  const venvExists = await fileExists(workerVenvPython);
  const venvVersion = venvExists ? await getVenvPythonVersion() : null;
  const venvCompatible = isPythonCompatible(venvVersion);

  checks.push(makeCheck(
    "System Python (>=3.11)",
    !!systemPython,
    systemPython || `No Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ found — install it and rerun onboard`,
  ));
  checks.push(makeCheck(
    "Worker python exists",
    venvExists,
    venvExists ? workerVenvPython : `Missing at ${workerVenvPython}`,
  ));
  if (venvExists) {
    checks.push(makeCheck(
      "Worker python version",
      venvCompatible,
      venvVersion
        ? `${venvVersion.major}.${venvVersion.minor}${venvCompatible ? "" : ` (need ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ — rerun onboard to repair)`}`
        : "Unknown — rerun onboard to repair",
    ));
  }
  checks.push(makeCheck(
    "Web package.json exists",
    await fileExists(webPackageJson),
    await fileExists(webPackageJson) ? webPackageJson : `Missing at ${webPackageJson}`,
  ));
  checks.push(makeCheck(
    "Web next binary exists",
    await fileExists(webNextBin),
    await fileExists(webNextBin) ? webNextBin : `Missing at ${webNextBin}`,
  ));

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
  const webDetection = await resolveWebInstallation(config, process.cwd());
  const runtimeState = await readState();
  const webState = await readWebState();
  const workerUrl = config.worker?.baseUrl || DEFAULT_WORKER_URL;
  const webUrl = config.web?.baseUrl || DEFAULT_WEB_URL;
  const workerBinding = parseWorkerBinding(workerUrl);
  const webBinding = parseLocalHttpBinding(webUrl, "web UI URL");
  const workerRunning = await isWorkerProcessRunning(runtimeState);
  const webRunning = await isProcessRunning(webState?.pid);
  const portState = await checkPortInUse(workerBinding.host, workerBinding.port, DEFAULT_PORT_CHECK_TIMEOUT_MS);
  const webPortState = await checkPortInUse(webBinding.host, webBinding.port, DEFAULT_PORT_CHECK_TIMEOUT_MS);
  const workerHealth = portState.inUse || workerRunning.running
    ? await checkWorkerHealth(
      workerUrl,
      DEFAULT_WORKER_HEALTH_TIMEOUT_MS,
    )
    : { reachable: false, message: "Worker is stopped." };
  const webHealth = webPortState.inUse || webRunning.running
    ? await checkWebHealth(webUrl, DEFAULT_WEB_HEALTH_TIMEOUT_MS)
    : { reachable: false, message: "Web UI is stopped." };
  const modelConnectivity = await checkModelConnectivity(
    config.model,
    DEFAULT_MODEL_CONNECTIVITY_TIMEOUT_MS,
  );
  const runtimeWorkerUrl = runtimeState?.workerUrl || runtimeState?.expectedWorkerUrl;
  const urlMatches = runtimeWorkerUrl
    ? runtimeWorkerUrl === (config.worker?.baseUrl || DEFAULT_WORKER_URL)
    : !workerRunning.running;

  checks.push(
    makeCheck(
      "Selected worker installation path",
      workerDetection.installed,
      workerDetection.summary,
    ),
  );
  checks.push(
    makeCheck(
      "Selected web installation path",
      webDetection.installed,
      webDetection.summary,
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
      "Web availability",
      webHealth.reachable,
      webHealth.message,
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
        ? runtimeWorkerUrl
          ? `Configured URL matches ${runtimeWorkerUrl}.`
          : "No active runtime state is recorded because the worker is stopped."
        : `Configured URL is '${config.worker?.baseUrl || DEFAULT_WORKER_URL}', runtime state is '${runtimeWorkerUrl || "not available"}'.`,
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
  await ensureBaseDirectories();
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
  await ensureRuntimeInstalled();
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
  await ensureBaseDirectories();
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
    const existingHealth = await checkWorkerHealth(workerUrl, DEFAULT_WORKER_HEALTH_TIMEOUT_MS);
    if (existingHealth.reachable) {
      await writeRuntimeState({
        ...(runtimeState || {}),
        status: "running",
        healthyAt: new Date().toISOString(),
        workerUrl,
        pidFile: PID_PATH,
        logPath: WORKER_LOG_PATH,
        note: "Reusing an existing healthy RepoOperator worker.",
      });
      if (interactive) {
        term.summaryBox("Local worker", [
          ["Status", "already running"],
          ["Worker URL", workerUrl],
          ["Detail", existingHealth.message],
        ]);
      }
      return;
    }
    const occupiedMessage = `Configured worker URL ${workerUrl} is already in use by a non-RepoOperator process. Stop it or choose a different worker port.`;
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
    "repooperator_worker.main:app",
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
  await ensureBaseDirectories();
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
    const portPid = await findPidOnPort(workerBinding.port);
    const processLooksLikeWorker = portPid ? await isRepoOperatorWorkerProcess(portPid) : false;
    if (workerHealth.reachable || processLooksLikeWorker) {
      const cleanupPid = portPid || runtimeState?.pid;
      if (cleanupPid) {
        const cleanupResult = await stopWorkerProcess(cleanupPid);
        if (cleanupResult.exited) {
          await clearRuntimeStateFiles();
          if (interactive) {
            term.summaryBox("Local worker stopped", [
              ["Status", "stopped stale RepoOperator worker"],
              ["PID", String(cleanupPid)],
            ]);
          }
          return;
        }
        throw new Error(`Found a RepoOperator worker on ${workerUrl}, but could not stop PID ${cleanupPid}.`);
      }
    }
    const detail = portPid
      ? `Port ${workerBinding.port} is occupied by PID ${portPid}, which does not appear to be a RepoOperator worker.`
      : `Another process is still occupying ${workerUrl}.`;
    throw new Error(`${PRODUCT_NAME} did not stop that process. ${detail}`);
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

async function appendWebLaunchLog({ webPath, command, cwd, pathPrefix, webUrl, workerUrl }) {
  await ensureLogFileExists(WEB_LOG_PATH);
  const lines = [
    "",
    `[${new Date().toISOString()}] RepoOperator web launch`,
    `selected web path: ${webPath}`,
    `cwd: ${cwd}`,
    `command: ${command}`,
    `PATH prefix: ${pathPrefix}`,
    `web URL: ${webUrl}`,
    `worker URL: ${workerUrl}`,
    "",
  ];
  await fsp.appendFile(WEB_LOG_PATH, lines.join("\n"), "utf-8");
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
  const webBinDir = path.join(webInstallation.detectedPath, "node_modules", ".bin");
  const env = {
    ...process.env,
    NEXT_PUBLIC_LOCAL_WORKER_BASE_URL: workerUrl,
    PATH: `${webBinDir}${path.delimiter}${process.env.PATH || ""}`,
  };
  await appendWebLaunchLog({
    webPath: webInstallation.detectedPath,
    command: launchedCommand,
    cwd: webInstallation.detectedPath,
    pathPrefix: webBinDir,
    webUrl,
    workerUrl,
  });

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
  await ensureBaseDirectories();
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
  const webHealth = portState.inUse
    ? await checkWebHealth(webUrl, DEFAULT_WEB_HEALTH_TIMEOUT_MS)
    : { reachable: false, message: "Web UI is stopped." };

  if (!stopResult.exited) {
    throw new Error(
      `${PRODUCT_NAME} could not fully stop the recorded web UI process${webState?.pid ? ` ${webState.pid}` : ""}.`,
    );
  }

  if (portState.inUse) {
    const portPid = await findPidOnPort(webBinding.port);
    const processLooksLikeWeb = portPid ? await isRepoOperatorWebProcess(portPid) : false;
    if (webHealth.reachable || processLooksLikeWeb) {
      const cleanupPid = portPid || webState?.pid;
      if (cleanupPid) {
        const cleanupResult = await stopWorkerProcess(cleanupPid);
        if (cleanupResult.exited) {
          await clearWebRuntimeStateFiles();
          if (interactive) {
            term.summaryBox("Web UI stopped", [
              ["Status", "stopped stale RepoOperator web process"],
              ["PID", String(cleanupPid)],
            ]);
          }
          return;
        }
        throw new Error(`Found a RepoOperator web process on ${webUrl}, but could not stop PID ${cleanupPid}.`);
      }
    }
    const detail = portPid
      ? `Port ${webBinding.port} is occupied by PID ${portPid}, which does not appear to be the RepoOperator web UI.`
      : `Another process is still occupying ${webUrl}.`;
    throw new Error(`${PRODUCT_NAME} did not stop that process. ${detail}`);
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
  await ensureBaseDirectories();
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
  await fsp.mkdir(CONFIG_DIR, { recursive: true });
  await fsp.mkdir(RUN_DIR, { recursive: true });
  await fsp.mkdir(LOG_DIR, { recursive: true });
}

// ---------------------------------------------------------------------------
// Runtime bootstrap
// ---------------------------------------------------------------------------

function isDevelopmentMode() {
  return process.env.REPOOPERATOR_DEV === "1";
}

function isCliRunningFromMonorepoSource() {
  const monorepoWorker = path.resolve(__dirname, "../../../apps/local-worker/pyproject.toml");
  const monorepoWeb = path.resolve(__dirname, "../../../apps/web/package.json");
  return fs.existsSync(monorepoWorker) && fs.existsSync(monorepoWeb);
}

function allowRepoSourceRuntime() {
  return isDevelopmentMode() || isCliRunningFromMonorepoSource();
}

function getBundledWorkerSourceDir() {
  const packageRuntimePath = path.resolve(__dirname, "../runtime/local-worker");
  if (fs.existsSync(path.join(packageRuntimePath, "pyproject.toml"))) {
    return packageRuntimePath;
  }

  const monorepoPath = path.resolve(__dirname, "../../../apps/local-worker");
  if (fs.existsSync(path.join(monorepoPath, "pyproject.toml"))) {
    return monorepoPath;
  }

  return null;
}

function getBundledWebSourceDir() {
  const packageRuntimePath = path.resolve(__dirname, "../runtime/web");
  if (fs.existsSync(path.join(packageRuntimePath, "package.json"))) {
    return packageRuntimePath;
  }

  const monorepoPath = path.resolve(__dirname, "../../../apps/web");
  if (fs.existsSync(path.join(monorepoPath, "package.json"))) {
    return monorepoPath;
  }

  return null;
}

async function isWorkerRuntimeInstalled() {
  return fileExists(path.join(RUNTIME_VENV_DIR, "bin", "python"))
    && fileExists(path.join(RUNTIME_WORKER_DIR, "src", "repooperator_worker", "main.py"));
}

async function isWebRuntimeInstalled() {
  return fileExists(path.join(RUNTIME_WEB_DIR, "package.json"))
    && fileExists(path.join(RUNTIME_WEB_DIR, "node_modules", ".bin", "next"));
}

async function copyRuntimeDirectory(src, dest) {
  if (path.resolve(src) === path.resolve(dest)) {
    return;
  }
  await fsp.cp(src, dest, {
    recursive: true,
    force: true,
    filter: (source) => {
      const base = path.basename(source);
      return ![
        "node_modules",
        ".venv",
        ".git",
        "__pycache__",
        ".next",
        "dist",
        "build",
      ].includes(base) && !base.endsWith(".egg-info") && !base.endsWith(".tgz");
    },
  });
}

async function getPythonVersion(executable) {
  try {
    const result = await runCommandCapture(executable, [
      "-c",
      "import sys; print(sys.version_info.major, sys.version_info.minor)",
    ]);
    if (result.returncode !== 0) return null;
    const parts = result.stdout.trim().split(/\s+/);
    const major = parseInt(parts[0], 10);
    const minor = parseInt(parts[1], 10);
    if (isNaN(major) || isNaN(minor)) return null;
    return { major, minor };
  } catch {
    return null;
  }
}

function isPythonCompatible(versionInfo) {
  if (!versionInfo) return false;
  if (versionInfo.major !== MIN_PYTHON_MAJOR) return false;
  return versionInfo.minor >= MIN_PYTHON_MINOR;
}

async function findCompatiblePython() {
  const envOverride = process.env.REPOOPERATOR_PYTHON;
  if (envOverride) {
    const version = await getPythonVersion(envOverride);
    if (isPythonCompatible(version)) return envOverride;
    if (version) {
      throw new Error(
        `REPOOPERATOR_PYTHON is set to "${envOverride}" but it is Python ${version.major}.${version.minor}, which is below the required ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+.`,
      );
    }
    throw new Error(
      `REPOOPERATOR_PYTHON is set to "${envOverride}" but it could not be executed. Check the path and try again.`,
    );
  }

  for (const candidate of PYTHON_CANDIDATES) {
    if (!(await commandExists(candidate))) continue;
    const version = await getPythonVersion(candidate);
    if (isPythonCompatible(version)) return candidate;
  }

  return null;
}

function formatNoPythonError(foundVersion) {
  const required = `Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+`;
  const found = foundVersion
    ? `Python ${foundVersion.major}.${foundVersion.minor} was found but is too old.`
    : "No compatible Python installation was found.";

  const platform = process.platform;
  let installHint;
  if (platform === "darwin") {
    installHint = [
      `Install ${required} via Homebrew:`,
      "  brew install python@3.12",
      "Or download from https://www.python.org/downloads/",
    ].join("\n");
  } else if (platform === "linux") {
    installHint = [
      `Install ${required} via your package manager, e.g.:`,
      "  sudo apt install python3.12   # Debian/Ubuntu",
      "  sudo dnf install python3.12   # Fedora/RHEL",
      "Or download from https://www.python.org/downloads/",
    ].join("\n");
  } else {
    installHint = `Download and install ${required} from https://www.python.org/downloads/`;
  }

  return `${found}\n\n${installHint}\n\nAfter installing Python, rerun \`repooperator onboard\`.`;
}

async function getVenvPythonVersion() {
  const venvPython = path.join(RUNTIME_VENV_DIR, "bin", "python");
  if (!(await fileExists(venvPython))) return null;
  return getPythonVersion(venvPython);
}

async function installWorkerRuntime() {
  const sourceDir = getBundledWorkerSourceDir();
  if (!sourceDir) {
    throw new Error(`${PRODUCT_NAME} could not find bundled local worker sources. Reinstall the repooperator npm package.`);
  }

  const selectedPython = await findCompatiblePython();
  if (!selectedPython) {
    let foundVersion = null;
    for (const candidate of PYTHON_CANDIDATES) {
      if (!(await commandExists(candidate))) continue;
      foundVersion = await getPythonVersion(candidate);
      if (foundVersion) break;
    }
    throw new Error(formatNoPythonError(foundVersion));
  }

  await fsp.mkdir(RUNTIME_DIR, { recursive: true });
  await fsp.rm(RUNTIME_WORKER_DIR, { recursive: true, force: true });
  await copyRuntimeDirectory(sourceDir, RUNTIME_WORKER_DIR);

  const venvPython = path.join(RUNTIME_VENV_DIR, "bin", "python");
  let needsNewVenv = !(await fileExists(venvPython));
  if (!needsNewVenv) {
    const existingVersion = await getVenvPythonVersion();
    if (!isPythonCompatible(existingVersion)) {
      await fsp.rm(RUNTIME_VENV_DIR, { recursive: true, force: true });
      needsNewVenv = true;
    }
  }

  if (needsNewVenv) {
    const venvResult = await runCommandCapture(selectedPython, ["-m", "venv", RUNTIME_VENV_DIR]);
    if (venvResult.returncode !== 0) {
      throw new Error(`Failed to create worker virtual environment at ${RUNTIME_VENV_DIR}.\n${venvResult.stderr}`);
    }
  }

  const pipResult = await runCommandCapture(venvPython, ["-m", "pip", "install", "-U", "pip"]);
  if (pipResult.returncode !== 0) {
    throw new Error(`Failed to upgrade pip in worker virtual environment.\n${pipResult.stderr}`);
  }

  const installResult = await runCommandCapture(venvPython, ["-m", "pip", "install", "-e", RUNTIME_WORKER_DIR]);
  if (installResult.returncode !== 0) {
    throw new Error(`Failed to install local worker runtime.\n${installResult.stderr}`);
  }
}

async function installWebRuntime() {
  const sourceDir = getBundledWebSourceDir();
  if (!sourceDir) {
    throw new Error(`${PRODUCT_NAME} could not find bundled web sources. Reinstall the repooperator npm package.`);
  }
  if (!(await commandExists("npm"))) {
    throw new Error("npm is required for the web UI. Install Node.js and rerun onboarding.");
  }

  await fsp.mkdir(RUNTIME_DIR, { recursive: true });
  await fsp.rm(RUNTIME_WEB_DIR, { recursive: true, force: true });
  await copyRuntimeDirectory(sourceDir, RUNTIME_WEB_DIR);
  const installResult = await runCommandCapture("npm", ["install"], { cwd: RUNTIME_WEB_DIR });
  if (installResult.returncode !== 0) {
    throw new Error(`Failed to install web runtime dependencies.\n${installResult.stderr}`);
  }
}

async function ensureRuntimeInstalled() {
  await ensureBaseDirectories();

  const workerPackageExists = await fileExists(path.join(RUNTIME_WORKER_DIR, "pyproject.toml"));
  const workerInstalled = workerPackageExists && await isWorkerRuntimeInstalled();
  const webPackageExists = await fileExists(path.join(RUNTIME_WEB_DIR, "package.json"));
  const webInstalled = await isWebRuntimeInstalled();

  if (workerInstalled && webInstalled) {
    return;
  }

  term.line("info", "Runtime setup", "Preparing the local worker and web UI runtime.");
  await fsp.mkdir(RUNTIME_DIR, { recursive: true });

  if (!workerInstalled) {
    await term.spinner("Prepare local worker runtime", () => installWorkerRuntime());
    term.line("success", "Worker runtime ready", RUNTIME_VENV_DIR);
  }

  if (!webInstalled) {
    if (webPackageExists) {
      await term.spinner("Repair web runtime dependencies", async () => {
        const result = await runCommandCapture("npm", ["install"], { cwd: RUNTIME_WEB_DIR });
        if (result.returncode !== 0) {
          throw new Error(`Failed to repair web runtime dependencies.\n${result.stderr}`);
        }
      });
    } else {
      await term.spinner("Prepare web runtime", () => installWebRuntime());
    }
    term.line("success", "Web runtime ready", RUNTIME_WEB_DIR);
  }
}

async function runSetupRuntime() {
  await ensureRuntimeInstalled();
  term.summaryBox("Runtime ready", [
    ["Runtime path", RUNTIME_DIR],
    ["Worker venv", RUNTIME_VENV_DIR],
    ["Web path", RUNTIME_WEB_DIR],
  ]);
}

async function resolveWorkerInstallation(config, startDir) {
  if (process.env.REPOOPERATOR_WORKER_PATH) {
    const envPath = process.env.REPOOPERATOR_WORKER_PATH;
    if (await fileExists(path.join(envPath, "pyproject.toml"))) {
      return {
        installed: true,
        installMode: "env-override",
        detectedPath: envPath,
        summary: `Using REPOOPERATOR_WORKER_PATH at ${envPath}`,
      };
    }
  }

  if (await fileExists(path.join(RUNTIME_WORKER_DIR, "pyproject.toml"))) {
    return {
      installed: true,
      installMode: "runtime",
      detectedPath: RUNTIME_WORKER_DIR,
      summary: `Runtime-installed local worker at ${RUNTIME_WORKER_DIR}`,
    };
  }

  if (allowRepoSourceRuntime() && config?.worker?.detectedPath && (await fileExists(path.join(config.worker.detectedPath, "pyproject.toml")))) {
    return {
      installed: true,
      installMode: config.worker.installMode || "repo-source",
      detectedPath: config.worker.detectedPath,
      summary: `Detected a repo-source local worker at ${config.worker.detectedPath}`,
    };
  }

  if (allowRepoSourceRuntime()) {
    return detectLocalWorkerInstallation(startDir);
  }

  return {
    installed: false,
    installMode: "not-detected",
    detectedPath: null,
    summary: "No runtime-installed local worker was detected. Re-run onboarding to repair the runtime.",
  };
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
  if (process.env.REPOOPERATOR_WEB_PATH) {
    const envPath = process.env.REPOOPERATOR_WEB_PATH;
    if (await fileExists(path.join(envPath, "package.json"))) {
      return {
        installed: true,
        detectedPath: envPath,
        summary: `Using REPOOPERATOR_WEB_PATH at ${envPath}`,
      };
    }
  }

  if (await fileExists(path.join(RUNTIME_WEB_DIR, "package.json"))) {
    const nextExists = await fileExists(path.join(RUNTIME_WEB_DIR, "node_modules", ".bin", "next"));
    return {
      installed: nextExists,
      detectedPath: RUNTIME_WEB_DIR,
      summary: nextExists
        ? `Runtime-installed web UI at ${RUNTIME_WEB_DIR}`
        : `Runtime web UI exists at ${RUNTIME_WEB_DIR}, but node_modules/.bin/next is missing.`,
    };
  }

  if (allowRepoSourceRuntime() && config?.web?.detectedPath && (await fileExists(path.join(config.web.detectedPath, "package.json")))) {
    return {
      installed: true,
      detectedPath: config.web.detectedPath,
      summary: `Detected a repo-source web UI at ${config.web.detectedPath}`,
    };
  }

  if (allowRepoSourceRuntime()) {
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
  }

  return {
    installed: false,
    detectedPath: null,
    summary: "No runtime-installed web UI was detected. Re-run onboarding to repair the runtime.",
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
  const runtimePythonPath = path.join(RUNTIME_VENV_DIR, "bin", "python");
  if (await fileExists(runtimePythonPath)) {
    return { pythonPath: runtimePythonPath };
  }

  const localPythonPath = path.join(workerPath, ".venv", "bin", "python");
  if (await fileExists(localPythonPath)) {
    return { pythonPath: localPythonPath };
  }

  const compatible = await findCompatiblePython();
  if (!compatible) {
    let foundVersion = null;
    for (const candidate of PYTHON_CANDIDATES) {
      if (!(await commandExists(candidate))) continue;
      foundVersion = await getPythonVersion(candidate);
      if (foundVersion) break;
    }
    throw new Error(formatNoPythonError(foundVersion));
  }
  throw new Error(
    `Worker Python executable is missing. Re-run \`${CLI_COMMAND} onboard\` to repair the runtime.`,
  );
}

async function resolveWorkerLaunchConfig(workerPath) {
  const srcPath = path.join(workerPath, "src");
  const moduleEntry = path.join(srcPath, "repooperator_worker", "main.py");

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

async function promptReonboardingPlan(rl) {
  while (true) {
    printOptionList("What would you like to update?", [
      ["1", "Validate only", "Keep current settings and refresh runtime metadata"],
      ["2", "Model connection", "Keep repositories, update model settings"],
      ["3", "Repository sources", "Keep model, update or add repository sources"],
      ["4", "Model and repositories", "Update both primary setup areas"],
      ["5", "Full reconfiguration", "Review model, repositories, and local runtime paths"],
    ]);
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";
    if (answer === "1") {
      return { updateModel: false, updateRepositories: false, updateRuntime: false, fullReconfigure: false };
    }
    if (answer === "2") {
      return { updateModel: true, updateRepositories: false, updateRuntime: false, fullReconfigure: false };
    }
    if (answer === "3") {
      return { updateModel: false, updateRepositories: true, updateRuntime: false, fullReconfigure: false };
    }
    if (answer === "4") {
      return { updateModel: true, updateRepositories: true, updateRuntime: false, fullReconfigure: false };
    }
    if (answer === "5") {
      return { updateModel: true, updateRepositories: true, updateRuntime: true, fullReconfigure: true };
    }
    term.line("warning", "Invalid choice", "Please choose a number from 1 to 5.");
  }
}

function hasRuntimeRelevantConfigChanged(previousConfig, nextConfig) {
  if (!previousConfig) {
    return true;
  }
  return runtimeConfigFingerprint(previousConfig) !== runtimeConfigFingerprint(nextConfig);
}

function runtimeConfigFingerprint(config) {
  const safe = {
    model: {
      connectionMode: config?.model?.connectionMode || null,
      provider: config?.model?.provider || null,
      model: config?.model?.model || null,
      baseUrl: config?.model?.baseUrl || null,
      apiKeyState: config?.model?.apiKey ? `present:${hashSecret(config.model.apiKey)}` : "absent",
    },
    gitProvider: {
      provider: config?.gitProvider?.provider || null,
      baseUrl: config?.gitProvider?.baseUrl || null,
      tokenState: config?.gitProvider?.token ? `present:${hashSecret(config.gitProvider.token)}` : "absent",
    },
    repositorySources: Array.isArray(config?.repositorySources)
      ? config.repositorySources.map((source) => ({
          provider: source?.provider || null,
          baseUrl: source?.baseUrl || null,
          owner: source?.owner || null,
          tokenState: source?.token ? `present:${hashSecret(source.token)}` : "absent",
        }))
      : [],
    localRepoBaseDir: config?.localRepoBaseDir || null,
    workerBaseUrl: config?.worker?.baseUrl || null,
  };
  return crypto.createHash("sha256").update(JSON.stringify(safe)).digest("hex");
}

function hashSecret(value) {
  return crypto.createHash("sha256").update(String(value)).digest("hex").slice(0, 12);
}

async function promptRepositorySourceConfig(rl, existingConfig = null) {
  const existingSources = normalizeRepositorySources(existingConfig);
  if (existingSources.length) {
    term.summaryBox("Saved repository sources", [
      ["Default", formatProviderSummary(existingConfig.gitProvider)],
      ["Sources", formatRepositorySourcesSummary(existingConfig)],
    ]);
  }

  if (existingSources.length && await promptYesNo(rl, "Keep current default repository source?", true)) {
    if (await promptYesNo(rl, "Add another repository source during this onboarding run?", false)) {
      const added = await promptSingleRepositorySource(rl, null);
      if (added.provider === "none") {
        return preserveRepositorySourceConfig(existingConfig);
      }
      const repositorySources = upsertRepositorySource(existingSources, added);
      const makeDefault = await promptYesNo(rl, `Make ${formatProviderSummary(added)} the default repository source?`, true);
      return {
        gitProvider: makeDefault ? added : existingConfig.gitProvider,
        repositorySources,
      };
    }

    return preserveRepositorySourceConfig(existingConfig);
  }

  if (existingSources.length) {
    while (true) {
      printOptionList("Repository source update", [
        ["1", "Change default", "Choose one of the saved sources as default"],
        ["2", "Add source", "Add GitLab, GitHub, or local and make it default"],
        ["3", "Replace sources", "Start repository source setup fresh"],
      ]);
      const answer = (await rl.question("Choice [2]: ")).trim() || "2";
      if (answer === "1") {
        const gitProvider = await chooseExistingRepositorySource(rl, existingSources);
        return { gitProvider, repositorySources: existingSources };
      }
      if (answer === "2") {
        const added = await promptSingleRepositorySource(rl, null);
        if (added.provider === "none") {
          return preserveRepositorySourceConfig(existingConfig);
        }
        return {
          gitProvider: added,
          repositorySources: upsertRepositorySource(existingSources, added),
        };
      }
      if (answer === "3") {
        const next = await promptSingleRepositorySource(rl, null);
        return {
          gitProvider: next,
          repositorySources: next.provider === "none" ? [] : [next],
        };
      }
      term.line("warning", "Invalid choice", "Please choose 1, 2, or 3.");
    }
  }

  const gitProvider = await promptSingleRepositorySource(rl, null);
  return {
    gitProvider,
    repositorySources: gitProvider.provider === "none" ? [] : [gitProvider],
  };
}

async function promptSingleRepositorySource(rl, existingProviderConfig) {
  const gitProvider = await promptGitProvider(rl);
  const existingForProvider = existingProviderConfig?.provider === gitProvider
    ? existingProviderConfig
    : null;
  return promptGitProviderConfig(rl, gitProvider, existingForProvider);
}

async function chooseExistingRepositorySource(rl, sources) {
  while (true) {
    printOptionList(
      "Choose the default repository source",
      sources.map((source, index) => [
        String(index + 1),
        formatProviderSummary(source),
        source.provider === "local" ? "local projects" : "hosted provider",
      ]),
    );
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";
    const choice = Number(answer);
    if (Number.isInteger(choice) && choice >= 1 && choice <= sources.length) {
      return sources[choice - 1];
    }
    term.line("warning", "Invalid choice", `Please choose a number from 1 to ${sources.length}.`);
  }
}

function preserveRepositorySourceConfig(existingConfig) {
  const repositorySources = normalizeRepositorySources(existingConfig);
  const gitProvider = existingConfig?.gitProvider || repositorySources[0] || { provider: "none" };
  return { gitProvider, repositorySources };
}

function normalizeRepositorySources(config) {
  const sources = [];
  if (Array.isArray(config?.repositorySources)) {
    for (const source of config.repositorySources) {
      if (source?.provider && source.provider !== "none") {
        sources.push(source);
      }
    }
  }
  if (config?.gitProvider?.provider && config.gitProvider.provider !== "none") {
    sources.unshift(config.gitProvider);
  }
  return dedupeRepositorySources(sources);
}

function upsertRepositorySource(sources, source) {
  if (!source?.provider || source.provider === "none") {
    return dedupeRepositorySources(sources);
  }
  return dedupeRepositorySources([source, ...sources]);
}

function dedupeRepositorySources(sources) {
  const seen = new Set();
  const unique = [];
  for (const source of sources) {
    const key = source.provider === "local"
      ? "local"
      : `${source.provider}:${source.baseUrl || ""}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push(source);
  }
  return unique;
}

function formatRepositorySourcesSummary(config) {
  const sources = normalizeRepositorySources(config);
  if (!sources.length) {
    return "none configured";
  }
  return sources.map(formatProviderSummary).join(", ");
}

function splitGitHubBaseUrlAndScope(value) {
  const fallback = { baseUrl: "https://github.com", scopeFromPath: "" };
  if (!value?.trim()) {
    return fallback;
  }

  try {
    const parsed = new URL(value.trim());
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    parsed.pathname = "";
    parsed.search = "";
    parsed.hash = "";
    return {
      baseUrl: parsed.toString().replace(/\/$/, ""),
      scopeFromPath: pathParts[0] || "",
    };
  } catch {
    return { baseUrl: value.trim().replace(/\/+$/, ""), scopeFromPath: "" };
  }
}

async function promptGitHubMode(rl, existingProviderConfig = null) {
  const defaultChoice = existingProviderConfig?.baseUrl && existingProviderConfig.baseUrl !== "https://github.com"
    ? "2"
    : "1";
  while (true) {
    printOptionList("Choose GitHub hosting", [
      ["1", "Public GitHub", "Use github.com; no base URL needed"],
      ["2", "GitHub Enterprise", "Use a company-hosted GitHub URL"],
    ]);
    const answer = (await rl.question(`Choice [${defaultChoice}]: `)).trim() || defaultChoice;
    if (answer === "1") {
      return "public";
    }
    if (answer === "2") {
      return "enterprise";
    }
    term.line("warning", "Invalid choice", "Please choose 1 or 2.");
  }
}

async function promptGitProviderConfig(rl, provider, existingProviderConfig = null) {
  if (provider === "gitlab") {
    term.summaryBox("GitLab source", [
      "Use a GitLab personal, project, or group token with repository read access.",
      "RepoOperator stores the base URL and token locally for the worker.",
    ]);
    const baseUrl = await promptWithDefault(
      rl,
      "GitLab base URL",
      existingProviderConfig?.baseUrl || "https://gitlab.com",
    );
    const token = await promptWithDefault(rl, "GitLab token", existingProviderConfig?.token || "");
    return { provider: "gitlab", baseUrl, token };
  }

  if (provider === "github") {
    term.summaryBox("GitHub source", [
      "Choose Public GitHub for github.com or GitHub Enterprise for a company-hosted GitHub URL.",
      "Public GitHub automatically uses https://github.com.",
      "Owner or organization filtering is a separate optional scope.",
    ]);
    const githubMode = await promptGitHubMode(rl, existingProviderConfig);
    let baseUrl = "https://github.com";
    let scopeFromPath = "";
    if (githubMode === "enterprise") {
      const rawBaseUrl = await promptWithDefault(
        rl,
        "GitHub Enterprise base URL (host only)",
        existingProviderConfig?.baseUrl && existingProviderConfig.baseUrl !== "https://github.com"
          ? existingProviderConfig.baseUrl
          : "https://github.example.com",
      );
      const splitBaseUrl = splitGitHubBaseUrlAndScope(rawBaseUrl);
      baseUrl = splitBaseUrl.baseUrl;
      scopeFromPath = splitBaseUrl.scopeFromPath;
      if (scopeFromPath) {
        term.line(
          "warning",
          "GitHub Enterprise URL adjusted",
          `Using ${baseUrl} as the base URL and ${scopeFromPath} as the owner/org scope.`,
        );
      }
    }
    const owner = await promptWithDefault(
      rl,
      "Optional GitHub owner/org scope",
      existingProviderConfig?.owner || scopeFromPath || "",
    );
    const token = await promptWithDefault(rl, "GitHub token", existingProviderConfig?.token || "");
    return {
      provider: "github",
      baseUrl,
      githubMode,
      owner: owner || undefined,
      token,
    };
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

async function promptModelConfig(rl, existingModelConfig = null) {
  if (existingModelConfig && await promptYesNo(rl, `Keep current model settings (${formatModelSummary(existingModelConfig)})?`, true)) {
    return existingModelConfig;
  }

  const connectionMode = await promptModelConnectionMode(rl, existingModelConfig?.connectionMode);

  if (connectionMode === "local-runtime") {
    return promptLocalRuntimeModelConfig(rl, existingModelConfig);
  }

  return promptRemoteApiModelConfig(rl, existingModelConfig);
}

async function promptLocalRuntimeModelConfig(rl, existingModelConfig = null) {
  const provider = await promptLocalRuntimeProvider(rl, existingModelConfig?.provider);
  if (provider === "ollama") {
    return promptOllamaModelConfig(rl, existingModelConfig?.provider === "ollama" ? existingModelConfig : null);
  }
  if (provider === "vllm") {
    return promptVllmModelConfig(rl, existingModelConfig?.provider === "vllm" ? existingModelConfig : null);
  }
  throw new Error(`Unsupported local runtime provider: ${provider}`);
}

async function promptRemoteApiModelConfig(rl, existingModelConfig = null) {
  const provider = await promptRemoteApiProvider(rl, existingModelConfig?.provider);

  const providerConfig = MODEL_PROVIDER_CONFIG[provider];

  term.summaryBox(`Remote model API: ${providerConfig.label}`, [
    "RepoOperator will use these settings when the local worker calls your model API.",
    "Secrets are stored locally in ~/.repooperator/config.json.",
  ]);

  const existingMatchesProvider = existingModelConfig?.provider === provider;
  let baseUrl = existingMatchesProvider ? existingModelConfig.baseUrl || "" : providerConfig.defaultBaseUrl || "";
  let apiKey = existingMatchesProvider ? existingModelConfig.apiKey || "" : providerConfig.defaultApiKey || "";
  let model = existingMatchesProvider ? existingModelConfig.model || "" : providerConfig.defaultModel || "";

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

async function promptOllamaModelConfig(rl, existingModelConfig = null) {
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

  const baseUrl = await promptWithDefault(rl, "Ollama base URL", existingModelConfig?.baseUrl || OLLAMA_DEFAULT_BASE_URL);
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

async function promptVllmModelConfig(rl, existingModelConfig = null) {
  term.summaryBox("Local model runtime: vLLM", [
    "RepoOperator will use an OpenAI-compatible vLLM endpoint.",
    "RepoOperator does not start vLLM. Start it yourself on this machine or a trusted LAN host.",
  ]);

  const baseUrl = await promptWithDefault(rl, "vLLM base URL", existingModelConfig?.baseUrl || VLLM_DEFAULT_BASE_URL);
  const apiKey = await promptWithDefault(rl, "API key (optional)", existingModelConfig?.apiKey || "");
  const probe = await term.spinner("Check vLLM /models", () => checkModelConnectivity({
    connectionMode: "local-runtime",
    provider: "vllm",
    baseUrl,
    apiKey,
    model: existingModelConfig?.model || "unknown",
  }, DEFAULT_MODEL_CONNECTIVITY_TIMEOUT_MS));
  if (probe.reachable) {
    term.line("success", "vLLM reachable", probe.message);
  } else {
    term.line("warning", "vLLM not reachable yet", probe.message);
  }
  const model = await promptWithDefault(rl, "Model name", existingModelConfig?.model || "");
  return {
    connectionMode: "local-runtime",
    provider: "vllm",
    baseUrl,
    apiKey,
    model,
  };
}

async function promptModelConnectionMode(rl, existingConnectionMode = null) {
  while (true) {
    printOptionList("Choose how RepoOperator should connect to a model", [
      ["1", "Local model runtime", "Ollama on this machine"],
      ["2", "Remote model API", "OpenAI-compatible or hosted provider"],
    ]);
    const defaultChoice = existingConnectionMode === "remote-api" ? "2" : "1";
    const answer = (await rl.question(`Choice [${defaultChoice}]: `)).trim() || defaultChoice;

    if (answer === "1") {
      return "local-runtime";
    }
    if (answer === "2") {
      return "remote-api";
    }
    term.line("warning", "Invalid choice", "Please choose 1 or 2.");
  }
}

async function promptLocalRuntimeProvider(rl, _existingProvider = null) {
  while (true) {
    printOptionList("Choose a local model runtime", [
      ["1", "Ollama", "Local OpenAI-compatible model server"],
      ["2", "vLLM", "OpenAI-compatible endpoint on this machine or trusted LAN"],
    ]);
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "ollama";
    }
    if (answer === "2") {
      return "vllm";
    }
    term.line("warning", "Invalid choice", "Please choose 1 or 2.");
  }
}

async function promptRemoteApiProvider(rl, existingProvider = null) {
  while (true) {
    printOptionList("Choose a remote model API", [
      ["1", "OpenAI-compatible", "Enterprise gateways and compatible APIs"],
      ["2", "OpenAI", "OpenAI API"],
      ["3", "Anthropic", "Anthropic API"],
      ["4", "Gemini", "Gemini OpenAI-compatible endpoint"],
    ]);
    const defaultChoice = remoteApiProviderToChoice(existingProvider) || "1";
    const answer = (await rl.question(`Choice [${defaultChoice}]: `)).trim() || defaultChoice;

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
  await ensureBaseDirectories();
  if (!(await fileExists(CONFIG_PATH))) {
    throw new Error(`${PRODUCT_NAME} is not configured yet. Run \`${CLI_COMMAND} onboard\` first.`);
  }
  return readConfig();
}

async function readConfig() {
  await ensureBaseDirectories();
  const raw = await fsp.readFile(CONFIG_PATH, "utf-8");
  return normalizeConfig(JSON.parse(raw));
}

async function readOptionalConfig() {
  await ensureBaseDirectories();
  if (!(await fileExists(CONFIG_PATH))) {
    return null;
  }
  return readConfig();
}

async function readState() {
  await ensureBaseDirectories();
  if (await fileExists(STATE_PATH)) {
    const raw = await fsp.readFile(STATE_PATH, "utf-8");
    return JSON.parse(raw);
  }
  return null;
}

async function readWebState() {
  await ensureBaseDirectories();
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

async function readPidFile(filePath) {
  if (!(await fileExists(filePath))) {
    return null;
  }
  const raw = await fsp.readFile(filePath, "utf-8");
  const pid = Number(raw.trim());
  return Number.isInteger(pid) && pid > 0 ? pid : null;
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

async function findPidOnPort(port) {
  const result = await runCommandCapture("lsof", ["-t", `-iTCP:${port}`, "-sTCP:LISTEN"]);
  if (result.returncode !== 0) {
    return null;
  }
  const pid = Number(result.stdout.trim().split(/\r?\n/).find(Boolean));
  return Number.isInteger(pid) && pid > 0 ? pid : null;
}

async function isRepoOperatorWorkerProcess(pid) {
  const result = await runCommandCapture("ps", ["-p", String(pid), "-o", "args="]);
  if (result.returncode !== 0) {
    return false;
  }
  const args = result.stdout.toLowerCase();
  return args.includes("repooperator_worker") || (args.includes("uvicorn") && args.includes("repooperator"));
}

async function isRepoOperatorWebProcess(pid) {
  const result = await runCommandCapture("ps", ["-p", String(pid), "-o", "args="]);
  if (result.returncode !== 0) {
    return false;
  }
  const args = result.stdout.toLowerCase();
  return args.includes("next dev") || args.includes("repooperator-web") || args.includes(".repooperator/runtime/web");
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
    const validation = await validateModelListResponse(response, modelConfig, probe);
    if (!validation.ok) {
      return {
        reachable: false,
        message: validation.message,
      };
    }

    return {
      reachable: true,
      message: validation.message || `Model endpoint responded successfully at ${probe.url} with status ${response.status}.`,
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

async function validateModelListResponse(response, modelConfig, probe) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return { ok: true, message: "" };
  }
  let payload;
  try {
    payload = await response.clone().json();
  } catch {
    return { ok: true, message: "" };
  }
  const modelIds = extractModelIds(payload);
  if (!modelIds.length) {
    return { ok: true, message: `Model endpoint responded at ${probe.url}, but did not list model IDs.` };
  }
  const configured = modelConfig.model || modelConfig.modelName;
  if (configured && !modelIds.includes(configured)) {
    return {
      ok: false,
      message: [
        `Model endpoint is reachable at ${probe.url}, but configured model "${configured}" was not found.`,
        `Available model IDs: ${modelIds.slice(0, 12).join(", ")}`,
      ].join(" "),
    };
  }
  return {
    ok: true,
    message: `Model endpoint responded at ${probe.url}. Configured model "${configured || modelIds[0]}" is available.`,
  };
}

function extractModelIds(payload) {
  const data = Array.isArray(payload?.data) ? payload.data : Array.isArray(payload?.models) ? payload.models : [];
  return data
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item.id === "string") return item.id;
      if (item && typeof item.name === "string") return item.name;
      if (item && typeof item.model === "string") return item.model;
      return null;
    })
    .filter(Boolean);
}

function buildModelConnectivityProbe(modelConfig) {
  const baseUrl = modelConfig.baseUrl.replace(/\/+$/, "");

  if (
    modelConfig.provider === "openai" ||
    modelConfig.provider === "gemini" ||
    modelConfig.provider === "ollama" ||
    modelConfig.provider === "vllm" ||
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
  if (modelConfig.provider === "vllm") {
    return `Expected a vLLM OpenAI-compatible models endpoint. Confirm vLLM is running on a trusted host and that ${probe.url} is reachable.`;
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
  if (tail.includes("ModuleNotFoundError") || tail.includes("No module named 'repooperator_worker'")) {
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
  const redactedRepositorySources = Array.isArray(normalized.repositorySources)
    ? normalized.repositorySources.map((source) => ({
        ...source,
        token: source.token ? redactSecret(source.token) : "",
      }))
    : normalized.repositorySources;
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
    repositorySources: redactedRepositorySources,
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
    const scope = gitProvider.owner ? `, owner/org: ${gitProvider.owner}` : "";
    return `${gitProvider.provider} (${gitProvider.baseUrl}${scope})`;
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

function remoteApiProviderToChoice(provider) {
  if (provider === "openai-compatible") {
    return "1";
  }
  if (provider === "openai") {
    return "2";
  }
  if (provider === "anthropic") {
    return "3";
  }
  if (provider === "gemini") {
    return "4";
  }
  return null;
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
      gitProvider: normalizeRepositorySourceConfig(config.gitProvider),
      repositorySources: Array.isArray(config.repositorySources)
        ? config.repositorySources.map(normalizeRepositorySourceConfig)
        : config.repositorySources,
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
      gitProvider: normalizeRepositorySourceConfig(config.gitProvider),
      repositorySources: Array.isArray(config.repositorySources)
        ? config.repositorySources.map(normalizeRepositorySourceConfig)
        : config.repositorySources,
    };
    delete normalized.modelBackend;
    return normalized;
  }

  return config;
}

function normalizeRepositorySourceConfig(source) {
  if (!source || typeof source !== "object") {
    return source;
  }
  if (source.provider !== "github" || !source.baseUrl) {
    return source;
  }
  const splitBaseUrl = splitGitHubBaseUrlAndScope(source.baseUrl);
  if (!splitBaseUrl.scopeFromPath) {
    return {
      ...source,
      baseUrl: splitBaseUrl.baseUrl,
    };
  }
  return {
    ...source,
    baseUrl: splitBaseUrl.baseUrl,
    owner: source.owner || splitBaseUrl.scopeFromPath,
  };
}

function normalizeModelConfig(modelConfig) {
  if (!modelConfig || typeof modelConfig !== "object") {
    return modelConfig;
  }

  const connectionMode = modelConfig.connectionMode
    || (["ollama", "vllm"].includes(modelConfig.provider) ? "local-runtime" : "remote-api");

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
