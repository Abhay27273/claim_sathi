import IntakeForm from "./IntakeForm";

export default function Home() {
  return (
    <main>
      <h1>ClaimSaathi</h1>
      <p>
        Upload your rejection letter and policy wording for a free Case Strength report.
        This is self-help drafting, not legal advice.
      </p>
      <IntakeForm />
    </main>
  );
}
