import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { Layout } from "./Layout";
import { FilterProvider } from "./filterContext";
import { Leaderboard } from "./pages/Leaderboard";
import { ModelDetail } from "./pages/ModelDetail";
import { TrackEvaluations } from "./pages/TrackEvaluations";
import { Methodology } from "./pages/Methodology";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <FilterProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Leaderboard />} />
            <Route path="/models/:runId" element={<ModelDetail />} />
            {/* One page per dimension. The old combined page redirects so any
                shared link still lands somewhere sensible. */}
            <Route path="/models/:runId/evaluations/:track" element={<TrackEvaluations />} />
            <Route
              path="/models/:runId/evaluations"
              element={<Navigate to="../evaluations/simple" replace />}
            />
            <Route path="/methodology" element={<Methodology />} />
          </Route>
        </Routes>
      </FilterProvider>
    </BrowserRouter>
  </StrictMode>,
);
