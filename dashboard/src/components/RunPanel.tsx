import { api, type Run } from "../api";
import { time, todoLabels } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";
import { Message } from "./Message";

export function RunPanel() {
  const { data: run, error } = useLoad(api.getCurrentRun, REFRESH_MS);

  return (
    <section className="panel run" aria-labelledby="run-title">
      <h2 id="run-title">Current run</h2>
      {run === undefined && <Message error={error} />}
      {run === null && (
        <p className="muted">
          No run yet. They start from the command line, with{" "}
          <code className="mono">uv run -m agent</code>.
        </p>
      )}
      {run && <RunDetails run={run} />}
    </section>
  );
}

function RunDetails({ run }: Readonly<{ run: Run }>) {
  const when = run.finished_at
    ? `Finished at ${time(run.finished_at)}`
    : `Running since ${time(run.started_at)}`;
  const cap = `up to ${String(run.cap)} ${run.cap === 1 ? "claim" : "claims"}`;
  const done = run.todos.filter((todo) => todo.status === "done").length;
  const progress =
    run.todos.length > 0
      ? ` ${String(done)} of ${String(run.todos.length)} done.`
      : "";
  return (
    <>
      <p className="muted">{`${when}, ${cap}.${progress}`}</p>
      {run.todos.length === 0 ? (
        <p className="muted">The agent hasn't planned its work yet.</p>
      ) : (
        <ol className="todos" aria-label="The agent's to-do list">
          {run.todos.map((todo, index) => (
            <li key={`${String(index)}-${todo.content}`}>
              <span className={`chip todo-${todo.status}`}>
                {todoLabels[todo.status]}
              </span>
              <span>{todo.content}</span>
            </li>
          ))}
        </ol>
      )}
      {run.summary && (
        <>
          <h3>Summary</h3>
          <p className="summary">{run.summary}</p>
        </>
      )}
    </>
  );
}
