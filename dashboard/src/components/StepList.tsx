import { type ReactNode, useCallback } from "react";
import { api, type Step } from "../api";
import { time } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";
import { Message } from "./Message";

const SUMMARY_LENGTH = 90;

export function StepList({ claimId }: Readonly<{ claimId: string }>) {
  const load = useCallback(() => api.listSteps(claimId), [claimId]);
  const { data: steps, error } = useLoad(load, REFRESH_MS);

  return (
    <section className="panel" aria-labelledby="steps-title">
      <h2 id="steps-title">Agent at work</h2>
      {!steps && <Message error={error} />}
      {steps?.length === 0 && (
        <p className="muted">
          No steps yet. They appear here as the agent works.
        </p>
      )}
      {steps && steps.length > 0 && (
        <ol className="steps">
          {steps.map((step) => (
            <li key={step.step_id} className={`step step-${step.kind}`}>
              <span className="step-time small muted">
                {time(step.created_at)}
              </span>
              <StepBody step={step} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function StepBody({ step }: Readonly<{ step: Step }>) {
  if (step.kind === "tool_call")
    return (
      <p>
        <span className="step-label">Called</span>{" "}
        <code className="mono">{step.content}</code>
      </p>
    );
  if (step.kind === "error")
    return (
      <p>
        <span className="chip step-failed">Failed</span> {step.content}
      </p>
    );
  if (step.kind === "read") {
    const [heading, ...text] = step.content.split("\n\n");
    return <Folded label="Read" summary={heading} text={text.join("\n\n")} />;
  }
  if (step.kind === "tool_result") {
    const summary =
      step.content.length > SUMMARY_LENGTH
        ? `${step.content.slice(0, SUMMARY_LENGTH)}...`
        : step.content;
    return (
      <Folded
        label="Result"
        summary={<code className="mono">{summary}</code>}
        text={step.content}
      />
    );
  }
  return (
    <p>
      <span className="step-label">Agent</span> {step.content}
    </p>
  );
}

function Folded({
  label,
  summary,
  text,
}: Readonly<{ label: string; summary: ReactNode; text: string }>) {
  return (
    <details>
      <summary>
        <span className="step-label">{label}</span> {summary}
      </summary>
      <pre className="step-result">{text}</pre>
    </details>
  );
}
