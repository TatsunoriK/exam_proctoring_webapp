import React from "react";
import { createRoot } from "react-dom/client";
// GitHub Pages hosts only static files. ExamFlow requires same-origin cookies
// from the locally running backend, so enter the app through that server.
if (import.meta.env.VITE_API_ORIGIN) {
  location.replace(new URL("/", import.meta.env.VITE_API_ORIGIN).href);
} else if (location.pathname === "/" || location.pathname === "/examflow" || location.pathname === "/login") {
  import("./examflow/styles.css");
  const module = location.pathname === "/login" ? await import("./examflow/auth-ui.tsx") : await import("./examflow/ui.tsx");
  const Page = module.default;
  createRoot(document.getElementById("root")).render(<React.StrictMode><Page /></React.StrictMode>);
} else {
  await import("./index.css");
  const { default: App } = await import("./App.jsx");
  createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
}
