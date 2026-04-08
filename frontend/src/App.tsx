import React, { useState } from "react";

import Dashboard from "./pages/Dashboard";
import InstitutionDetailPage from "./pages/InstitutionDetail";
import SearchRunDetailPage from "./pages/SearchRunDetail";
import "./App.css";

type Page =
  | { name: "dashboard" }
  | { name: "run-detail"; runId: string }
  | { name: "institution-detail"; institutionId: string };

function App() {
  const [page, setPage] = useState<Page>({ name: "dashboard" });

  const goToDashboard = () => setPage({ name: "dashboard" });

  switch (page.name) {
    case "dashboard":
      return (
        <Dashboard
          onSelectRun={(runId) => setPage({ name: "run-detail", runId })}
          onSelectInstitution={(institutionId) =>
            setPage({ name: "institution-detail", institutionId })
          }
        />
      );
    case "run-detail":
      return <SearchRunDetailPage runId={page.runId} onBack={goToDashboard} />;
    case "institution-detail":
      return (
        <InstitutionDetailPage
          institutionId={page.institutionId}
          onBack={goToDashboard}
        />
      );
    default:
      return null;
  }
}

export default App;
