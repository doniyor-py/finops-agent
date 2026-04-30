/**
 * Invoice queue — sorts by tier severity, applies optional filtering.
 */

import { useMemo, useState } from "react";
import { InvoiceCard } from "./InvoiceCard.jsx";

const TIER_RANK = { HARD_BLOCK: 0, ESCALATE: 1, AUTO: 2 };

function rankInvoice(inv) {
  const tier = inv.autonomy_tier;
  if (tier && TIER_RANK[tier] !== undefined) return TIER_RANK[tier];
  if (inv.aml_result?.hard_block_required) return TIER_RANK.HARD_BLOCK;
  return 3;
}

export function InvoiceQueue({ invoices, onApprove, onBlock, onMarkPaid, onAmlOpen }) {
  const [filter, setFilter] = useState("all");

  const sorted = useMemo(() => {
    const list = (invoices || []).slice();
    list.sort((a, b) => {
      const r = rankInvoice(a) - rankInvoice(b);
      if (r !== 0) return r;
      return Number(b.amount ?? b.amount_gbp ?? 0) - Number(a.amount ?? a.amount_gbp ?? 0);
    });
    if (filter === "all") return list;
    if (filter === "auto") return list.filter((i) => i.autonomy_tier === "AUTO");
    if (filter === "escalate") return list.filter((i) => i.autonomy_tier === "ESCALATE");
    if (filter === "hard") return list.filter((i) => i.autonomy_tier === "HARD_BLOCK");
    if (filter === "aml") return list.filter((i) => (i.aml_result?.flag_count || 0) > 0);
    return list;
  }, [invoices, filter]);

  return (
    <section className="finoks-queue">
      <header className="finoks-queue__header">
        <h2>Invoice queue</h2>
        <div className="finoks-queue__filters">
          {["all", "auto", "escalate", "hard", "aml"].map((id) => (
            <button
              key={id}
              type="button"
              className={`finoks-chip ${filter === id ? "is-active" : ""}`}
              onClick={() => setFilter(id)}
            >
              {{
                all: "All",
                auto: "Auto",
                escalate: "Escalate",
                hard: "Hard block",
                aml: "AML flags",
              }[id]}
            </button>
          ))}
        </div>
      </header>

      {sorted.length === 0 ? (
        <p className="finoks-muted">
          No invoices loaded yet. Use <strong>Load demo</strong> in the navbar to populate the agent.
        </p>
      ) : (
        <ul className="finoks-queue__list">
          {sorted.map((inv) => (
            <li key={inv.invoice_id || inv.id}>
              <InvoiceCard
                invoice={inv}
                onApprove={onApprove}
                onBlock={onBlock}
                onMarkPaid={onMarkPaid}
                onAmlOpen={onAmlOpen}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
