import { useEffect, useState } from "react";
import { getHealth } from "./api";

export function App() {
  const [status, setStatus] = useState("Checking local API…");

  useEffect(() => {
    getHealth().then(
      () => setStatus("Local API connected."),
      () => setStatus("Local API unavailable."),
    );
  }, []);

  return (
    <main>
      <h1>Vestor</h1>
      <p>Local UK compensation planner scaffold.</p>
      <p>Runs offline after installation. Data is not saved.</p>
      <p role="status">{status}</p>
    </main>
  );
}
