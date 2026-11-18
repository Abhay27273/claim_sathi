"use client";

import { useState } from "react";

type RuleResult = { name: string; passed: boolean; explanation: string };

type PreviewResponse = {
  case_id: string;
  case_status: string;
  classification: { category: string; confidence: number; evidence_snippet?: string } | null;
  extracted_facts: Record<string, unknown> | null;
  rule_results: RuleResult[];
  evidence_gaps: { missing_documents: string[]; reasoning: string } | null;
  contestable: boolean | null;
  detail?: string;
};

type OrderResponse = { order_id: string; amount_paise: number; tier: string; key_id: string; detail?: string };

type DraftResponse = {
  case_id: string;
  case_status: string;
  letter_gro?: string;
  letter?: string;
  validation: Record<string, { passed: boolean; failures: string[]; attempt: number }>;
  detail?: string;
};

declare global {
  interface Window {
    Razorpay: new (options: Record<string, unknown>) => { open: () => void };
  }
}

function loadRazorpayScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load Razorpay checkout script"));
    document.body.appendChild(script);
  });
}

export default function IntakeForm() {
  const [policyId, setPolicyId] = useState("");
  const [rejectionFile, setRejectionFile] = useState<File | null>(null);
  const [policyFile, setPolicyFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [letters, setLetters] = useState<Record<string, string>>({});
  const [fullLadderPaid, setFullLadderPaid] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!rejectionFile) {
      setError("Please attach the rejection letter.");
      return;
    }
    setLoading(true);
    setError(null);
    setPreview(null);

    const form = new FormData();
    form.append("policy_id", policyId);
    form.append("doc_types", "rejection_letter");
    form.append("files", rejectionFile);
    if (policyFile) {
      form.append("doc_types", "policy_wording");
      form.append("files", policyFile);
    }

    try {
      const res = await fetch("/api/cases", { method: "POST", body: form });
      const data: PreviewResponse = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Something went wrong.");
        return;
      }
      setPreview(data);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setLoading(false);
    }
  }

  async function handlePay(tier: "gro_letter" | "full_ladder") {
    if (!preview) return;
    setError(null);
    try {
      const orderRes = await fetch(`/api/cases/${preview.case_id}/orders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
      });
      const order: OrderResponse = await orderRes.json();
      if (!orderRes.ok) {
        setError(order.detail ?? "Could not create the order.");
        return;
      }

      await loadRazorpayScript();
      const razorpay = new window.Razorpay({
        key: order.key_id,
        amount: order.amount_paise,
        currency: "INR",
        name: "ClaimSaathi",
        description: tier === "full_ladder" ? "Full escalation ladder" : "GRO complaint letter",
        order_id: order.order_id,
        handler: async (response: {
          razorpay_order_id: string;
          razorpay_payment_id: string;
          razorpay_signature: string;
        }) => {
          const draftRes = await fetch(`/api/cases/${preview.case_id}/draft`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(response),
          });
          const draft: DraftResponse = await draftRes.json();
          if (!draftRes.ok) {
            setError(draft.detail ?? "Payment was captured but drafting failed.");
            return;
          }
          if (tier === "full_ladder") setFullLadderPaid(true);
          if (draft.letter_gro) setLetters((prev) => ({ ...prev, gro: draft.letter_gro! }));
        },
      });
      razorpay.open();
    } catch {
      setError("Could not start the payment flow.");
    }
  }

  async function handleEscalate(stage: "bima_bharosa" | "ombudsman") {
    if (!preview) return;
    setError(null);
    try {
      const res = await fetch(`/api/cases/${preview.case_id}/escalate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage }),
      });
      const data: DraftResponse = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "Escalation failed.");
        return;
      }
      if (data.letter) setLetters((prev) => ({ ...prev, [stage]: data.letter! }));
    } catch {
      setError("Could not reach the server.");
    }
  }

  return (
    <div>
      <form onSubmit={handleSubmit} className="card">
        <label htmlFor="policyId">Policy ID</label>
        <input
          id="policyId"
          type="text"
          value={policyId}
          onChange={(e) => setPolicyId(e.target.value)}
          placeholder="UUID from your ClaimSaathi policy record"
          required
        />

        <label htmlFor="rejectionFile">Rejection letter (PDF/JPG/PNG)</label>
        <input
          id="rejectionFile"
          type="file"
          accept="application/pdf,image/jpeg,image/png"
          onChange={(e) => setRejectionFile(e.target.files?.[0] ?? null)}
          required
        />

        <label htmlFor="policyFile">Policy wording (optional, improves accuracy)</label>
        <input
          id="policyFile"
          type="file"
          accept="application/pdf,image/jpeg,image/png"
          onChange={(e) => setPolicyFile(e.target.files?.[0] ?? null)}
        />

        <button type="submit" disabled={loading}>
          {loading ? "Analyzing..." : "Get my free Case Strength report"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {preview && (
        <div className="card">
          <h2>Case Strength Report</h2>
          <p>
            Category:{" "}
            <span className={`pill ${preview.contestable ? "ok" : "warn"}`}>
              {preview.classification?.category ?? "unknown"}
            </span>
          </p>
          <p>
            <strong>{preview.contestable ? "Contestable" : "Not obviously contestable"}</strong>
          </p>

          <h3>Rule checks</h3>
          <ul>
            {preview.rule_results.map((r) => (
              <li key={r.name}>
                <span className={`pill ${r.passed ? "ok" : "warn"}`}>{r.passed ? "OK" : "ISSUE"}</span>{" "}
                <strong>{r.name}</strong>: {r.explanation}
              </li>
            ))}
          </ul>

          {preview.evidence_gaps && preview.evidence_gaps.missing_documents.length > 0 && (
            <>
              <h3>Missing documents</h3>
              <ul>
                {preview.evidence_gaps.missing_documents.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </>
          )}

          {preview.case_status === "needs_human_review_fraud" ? (
            <p className="error">
              This case involves a fraud allegation and has been routed to human/legal review.
              It cannot be auto-drafted.
            </p>
          ) : (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
              <button onClick={() => handlePay("gro_letter")}>Pay ₹499 for GRO letter</button>
              <button onClick={() => handlePay("full_ladder")}>Pay ₹1,499 for full ladder</button>
            </div>
          )}
        </div>
      )}

      {letters.gro && (
        <div className="card">
          <h2>Grievance Officer letter</h2>
          <div className="letter">{letters.gro}</div>
          {fullLadderPaid && (
            <button style={{ marginTop: "1rem" }} onClick={() => handleEscalate("bima_bharosa")}>
              Escalate to Bima Bharosa
            </button>
          )}
        </div>
      )}

      {letters.bima_bharosa && (
        <div className="card">
          <h2>Bima Bharosa escalation letter</h2>
          <div className="letter">{letters.bima_bharosa}</div>
          <button style={{ marginTop: "1rem" }} onClick={() => handleEscalate("ombudsman")}>
            Escalate to Insurance Ombudsman
          </button>
        </div>
      )}

      {letters.ombudsman && (
        <div className="card">
          <h2>Insurance Ombudsman complaint</h2>
          <div className="letter">{letters.ombudsman}</div>
        </div>
      )}
    </div>
  );
}
