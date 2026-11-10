import { api } from "../api";
import { Message } from "../components/Message";
import { useLoad } from "../useLoad";

export function InstructionsPage() {
  const { data, error } = useLoad(api.getInstructions);

  return (
    <>
      <h1>Agent instructions</h1>
      <p className="lead">
        What the agent reads before it runs the queue, and before each claim
        agent works a claim. It looks up the sections of the policy wording and
        the claims manual it needs as it goes. This page is read only.
      </p>
      {data ? (
        <>
          <section className="panel instructions-panel">
            <h2>Running the queue</h2>
            <pre className="instructions">{data.queue}</pre>
          </section>
          <section className="panel instructions-panel">
            <h2>Working a claim</h2>
            <pre className="instructions">{data.claim}</pre>
          </section>
        </>
      ) : (
        <Message error={error} />
      )}
    </>
  );
}
