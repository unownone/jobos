import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import favicon from "./assets/brand/favicon.png";
import "./styles.css";

const icon = document.createElement("link");
icon.rel = "icon";
icon.href = favicon;
document.head.appendChild(icon);

const root = document.getElementById("root");
if (!root) {
  throw new Error("Missing #root");
}

createRoot(root).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
