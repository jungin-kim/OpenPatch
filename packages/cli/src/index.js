const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const readline = require("node:readline/promises");
const { spawn } = require("node:child_process");
const { stdin, stdout } = require("node:process");

const CONFIG_DIR = path.join(os.homedir(), ".openpatch");
const CONFIG_PATH = path.join(CONFIG_DIR, "config.json");
const DAEMON_DIR = path.join(CONFIG_DIR, "daemon");
const RUN_DIR = path.join(CONFIG_DIR, "run");
const LOG_DIR = path.join(CONFIG_DIR, "logs");
const STATE_PATH = path.join(DAEMON_DIR, "state.json");
const WORKER_LOG_PATH = path.join(LOG_DIR, "worker.log");
const DEFAULT_WORKER_URL = "http://127.0.0.1:8000";
const DEFAULT_REPO_BASE_DIR = path.join(os.homedir(), ".openpatch", "repos");
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
    defaultBaseUrl: "http://127.0.0.1:11434/v1",
    defaultApiKey: "ollama",
    defaultModel: "llama3.2",
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
    case "logs":
      await showWorkerLogs();
      return;
    default:
      throw new Error("Unknown worker command. Use start, stop, restart, or logs.");
  }
}

async function runOnboard() {
  await ensureBaseDirectories();
  const rl = readline.createInterface({ input: stdin, output: stdout });

  try {
    console.log("OpenPatch onboarding");
    console.log("Set up OpenPatch on this machine.");
    console.log("We will save your local settings, connect a model provider, choose a git provider, and prepare the local worker runtime.");
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
    });

    console.log("");
    console.log("OpenPatch is now configured.");
    console.log(`Config file: ${CONFIG_PATH}`);
    console.log(`Worker detection: ${workerDetection.summary}`);

    const startAnswer = (
      await rl.question("Start the local worker now? [Y/n]: ")
    ).trim().toLowerCase();
    if (startAnswer === "" || startAnswer === "y" || startAnswer === "yes") {
      try {
        await startWorker({ interactive: false });
        console.log("The local worker has been started.");
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        console.log(`Worker start failed: ${message}`);
        console.log("You can try again with `openpatch worker start` after fixing the issue.");
      }
    } else {
      console.log("Skipping worker start.");
    }

    console.log("Next steps:");
    console.log("  1. Run `openpatch doctor`");
    console.log("  2. Run `openpatch status`");
    console.log("  3. Use `openpatch worker logs` if the worker does not come up cleanly");
  } finally {
    rl.close();
  }
}

async function runDoctor() {
  const checks = [];
  const configExists = await fileExists(CONFIG_PATH);
  checks.push(
    makeCheck(
      "Config file exists",
      configExists,
      configExists ? CONFIG_PATH : "Run `openpatch onboard` first.",
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
  const workerRunning = await isWorkerProcessRunning(runtimeState);
  const workerHealth = await checkWorkerHealth(config.worker?.baseUrl || DEFAULT_WORKER_URL);
  const urlMatches =
    Boolean(runtimeState?.workerUrl) &&
    runtimeState.workerUrl === (config.worker?.baseUrl || DEFAULT_WORKER_URL);

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
      workerRunning.message,
    ),
  );
  checks.push(
    makeCheck(
      "Local worker reachable",
      workerHealth.reachable,
      workerHealth.message,
    ),
  );
  checks.push(
    makeCheck(
      "Configured worker URL matches runtime state",
      urlMatches,
      urlMatches
        ? `Configured URL matches ${runtimeState.workerUrl}.`
        : `Configured URL is '${config.worker?.baseUrl || DEFAULT_WORKER_URL}', runtime state is '${runtimeState?.workerUrl || "not available"}'.`,
    ),
  );
  checks.push(
    makeCheck(
      "Model provider config present",
      Boolean(
        config.model?.provider &&
          config.model?.baseUrl &&
          config.model?.model &&
          hasRequiredModelFields(config.model),
      ),
      config.model?.provider
        ? `Configured provider: ${formatModelSummary(config.model)}`
        : "Expected a model provider plus its required fields.",
    ),
  );
  checks.push(
    makeCheck(
      "Git provider config present",
      Boolean(config.gitProvider?.provider && config.gitProvider.provider !== "none"),
      "Expected a selected git provider in the local config.",
    ),
  );

  printChecks(checks);
  if (checks.some((check) => !check.ok)) {
    process.exitCode = 1;
  }
}

async function runStatus() {
  const configExists = await fileExists(CONFIG_PATH);
  if (!configExists) {
    console.log("OpenPatch is not configured yet.");
    console.log("Run `openpatch onboard` to create the local configuration.");
    process.exitCode = 1;
    return;
  }

  const config = await readConfig();
  const runtimeState = await readState();
  const workerRunning = await isWorkerProcessRunning(runtimeState);
  const workerHealth = await checkWorkerHealth(config.worker?.baseUrl || DEFAULT_WORKER_URL);

  console.log("OpenPatch status");
  console.log("");
  console.log(`Config file: ${CONFIG_PATH}`);
  console.log(`Configured worker URL: ${config.worker?.baseUrl || DEFAULT_WORKER_URL}`);
  console.log(`Worker install mode: ${config.worker?.installMode || "unknown"}`);
  console.log(`Worker detected path: ${config.worker?.detectedPath || "not detected"}`);
  console.log(`Worker process running: ${workerRunning.running ? "yes" : "no"}`);
  console.log(`Worker process detail: ${workerRunning.message}`);
  console.log(`Worker reachable: ${workerHealth.reachable ? "yes" : "no"}`);
  console.log(`Worker health detail: ${workerHealth.message}`);
  console.log(`Worker log file: ${runtimeState?.logPath || WORKER_LOG_PATH}`);
  console.log(`Model provider: ${config.model?.provider || "not configured"}`);
  console.log(`Model summary: ${formatModelSummary(config.model)}`);
  console.log(`Selected git provider: ${formatProviderSummary(config.gitProvider)}`);
  console.log(`Local repo base dir: ${config.localRepoBaseDir || "not configured"}`);
  console.log(`Daemon prepared: ${config.daemon?.prepared ? "yes" : "no"}`);
}

async function startWorker({ interactive }) {
  await ensureBaseDirectories();
  const config = await requireConfig();
  const workerInstallation = await resolveWorkerInstallation(config, process.cwd());
  const runtimeState = await readState();
  const running = await isWorkerProcessRunning(runtimeState);

  if (running.running) {
    if (interactive) {
      console.log(`The local worker is already running. ${running.message}`);
    }
    return;
  }

  if (!workerInstallation.installed || !workerInstallation.detectedPath) {
    throw new Error(
      "Local worker not installed. OpenPatch could not find apps/local-worker in the current repository tree.",
    );
  }

  const workerRuntime = await resolveWorkerRuntime(workerInstallation.detectedPath);
  await ensureLogFileExists(WORKER_LOG_PATH);
  const logStream = fs.openSync(WORKER_LOG_PATH, "a");

  const env = {
    ...process.env,
    LOCAL_REPO_BASE_DIR: config.localRepoBaseDir || DEFAULT_REPO_BASE_DIR,
    OPENAI_BASE_URL: config.model?.baseUrl || "",
    OPENAI_API_KEY: config.model?.apiKey || "",
    OPENAI_MODEL: config.model?.model || "",
  };

  if (config.gitProvider?.provider === "gitlab") {
    if (config.gitProvider.baseUrl) {
      env.GITLAB_BASE_URL = config.gitProvider.baseUrl;
    }
  }

  const child = spawn(
    workerRuntime.pythonPath,
    [
      "-m",
      "uvicorn",
      "openpatch_worker.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
    ],
    {
      cwd: workerInstallation.detectedPath,
      detached: true,
      stdio: ["ignore", logStream, logStream],
      env,
    },
  );

  child.unref();

  await writeJson(STATE_PATH, {
    preparedAt: runtimeState?.preparedAt || new Date().toISOString(),
    startedAt: new Date().toISOString(),
    status: "running",
    pid: child.pid,
    workerUrl: config.worker?.baseUrl || DEFAULT_WORKER_URL,
    logPath: WORKER_LOG_PATH,
    installMode: workerInstallation.installMode,
    workerPath: workerInstallation.detectedPath,
    pythonPath: workerRuntime.pythonPath,
  });

  const startupHealth = await waitForWorkerHealth(config.worker?.baseUrl || DEFAULT_WORKER_URL, 12_000);
  if (!startupHealth.reachable) {
    await safeStopWorkerProcess(child.pid);
    await writeJson(STATE_PATH, {
      ...(await readState()),
      status: "failed",
      failedAt: new Date().toISOString(),
      lastError: startupHealth.message,
    });
    throw new Error(
      `Worker startup failed. ${startupHealth.message} Check logs with \`openpatch worker logs\`.`,
    );
  }

  if (interactive) {
    console.log("OpenPatch local worker started.");
    console.log(`Worker URL: ${config.worker?.baseUrl || DEFAULT_WORKER_URL}`);
    console.log(`Logs: ${WORKER_LOG_PATH}`);
  }
}

async function stopWorker({ interactive }) {
  const runtimeState = await readState();
  const running = await isWorkerProcessRunning(runtimeState);

  if (!runtimeState?.pid || !running.running) {
    if (interactive) {
      console.log("The local worker is not currently running.");
    }
    await writeJson(STATE_PATH, {
      ...(runtimeState || {}),
      status: "stopped",
      stoppedAt: new Date().toISOString(),
    });
    return;
  }

  await safeStopWorkerProcess(runtimeState.pid);
  await writeJson(STATE_PATH, {
    ...runtimeState,
    status: "stopped",
    stoppedAt: new Date().toISOString(),
  });

  if (interactive) {
    console.log("OpenPatch local worker stopped.");
  }
}

async function restartWorker() {
  await stopWorker({ interactive: false });
  await startWorker({ interactive: false });
  console.log("OpenPatch local worker restarted.");
}

async function showWorkerLogs() {
  const state = await readState();
  const logPath = state?.logPath || WORKER_LOG_PATH;

  if (!(await fileExists(logPath))) {
    throw new Error(`Worker log file not found at ${logPath}`);
  }

  const logContent = await fsp.readFile(logPath, "utf-8");
  console.log(`OpenPatch worker logs: ${logPath}`);
  console.log("");
  process.stdout.write(logContent || "(log file is empty)\n");
}

async function ensureBaseDirectories() {
  await fsp.mkdir(CONFIG_DIR, { recursive: true });
  await fsp.mkdir(DAEMON_DIR, { recursive: true });
  await fsp.mkdir(RUN_DIR, { recursive: true });
  await fsp.mkdir(LOG_DIR, { recursive: true });
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

async function checkWorkerHealth(baseUrl) {
  try {
    const response = await fetch(`${baseUrl}/health`);
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
    const message = error instanceof Error ? error.message : String(error);
    return {
      reachable: false,
      message: `Worker is not reachable at ${baseUrl}: ${message}`,
    };
  }
}

async function waitForWorkerHealth(baseUrl, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const health = await checkWorkerHealth(baseUrl);
    if (health.reachable) {
      return health;
    }
    await sleep(500);
  }
  return {
    reachable: false,
    message: `Worker did not become healthy at ${baseUrl} within ${Math.round(timeoutMs / 1000)} seconds.`,
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
    return { provider: "gitlab", baseUrl };
  }

  if (provider === "github") {
    const baseUrl = await promptWithDefault(
      rl,
      "GitHub base URL",
      "https://github.com",
    );
    return { provider: "github", baseUrl };
  }

  return { provider: "none" };
}

async function promptModelConfig(rl) {
  const provider = await promptModelProvider(rl);
  const providerConfig = MODEL_PROVIDER_CONFIG[provider];

  console.log("");
  console.log(`Model provider: ${providerConfig.label}`);
  console.log("OpenPatch will use these settings when the local worker calls your centralized model backend.");

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
    provider,
    baseUrl,
    apiKey,
    model,
  };
}

async function promptModelProvider(rl) {
  while (true) {
    console.log("Choose a model provider:");
    console.log("  1. OpenAI");
    console.log("  2. Anthropic");
    console.log("  3. Gemini");
    console.log("  4. Ollama");
    console.log("  5. OpenAI-compatible");
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "openai";
    }
    if (answer === "2") {
      return "anthropic";
    }
    if (answer === "3") {
      return "gemini";
    }
    if (answer === "4") {
      return "ollama";
    }
    if (answer === "5") {
      return "openai-compatible";
    }
    console.log("Please choose 1, 2, 3, 4, or 5.");
  }
}

async function promptGitProvider(rl) {
  while (true) {
    console.log("Select a git provider:");
    console.log("  1. GitLab");
    console.log("  2. GitHub");
    console.log("  3. None for now");
    const answer = (await rl.question("Choice [1]: ")).trim() || "1";

    if (answer === "1") {
      return "gitlab";
    }
    if (answer === "2") {
      return "github";
    }
    if (answer === "3") {
      return "none";
    }
    console.log("Please choose 1, 2, or 3.");
  }
}

async function promptWithDefault(rl, label, defaultValue) {
  const suffix = defaultValue ? ` [${defaultValue}]` : "";
  const answer = await rl.question(`${label}${suffix}: `);
  const trimmed = answer.trim();
  return trimmed || defaultValue;
}

async function showConfig() {
  const config = await requireConfig();
  console.log("OpenPatch config");
  console.log("");
  console.log(JSON.stringify(redactConfig(config), null, 2));
}

async function requireConfig() {
  if (!(await fileExists(CONFIG_PATH))) {
    throw new Error("OpenPatch is not configured yet. Run `openpatch onboard` first.");
  }
  return readConfig();
}

async function readConfig() {
  const raw = await fsp.readFile(CONFIG_PATH, "utf-8");
  return normalizeConfig(JSON.parse(raw));
}

async function readState() {
  if (!(await fileExists(STATE_PATH))) {
    return null;
  }
  const raw = await fsp.readFile(STATE_PATH, "utf-8");
  return JSON.parse(raw);
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
      message: "No worker pid is recorded in the local runtime state.",
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

async function safeStopWorkerProcess(pid) {
  try {
    process.kill(-pid, "SIGTERM");
  } catch {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      return;
    }
  }

  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    try {
      process.kill(pid, 0);
      await sleep(200);
    } catch {
      return;
    }
  }

  try {
    process.kill(-pid, "SIGKILL");
  } catch {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      return;
    }
  }
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
    return "not configured";
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
  return `${modelConfig.provider} | ${modelConfig.model} | ${modelConfig.baseUrl}`;
}

function hasRequiredModelFields(modelConfig) {
  if (!modelConfig?.provider || !MODEL_PROVIDER_OPTIONS.includes(modelConfig.provider)) {
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
    return config;
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

function printChecks(checks) {
  console.log("OpenPatch doctor");
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
  console.log("OpenPatch CLI");
  console.log("");
  console.log("Usage:");
  console.log("  openpatch config show");
  console.log("  openpatch onboard");
  console.log("  openpatch doctor");
  console.log("  openpatch status");
  console.log("  openpatch worker start");
  console.log("  openpatch worker stop");
  console.log("  openpatch worker restart");
  console.log("  openpatch worker logs");
}

module.exports = {
  runCli,
};
