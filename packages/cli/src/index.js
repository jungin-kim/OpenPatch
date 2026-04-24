const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
const readline = require("node:readline/promises");
const { stdin, stdout } = require("node:process");

const CONFIG_DIR = path.join(os.homedir(), ".openpatch");
const CONFIG_PATH = path.join(CONFIG_DIR, "config.json");
const DAEMON_DIR = path.join(CONFIG_DIR, "daemon");
const RUN_DIR = path.join(CONFIG_DIR, "run");
const LOG_DIR = path.join(CONFIG_DIR, "logs");
const DEFAULT_WORKER_URL = "http://127.0.0.1:8000";
const DEFAULT_MODEL_BASE_URL = "https://api.openai.com/v1";
const DEFAULT_MODEL = "gpt-4.1-mini";
const DEFAULT_REPO_BASE_DIR = path.join(os.homedir(), ".openpatch", "repos");

async function runCli() {
  const command = process.argv[2];

  switch (command) {
    case "onboard":
      await runOnboard();
      return;
    case "doctor":
      await runDoctor();
      return;
    case "status":
      await runStatus();
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

async function runOnboard() {
  await ensureBaseDirectories();
  const rl = readline.createInterface({ input: stdin, output: stdout });

  try {
    console.log("OpenPatch onboarding");
    console.log("This will create your local OpenPatch configuration and prepare your machine for a future worker daemon install.");
    console.log("");

    const modelBaseUrl = await promptWithDefault(
      rl,
      "Model API base URL",
      DEFAULT_MODEL_BASE_URL,
    );
    const modelApiKey = await promptWithDefault(
      rl,
      "Model API key",
      "",
    );
    const modelName = await promptWithDefault(rl, "Model name", DEFAULT_MODEL);
    const gitProvider = await promptGitProvider(rl);
    const localRepoBaseDir = await promptWithDefault(
      rl,
      "Local repository base directory",
      DEFAULT_REPO_BASE_DIR,
    );

    const workerDetection = await detectLocalWorkerInstallation(process.cwd());
    const config = {
      version: 1,
      createdAt: new Date().toISOString(),
      worker: {
        baseUrl: DEFAULT_WORKER_URL,
        installed: workerDetection.installed,
        installMode: workerDetection.installMode,
        detectedPath: workerDetection.detectedPath,
      },
      modelBackend: {
        provider: "openai-compatible",
        baseUrl: modelBaseUrl,
        apiKey: modelApiKey,
        model: modelName,
      },
      gitProvider: buildGitProviderConfig(gitProvider),
      localRepoBaseDir,
      daemon: {
        prepared: true,
        runDirectory: RUN_DIR,
        logDirectory: LOG_DIR,
        stateFile: path.join(DAEMON_DIR, "state.json"),
        launchStrategy: workerDetection.installed ? "repo-source" : "pending-install",
      },
    };

    await writeJson(CONFIG_PATH, config);
    await writeJson(path.join(DAEMON_DIR, "state.json"), {
      preparedAt: new Date().toISOString(),
      expectedWorkerUrl: DEFAULT_WORKER_URL,
      installMode: workerDetection.installMode,
      workerDetected: workerDetection.installed,
    });

    console.log("");
    console.log("OpenPatch is now configured.");
    console.log(`Config file: ${CONFIG_PATH}`);
    console.log(`Worker detection: ${workerDetection.summary}`);
    console.log("Next step: run `openpatch doctor` to validate the setup.");
  } finally {
    rl.close();
  }
}

async function runDoctor() {
  const checks = [];
  const configExists = await fileExists(CONFIG_PATH);
  checks.push(makeCheck("Config file exists", configExists, configExists ? CONFIG_PATH : "Run `openpatch onboard` first."));

  if (!configExists) {
    printChecks(checks);
    process.exitCode = 1;
    return;
  }

  const config = await readConfig();
  const workerDetection = await detectLocalWorkerInstallation(process.cwd());
  const workerHealth = await checkWorkerHealth(config.worker?.baseUrl || DEFAULT_WORKER_URL);

  checks.push(
    makeCheck(
      "Local worker installation detected",
      workerDetection.installed,
      workerDetection.summary,
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
      "Model backend config present",
      Boolean(
        config.modelBackend?.baseUrl &&
          config.modelBackend?.apiKey &&
          config.modelBackend?.model,
      ),
      "Expected model base URL, API key, and model name.",
    ),
  );
  checks.push(
    makeCheck(
      "Git provider config present",
      Boolean(config.gitProvider?.provider),
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
  const workerHealth = await checkWorkerHealth(config.worker?.baseUrl || DEFAULT_WORKER_URL);

  console.log("OpenPatch status");
  console.log("");
  console.log(`Config file: ${CONFIG_PATH}`);
  console.log(`Worker URL: ${config.worker?.baseUrl || DEFAULT_WORKER_URL}`);
  console.log(`Worker install mode: ${config.worker?.installMode || "unknown"}`);
  console.log(`Worker reachable: ${workerHealth.reachable ? "yes" : "no"}`);
  console.log(`Worker detail: ${workerHealth.message}`);
  console.log(`Model provider: ${config.modelBackend?.provider || "not configured"}`);
  console.log(`Model base URL: ${config.modelBackend?.baseUrl || "not configured"}`);
  console.log(`Model name: ${config.modelBackend?.model || "not configured"}`);
  console.log(`Git provider: ${config.gitProvider?.provider || "not configured"}`);
  if (config.gitProvider?.baseUrl) {
    console.log(`Git provider base URL: ${config.gitProvider.baseUrl}`);
  }
  console.log(`Local repo base dir: ${config.localRepoBaseDir || "not configured"}`);
  console.log(`Daemon prepared: ${config.daemon?.prepared ? "yes" : "no"}`);
}

async function ensureBaseDirectories() {
  await fs.mkdir(CONFIG_DIR, { recursive: true });
  await fs.mkdir(DAEMON_DIR, { recursive: true });
  await fs.mkdir(RUN_DIR, { recursive: true });
  await fs.mkdir(LOG_DIR, { recursive: true });
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

function buildGitProviderConfig(provider) {
  if (provider === "gitlab") {
    return { provider: "gitlab" };
  }
  if (provider === "github") {
    return { provider: "github" };
  }
  return { provider: "none" };
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

async function readConfig() {
  const raw = await fs.readFile(CONFIG_PATH, "utf-8");
  return JSON.parse(raw);
}

async function writeJson(filePath, value) {
  await fs.writeFile(filePath, JSON.stringify(value, null, 2) + "\n", "utf-8");
}

async function fileExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function makeCheck(name, ok, detail) {
  return { name, ok, detail };
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
  console.log("  openpatch onboard");
  console.log("  openpatch doctor");
  console.log("  openpatch status");
}

module.exports = {
  runCli,
};
