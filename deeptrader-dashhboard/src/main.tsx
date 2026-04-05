import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Root element with id 'root' was not found.");
}

function shouldUseStrictMode(): boolean {
  if (typeof window === "undefined") return true;
  const hostname = window.location.hostname.toLowerCase();
  const isLocalDevHost = hostname === "localhost" || hostname === "127.0.0.1";
  return import.meta.env.DEV && isLocalDevHost;
}

createRoot(rootElement).render(
  shouldUseStrictMode() ? (
    <StrictMode>
      <App />
    </StrictMode>
  ) : (
    <App />
  )
);
