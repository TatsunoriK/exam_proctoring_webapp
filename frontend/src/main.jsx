import React from "react";
import { createRoot } from "react-dom/client";
const examflow = location.pathname === "/" || location.pathname === "/examflow" || location.pathname === "/login";
if (examflow) {
  import("./examflow/styles.css");
  const module = location.pathname === "/login" ? await import("./examflow/auth-ui.tsx") : await import("./examflow/ui.tsx");
  const Page = module.default;
  createRoot(document.getElementById("root")).render(<React.StrictMode><Page /></React.StrictMode>);
} else {
  await import("./index.css");
  const { default: App } = await import("./App.jsx");
  createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
}
