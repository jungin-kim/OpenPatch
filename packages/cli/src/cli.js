const { runCli } = require("./index");

runCli().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`RepoOperator CLI error: ${message}`);
  process.exit(1);
});
