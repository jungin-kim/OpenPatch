"use client";

export type ProgressStep = {
  node: string;
  message: string;
};

type Props = {
  steps: ProgressStep[];
  done: boolean;
};

const NODE_ICONS: Record<string, string> = {
  load_context: "📂",
  classify_intent: "🔍",
  resolve_target_files: "🎯",
  generate_change_plan: "📝",
  generate_patch: "⚡",
  validate_patch: "✅",
  return_proposal: "📋",
  answer_read_only: "💬",
  ask_clarification: "❓",
  recommend_change_targets: "📌",
  run_local_tool_request: "🛠",
  run_local_command_request: "⚙️",
  permission_required: "🔒",
  proposal_error: "⚠️",
};

export function ProgressTimeline({ steps, done }: Props) {
  if (steps.length === 0) return null;

  return (
    <div className="progress-timeline">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1;
        const isActive = isLast && !done;
        return (
          <span
            key={`${step.node}-${i}`}
            className={`progress-step${isActive ? " progress-step-active" : ""}`}
          >
            <span className="progress-step-icon">{NODE_ICONS[step.node] ?? "▸"}</span>
            {step.message}
          </span>
        );
      })}
    </div>
  );
}
