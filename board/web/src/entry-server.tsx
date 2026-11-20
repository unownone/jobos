import { StrictMode } from "react";
import { renderToString } from "react-dom/server";

import { pageFromName, type PageName } from "./pages/registry";

export function renderPage(name: PageName): string {
  const Page = pageFromName(name);
  return renderToString(
    <StrictMode>
      <Page />
    </StrictMode>,
  );
}
