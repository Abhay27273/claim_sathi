"""Dev-only: seed a minimal user -> family -> family_member -> policy chain so
/cases has a policy_id to attach documents to. Prints the policy_id to use.

    python scripts/seed_dev_data.py
"""
import os

import psycopg
from psycopg.rows import dict_row


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (phone) VALUES ('+919999999999') RETURNING id")
            user_id = cur.fetchone()["id"]

            cur.execute("INSERT INTO families (owner_user_id) VALUES (%s) RETURNING id", (user_id,))
            family_id = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO family_members (family_id, name, relationship) VALUES (%s, %s, %s) RETURNING id",
                (family_id, "Dev Test Member", "self"),
            )
            member_id = cur.fetchone()["id"]

            cur.execute(
                """
                INSERT INTO policies (family_member_id, insurer_name, policy_number, coverage_start_date)
                VALUES (%s, %s, %s, %s) RETURNING id
                """,
                (member_id, "Dev Test Insurer", "DEV-POLICY-001", "2021-01-01"),
            )
            policy_id = cur.fetchone()["id"]
        conn.commit()

    print(f"policy_id={policy_id}")


if __name__ == "__main__":
    main()
