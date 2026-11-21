import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { pageFromName } from "./pages/registry";
import "./index.css";

const root = document.getElementById("root");
if (root) {
  const Page = pageFromName(document.body.dataset.page);
  createRoot(root).render(
    <StrictMode>
      <Page />
    </StrictMode>,
  );
}
