-- ClaimSaathi core schema. See IMPLEMENTATION_PLAN.md section 7.
-- Superseded by Alembic migrations once the app has its first release;
-- this file is the authoritative starting point for `alembic revision --autogenerate`.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT UNIQUE NOT NULL,
    otp_verified_at TIMESTAMPTZ,
    consent_given_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE families (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE family_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_id UUID NOT NULL REFERENCES families(id),
    name TEXT NOT NULL,
    relationship TEXT,
    date_of_birth DATE
);

CREATE TABLE policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    family_member_id UUID NOT NULL REFERENCES family_members(id),
    insurer_name TEXT NOT NULL,
    policy_number TEXT,
    coverage_start_date DATE NOT NULL,
    ported_continuous_coverage BOOLEAN NOT NULL DEFAULT false,
    ported_from_date DATE,
    disclosed_peds JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id UUID NOT NULL REFERENCES policies(id),
    stage TEXT NOT NULL DEFAULT 'intake',
    -- intake | preprocess | classify | extract | rule_check | evidence_gap
    -- | draft | validate | user_approve | track_gro | escalate_bima_bharosa
    -- | ombudsman | outcome | human_review
    rejection_category TEXT,
    contestable BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    type TEXT NOT NULL, -- rejection_letter | policy_wording | discharge_summary | other
    mime_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    page_image_paths JSONB,
    ocr_confidence NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE extracted_facts (
    case_id UUID PRIMARY KEY REFERENCES cases(id),
    facts JSONB NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rule_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    rule_name TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    explanation TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE letters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    stage TEXT NOT NULL, -- gro | bima_bharosa | ombudsman
    draft_text TEXT NOT NULL,
    validated BOOLEAN NOT NULL DEFAULT false,
    validation_attempt INT NOT NULL DEFAULT 0,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE deadlines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    type TEXT NOT NULL, -- gro_30_day | ombudsman_1_year
    due_at TIMESTAMPTZ NOT NULL,
    reminded_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'pending' -- pending | met | missed
);

CREATE TABLE payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    amount_inr NUMERIC NOT NULL,
    tier TEXT NOT NULL, -- gro_letter | full_ladder
    razorpay_ref TEXT,
    paid_at TIMESTAMPTZ
);

CREATE TABLE grok_usage_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    node TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INT,
    completion_tokens INT,
    cost_inr NUMERIC,
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE outcomes (
    case_id UUID PRIMARY KEY REFERENCES cases(id),
    result TEXT NOT NULL, -- reversed | partially_reversed | upheld | withdrawn
    amount_recovered_inr NUMERIC,
    reported_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- OTP hash, not plaintext -- same principle as a password even though it's
-- short-lived. services/gateway/otp.py.
CREATE TABLE otp_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT NOT NULL,
    otp_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    token TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_otp_requests_phone ON otp_requests(phone);
CREATE INDEX idx_user_sessions_token ON user_sessions(token);

-- A case lands here when graph.py sets case_status to needs_human_review_fraud
-- or needs_human_review_max_attempts. resolved_by is free text for now --
-- there's no real reviewer-identity auth yet, only the shared GATEWAY_API_KEY.
CREATE TABLE human_review_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES cases(id),
    note TEXT,
    action TEXT NOT NULL, -- cleared_for_draft | rejected | escalated_to_lawyer
    resolved_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_cases_policy_id ON cases(policy_id);
CREATE INDEX idx_documents_case_id ON documents(case_id);
CREATE INDEX idx_deadlines_due_at ON deadlines(due_at) WHERE status = 'pending';
CREATE INDEX idx_grok_usage_case_id ON grok_usage_log(case_id);
CREATE INDEX idx_human_review_notes_case_id ON human_review_notes(case_id);
