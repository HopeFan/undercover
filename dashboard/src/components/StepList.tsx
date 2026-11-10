import { useCallback } from "react";
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
  if (step.kind === "read") {
    const [heading, ...text] = step.content.split("\n\n");
    return (
      <details>
        <summary>
          <span className="step-label">Read</span> {heading}
        </summary>
        <pre className="step-result">{text.join("\n\n")}</pre>
      </details>
    );
  }
  if (step.kind === "tool_result") {
    const summary =
      step.content.length > SUMMARY_LENGTH
        ? `${step.content.slice(0, SUMMARY_LENGTH)}...`
        : step.content;
    return (
      <details>
        <summary>
          <span className="step-label">Result</span>{" "}
          <code className="mono">{summary}</code>
        </summary>
        <pre className="step-result">{step.content}</pre>
      </details>
    );
  }
  return (
    <p>
      <span className="step-label">Agent</span> {step.content}
    </p>
  );
}
