/**
 * Regression net for the interactive-prompt helpers and the startup-failure
 * copy added in 0.15.0 (CLI onboarding UX + error messages).
 *
 * These guard the two things that are easy to silently break:
 *   1. Secrets typed at `onboard` must never echo to the terminal in plaintext.
 *   2. Invalid URLs / empty required fields must be re-asked, not stored.
 *
 * Run with:  npm --prefix packages/cli test
 */
const test = require("node:test");
const assert = require("node:assert");
const readline = require("node:readline/promises");
const { PassThrough } = require("node:stream");

const {
  promptSecret,
  promptUrl,
  promptRequired,
  isValidHttpUrl,
  describeStartupFailureAction,
} = require("../src/index.js");

function makeRl() {
  const input = new PassThrough();
  const output = new PassThrough();
  let captured = "";
  output.on("data", (c) => {
    captured += c.toString();
  });
  const rl = readline.createInterface({ input, output, terminal: true });
  return { rl, input, output, getCaptured: () => captured };
}

// Write lines into the readline input across ticks so terminal-mode readline
// processes them the way a real TTY would.
function feedLines(input, lines) {
  let i = 0;
  const next = () => {
    if (i >= lines.length) return;
    input.write(lines[i++] + "\n");
    setImmediate(next);
  };
  setImmediate(next);
}

test("isValidHttpUrl accepts http/https and rejects everything else", () => {
  assert.equal(isValidHttpUrl("http://localhost:11434/v1"), true);
  assert.equal(isValidHttpUrl("https://api.openai.com/v1"), true);
  assert.equal(isValidHttpUrl("not a url"), false);
  assert.equal(isValidHttpUrl("ftp://example.com"), false);
  assert.equal(isValidHttpUrl("localhost:11434"), false);
  assert.equal(isValidHttpUrl(""), false);
  assert.equal(isValidHttpUrl(null), false);
});

test("promptSecret returns the typed value but never echoes it in plaintext", async () => {
  const { rl, input, getCaptured } = makeRl();
  feedLines(input, ["sk-supersecret"]);
  const value = await promptSecret(rl, "API key", "");
  rl.close();
  assert.equal(value, "sk-supersecret");
  const captured = getCaptured();
  assert.ok(!captured.includes("sk-supersecret"), "secret leaked to terminal output");
  assert.ok(captured.includes("•"), "expected masked bullets in output");
});

test("promptSecret keeps the stored value when the user presses Enter", async () => {
  const { rl, input } = makeRl();
  feedLines(input, [""]);
  const value = await promptSecret(rl, "API key", "existing-token");
  rl.close();
  assert.equal(value, "existing-token");
});

test("promptUrl re-asks on an invalid URL then accepts a valid one", async () => {
  const { rl, input } = makeRl();
  feedLines(input, ["bogus", "http://localhost:8000"]);
  const value = await promptUrl(rl, "Base URL", "");
  rl.close();
  assert.equal(value, "http://localhost:8000");
});

test("promptUrl accepts the default on empty input", async () => {
  const { rl, input } = makeRl();
  feedLines(input, [""]);
  const value = await promptUrl(rl, "Base URL", "http://localhost:11434/v1");
  rl.close();
  assert.equal(value, "http://localhost:11434/v1");
});

test("promptRequired re-asks on empty input then accepts a value", async () => {
  const { rl, input } = makeRl();
  feedLines(input, ["", "gpt-4o"]);
  const value = await promptRequired(rl, "Model name", "");
  rl.close();
  assert.equal(value, "gpt-4o");
});

test("describeStartupFailureAction gives a cause and an action per failure type", () => {
  const port = describeStartupFailureAction("port_in_use", { workerUrl: "http://localhost:8000", kind: "worker" });
  assert.match(port.cause, /in use/i);
  assert.match(port.action, /onboard/);

  const imp = describeStartupFailureAction("import_failure", { kind: "worker" });
  assert.match(imp.cause, /import/i);
  assert.match(imp.action, /reinstall/i);

  const timeout = describeStartupFailureAction("health_timeout", { kind: "web", webUrl: "http://localhost:3000" });
  assert.match(timeout.cause, /healthy/i);

  const exited = describeStartupFailureAction("process_exited", { kind: "worker" });
  assert.match(exited.cause, /exited/i);
});
