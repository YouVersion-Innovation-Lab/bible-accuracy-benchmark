import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { Layout } from "./Layout";
import { ExtendedLeaderboard, Leaderboard } from "./pages/Leaderboard";
import { ExtendedModelDetail, ModelDetail } from "./pages/ModelDetail";
import { TrackEvaluations } from "./pages/TrackEvaluations";
import { Methodology } from "./pages/Methodology";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Leaderboard />} />
          <Route path="/models/:runId" element={<ModelDetail />} />
          {/* The Extended Benchmark (beta) is the same board and the same model
              report over the dimensions we hold out of the ranking. */}
          <Route path="/extended" element={<ExtendedLeaderboard />} />
          <Route path="/extended/models/:runId" element={<ExtendedModelDetail />} />
          {/* One page per dimension, shared by both boards — a dimension's test
              cases read the same whichever board sent you there. The old
              combined page redirects so any shared link still lands somewhere
              sensible. */}
          <Route path="/models/:runId/evaluations/:track" element={<TrackEvaluations />} />
          <Route
            path="/models/:runId/evaluations"
            element={<Navigate to="../evaluations/simple" replace />}
          />
          <Route path="/methodology" element={<Methodology />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
