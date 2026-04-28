const tty = Boolean(process.stdout.isTTY);
const noColor = Boolean(process.env.NO_COLOR);

const codes = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  cyan: "\x1b[36m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  red: "\x1b[31m",
  blue: "\x1b[34m",
  gray: "\x1b[90m",
};

function color(value, code) {
  if (!tty || noColor || !code) {
    return value;
  }
  return `${code}${value}${codes.reset}`;
}

const style = {
  bold: (value) => color(value, codes.bold),
  dim: (value) => color(value, codes.dim),
  cyan: (value) => color(value, codes.cyan),
  green: (value) => color(value, codes.green),
  yellow: (value) => color(value, codes.yellow),
  red: (value) => color(value, codes.red),
  blue: (value) => color(value, codes.blue),
  gray: (value) => color(value, codes.gray),
};

const symbol = {
  success: style.green("✓"),
  warning: style.yellow("!"),
  error: style.red("×"),
  info: style.cyan("→"),
  pending: style.blue("•"),
};

function terminalWidth() {
  return Math.max(40, Math.min(process.stdout.columns || 88, 100));
}

function visibleLength(value) {
  return value.replace(/\x1b\[[0-9;]*m/g, "").length;
}

function padRight(value, width) {
  const length = visibleLength(value);
  if (length >= width) {
    return value;
  }
  return `${value}${" ".repeat(width - length)}`;
}

function wrapLine(value, width) {
  const words = String(value).split(/\s+/).filter(Boolean);
  const lines = [];
  let current = "";

  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (visibleLength(next) > width && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }

  if (current) {
    lines.push(current);
  }
  return lines.length ? lines : [""];
}

function box({ title, subtitle, lines = [], width = terminalWidth() - 2 }) {
  const innerWidth = Math.max(30, width - 4);
  const top = `╭${"─".repeat(innerWidth + 2)}╮`;
  const bottom = `╰${"─".repeat(innerWidth + 2)}╯`;
  const body = [];

  if (title) {
    body.push(`│ ${padRight(style.bold(title), innerWidth)} │`);
  }
  if (subtitle) {
    for (const line of wrapLine(subtitle, innerWidth)) {
      body.push(`│ ${padRight(style.dim(line), innerWidth)} │`);
    }
  }
  if ((title || subtitle) && lines.length) {
    body.push(`│ ${" ".repeat(innerWidth)} │`);
  }
  for (const line of lines) {
    for (const wrapped of wrapLine(line, innerWidth)) {
      body.push(`│ ${padRight(wrapped, innerWidth)} │`);
    }
  }

  return [top, ...body, bottom].join("\n");
}

function banner() {
  if (terminalWidth() < 72) {
    return `${style.cyan(style.bold("RepoOperator"))}\n${style.dim("Local-first repository assistant for teams and companies.")}`;
  }

  const logo = [
    "  ____                  ___                       _             ",
    " |  _ \\ ___ _ __   ___ / _ \\ _ __   ___ _ __ __ _| |_ ___  _ __ ",
    " | |_) / _ \\ '_ \\ / _ \\ | | | '_ \\ / _ \\ '__/ _` | __/ _ \\| '__|",
    " |  _ <  __/ |_) | (_) | |_| | |_) |  __/ | | (_| | || (_) | |   ",
    " |_| \\_\\___| .__/ \\___/ \\___/| .__/ \\___|_|  \\__,_|\\__\\___/|_|   ",
    "           |_|               |_|                                  ",
  ];
  return `${style.cyan(logo.join("\n"))}\n${style.dim("Local-first repository assistant for teams and companies.")}`;
}

function heading(step, title, detail) {
  const prefix = step ? `${style.cyan(step)} ` : "";
  console.log("");
  console.log(`${prefix}${style.bold(title)}`);
  if (detail) {
    console.log(style.dim(detail));
  }
  console.log(style.gray("─".repeat(Math.min(terminalWidth() - 2, 76))));
}

function line(kind, label, detail) {
  const icons = {
    success: symbol.success,
    warning: symbol.warning,
    error: symbol.error,
    info: symbol.info,
    pending: symbol.pending,
  };
  const icon = icons[kind] || symbol.info;
  console.log(`${icon} ${style.bold(label)}${detail ? ` ${style.dim(detail)}` : ""}`);
}

function summaryBox(title, rows, subtitle) {
  const lines = rows.map((row) => {
    if (Array.isArray(row)) {
      const [label, value] = row;
      return `${label}: ${value}`;
    }
    return row;
  });
  console.log(box({ title, subtitle, lines }));
}

function table(headers, rows) {
  const widths = headers.map((header, index) => {
    const rowMax = rows.reduce(
      (max, row) => Math.max(max, visibleLength(String(row[index] ?? ""))),
      visibleLength(header),
    );
    return Math.min(Math.max(rowMax, 8), 36);
  });

  const renderRow = (row) =>
    row
      .map((cell, index) => padRight(String(cell ?? ""), widths[index]))
      .join("  ");

  console.log(style.dim(renderRow(headers)));
  console.log(style.gray(widths.map((width) => "─".repeat(width)).join("  ")));
  for (const row of rows) {
    console.log(renderRow(row));
  }
}

async function spinner(label, task) {
  if (!tty) {
    console.log(`${symbol.info} ${label}`);
    const result = await task();
    console.log(`${symbol.success} ${label}`);
    return result;
  }

  const frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
  let index = 0;
  process.stdout.write(`${style.cyan(frames[index])} ${label}`);
  const timer = setInterval(() => {
    index = (index + 1) % frames.length;
    process.stdout.write(`\r${style.cyan(frames[index])} ${label}`);
  }, 80);

  try {
    const result = await task();
    clearInterval(timer);
    process.stdout.write(`\r${symbol.success} ${label}\n`);
    return result;
  } catch (error) {
    clearInterval(timer);
    process.stdout.write(`\r${symbol.error} ${label}\n`);
    throw error;
  }
}

module.exports = {
  banner,
  box,
  heading,
  line,
  spinner,
  style,
  summaryBox,
  symbol,
  table,
};
