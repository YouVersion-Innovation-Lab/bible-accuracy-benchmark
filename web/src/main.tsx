import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import { Layout } from "./Layout";
import { Leaderboard } from "./pages/Leaderboard";
import { ModelDetail } from "./pages/ModelDetail";
import { Failures } from "./pages/Failures";
import { Methodology } from "./pages/Methodology";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Leaderboard />} />
          <Route path="/models/:runId" element={<ModelDetail />} />
          <Route path="/models/:runId/failures" element={<Failures />} />
          <Route path="/methodology" element={<Methodology />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
