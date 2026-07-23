import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import { Layout } from "./Layout";
import { FilterProvider } from "./filterContext";
import { Leaderboard } from "./pages/Leaderboard";
import { ModelDetail } from "./pages/ModelDetail";
import { Evaluations } from "./pages/Evaluations";
import { Methodology } from "./pages/Methodology";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <FilterProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Leaderboard />} />
            <Route path="/models/:runId" element={<ModelDetail />} />
            <Route path="/models/:runId/evaluations" element={<Evaluations />} />
            <Route path="/methodology" element={<Methodology />} />
          </Route>
        </Routes>
      </FilterProvider>
    </BrowserRouter>
  </StrictMode>,
);
