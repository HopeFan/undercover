import { Link } from "react-router";
import { api, type Status } from "../api";
import { DecisionChip, StatusChip } from "../components/Chips";
import { Message } from "../components/Message";
import { date, label, money, statusLabels } from "../format";
import { REFRESH_MS, useLoad } from "../useLoad";

const states: Status[] = [
  "waiting",
  "in_progress",
  "waiting_for_sign_off",
  "decided",
  "left_for_handler",
];

export function QueuePage() {
  const { data: claims, error } = useLoad(api.listClaims, REFRESH_MS);
  if (!claims) return <Message error={error} />;

  return (
    <>
      <h1>Claims queue</h1>
      <section className="tiles" aria-label="Claims by state">
        {states.map((status) => {
          const count = claims.filter((c) => c.status === status).length;
          return (
            <div
              className="panel tile"
              key={status}
              aria-label={`${statusLabels[status]}: ${String(count)}`}
            >
              <StatusChip status={status} />
              <span className="tile-count mono">{count}</span>
            </div>
          );
        })}
      </section>
      <section className="panel table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Claim</th>
              <th>Customer</th>
              <th>Type</th>
              <th>Summary</th>
              <th className="num">Claimed</th>
              <th>Submitted</th>
              <th>State</th>
              <th>Decision</th>
              <th className="num">Payout</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((claim) => (
              <tr key={claim.claim_id}>
                <td className="nowrap">
                  <Link className="mono" to={`/claims/${claim.claim_id}`}>
                    {claim.claim_id}
                  </Link>
                </td>
                <td>{claim.customer_name}</td>
                <td>{label(claim.claim_type)}</td>
                <td>{claim.summary}</td>
                <td className="num mono">{money(claim.amount_claimed)}</td>
                <td className="nowrap">{date(claim.submitted_on)}</td>
                <td>
                  <StatusChip status={claim.status} />
                </td>
                <td>
                  {claim.decision && <DecisionChip decision={claim.decision} />}
                </td>
                <td className="num mono">
                  {claim.payout !== null && money(claim.payout)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
