"use client";

export type ProgressStep = {
  node: string;
  phase?: string;
  message: string;
  status?: string;
  elapsedMs?: number;
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
          <div
            key={`${step.node}-${i}`}
            className={`progress-step${isActive ? " progress-step-active" : ""}`}
          >
            <span className="progress-step-icon">{NODE_ICONS[step.node] ?? "▸"}</span>
            <span className="progress-step-content">
              <span className="progress-step-phase">{step.phase || step.node}</span>
              <span>{step.message}</span>
            </span>
            {step.elapsedMs !== undefined ? (
              <span className="progress-step-time">{(step.elapsedMs / 1000).toFixed(1)}s</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
